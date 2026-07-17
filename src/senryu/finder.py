from dataclasses import dataclass

from .tokenizer import Morpheme

# これらの品詞は単独では文節を開始できず、直前の語に付属して初めて意味を成す
# (例: 「友達と会話」の「と」から始まる句は文法的に浮いていて不自然)。
# 各パートの先頭形態素がこれらの品詞であれば、その分割は句の途中で
# ぶった切っているだけなので候補から除外する。
_NON_STARTING_POS = {"助詞", "助動詞", "接尾辞", "補助記号", "空白"}

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


@dataclass
class Candidate:
    """5-7-5 または 5-7-5-7-7 の部分列候補を表すデータクラス。

    start_idx と end_idx は morphemes リスト内のインデックス範囲。
    text は原文から抽出した完全なテキスト。
    parts は各パートに分割されたテキスト(3要素または5要素)。
    pattern は parts に対応する各パートのモーラ数(例: (5, 7, 5))。
    """

    start_idx: int
    end_idx: int
    text: str
    parts: tuple[str, ...]
    pattern: tuple[int, ...]


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
        parts = tuple(
            text[morphemes[idxs[i]].start:morphemes[idxs[i + 1] - 1].end]
            for i in range(len(idxs) - 1)
        )
        full_text = text[morphemes[idxs[0]].start:morphemes[idxs[-1] - 1].end]
        return [
            Candidate(
                start_idx=idxs[0],
                end_idx=idxs[-1],
                text=full_text,
                parts=parts,
                pattern=full_pattern,
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

    優先順位(README「検出ロジックについて」の代用指標と同一。変更する場合は
    README 側も更新すること):
    1. テキスト長が長いもの(降順)
    2. 形態素数が少ないもの(昇順)
    3. 開始位置が早いもの(昇順)

    返り値: 最適な Candidate、またはリストが空の場合は None。
    """
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda c: (-len(c.text), c.end_idx - c.start_idx, c.start_idx),
    )[0]
