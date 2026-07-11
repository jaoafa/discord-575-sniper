from src.senryu.finder import Candidate, find_candidates, pick_best
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


def test_pick_best_prefers_longer_text_span():
    """pick_best がテキスト長がより長い候補を優先して選ぶことを確認する。"""
    short = Candidate(start_idx=0, end_idx=1, text="ああ", parts=("あ", "あ", "あ"))
    long = Candidate(start_idx=0, end_idx=1, text="ああああああ", parts=("ああ", "ああ", "ああ"))
    assert pick_best([short, long]) is long


def test_pick_best_prefers_fewer_morphemes_on_tie_length():
    """テキスト長が同じ場合、pick_best が形態素数の少ない候補を優先することを確認する。"""
    fewer = Candidate(start_idx=0, end_idx=2, text="ああああ", parts=("あ", "あ", "ああ"))
    more = Candidate(start_idx=0, end_idx=4, text="ああああ", parts=("あ", "あ", "ああ"))
    assert pick_best([more, fewer]) is fewer


def test_pick_best_returns_none_for_empty_list():
    """候補リストが空の場合 pick_best が None を返すことを確認する。"""
    assert pick_best([]) is None
