"""records.db を読み取り専用で開き、検出品質の評価指標を出力するオフライン評価スクリプト。

使い方: python -m src.evaluate [--db PATH] [--unique]
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .senryu.finder import find_candidates, pick_best
from .senryu.tokenizer import Morpheme

DEFAULT_DB_PATH = "data/records.db"

# 稼働中の Bot が書き込み中でも少し待てるようにする(秒)。
_BUSY_TIMEOUT_SECONDS = 5.0

_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "records": {
        "id", "user_id", "part1", "part2", "part3", "part4", "part5",
        "morphemes_json", "overall_match",
    },
    "chain_records": {"id", "parts_json"},
    "praises": {"source", "source_id", "count"},
    "disapprovals": {"source", "source_id", "user_id"},
}

OUTCOME_KEPT = "維持"
OUTCOME_CHANGED = "別候補に変更"
OUTCOME_EXCLUDED = "除外"
_OUTCOMES = (OUTCOME_KEPT, OUTCOME_CHANGED, OUTCOME_EXCLUDED)


class EvaluationError(Exception):
    """評価を続行できない入力(DB の欠落・スキーマ不足など)を表す。"""


@dataclass
class Item:
    """評価の 1 件(レコード単位、または --unique でまとめたテキスト単位)。

    morphemes_json / overall_match は records 由来の件のみ持ち、再現に使う。
    """

    id: int
    parts: tuple[str, ...]
    praised: bool
    other_votes: int
    self_votes: int
    morphemes_json: str | None = None
    overall_match: float | None = None

    @property
    def has_other_disapproval(self) -> bool:
        return self.other_votes > 0

    @property
    def has_self_only_disapproval(self) -> bool:
        return self.self_votes > 0 and self.other_votes == 0


def open_readonly(path: str) -> sqlite3.Connection:
    """SQLite DB を読み取り専用で開く。存在しないファイルを新規作成することはない。"""
    db_path = Path(path)
    if not db_path.is_file():
        raise EvaluationError(f"DB ファイルが見つかりません: {path}")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_SECONDS)


def check_schema(conn: sqlite3.Connection) -> None:
    """評価に必要なテーブル・列が揃っているかを確認し、不足があれば EvaluationError にする。"""
    missing: list[str] = []
    for table, required in _REQUIRED_COLUMNS.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing.extend(f"{table}.{c}" for c in sorted(required - columns))
    if missing:
        raise EvaluationError(
            "DB のスキーマが古いため評価できません。不足: " + ", ".join(missing)
        )


def _load_ratings(
    conn: sqlite3.Connection,
) -> tuple[dict[tuple[str, int], int], dict[tuple[str, int], list[int]]]:
    praises = {
        (source, source_id): count
        for source, source_id, count in conn.execute(
            "SELECT source, source_id, count FROM praises"
        )
    }
    disapprovals: dict[tuple[str, int], list[int]] = {}
    for source, source_id, user_id in conn.execute(
        "SELECT source, source_id, user_id FROM disapprovals"
    ):
        disapprovals.setdefault((source, source_id), []).append(user_id)
    return praises, disapprovals


def _build_item(
    *,
    source: str,
    row_id: int,
    parts: tuple[str, ...],
    author_ids: frozenset[int],
    praises: dict[tuple[str, int], int],
    disapprovals: dict[tuple[str, int], list[int]],
    morphemes_json: str | None = None,
    overall_match: float | None = None,
) -> Item:
    voters = disapprovals.get((source, row_id), [])
    self_votes = sum(1 for v in voters if v in author_ids)
    return Item(
        id=row_id,
        parts=parts,
        praised=praises.get((source, row_id), 0) > 0,
        other_votes=len(voters) - self_votes,
        self_votes=self_votes,
        morphemes_json=morphemes_json,
        overall_match=overall_match,
    )


def load_records(conn: sqlite3.Connection) -> list[Item]:
    """records を Item のリスト(id 昇順)として読み込む。"""
    praises, disapprovals = _load_ratings(conn)
    items = []
    for row in conn.execute(
        "SELECT id, user_id, part1, part2, part3, part4, part5, morphemes_json, overall_match "
        "FROM records ORDER BY id"
    ):
        items.append(
            _build_item(
                source="record",
                row_id=row[0],
                parts=tuple(p for p in row[2:7] if p is not None),
                author_ids=frozenset({row[1]}),
                praises=praises,
                disapprovals=disapprovals,
                morphemes_json=row[7],
                overall_match=row[8],
            )
        )
    return items


def load_chain_records(conn: sqlite3.Connection) -> list[Item]:
    """chain_records を Item のリスト(id 昇順)として読み込む。"""
    praises, disapprovals = _load_ratings(conn)
    items = []
    for row_id, parts_json in conn.execute("SELECT id, parts_json FROM chain_records ORDER BY id"):
        try:
            entries = json.loads(parts_json)
            parts = tuple(e["text"] for e in entries)
            author_ids = frozenset(e["user_id"] for e in entries)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise EvaluationError(
                f"chain_records.id={row_id} の parts_json を解釈できません: {e!r}"
            ) from e
        items.append(
            _build_item(
                source="chain_record",
                row_id=row_id,
                parts=parts,
                author_ids=author_ids,
                praises=praises,
                disapprovals=disapprovals,
            )
        )
    return items


def merge_unique(items: list[Item]) -> list[Item]:
    """同じテキスト(parts)の件を 1 件にまとめる。

    評価フラグは構成レコードの OR、票数は合算し、再現に使う形態素は id が最大の件のものを使う。
    """
    groups: dict[tuple[str, ...], list[Item]] = {}
    for item in items:
        groups.setdefault(item.parts, []).append(item)
    merged = []
    for parts, group in groups.items():
        latest = max(group, key=lambda i: i.id)
        merged.append(
            Item(
                id=latest.id,
                parts=parts,
                praised=any(i.praised for i in group),
                other_votes=sum(i.other_votes for i in group),
                self_votes=sum(i.self_votes for i in group),
                morphemes_json=latest.morphemes_json,
                overall_match=latest.overall_match,
            )
        )
    return merged


def replay(item: Item) -> str | None:
    """保存された形態素に現行の候補選択を再実行し、維持・別候補に変更・除外のいずれかを返す。

    morphemes_json を復元できない場合は None を返す。
    overall_match が保存されていればメッセージ全体の総モーラ数を復元して coverage に反映する。
    """
    try:
        morphemes = [
            Morpheme(
                surface=d["surface"], reading=d["reading"], mora=d["mora"],
                start=0, end=0, pos=d["pos"],
            )
            for d in json.loads(item.morphemes_json)
        ]
        span = sum(m.mora for m in morphemes)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    total_mora = None
    if item.overall_match is not None and item.overall_match > 0:
        total_mora = round(span / item.overall_match)
    best = pick_best(find_candidates(morphemes, "", total_mora=total_mora))
    if best is None:
        return OUTCOME_EXCLUDED
    return OUTCOME_KEPT if best.parts == item.parts else OUTCOME_CHANGED


def _count_flags(items: list[Item]) -> tuple[int, int, int, int]:
    return (
        len(items),
        sum(i.praised for i in items),
        sum(i.has_other_disapproval for i in items),
        sum(i.has_self_only_disapproval for i in items),
    )


def _render_summary(name: str, items: list[Item], *, with_overall_match: bool) -> list[str]:
    total, praised, other, self_only = _count_flags(items)
    head = f"{name}: {total} 件"
    if with_overall_match:
        head += f" (overall_match あり {sum(i.overall_match is not None for i in items)} 件)"
    return [
        head,
        f"  あっぱれ付き: {praised} 件 / 他者👎付き: {other} 件 / 本人のみ👎: {self_only} 件",
        f"  👎 票: 他者 {sum(i.other_votes for i in items)} / 本人 {sum(i.self_votes for i in items)}",
    ]


def render_report(records: list[Item], chain_records: list[Item], *, unique: bool) -> str:
    """評価サマリと再現結果を標準出力用の文字列に整形する。"""
    unit = "ユニークテキスト" if unique else "レコード"
    lines = [f"== 評価サマリ (単位: {unit}) =="]
    lines += _render_summary("records", records, with_overall_match=True)
    lines += _render_summary("chain_records", chain_records, with_overall_match=False)

    by_outcome: dict[str, list[Item]] = {o: [] for o in _OUTCOMES}
    unrestorable = 0
    for item in records:
        outcome = replay(item)
        if outcome is None:
            unrestorable += 1
        else:
            by_outcome[outcome].append(item)

    lines += ["", "== 再現結果 (現行ロジック、records のみ) =="]
    lines.append("区分\t件数\tあっぱれ\t他者👎\t本人のみ👎")
    for outcome in _OUTCOMES:
        lines.append("\t".join([outcome, *map(str, _count_flags(by_outcome[outcome]))]))
    lines.append(f"復元不可: {unrestorable} 件")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """評価を実行して結果を標準出力に出す。失敗時は理由を標準エラーに出して 1 を返す。"""
    parser = argparse.ArgumentParser(
        description="records.db を読み取り専用で開き、検出品質の評価指標を出力する。"
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="records.db のパス")
    parser.add_argument(
        "--unique", action="store_true", help="同一テキストを 1 件にまとめて集計する"
    )
    args = parser.parse_args(argv)
    try:
        conn = open_readonly(args.db)
        try:
            check_schema(conn)
            records = load_records(conn)
            chain_records = load_chain_records(conn)
        finally:
            conn.close()
    except EvaluationError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError as e:
        print(f"エラー: DB を読み取れませんでした ({args.db}): {e}", file=sys.stderr)
        return 1
    if args.unique:
        records = merge_unique(records)
        chain_records = merge_unique(chain_records)
    print(render_report(records, chain_records, unique=args.unique))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
