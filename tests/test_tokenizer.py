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


def test_tokenize_space_morpheme_has_zero_mora():
    """空白形態素(pos="空白")のモーラ数が0として扱われることを確認する(Issue #8)。"""
    morphemes = tokenize("並べる。 それだけで、")
    space_morphemes = [m for m in morphemes if m.pos == "空白"]
    assert space_morphemes, "expected at least one space morpheme"
    assert all(m.mora == 0 for m in space_morphemes)


def test_tokenize_placeholder_symbol_has_zero_mora():
    """読みが不明な補助記号(→★○♡など)のモーラ数が0として扱われることを確認する。"""
    for symbol in "→★○♡":
        morphemes = tokenize(f"好き{symbol}です")
        symbol_morphemes = [m for m in morphemes if m.surface == symbol]
        assert symbol_morphemes, f"expected a morpheme for {symbol!r}"
        assert all(m.mora == 0 for m in symbol_morphemes), symbol


def test_tokenize_word_kigou_keeps_real_mora_count():
    """実在する単語「記号」(名詞、キゴウ=3モーラ)は正しくカウントされることを確認する。

    プレースホルダー判定は pos が空白・補助記号の場合に限定されるため、
    名詞「記号」自体は誤って0モーラ扱いされない。
    """
    morphemes = tokenize("記号")
    assert len(morphemes) == 1
    assert morphemes[0].pos == "名詞"
    assert morphemes[0].mora == 3
