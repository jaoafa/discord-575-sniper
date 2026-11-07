"""質の低い・重複した records の行を quarantined_records へ退避・復元する運用スクリプト。

使い方:
    python -m src.quarantine [--db PATH] [--apply]
    python -m src.quarantine restore [--db PATH] [--apply] (--all | --id ID [--id ID ...])

既定は dry-run で、DB を変更しない。--apply で実行し、変更前に DB のバックアップを作る。
実行は Bot を止めた状態で行う。
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import evaluate
from .senryu import finder
from .senryu.tokenizer import Morpheme

LOW_SCORE_THRESHOLD = 0.5

REASONS = ("duplicate", "only_sokuon", "disapproved", "low_score", "rejudged")

_QUARANTINE_TABLE = "quarantined_records"
_BUSY_TIMEOUT_SECONDS = 5.0
_PART_COLUMNS = ("part1", "part2", "part3", "part4", "part5")
_PATTERNS = {3: finder.SENRYU_PATTERN, 5: finder.TANKA_PATTERN}

_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "records": {"id", *_PART_COLUMNS, "morphemes_json", "score", "overall_match"},
    "praises": {"source", "source_id", "count"},
    "disapprovals": {"source", "source_id"},
}


class QuarantineError(Exception):
    """退避・復元を続行できない入力(DB の欠落・スキーマ不足・不正な行など)を表す。"""


def _connect(path: str, *, writable: bool) -> sqlite3.Connection:
    """DB を開いて必須列を検証する。存在しないファイルを新規作成することはない。

    書き込み用の接続は明示的に BEGIN を発行するため isolation_level=None で開く。
    """
    if not Path(path).is_file():
        raise QuarantineError(f"DB ファイルが見つかりません: {path}")
    if writable:
        conn = sqlite3.connect(path, isolation_level=None, timeout=_BUSY_TIMEOUT_SECONDS)
    else:
        conn = evaluate.open_readonly(path)
    try:
        _check_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row | tuple]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _check_schema(conn: sqlite3.Connection) -> None:
    missing: list[str] = []
    for table, required in _REQUIRED_COLUMNS.items():
        names = {row[1] for row in _columns(conn, table)}
        missing.extend(f"{table}.{c}" for c in sorted(required - names))
    if missing:
        raise QuarantineError("DB のスキーマが古いため処理できません。不足: " + ", ".join(missing))


def _record_column_names(conn: sqlite3.Connection) -> list[str]:
    return [row[1] for row in _columns(conn, "records")]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _parse_morphemes(record_id: int, morphemes_json: str | None) -> list[Morpheme]:
    try:
        morphemes = []
        for d in json.loads(morphemes_json):
            surface, reading, pos, mora = d["surface"], d["reading"], d["pos"], d["mora"]
            texts_ok = all(isinstance(v, str) for v in (surface, reading, pos))
            mora_ok = isinstance(mora, int) and not isinstance(mora, bool) and mora >= 0
            if not (texts_ok and mora_ok):
                raise TypeError(f"要素の型が不正です: {d!r}")
            morphemes.append(
                Morpheme(surface=surface, reading=reading, mora=mora, start=0, end=0, pos=pos)
            )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise QuarantineError(
            f"records.id={record_id} の morphemes_json を解釈できません: {e!r}"
        ) from e
    return morphemes


def _split_parts(
    record_id: int, morphemes: list[Morpheme], part_count: int
) -> list[list[Morpheme]]:
    """mora の累積が各パートの音数に達する位置で形態素をパートごとに分ける。"""
    pattern = _PATTERNS.get(part_count)
    if pattern is None:
        raise QuarantineError(
            f"records.id={record_id} のパート数が 3 でも 5 でもありません: {part_count}"
        )
    parts: list[list[Morpheme]] = []
    current: list[Morpheme] = []
    acc = 0
    for m in morphemes:
        if len(parts) == len(pattern):
            if m.mora > 0:
                raise QuarantineError(
                    f"records.id={record_id} の mora の合計が音数パターン {pattern} を超えています"
                )
            continue
        current.append(m)
        acc += m.mora
        target = pattern[len(parts)]
        if acc > target:
            raise QuarantineError(
                f"records.id={record_id} の mora の累積が {len(parts) + 1} パート目の音数 "
                f"{target} にちょうど達しません"
            )
        if acc == target:
            parts.append(current)
            current, acc = [], 0
    if len(parts) != len(pattern):
        raise QuarantineError(
            f"records.id={record_id} の mora の合計が音数パターン {pattern} に足りません"
        )
    return parts


def _is_rejected_by_current_logic(item: evaluate.Item) -> bool:
    return evaluate.replay(item) == evaluate.OUTCOME_EXCLUDED


def classify(conn: sqlite3.Connection) -> dict[int, str]:
    """退避対象の records.id と退避理由を id 昇順で返す。DB は変更しない。

    あっぱれが付いた記録はどの理由でも対象外。理由は REASONS の優先順で最初に該当する 1 つ。
    重複は、免除の有無に関係なく同一テキストのうち最小 id の 1 件だけを残す。
    """
    praised = {
        row[0] for row in conn.execute(
            "SELECT source_id FROM praises WHERE source = 'record' AND count > 0"
        )
    }
    disapproved = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT source_id FROM disapprovals WHERE source = 'record'"
        )
    }
    first_id_by_text: dict[str, int] = {}
    plan: dict[int, str] = {}
    for row in conn.execute(
        "SELECT id, part1, part2, part3, part4, part5, morphemes_json, score, overall_match "
        "FROM records ORDER BY id"
    ).fetchall():
        record_id, morphemes_json, score, overall_match = row[0], row[6], row[7], row[8]
        morphemes = _parse_morphemes(record_id, morphemes_json)
        part_count = sum(p is not None for p in row[1:6])
        parts = _split_parts(record_id, morphemes, part_count)
        text = "".join(m.surface for m in morphemes if m.mora > 0)
        is_duplicate = text in first_id_by_text
        first_id_by_text.setdefault(text, record_id)
        if record_id in praised:
            continue
        if is_duplicate:
            plan[record_id] = "duplicate"
        elif not all(finder.has_substantive_mora(p) for p in parts):
            plan[record_id] = "only_sokuon"
        elif record_id in disapproved:
            plan[record_id] = "disapproved"
        elif score is not None and score < LOW_SCORE_THRESHOLD:
            plan[record_id] = "low_score"
        elif _is_rejected_by_current_logic(
            evaluate.Item(
                id=record_id, parts=tuple(p for p in row[1:6] if p is not None), praised=False,
                other_votes=0, self_votes=0, morphemes_json=morphemes_json,
                overall_match=overall_match,
            )
        ):
            plan[record_id] = "rejudged"
    return plan


def _ids_line(ids: list[int]) -> str:
    return "  ID: " + (", ".join(map(str, ids)) if ids else "なし")


def render_plan(plan: dict[int, str], total: int, *, applied: bool) -> str:
    """退避の対象(または結果)を理由ごとの件数と ID に整形する。"""
    lines = ["== 退避結果 ==" if applied else "== 退避対象 (dry-run) =="]
    for reason in REASONS:
        ids = [rid for rid, r in plan.items() if r == reason]
        lines += [f"{reason}: {len(ids)} 件", _ids_line(ids)]
    lines.append(f"合計: {len(plan)} 件 / records 全体: {total} 件")
    return "\n".join(lines)


def render_restore(ids: list[int], *, applied: bool) -> str:
    """復元の対象(または結果)を件数と ID に整形する。"""
    head = "== 復元結果 ==" if applied else "== 復元対象 (dry-run) =="
    return "\n".join([head, f"復元: {len(ids)} 件", _ids_line(ids)])


def _ensure_quarantine_table(conn: sqlite3.Connection) -> None:
    """quarantined_records を records と同じ列で作成する。既存で列が不足していれば中止する。"""
    definitions = []
    for _, name, column_type, notnull, _, _ in _columns(conn, "records"):
        if name == "id":
            definitions.append('"id" INTEGER PRIMARY KEY')
        else:
            definitions.append(f'"{name}" {column_type}{" NOT NULL" if notnull else ""}')
    definitions += ['"quarantined_at" TEXT NOT NULL', '"quarantine_reason" TEXT NOT NULL']
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_QUARANTINE_TABLE} ({', '.join(definitions)})")
    _check_quarantine_columns(conn)


def _check_quarantine_columns(conn: sqlite3.Connection) -> None:
    missing = set(_record_column_names(conn)) - {r[1] for r in _columns(conn, _QUARANTINE_TABLE)}
    if missing:
        raise QuarantineError(
            f"{_QUARANTINE_TABLE} に records の列が不足しています: {', '.join(sorted(missing))}"
        )


def _backup(conn: sqlite3.Connection, db_path: str) -> Path:
    """変更前の DB を <db>.bak-<UTC 日時> に複製する。失敗したら例外にして変更に進ませない。"""
    path = Path(db_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.name}.bak-{stamp}")
    serial = 1
    while dest.exists():
        dest = path.with_name(f"{path.name}.bak-{stamp}-{serial}")
        serial += 1
    dest_conn = sqlite3.connect(str(dest))
    try:
        conn.backup(dest_conn)
    except sqlite3.Error as e:
        dest_conn.close()
        dest.unlink(missing_ok=True)
        raise QuarantineError(f"バックアップを作成できませんでした ({dest}): {e}") from e
    dest_conn.close()
    return dest


def _move_rows(
    conn: sqlite3.Connection, ids: list[int], *, to_quarantine: bool, reasons: dict[int, str]
) -> None:
    columns = ", ".join(f'"{c}"' for c in _record_column_names(conn))
    if to_quarantine:
        insert = (
            f"INSERT INTO {_QUARANTINE_TABLE} ({columns}, quarantined_at, quarantine_reason) "
            f"SELECT {columns}, ?, ? FROM records WHERE id = ?"
        )
        delete = "DELETE FROM records WHERE id = ?"
        now = datetime.now(timezone.utc).isoformat()
        for rid in ids:
            conn.execute(insert, (now, reasons[rid], rid))
            conn.execute(delete, (rid,))
    else:
        insert = (
            f"INSERT INTO records ({columns}) SELECT {columns} FROM {_QUARANTINE_TABLE} "
            f"WHERE id = ?"
        )
        delete = f"DELETE FROM {_QUARANTINE_TABLE} WHERE id = ?"
        for rid in ids:
            conn.execute(insert, (rid,))
            conn.execute(delete, (rid,))


def _run_in_transaction(conn: sqlite3.Connection, work) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        work()
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def run_quarantine(db_path: str, *, apply: bool) -> str:
    """退避を dry-run または実行し、標準出力用の文字列を返す。"""
    conn = _connect(db_path, writable=apply)
    try:
        plan = classify(conn)
        total = _count(conn, "records")
        if not apply:
            return render_plan(plan, total, applied=False)
        if not plan:
            return render_plan(plan, total, applied=True)
        backup_path = _backup(conn, db_path)
        result: dict[str, object] = {}

        def work() -> None:
            result["plan"] = classify(conn)
            result["total"] = _count(conn, "records")
            if result["plan"]:
                _ensure_quarantine_table(conn)
                _move_rows(
                    conn, list(result["plan"]), to_quarantine=True, reasons=result["plan"]
                )

        _run_in_transaction(conn, work)
        rendered = render_plan(result["plan"], result["total"], applied=True)
        return f"{rendered}\nバックアップ: {backup_path}"
    finally:
        conn.close()


def _restore_targets(conn: sqlite3.Connection, ids: list[int] | None) -> list[int]:
    """復元対象の id を検証して返す。ids が None なら quarantined_records の全件。"""
    if not _table_exists(conn, _QUARANTINE_TABLE):
        raise QuarantineError(f"{_QUARANTINE_TABLE} テーブルがありません")
    _check_quarantine_columns(conn)
    available = {r[0] for r in conn.execute(f"SELECT id FROM {_QUARANTINE_TABLE}")}
    if ids is None:
        targets = sorted(available)
    else:
        unknown = sorted(set(ids) - available)
        if unknown:
            raise QuarantineError(f"{_QUARANTINE_TABLE} に存在しない id: {unknown}")
        targets = sorted(set(ids))
    existing = {r[0] for r in conn.execute("SELECT id FROM records")}
    conflicts = [i for i in targets if i in existing]
    if conflicts:
        raise QuarantineError(f"records に同じ id が既にあります: {conflicts}")
    return targets


def run_restore(db_path: str, *, ids: list[int] | None, apply: bool) -> str:
    """復元を dry-run または実行し、標準出力用の文字列を返す。ids が None なら全件。"""
    conn = _connect(db_path, writable=apply)
    try:
        targets = _restore_targets(conn, ids)
        if not apply:
            return render_restore(targets, applied=False)
        if not targets:
            return render_restore(targets, applied=True)
        backup_path = _backup(conn, db_path)
        result: dict[str, list[int]] = {}

        def work() -> None:
            result["targets"] = _restore_targets(conn, ids)
            _move_rows(conn, result["targets"], to_quarantine=False, reasons={})

        _run_in_transaction(conn, work)
        return render_restore(result["targets"], applied=True) + f"\nバックアップ: {backup_path}"
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="質の低い・重複した records を quarantined_records へ退避する。"
        "既定は dry-run。"
    )
    parser.add_argument("--db", default=evaluate.DEFAULT_DB_PATH, help="records.db のパス")
    parser.add_argument("--apply", action="store_true", help="dry-run ではなく実際に退避する")
    subparsers = parser.add_subparsers(dest="command", required=False)
    restore = subparsers.add_parser("restore", help="退避した記録を records に戻す")
    # サブパーサーの既定値が親で指定した値を上書きしないよう SUPPRESS にする。
    restore.add_argument("--db", default=argparse.SUPPRESS, help="records.db のパス")
    restore.add_argument(
        "--apply", action="store_true", default=argparse.SUPPRESS,
        help="dry-run ではなく実際に復元する",
    )
    target = restore.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="退避した記録をすべて戻す")
    target.add_argument(
        "--id", type=int, action="append", dest="ids", help="戻す records.id (複数指定可)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """退避または復元を実行して結果を標準出力に出す。失敗時は理由を標準エラーに出して 1 を返す。"""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "restore":
            output = run_restore(args.db, ids=None if args.all else args.ids, apply=args.apply)
        else:
            output = run_quarantine(args.db, apply=args.apply)
    except QuarantineError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError as e:
        print(f"エラー: DB の操作に失敗しました ({args.db}): {e}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
