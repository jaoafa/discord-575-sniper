from dataclasses import dataclass

from sudachipy import Dictionary, SplitMode

from .mora import count_mora

_tokenizer_obj = Dictionary().create()

# SudachiPyは読みを特定できない空白・記号(スペース、→★○♡など)に対して
# reading="キゴウ"(「記号」のカタカナ表記)という汎用プレースホルダーを返す。
# これはカタカナ3文字からなるため count_mora() にかけると実際には発音されない
# はずの1文字が3モーラとして誤加算されてしまう。
# この現象が起こりうる品詞(空白・補助記号)に限定してプレースホルダー読みを
# 検出し、モーラ数0として扱う。名詞「記号」(きごう)など実際に読みが
# "キゴウ"になる正当な語は pos が異なるため対象外。
_SYMBOL_LIKE_POS = {"空白", "補助記号"}
_PLACEHOLDER_READING = "キゴウ"


@dataclass
class Morpheme:
    """SudachiPyで解析した1形態素の情報を保持するデータクラス。

    start/end はサニタイズ済みテキスト内の文字オフセット。
    pos は品詞の大分類(例: "名詞" "助詞")。5-7-5 各パートの開始位置として
    不自然な品詞(助詞・助動詞など)を除外する判定に使う。
    """

    surface: str
    reading: str
    mora: int
    start: int
    end: int
    pos: str = ""


def tokenize(text: str) -> list["Morpheme"]:
    """テキストを形態素解析し、Morpheme のリストを返す。

    SplitMode.C(最も長い単位)で分割する。空文字列の場合は空リストを返す。
    """
    if not text:
        return []
    morphemes = []
    for m in _tokenizer_obj.tokenize(text, SplitMode.C):
        surface = m.surface()
        reading = m.reading_form()
        pos = m.part_of_speech()[0]
        is_placeholder_reading = pos in _SYMBOL_LIKE_POS and reading == _PLACEHOLDER_READING
        mora = 0 if is_placeholder_reading else count_mora(reading)
        morphemes.append(
            Morpheme(
                surface=surface,
                reading=reading,
                mora=mora,
                start=m.begin(),
                end=m.end(),
                pos=pos,
            )
        )
    return morphemes
