from src.senryu.mora import count_mora


def test_basic_katakana():
    """通常のカタカナ読みのモーラ数が文字数どおりに数えられることを確認する。"""
    assert count_mora("トンボ") == 3


def test_long_vowel():
    """長音符「ー」が1モーラとして数えられることを確認する。"""
    assert count_mora("ラーメン") == 4


def test_small_you_on():
    """拗音(捨て仮名)が前の文字と合わせて1モーラに数えられることを確認する。"""
    assert count_mora("キャベツ") == 3


def test_small_vowel_extension():
    """小さい母音字が前の文字と合わせて1モーラに数えられることを確認する。"""
    assert count_mora("ファイル") == 3


def test_sokuon():
    """促音「ッ」が1モーラとして数えられることを確認する。"""
    assert count_mora("キップ") == 3


def test_empty_reading():
    """空文字列の読みでモーラ数が0になることを確認する。"""
    assert count_mora("") == 0


def test_count_mora_punctuation_is_zero():
    """句読点や感嘆符のみの読みではモーラ数が0になることを確認する。"""
    assert count_mora("。") == 0
    assert count_mora("、") == 0
    assert count_mora("！") == 0


def test_count_mora_emoji_is_zero():
    """絵文字のみの読みではモーラ数が0になることを確認する。"""
    assert count_mora("😀") == 0


def test_count_mora_katakana_block_symbols_are_zero():
    """Unicode のカタカナブロックに含まれるが実際のカタカナではない記号
    (中点・繰り返し記号など)がモーラ数0になることを確認する。
    """
    assert count_mora("・") == 0
    assert count_mora("゠") == 0
    assert count_mora("ヽ") == 0
    assert count_mora("ヾ") == 0
    assert count_mora("ヿ") == 0


def test_count_mora_ignores_middle_dot_between_katakana():
    """カタカナ語中の中点「・」がモーラとして数えられないことを確認する
    (例: 「ハリー・ポッター」は 3+0+4=7 モーラ)。
    """
    assert count_mora("ハリー・ポッター") == 7
