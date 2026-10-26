from dataclasses import dataclass

from .tokenizer import Morpheme

# これらの品詞は単独では文節を開始できず、直前の語に付属して初めて意味を成す
# (例: 「友達と会話」の「と」から始まる句は文法的に浮いていて不自然)。
# 各パートの先頭形態素がこれらの品詞であれば、その分割は句の途中で
# ぶった切っているだけなので候補から除外する。
_NON_STARTING_POS = {"助詞", "助動詞", "接尾辞", "補助記号", "空白"}

# mora=0 は本来「補助記号」「空白」(記号・プレースホルダー読み)でのみ発生する想定だが、
# 未知語(英単語など)や非日本語文字は読みが取得できず同じく mora=0 になる。
# これらは prefix sum 上で透明な存在として扱われ、モーラ不足を補って
# 5-7-5 に収まってしまう false positive の原因になるため、
# この品詞集合に含まれない mora=0 形態素を含む候補は除外する。
_ZERO_MORA_IGNORE_POS = {"補助記号", "空白"}

# 候補の「質」を決めるスコア(0.0〜1.0 付近)の定数。句読点・改行・全体一致度は
# あくまでソフトな手掛かりで、単独では候補を禁止しない(句内区切りがちょうど1つだけの
# 候補は MIN_SCORE を下回らない)。値は暫定で、records.score と評価データを見て調整する。
BASE_SCORE = 0.5
COVERAGE_WEIGHT = 0.3
EDGE_BONUS = 0.1
BREAK_IN_PART_PENALTY = 0.2
MIN_SCORE = 0.3

# 句の切れ目の手掛かりになる記号。改行は surface に \n を含む空白形態素で判定する。
_BREAK_CHARS = set("、。,.，．!?！？…‥")

# find_candidates が探索する音数パターン(各要素は1パートあたりのモーラ数)。
SENRYU_PATTERN: tuple[int, ...] = (5, 7, 5)
TANKA_PATTERN: tuple[int, ...] = (5, 7, 5, 7, 7)
DEFAULT_PATTERNS: tuple[tuple[int, ...], ...] = (SENRYU_PATTERN, TANKA_PATTERN)


def can_start_part(m: Morpheme) -> bool:
    """形態素が各パートの先頭になり得るかどうかを判定する。

    単一メッセージ内探索(本モジュール)と複数メッセージ結合探索(chain.py)の
    両方から使う共通の判定なので、モジュール非公開名にしていない。
    """
    return m.pos not in _NON_STARTING_POS


def has_unknown_mora_word(morphemes: list[Morpheme]) -> bool:
    """読みが取得できず mora=0 になった、記号・空白以外の形態素が含まれるかを判定する。

    単一メッセージ内探索(本モジュール)と複数メッセージ結合探索(chain.py)の
    両方から使う共通の判定なので、モジュール非公開名にしていない。
    """
    return any(
        m.mora == 0 and m.pos not in _ZERO_MORA_IGNORE_POS
        for m in morphemes
    )


def has_substantive_mora(morphemes: list[Morpheme]) -> bool:
    """促音(ッ)以外のモーラを持つ形態素が含まれるかを判定する。

    「っ」だけの並びは発音として成立しないため、各パートがこれに該当すれば候補から除外する。
    「きっぷ」のように語中の促音は、他のモーラがあるため該当しない。
    単一メッセージ内探索(本モジュール)と複数メッセージ結合探索(chain.py)の
    両方から使う共通の判定なので、モジュール非公開名にしていない。
    """
    return any(m.mora - m.reading.count("ッ") > 0 for m in morphemes if m.mora > 0)


def _is_break(m: Morpheme) -> bool:
    """形態素が句読点または改行(句の切れ目の手掛かり)かどうかを判定する。"""
    return "\n" in m.surface or (m.pos == "補助記号" and m.surface in _BREAK_CHARS)


def _is_boundary(m: Morpheme) -> bool:
    """形態素が区切りまたは空白(句の境界の手掛かり)かどうかを判定する。"""
    return _is_break(m) or m.pos == "空白"


def score_candidate(
    morphemes: list[Morpheme], part_ranges: list[tuple[int, int]]
) -> tuple[float, float]:
    """候補の質を表す (score, coverage) を求める。

    part_ranges は各パートの形態素範囲 [start, end)。coverage は候補の総モーラ数を
    morphemes 全体の総モーラ数で割った値(全体が0モーラなら1.0)。
    score は coverage が高いほど、候補の先頭・末尾が文や句の境界に揃っているほど高く、
    パートの途中に句読点・改行が入っているほど低い。助詞・助動詞で終わるかどうかは見ない。
    単一メッセージ内探索(本モジュール)と複数メッセージ結合探索(chain.py)の
    両方から使う共通の判定なので、モジュール非公開名にしていない。
    """
    total = sum(m.mora for m in morphemes)
    span = sum(m.mora for s, e in part_ranges for m in morphemes[s:e])
    coverage = span / total if total else 1.0

    inner_breaks = 0
    for s, e in part_ranges:
        # パート末尾側に付く区切りは自然な句切れなので、先頭・末尾の mora=0 を除いて数える。
        while s < e and morphemes[s].mora == 0:
            s += 1
        while e > s and morphemes[e - 1].mora == 0:
            e -= 1
        inner_breaks += sum(_is_break(m) for m in morphemes[s:e])

    first = part_ranges[0][0]
    start_aligned = first == 0 or _is_boundary(morphemes[first - 1])
    last_start, last_end = part_ranges[-1]
    while last_end > last_start and morphemes[last_end - 1].mora == 0:
        last_end -= 1
    end_aligned = last_end >= len(morphemes) or _is_boundary(morphemes[last_end])

    score = (
        BASE_SCORE
        + COVERAGE_WEIGHT * coverage
        + EDGE_BONUS * (start_aligned + end_aligned)
        - BREAK_IN_PART_PENALTY * inner_breaks
    )
    return score, coverage


