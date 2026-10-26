from src.senryu.finder import (
    BASE_SCORE,
    BREAK_IN_PART_PENALTY,
    COVERAGE_WEIGHT,
    EDGE_BONUS,
    MIN_SCORE,
    SENRYU_PATTERN,
    TANKA_PATTERN,
    Candidate,
    find_candidates,
    pick_best,
    score_candidate,
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


def test_find_candidates_excludes_window_containing_unknown_mora_word():
    """未知語などで mora=0 になった名詞を含む区間は、モーラ不足を補って
    5-7-5 に収まってしまっても候補から除外されることを確認する。"""
    morphemes = [
        _m("あいうえお", 5, 0, 5, pos="名詞"),
        _m("かきくけこさし", 7, 5, 12, pos="名詞"),
        _m("Vlog", 0, 12, 16, pos="名詞"),  # 読みが取得できず mora=0 の未知語
        _m("たちつてと", 5, 16, 21, pos="名詞"),
    ]
    text = "あいうえおかきくけこさしVlogたちつてと"
    candidates = find_candidates(morphemes, text)
    assert candidates == []


def test_find_candidates_allows_window_containing_zero_mora_symbol():
    """補助記号・空白による mora=0 は既存どおり除外対象にならず、
    かつその文字自体は検出結果テキストから除去されることを確認する。

    空白は can_start_part() によりパート先頭になれないため、
    直前のパートに取り込まれた形で候補が成立する。
    """
    morphemes = [
        _m("あいうえお", 5, 0, 5, pos="名詞"),
        _m("かきくけこさし", 7, 5, 12, pos="名詞"),
        _m("　", 0, 12, 13, pos="空白"),
        _m("たちつてと", 5, 13, 18, pos="名詞"),
    ]
    text = "あいうえおかきくけこさし　たちつてと"
    candidates = find_candidates(morphemes, text)
    assert len(candidates) == 1
    assert candidates[0].parts == ("あいうえお", "かきくけこさし", "たちつてと")
    assert candidates[0].text == "あいうえおかきくけこさしたちつてと"


def test_find_candidates_strips_zero_mora_symbol_from_middle_of_part():
    """パート内部に挟まった補助記号(句読点など)が検出結果テキストから除去されることを確認する。"""
    morphemes = [
        _m("あい", 2, 0, 2, pos="名詞"),
        _m("、", 0, 2, 3, pos="補助記号"),
        _m("うえお", 3, 3, 6, pos="名詞"),
        _m("かきくけこさし", 7, 6, 13, pos="名詞"),
        _m("たちつてと", 5, 13, 18, pos="名詞"),
    ]
    text = "あい、うえおかきくけこさしたちつてと"
    candidates = find_candidates(morphemes, text)
    assert len(candidates) == 1
    assert candidates[0].parts == ("あいうえお", "かきくけこさし", "たちつてと")
    assert candidates[0].text == "あいうえおかきくけこさしたちつてと"


def _r(surface, mora, reading="", pos="名詞"):
    return Morpheme(surface=surface, reading=reading, mora=mora, start=0, end=len(surface), pos=pos)


def _brk(surface="、"):
    return _r(surface, 0, reading=surface, pos="補助記号")


def test_sokuon_only_part_is_excluded():
    """「っ」だけで音数を満たす句を含む候補は採用されないことを確認する。"""
    morphemes = [
        _r("っっっっっ", 5, reading="ッッッッッ", pos="記号"),
        _r("かきくけこさし", 7),
        _r("たちつてと", 5),
    ]
    assert find_candidates(morphemes, "") == []


def test_word_internal_sokuon_is_kept():
    """「きっぷ」のように語中に促音を含む句は従来どおり候補になることを確認する。"""
    morphemes = [
        _r("きっぷ", 3, reading="キップ"),
        _r("あい", 2),
        _r("かきくけこさし", 7),
        _r("たちつてと", 5),
    ]
    candidates = find_candidates(morphemes, "")
    assert len(candidates) == 1
    assert candidates[0].parts[0] == "きっぷあい"


def test_clean_candidate_scores_higher_than_inner_break_candidate():
    """句内に区切りが無い候補のスコアが、句内に区切りを含む候補より高いことを確認する。"""
    clean = [_r("あいうえお", 5), _r("かきくけこさし", 7), _r("たちつてと", 5)]
    broken = [_r("あい", 2), _brk(), _r("うえお", 3), _r("かきくけこさし", 7), _r("たちつてと", 5)]
    clean_score, _ = score_candidate(clean, [(0, 1), (1, 2), (2, 3)])
    broken_score, _ = score_candidate(broken, [(0, 3), (3, 4), (4, 5)])
    assert clean_score == BASE_SCORE + COVERAGE_WEIGHT + 2 * EDGE_BONUS
    assert broken_score == clean_score - BREAK_IN_PART_PENALTY


def test_single_inner_break_candidate_is_still_detected():
    """句内に区切りがちょうど1つだけの有効な候補は、他に候補が無ければ採用されることを確認する。"""
    morphemes = [_r("あい", 2), _brk(), _r("うえお", 3), _r("かきくけこさし", 7), _r("たちつてと", 5)]
    best = pick_best(find_candidates(morphemes, ""))
    assert best is not None
    assert best.parts == ("あいうえお", "かきくけこさし", "たちつてと")


def test_two_inner_breaks_weak_candidate_is_rejected():
    """句内区切りが2つ以上で、全体一致度が低く両端も整列していない候補は棄却されることを確認する。"""
    core = [
        _r("あ", 1), _brk(), _r("い", 1), _brk(), _r("うえお", 3),
        _r("かきくけこさし", 7), _r("たちつてと", 5),
    ]
    weak = [_r("あ" * 10, 10)] + core + [_r("い" * 10, 10)]
    assert pick_best(find_candidates(weak, "")) is None
    # 同じ候補でも、メッセージ全体と一致していれば採用される。
    assert pick_best(find_candidates(core, "")) is not None


def test_newline_counts_as_break():
    """改行(空白形態素の \\n)も句内の区切りとして数えられることを確認する。"""
    newline = _r("\n", 0, reading="\n", pos="空白")
    morphemes = [_r("あい", 2), newline, _r("うえお", 3), _r("かきくけこさし", 7), _r("たちつてと", 5)]
    score, _ = score_candidate(morphemes, [(0, 3), (3, 4), (4, 5)])
    assert score == BASE_SCORE + COVERAGE_WEIGHT + 2 * EDGE_BONUS - BREAK_IN_PART_PENALTY


def test_break_at_end_of_part_is_not_penalized():
    """パート末尾側に付く区切り(自然な句切れ)は減点されないことを確認する。"""
    morphemes = [_r("あいうえお", 5), _brk(), _r("かきくけこさし", 7), _r("たちつてと", 5)]
    score, _ = score_candidate(morphemes, [(0, 2), (2, 3), (3, 4)])
    assert score == BASE_SCORE + COVERAGE_WEIGHT + 2 * EDGE_BONUS


def test_particle_ending_is_not_penalized():
    """助詞で終わる候補が、他の条件が同じ名詞終わりの候補と同じスコアになることを確認する。"""
    noun_end = [_r("あいうえお", 5), _r("かきくけこさし", 7), _r("たちつてと", 5)]
    particle_end = [_r("あいうえお", 5), _r("かきくけこさし", 7), _r("たちつてと", 5, pos="助詞")]
    ranges = [(0, 1), (1, 2), (2, 3)]
    assert score_candidate(noun_end, ranges) == score_candidate(particle_end, ranges)


def test_pick_best_prefers_higher_score_over_longer_text():
    """文字列長より score を優先して選ぶことを確認する。"""
    low = Candidate(0, 3, "あいうえおかきくけこさしたちつてと", ("a", "b", "c"), SENRYU_PATTERN, score=0.4)
    high = Candidate(5, 8, "短い", ("a", "b", "c"), SENRYU_PATTERN, score=0.9)
    assert pick_best([low, high]) is high


def test_pick_best_rejects_candidates_below_min_score():
    """MIN_SCORE 未満の候補しか無ければ None を返すことを確認する。"""
    c = Candidate(0, 3, "あ", ("a", "b", "c"), SENRYU_PATTERN, score=MIN_SCORE - 0.01)
    assert pick_best([c]) is None
