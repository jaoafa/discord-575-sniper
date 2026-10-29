import pytest

from src.discord_client import TokenizedMessage, _detect_single_message, build_reply
from src.senryu.explain import _truncate, build_explanation, explain_text
from src.senryu.finder import MIN_SCORE, find_candidates, pick_best
from src.senryu.preprocess import sanitize_text
from src.senryu.tokenizer import Morpheme, tokenize


def _m(surface, mora, pos="名詞", reading=""):
    return Morpheme(surface=surface, reading=reading, mora=mora, start=0, end=len(surface), pos=pos)


def _brk(surface="、"):
    return _m(surface, 0, pos="補助記号", reading=surface)


def test_explain_text_reports_detection_for_famous_haiku():
    """有名な五七五の句では「検出されます」と各句が示されることを確認する。"""
    result = explain_text("古池や蛙飛び込む水の音")
    assert "検出されます" in result
    assert "古池や" in result
    assert "蛙飛び込む" in result
    assert "水の音" in result
    assert "検出されません" not in result


def test_explain_text_reports_mora_shortage_without_rejected_split_list():
    """総モーラ数が足りない入力では、モーラ数不足と総モーラ数が示され、棄却分割の一覧は出ないことを確認する。"""
    result = explain_text("こんにちは")
    assert "検出されません" in result
    assert "5-7-5 にも 5-7-5-7-7 にも分割できません(モーラ数不足)" in result
    assert "総モーラ数: 5" in result
    assert "棄却された分割:" not in result


def test_build_explanation_reports_particle_at_first_part():
    """第1句の先頭が助詞になる分割は、句の番号つきで付属語を理由に棄却されることを確認する。"""
    morphemes = [
        _m("あい", 2, pos="動詞"),
        _m("うえおかき", 5, pos="助詞"),
        _m("くけこさしすせ", 7),
        _m("そたちつて", 5),
    ]
    result = build_explanation("あいうえおかきくけこさしすせそたちつて", morphemes)
    assert "棄却された分割:" in result
    assert "第1句の先頭が付属語です(品詞: 助詞)" in result
    assert "検出されます" not in result


def test_build_explanation_reports_auxiliary_verb_at_middle_part():
    """第2句の先頭が助動詞になる分割は、第2句として付属語を理由に棄却されることを確認する。"""
    morphemes = [
        _m("あいうえお", 5),
        _m("か", 1, pos="助動詞"),
        _m("きくけこさし", 6),
        _m("たちつてと", 5),
    ]
    result = build_explanation("あいうえおかきくけこさしたちつてと", morphemes)
    assert "第2句の先頭が付属語です(品詞: 助動詞)" in result
    assert "検出されます" not in result


def test_build_explanation_reports_unknown_mora_word():
    """記号・空白以外で mora=0 の語を含む分割は、未知語を理由に棄却されることを確認する。"""
    morphemes = [
        _m("あいうえお", 5),
        _m("かきくけこさし", 7),
        _m("Vlog", 0),
        _m("たちつてと", 5),
    ]
    result = build_explanation("あいうえおかきくけこさしVlogたちつてと", morphemes)
    assert "記号・空白以外で読みが取れない語(未知語)を含みます" in result
    assert "検出されます" not in result


def test_build_explanation_reports_sokuon_only_part():
    """促音だけで構成された句を含む分割は、促音のみを理由に棄却されることを確認する。"""
    morphemes = [
        _m("っっっっっ", 5, pos="記号", reading="ッッッッッ"),
        _m("かきくけこさし", 7),
        _m("たちつてと", 5),
    ]
    result = build_explanation("っっっっっかきくけこさしたちつてと", morphemes)
    assert "促音(ッ)だけで構成された句があります" in result
    assert "検出されます" not in result


def test_build_explanation_reports_score_shortage_with_score_and_threshold():
    """スコア不足で棄却された分割では、実際のスコアと MIN_SCORE が示されることを確認する。"""
    core = [
        _m("あ", 1), _brk(), _m("い", 1), _brk(), _m("うえお", 3),
        _m("かきくけこさし", 7), _m("たちつてと", 5),
    ]
    weak = [_m("あ" * 10, 10)] + core + [_m("い" * 10, 10)]
    candidates = find_candidates(weak, "")
    assert candidates
    assert pick_best(candidates) is None

    result = build_explanation("あ", weak)

    assert "検出されません" in result
    assert f"MIN_SCORE={MIN_SCORE:.2f}" in result
    for candidate in candidates:
        assert f"スコア不足です(score={candidate.score:.2f} < MIN_SCORE={MIN_SCORE:.2f})" in result


def test_build_explanation_limits_rejected_splits_to_five():
    """棄却された分割が6件以上ある場合は5件だけ示し、残りを件数で示すことを確認する。"""
    morphemes = []
    for _ in range(8):
        morphemes += [_m("うえおかき", 5, pos="助詞"), _m("くけこさしす", 6), _m("せ", 1)]
    result = build_explanation("あ", morphemes)
    assert result.count("\n- 5-7-5: ") == 5
    assert "ほか " in result


