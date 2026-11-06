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
    "approvals": {"source", "source_id", "user_id"},
    "praise_users": {"source", "source_id", "user_id"},
}

RATING_NONE = "評価なし"
RATING_POSITIVE = "肯定のみ"
RATING_NEGATIVE = "否定のみ"
RATING_BOTH = "肯定と否定"
_RATINGS = (RATING_NONE, RATING_POSITIVE, RATING_NEGATIVE, RATING_BOTH)

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
    approve_other_votes: int = 0
    approve_self_votes: int = 0
    rater_ids: frozenset[int] = frozenset()

    @property
    def rating(self) -> str:
        """他者による肯定(あっぱれ・👍)と否定(👎)の有無から評価区分を返す。

        本人の 👍 / 👎 は数えないため、他者の評価が無ければ「評価なし」になる。
        """
        positive = self.praised or self.approve_other_votes > 0
        negative = self.other_votes > 0
        if positive and negative:
            return RATING_BOTH
        if positive:
            return RATING_POSITIVE
        if negative:
            return RATING_NEGATIVE
        return RATING_NONE


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


@dataclass
class Ratings:
    """詠みごとの評価。キーは (source, source_id)。"""

    praises: dict[tuple[str, int], int]
    praise_users: dict[tuple[str, int], list[int]]
    approvals: dict[tuple[str, int], list[int]]
    disapprovals: dict[tuple[str, int], list[int]]


def _load_voters(conn: sqlite3.Connection, table: str) -> dict[tuple[str, int], list[int]]:
    voters: dict[tuple[str, int], list[int]] = {}
    for source, source_id, user_id in conn.execute(
        f"SELECT source, source_id, user_id FROM {table}"
    ):
        voters.setdefault((source, source_id), []).append(user_id)
    return voters


def _load_ratings(conn: sqlite3.Connection) -> Ratings:
    praises = {
        (source, source_id): count
        for source, source_id, count in conn.execute(
            "SELECT source, source_id, count FROM praises"
        )
    }
    return Ratings(
        praises=praises,
        praise_users=_load_voters(conn, "praise_users"),
        approvals=_load_voters(conn, "approvals"),
        disapprovals=_load_voters(conn, "disapprovals"),
    )


def _build_item(
    *,
    source: str,
    row_id: int,
    parts: tuple[str, ...],
    author_ids: frozenset[int],
    ratings: Ratings,
    morphemes_json: str | None = None,
    overall_match: float | None = None,
) -> Item:
    key = (source, row_id)
    disapprovers = ratings.disapprovals.get(key, [])
    approvers = ratings.approvals.get(key, [])
    praisers = ratings.praise_users.get(key, [])
    dis_self = sum(1 for v in disapprovers if v in author_ids)
    app_self = sum(1 for v in approvers if v in author_ids)
    return Item(
        id=row_id,
        parts=parts,
        praised=ratings.praises.get(key, 0) > 0,
        other_votes=len(disapprovers) - dis_self,
        self_votes=dis_self,
        morphemes_json=morphemes_json,
        overall_match=overall_match,
        approve_other_votes=len(approvers) - app_self,
        approve_self_votes=app_self,
        rater_ids=frozenset(disapprovers + approvers + praisers) - author_ids,
    )


def load_records(conn: sqlite3.Connection) -> list[Item]:
    """records を Item のリスト(id 昇順)として読み込む。"""
    ratings = _load_ratings(conn)
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
                ratings=ratings,
                morphemes_json=row[7],
                overall_match=row[8],
            )
        )
    return items


def load_chain_records(conn: sqlite3.Connection) -> list[Item]:
    """chain_records を Item のリスト(id 昇順)として読み込む。"""
    ratings = _load_ratings(conn)
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
                ratings=ratings,
            )
        )
    return items


def merge_unique(items: list[Item]) -> list[Item]:
    """同じテキスト(parts)の件を 1 件にまとめる。

    あっぱれの有無は構成レコードの OR、票数は合算、評価した人は和集合とし、再現に使う形態素は id が最大の件のものを使う。
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
                approve_other_votes=sum(i.approve_other_votes for i in group),
                approve_self_votes=sum(i.approve_self_votes for i in group),
                rater_ids=frozenset().union(*(i.rater_ids for i in group)),
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


def _count_ratings(items: list[Item]) -> list[int]:
    counts = Counter(i.rating for i in items)
    return [counts[r] for r in _RATINGS]


def _render_summary(name: str, items: list[Item], *, with_overall_match: bool) -> list[str]:
    head = f"{name}: {len(items)} 件"
    if with_overall_match:
        head += f" (overall_match あり {sum(i.overall_match is not None for i in items)} 件)"
    raters = frozenset().union(*(i.rater_ids for i in items))
    by_rating = " / ".join(
        f"{r}: {n} 件" for r, n in zip(_RATINGS, _count_ratings(items))
    )
    return [
        head,
        f"  {by_rating}",
        f"  評価した人数 (本人を除く): {len(raters)} 人",
        f"  票: あっぱれ付き {sum(i.praised for i in items)} 件"
        f" / 👍 他者 {sum(i.approve_other_votes for i in items)}"
        f" 本人 {sum(i.approve_self_votes for i in items)}"
        f" / 👎 他者 {sum(i.other_votes for i in items)}"
        f" 本人 {sum(i.self_votes for i in items)}",
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
    lines.append("\t".join(["区分", "件数", *_RATINGS]))
    for outcome in _OUTCOMES:
        items = by_outcome[outcome]
        lines.append("\t".join([outcome, str(len(items)), *map(str, _count_ratings(items))]))
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
