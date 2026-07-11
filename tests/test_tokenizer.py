from src.senryu.tokenizer import tokenize


def test_tokenize_basic():
    """トークン化した表層形を連結すると元のテキストに一致し、モーラ数が非負であることを確認する。"""
    morphemes = tokenize("古池や")
    surfaces = [m.surface for m in morphemes]
    assert "".join(surfaces) == "古池や"
    assert all(m.mora >= 0 for m in morphemes)


def test_tokenize_spans_reconstruct_text():
    """各形態素の start/end が元テキストの対応する部分文字列を正しく指すことを確認する。"""
    text = "蛙飛び込む水の音"
    morphemes = tokenize(text)
    for m in morphemes:
        assert text[m.start:m.end] == m.surface


def test_tokenize_empty_string():
    """空文字列をトークン化すると空リストが返ることを確認する。"""
    assert tokenize("") == []


def test_tokenize_furuikeya_is_five_mora_total():
    """「古池や」の全形態素のモーラ数合計が5になることを確認する。"""
    # 「古池や」は フルイケヤ = 5モーラ
    morphemes = tokenize("古池や")
    assert sum(m.mora for m in morphemes) == 5


def test_tokenize_sets_pos():
    """各形態素に品詞の大分類(pos)が設定されることを確認する。"""
    morphemes = tokenize("友達と会話")
    pos_by_surface = {m.surface: m.pos for m in morphemes}
    assert pos_by_surface["と"] == "助詞"
    assert pos_by_surface["会話"] == "名詞"
