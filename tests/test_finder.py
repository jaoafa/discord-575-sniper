from src.senryu.finder import (
    SENRYU_PATTERN,
    TANKA_PATTERN,
    Candidate,
    find_candidates,
    pick_best,
)
from src.senryu.tokenizer import Morpheme


def _m(surface, mora, start, end, pos=""):
    return Morpheme(surface=surface, reading="", mora=mora, start=start, end=end, pos=pos)


def test_find_candidates_exact_575():
    """形態素列がちょうど五七五になる場合に候補が1件見つかることを確認する。"""
    morphemes = [
        _m("あいうえお", 5, 0, 5),
        _m("かきくけこさし", 7, 5, 12),
        _m("たちつてと", 5, 12, 17),
    ]
    text = "あいうえおかきくけこさしたちつてと"
    candidates = find_candidates(morphemes, text)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.parts == ("あいうえお", "かきくけこさし", "たちつてと")
    assert c.text == text
    assert c.pattern == SENRYU_PATTERN


def test_find_candidates_no_match():
    """五七五を構成できない形態素列では候補が見つからないことを確認する。"""
    morphemes = [_m("あいう", 3, 0, 3)]
    text = "あいう"
    assert find_candidates(morphemes, text) == []


def test_find_candidates_within_longer_message():
    """前後に余分な語句を含む長いメッセージの中からも五七五の部分を検出できることを確認する。"""
    morphemes = [
        _m("ねえ", 2, 0, 2),
        _m("あいうえお", 5, 2, 7),
        _m("かきくけこさし", 7, 7, 14),
        _m("たちつてと", 5, 14, 19),
        _m("だよ", 2, 19, 21),
    ]
    text = "ねえあいうえおかきくけこさしたちつてとだよ"
    candidates = find_candidates(morphemes, text)
    assert len(candidates) == 1
    assert candidates[0].parts == ("あいうえお", "かきくけこさし", "たちつてと")


def test_find_candidates_excludes_part_starting_with_particle():
    """各パートの先頭が助詞の候補は不自然な句切りとして除外されることを確認する。"""
    morphemes = [
        _m("あい", 2, 0, 2, pos="動詞"),
        _m("うえおかき", 5, 2, 7, pos="助詞"),  # 助詞始まりなので part1 として不成立
        _m("くけこさしすせ", 7, 7, 14, pos="名詞"),
        _m("そたちつて", 5, 14, 19, pos="名詞"),
    ]
    text = "あいうえおかきくけこさしすせそたちつて"
    candidates = find_candidates(morphemes, text)
    assert candidates == []


def test_find_candidates_excludes_middle_part_starting_with_auxiliary_verb():
    """part2/part3 の先頭が助動詞など付属語の候補も除外されることを確認する。"""
    morphemes = [
        _m("あいうえお", 5, 0, 5, pos="名詞"),
        _m("か", 1, 5, 6, pos="助動詞"),  # part2 が助動詞始まりなので不成立
        _m("きくけこさし", 6, 6, 12, pos="名詞"),
        _m("たちつてと", 5, 12, 17, pos="名詞"),
    ]
    text = "あいうえおかきくけこさしたちつてと"
    candidates = find_candidates(morphemes, text)
    assert candidates == []


def test_find_candidates_exact_57577():
    """形態素列がちょうど五七五七七になる場合に短歌候補が1件見つかることを確認する。"""
    morphemes = [
        _m("あいうえお", 5, 0, 5),
        _m("かきくけこさし", 7, 5, 12),
        _m("たちつてと", 5, 12, 17),
        _m("なにぬねのはひ", 7, 17, 24),
        _m("ふへほまみむめ", 7, 24, 31),
    ]
    text = "あいうえおかきくけこさしたちつてとなにぬねのはひふへほまみむめ"
    candidates = find_candidates(morphemes, text)
    tanka_candidates = [c for c in candidates if c.pattern == TANKA_PATTERN]
    assert len(tanka_candidates) == 1
    assert tanka_candidates[0].parts == (
        "あいうえお",
        "かきくけこさし",
        "たちつてと",
        "なにぬねのはひ",
        "ふへほまみむめ",
    )
    assert tanka_candidates[0].text == text


def test_find_candidates_mixed_patterns_include_both_senryu_and_tanka():
    """短歌候補の先頭部分だけでも五七五として成立する場合、両方の候補が見つかることを確認する。"""
    morphemes = [
        _m("あいうえお", 5, 0, 5),
        _m("かきくけこさし", 7, 5, 12),
        _m("たちつてと", 5, 12, 17),
        _m("なにぬねのはひ", 7, 17, 24),
        _m("ふへほまみむめ", 7, 24, 31),
    ]
    text = "あいうえおかきくけこさしたちつてとなにぬねのはひふへほまみむめ"
    candidates = find_candidates(morphemes, text)
    patterns_found = {c.pattern for c in candidates}
    assert patterns_found == {SENRYU_PATTERN, TANKA_PATTERN}


def test_pick_best_prefers_tanka_over_senryu_substring():
    """五七五・五七五七七の両方が候補にある場合、pick_best がテキストの長い短歌側を選ぶことを確認する。"""
    morphemes = [
        _m("あいうえお", 5, 0, 5),
        _m("かきくけこさし", 7, 5, 12),
        _m("たちつてと", 5, 12, 17),
        _m("なにぬねのはひ", 7, 17, 24),
        _m("ふへほまみむめ", 7, 24, 31),
    ]
    text = "あいうえおかきくけこさしたちつてとなにぬねのはひふへほまみむめ"
    candidates = find_candidates(morphemes, text)
    best = pick_best(candidates)
    assert best.pattern == TANKA_PATTERN


def test_pick_best_prefers_longer_text_span():
    """pick_best がテキスト長がより長い候補を優先して選ぶことを確認する。"""
    short = Candidate(
        start_idx=0, end_idx=1, text="ああ", parts=("あ", "あ", "あ"), pattern=SENRYU_PATTERN
    )
    long = Candidate(
        start_idx=0, end_idx=1, text="ああああああ", parts=("ああ", "ああ", "ああ"), pattern=SENRYU_PATTERN
    )
    assert pick_best([short, long]) is long


def test_pick_best_prefers_fewer_morphemes_on_tie_length():
    """テキスト長が同じ場合、pick_best が形態素数の少ない候補を優先することを確認する。"""
    fewer = Candidate(
        start_idx=0, end_idx=2, text="ああああ", parts=("あ", "あ", "ああ"), pattern=SENRYU_PATTERN
    )
    more = Candidate(
        start_idx=0, end_idx=4, text="ああああ", parts=("あ", "あ", "ああ"), pattern=SENRYU_PATTERN
    )
    assert pick_best([more, fewer]) is fewer


def test_pick_best_returns_none_for_empty_list():
    """候補リストが空の場合 pick_best が None を返すことを確認する。"""
    assert pick_best([]) is None