def _join_surface(morphemes: list[Morpheme], start: int, end: int) -> str:
    """指定範囲の形態素から、mora=0(記号・空白)の形態素を除いた表層文字列を連結する。

    has_unknown_mora_word() のチェックを通過済みの区間であることが前提であり、
    その場合に残る mora=0 形態素は記号・空白品詞のみであることが保証されている。
    """
    return "".join(m.surface for m in morphemes[start:end] if m.mora > 0)


@dataclass
class Candidate:
    """5-7-5 または 5-7-5-7-7 の部分列候補を表すデータクラス。

    start_idx と end_idx は morphemes リスト内のインデックス範囲。
    text は parts を連結したテキストで、mora=0(記号・空白)の形態素は除去済みのため、
    原文の該当区間をそのまま抜き出した部分文字列とは限らない。
    parts は各パートに分割されたテキスト(3要素または5要素)。
    pattern は parts に対応する各パートのモーラ数(例: (5, 7, 5))。
    score / coverage は score_candidate() が求めた質の指標(詳細はそちらを参照)。
    """

    start_idx: int
    end_idx: int
    text: str
    parts: tuple[str, ...]
    pattern: tuple[int, ...]
    score: float = 1.0
    coverage: float = 1.0


def _find_from(
    morphemes: list[Morpheme],
    prefix: list[int],
    text: str,
    start: int,
    remaining_pattern: tuple[int, ...],
    part_starts: list[int],
    full_pattern: tuple[int, ...],
) -> list[Candidate]:
    """remaining_pattern の残りパートを start から再帰的に探索する。

    part_starts は確定済みの各パート開始インデックスの累積リスト。
    remaining_pattern は再帰のたびに先頭要素が削られていく残りパート、
    full_pattern は再帰全体を通じて変化しない探索対象パターン全体
    (Candidate.pattern に設定する値)。
    """
    if not remaining_pattern:
        idxs = part_starts + [start]
        if has_unknown_mora_word(morphemes[idxs[0]:idxs[-1]]):
            return []
        part_ranges = [(idxs[i], idxs[i + 1]) for i in range(len(idxs) - 1)]
        if not all(has_substantive_mora(morphemes[s:e]) for s, e in part_ranges):
            return []
        parts = tuple(_join_surface(morphemes, s, e) for s, e in part_ranges)
        full_text = "".join(parts)
        score, coverage = score_candidate(morphemes, part_ranges)
        return [
            Candidate(
                start_idx=idxs[0],
                end_idx=idxs[-1],
                text=full_text,
                parts=parts,
                pattern=full_pattern,
                score=score,
                coverage=coverage,
            )
        ]

    if not can_start_part(morphemes[start]):
        return []

    n = len(morphemes)
    target = remaining_pattern[0]
    is_last_part = len(remaining_pattern) == 1
    results = []
    for end in range(start + 1, n + 1):
        # prefix はモーラ数(常に非負)の累積和なので end を増やすほど広義単調増加する。
        # target を超えたら以降の end でも二度と target に戻らないため break で打ち切れる。
        s = prefix[end] - prefix[start]
        if s < target:
            continue
        if s > target:
            break
        if not is_last_part and end >= n:
            continue
        results.extend(
            _find_from(
                morphemes,
                prefix,
                text,
                end,
                remaining_pattern[1:],
                part_starts + [start],
                full_pattern,
            )
        )
    return results


def find_candidates(
    morphemes: list[Morpheme],
    text: str,
    patterns: tuple[tuple[int, ...], ...] = DEFAULT_PATTERNS,
) -> list[Candidate]:
    """形態素リストから patterns に含まれる各音数パターンの部分列候補をすべて探索する。

    morphemes: 形態素のリスト。mora フィールドが設定されていること。
    text: 元のテキスト文字列。start/end の参照に使用。
    patterns: 探索する音数パターンのタプル。デフォルトは 5-7-5(川柳)と
        5-7-5-7-7(短歌)の両方。

    返り値: 見つかった Candidate オブジェクトのリスト。
    """
    n = len(morphemes)
    if n == 0:
        return []

    prefix = [0] * (n + 1)
    for idx, m in enumerate(morphemes):
        prefix[idx + 1] = prefix[idx] + m.mora

    candidates = []
    for pattern in patterns:
        for i in range(n):
            candidates.extend(_find_from(morphemes, prefix, text, i, pattern, [], pattern))
    return candidates


def pick_best(candidates: list[Candidate]) -> Candidate | None:
    """複数の候補から最適なものを1つ選ぶ。

    score が MIN_SCORE 未満の候補は対象外とする。残りを次の優先順位で選ぶ
    (README「検出ロジックについて」の代用指標と同一。変更する場合は README 側も更新すること):
    1. score が高いもの(降順)
    2. テキスト長が長いもの(降順)
    3. 形態素数が少ないもの(昇順)
    4. 開始位置が早いもの(昇順)

    返り値: 最適な Candidate、または対象の候補が無い場合は None。
    """
    eligible = [c for c in candidates if c.score >= MIN_SCORE]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda c: (-c.score, -len(c.text), c.end_idx - c.start_idx, c.start_idx),
    )[0]
