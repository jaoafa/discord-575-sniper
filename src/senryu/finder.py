from dataclasses import dataclass

from .tokenizer import Morpheme

# これらの品詞は単独では文節を開始できず、直前の語に付属して初めて意味を成す
# (例: 「友達と会話」の「と」から始まる句は文法的に浮いていて不自然)。
# 5-7-5 各パートの先頭形態素がこれらの品詞であれば、その分割は句の途中で
# ぶった切っているだけなので候補から除外する。
_NON_STARTING_POS = {"助詞", "助動詞", "接尾辞", "補助記号", "空白"}


def _can_start_part(m: Morpheme) -> bool:
    """形態素が 5-7-5 の各パートの先頭になり得るかどうかを判定する。"""
    return m.pos not in _NON_STARTING_POS


@dataclass
class Candidate:
    """5-7-5 の部分列候補を表すデータクラス。

    start_idx と end_idx は morphemes リスト内のインデックス範囲。
    text は原文から抽出した完全なテキスト。
    parts は(5音, 7音, 5音)の3つ部分に分割されたテキスト。
    """

    start_idx: int
    end_idx: int
    text: str
    parts: tuple[str, str, str]


def find_candidates(morphemes: list[Morpheme], text: str) -> list[Candidate]:
    """形態素リストから 5-7-5 部分列の候補をすべて探索する。

    morphemes: 形態素のリスト。mora フィールドが設定されていること。
    text: 元のテキスト文字列。start/end の参照に使用。

    返り値: 見つかった Candidate オブジェクトのリスト。
    """
    n = len(morphemes)
    if n == 0:
        return []

    prefix = [0] * (n + 1)
    for idx, m in enumerate(morphemes):
        prefix[idx + 1] = prefix[idx] + m.mora

    def mora_sum(i: int, j: int) -> int:
        """形態素インデックス i から j 直前までのモーラ数の合計を返す。"""
        return prefix[j] - prefix[i]

    candidates = []
    for i in range(n):
        if not _can_start_part(morphemes[i]):
            continue
        for j in range(i + 1, n + 1):
            # mora_sum は mora(常に非負)の累積和なので j を増やすほど広義単調増加する。
            # 5 を超えたら以降の j でも二度と 5 に戻らないため break で打ち切れる。
            s1 = mora_sum(i, j)
            if s1 < 5:
                continue
            if s1 > 5:
                break
            if j >= n or not _can_start_part(morphemes[j]):
                continue
            for k in range(j + 1, n + 1):
                s2 = mora_sum(j, k)
                if s2 < 7:
                    continue
                if s2 > 7:
                    break
                if k >= n or not _can_start_part(morphemes[k]):
                    continue
                for m in range(k + 1, n + 1):
                    s3 = mora_sum(k, m)
                    if s3 < 5:
                        continue
                    if s3 > 5:
                        break
                    part1 = text[morphemes[i].start:morphemes[j - 1].end]
                    part2 = text[morphemes[j].start:morphemes[k - 1].end]
                    part3 = text[morphemes[k].start:morphemes[m - 1].end]
                    full_text = text[morphemes[i].start:morphemes[m - 1].end]
                    candidates.append(
                        Candidate(
                            start_idx=i,
                            end_idx=m,
                            text=full_text,
                            parts=(part1, part2, part3),
                        )
                    )
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