@pytest.mark.parametrize(
    "raw",
    [
        "古池や蛙飛び込む水の音",
        "こんにちは",
        "今日は天気がいいので古池や蛙飛び込む水の音を詠んでみた",
        "吾輩は猫である名前はまだ無い",
        "春の海ひねもすのたりのたりかな",
        "あいうえお、かきくけこさし、たちつてと!!!",
        "これはテストです",
        "ふるいけやかわずとびこむみずのおと",
        "Vlogかきくけこさしたちつてと",
        "っっっっっかきくけこさしたちつてと",
    ],
)
def test_explanation_detection_matches_build_reply(raw):
    """説明の検出可否と採用候補が、実際の検出(build_reply)の結果と一致することを確認する。"""
    result = explain_text(raw)
    detection = build_reply(raw)
    assert ("検出されます" in result) == (detection is not None)
    assert ("検出されません" in result) == (detection is None)
    if detection is not None:
        for part in detection.candidate.parts:
            assert part in result
        assert f"スコア: {detection.candidate.score:.2f}" in result


@pytest.mark.parametrize(
    "morphemes",
    [
        [_m("あいうえお", 5), _m("かきくけこさし", 7), _m("たちつてと", 5)],
        [
            _m("あいうえお", 5), _m("かきくけこさし", 7), _m("たちつてと", 5),
            _m("なにぬねのはひ", 7), _m("ふへほまみむめ", 7),
        ],
        [
            _m("ねえ", 2), _m("あいうえお", 5), _m("かきくけこさし", 7),
            _m("たちつてと", 5), _m("だよ", 2),
        ],
        [_m("あいう", 3)],
    ],
)
def test_explanation_detection_matches_detect_single_message_for_morphemes(morphemes):
    """形態素列を直接渡した場合も、説明の検出可否が _detect_single_message と一致することを確認する。"""
    text = "".join(m.surface for m in morphemes)
    detection = _detect_single_message(TokenizedMessage(text=text, morphemes=morphemes))
    result = build_explanation(text, morphemes)
    assert ("検出されます" in result) == (detection is not None)
    if detection is not None:
        assert detection.candidate.parts[0] in result


def test_explain_text_reports_tanka_parts():
    """五七五七七の短歌では、5句すべてが採用候補として示されることを確認する。"""
    morphemes = [
        _m("あいうえお", 5), _m("かきくけこさし", 7), _m("たちつてと", 5),
        _m("なにぬねのはひ", 7), _m("ふへほまみむめ", 7),
    ]
    result = build_explanation("あ", morphemes)
    for part in ("あいうえお", "かきくけこさし", "たちつてと", "なにぬねのはひ", "ふへほまみむめ"):
        assert part in result


def test_explain_text_reports_empty_after_sanitize():
    """サニタイズ後に空になる入力でも例外を出さず、空になる旨を返すことを確認する。"""
    result = explain_text("<@123456789>")
    assert "サニタイズ後のテキストが空です" in result
    assert "検出されません" in result


def test_explain_text_reports_chain_eligibility():
    """5モーラのメッセージは連歌チェーンに加われる旨、6モーラは加われない理由が示されることを確認する。"""
    assert "**連歌チェーン**: このメッセージ単体はチェーンに加われます(総モーラ数: 5)" in explain_text("古池や")
    ineligible = build_explanation("あ", [_m("あいうえおか", 6)])
    assert "**連歌チェーン**: 加われません — 総モーラ数が 5 でも 7 でもありません(総モーラ数: 6)" in ineligible


def test_explain_text_neutralizes_backticks_in_user_text():
    """入力に含まれるバッククォートが全角に置き換わり、コードブロックを壊さないことを確認する。"""
    raw = "あい`うえおかき"
    assert "`" in sanitize_text(raw)
    result = explain_text(raw)
    assert result.count("```") % 2 == 0
    assert "あい｀うえおかき" in result
    assert "`" not in result.replace("```", "")


def test_explain_text_stays_within_discord_message_limit_for_max_length_input():
    """200文字の入力でも返り値が2000文字以内に収まることを確認する。"""
    assert len(explain_text("あ" * 200)) <= 2000
    assert len(explain_text("古池や蛙飛び込む水の音" * 18)) <= 2000
    assert len(explain_text("、".join("あいうえお" for _ in range(40)))) <= 2000


def test_explain_text_terminates_for_many_zero_mora_symbols():
    """ゼロモーラの記号が長く続く入力でも、探索が打ち切られて結果を返すことを確認する。"""
    raw = "あいうえお" + "、" * 30 + "かきくけこさし" + "、" * 30 + "たちつてと" + "、" * 30 + "あいうえお"
    assert len(tokenize(sanitize_text(raw))) > 90
    assert len(explain_text(raw)) <= 2000


def test_truncate_keeps_short_message_unchanged():
    """2000文字以下のメッセージはそのまま返ることを確認する。"""
    assert _truncate("あ" * 2000) == "あ" * 2000


def test_truncate_closes_open_code_fence():
    """2000文字を超えるメッセージは2000文字以内に切り詰められ、開いたコードフェンスが閉じられることを確認する。"""
    message = "見出し\n```\n" + "あ" * 3000 + "\n```"
    result = _truncate(message)
    assert len(result) <= 2000
    assert result.count("```") % 2 == 0
    assert "…" in result
