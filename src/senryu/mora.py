from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from .tokenizer import Morpheme

_SMALL_KANA = set("ャュョァィゥェォ")

# カタカナ(全角)の Unicode 範囲。ー(長音記号, U+30FC)もこの範囲に含まれる。
_KATAKANA_RANGE = (0x30A0, 0x30FF)

# _KATAKANA_RANGE 内だがモーラを構成しない記号。
# ゠(U+30A0, 半濁点結合用)・・(U+30FB, 中点)・ヽヾ(U+30FD/30FE, 繰り返し記号)・
# ヿ(U+30FF)は Unicode の「カタカナ」ブロックに含まれるが実際のカタカナ文字ではない。
_NON_MORAIC_IN_RANGE = set("゠・ヽヾヿ")


def _is_katakana(ch: str) -> bool:
    """文字が実際のカタカナ(長音記号ーを含み、モーラを構成しない記号を除く)かどうかを判定する。"""
    if ch in _NON_MORAIC_IN_RANGE:
        return False
    return _KATAKANA_RANGE[0] <= ord(ch) <= _KATAKANA_RANGE[1]


def count_mora(reading: str) -> int:
    """カタカナ読み文字列のモーラ(拍)数を数える。

    促音(ッ)・撥音(ン)・長音(ー)はそれぞれ独立した1モーラとしてカウントする。
    拗音・外来語拡張用の小書き文字(_SMALL_KANA に定義)は直前の文字と合わせて
    1モーラとし、単独ではカウントしない。
    読みが取得できない記号・数字・絵文字などは SudachiPy が読みとして表層文字をそのまま返す
    ことがあるため、実際のカタカナ以外の文字はモーラ数0として扱う。
    """
    count = 0
    for ch in reading:
        if not _is_katakana(ch):
            continue
        if ch in _SMALL_KANA:
            continue
        count += 1
    return count


def total_mora(morphemes: "Sequence[Morpheme]") -> int:
    """形態素列全体の総モーラ数を求める。

    各形態素の mora フィールド(tokenize() が count_mora() で算出済み)を合算するだけで、読み文字列を再解析しない。
    """
    return sum(m.mora for m in morphemes)
