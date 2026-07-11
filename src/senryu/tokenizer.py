from dataclasses import dataclass

from sudachipy import Dictionary, SplitMode

from .mora import count_mora

_tokenizer_obj = Dictionary().create()


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
        morphemes.append(
            Morpheme(
                surface=surface,
                reading=reading,
                mora=count_mora(reading),
                start=m.begin(),
                end=m.end(),
                pos=m.part_of_speech()[0],
            )
        )
    return morphemes
