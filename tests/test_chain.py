import pytest

from src.senryu.chain import ChainTracker, chain_ineligibility_reason
from src.senryu.tokenizer import Morpheme


def _morphemes(surface: str, total_mora: int, pos: str = "名詞") -> list[Morpheme]:
    """指定した表層文字列・総モーラ数を持つ、単一形態素のリストを作るテスト用ヘルパー。"""
    return [Morpheme(surface=surface, reading="", mora=total_mora, start=0, end=len(surface), pos=pos)]


def test_returns_none_before_pattern_completes():
    """1件目のメッセージだけでは検出されないことを確認する。"""
    tracker = ChainTracker()
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    assert result is None


def test_detects_senryu_as_dokugin_when_same_author():
    """同一投稿者が連続して投稿した3件が5-7-5になると独吟として検出することを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=2.0,
    )
    assert result is not None
    assert result.kind == "独吟"
    assert result.pattern == (5, 7, 5)
    assert [p.text for p in result.parts] == ["古池や", "蛙飛び込む", "水の音"]


def test_detects_senryu_as_renga_when_different_authors():
    """複数投稿者が交互に投稿した3件が5-7-5になると連歌として検出することを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=1, message_id=1, text="お前かよ",
        morphemes=_morphemes("お前かよ", 5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=2, message_id=2, text="お前誰だよ",
        morphemes=_morphemes("お前誰だよ", 7), now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=1, message_id=3, text="俺アルファ",
        morphemes=_morphemes("俺アルファ", 5), now=2.0,
    )
    assert result is not None
    assert result.kind == "連歌"


def test_five_message_sequence_fires_at_third_message_not_fifth():
    """5-7-5-7-7という並びであっても、先頭3件が5-7-5に一致した時点で即座に川柳として検出・チェーンのリセットが起こることを確認する。

    SENRYU_PATTERN(5, 7, 5)はTANKA_PATTERN(5, 7, 5, 7, 7)の先頭3要素と定義上常に一致するため、複数メッセージ結合による短歌の検出は数学的に到達不可能。このテストはその挙動を明示的に固定する。
    """
    tracker = ChainTracker()
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=0, text="part0",
        morphemes=_morphemes("part0", 5), now=0.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="part1",
        morphemes=_morphemes("part1", 7), now=1.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="part2",
        morphemes=_morphemes("part2", 5), now=2.0,
    )
    assert result is not None
    assert result.pattern == (5, 7, 5)
    assert len(result.parts) == 3

    # 4件目・5件目(7モーラ)はリセット後のチェーンに積まれるだけで、
    # 5件目までの検出には至らない(チェーンは検出直後に空になっているため)。
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="part3",
        morphemes=_morphemes("part3", 7), now=3.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="part4",
        morphemes=_morphemes("part4", 7), now=4.0,
    )
    assert result is None


def test_message_starting_with_attached_word_does_not_extend_chain():
    """先頭形態素が助詞などの付属語であるメッセージは、モーラ数が5・7でもチェーンを延長しないことを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="とても",
        morphemes=_morphemes("とても", 7, pos="助詞"), now=1.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=2.0,
    )
    assert result is None


def test_unqualified_message_resets_chain():
    """総モーラ数が5でも7でもないメッセージが来るとチェーンがリセットされることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="こんにちは",
        morphemes=_morphemes("こんにちは", 6), now=1.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=2.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="水の音",
        morphemes=_morphemes("水の音", 5), now=3.0,
    )
    assert result is None


def test_timeout_over_180_seconds_resets_chain():
    """直前の保持メッセージから180秒を超えるとチェーンがリセットされることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=180.1,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=181.0,
    )
    assert result is None


def test_chain_within_180_seconds_still_matches():
    """180秒以内の間隔であれば検出が成立することを確認する(タイムアウト境界の健全性チェック)。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=179.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=358.0,
    )
    assert result is not None


def test_chain_cleared_completely_after_match():
    """検出後にチェーンが完全にクリアされ、直後の3件では再検出されないことを確認する。"""
    tracker = ChainTracker()
    for i, mora in enumerate([5, 7, 5]):
        tracker.process_message(
            channel_id=1, user_id=100, message_id=i, text=f"part{i}",
            morphemes=_morphemes(f"part{i}", mora), now=float(i),
        )
    # 検出直後、まだ2件しか積み上がっていないので None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=10, text="a",
        morphemes=_morphemes("a", 5), now=10.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=11, text="b",
        morphemes=_morphemes("b", 7), now=11.0,
    )
    assert result is None


def test_long_chain_of_non_matching_entries_then_matches():
    """5件を超えて保持メッセージが積み上がっても、直近3件が5-7-5になれば正しく
    検出できることを確認する(内部バッファが5件を超えて無制限に成長しても
    判定が直近の件数のみを見ることの確認)。
    """
    tracker = ChainTracker()
    for i in range(10):
        result = tracker.process_message(
            channel_id=1, user_id=100, message_id=i, text=f"part{i}",
            morphemes=_morphemes(f"part{i}", 7), now=float(i),
        )
        assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=100, text="古池や",
        morphemes=_morphemes("古池や", 5), now=100.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=101, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=101.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=102, text="水の音",
        morphemes=_morphemes("水の音", 5), now=102.0,
    )
    assert result is not None
    assert result.pattern == (5, 7, 5)
    assert [p.mora for p in result.parts] == [5, 7, 5]


def test_message_with_unknown_mora_word_resets_chain():
    """未知語(非記号品詞の mora=0)を含むメッセージは、モーラ数が5・7に合致していても
    チェーンをリセットして None を返すことを確認する(false positive 防止)。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    morphemes = [
        Morpheme(surface="Vlog", reading="", mora=0, start=0, end=4, pos="名詞"),
        Morpheme(surface="かきくけこさし", reading="", mora=7, start=4, end=11, pos="名詞"),
    ]
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="Vlogかきくけこさし",
        morphemes=morphemes, now=1.0,
    )
    assert result is None
    # ガードがなければ古池や(5)・Vlogかきくけこさし(7)・水の音(5)で5-7-5が
    # 成立してしまうが、ガードにより2件目でチェーンがリセットされているため
    # None になることを確認する。
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=2.0,
    )
    assert result is None


def test_chain_entry_text_strips_zero_mora_symbol():
    """ChainEntry.text がメッセージ全文ではなく、mora=0(記号・空白)の
    形態素を除いた表層文字列になっていることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    morphemes = [
        Morpheme(surface="かきくけこさし", reading="", mora=7, start=0, end=7, pos="名詞"),
        Morpheme(surface="、", reading="", mora=0, start=7, end=8, pos="補助記号"),
    ]
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="かきくけこさし、",
        morphemes=morphemes, now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=2.0,
    )
    assert result is not None
    assert [p.text for p in result.parts] == ["古池や", "かきくけこさし", "水の音"]


def test_empty_morphemes_resets_chain_without_raising():
    """形態素リストが空のメッセージ(添付ファイルのみ等でサニタイズ後に空文字列になった場合)を
    渡してもエラーにならず、チェーンがリセットされて None を返すことを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="",
        morphemes=[], now=1.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=2.0,
    )
    assert result is None


def test_channels_are_isolated():
    """チャンネルが異なればチェーンが独立して管理されることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    tracker.process_message(
        channel_id=2, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=2.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="水の音",
        morphemes=_morphemes("水の音", 5), now=3.0,
    )
    assert result is not None


def test_sokuon_only_message_resets_chain():
    """「っ」だけのメッセージ(5モーラ)はチェーンに加わらず、保持中のチェーンをリセットすることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes("古池や", 5), now=0.0,
    )
    sokuon = [Morpheme(surface="っっっっっ", reading="ッッッッッ", mora=5, start=0, end=5, pos="記号")]
    assert tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="っっっっっ", morphemes=sokuon, now=1.0,
    ) is None
    tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=2.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="水の音",
        morphemes=_morphemes("水の音", 5), now=3.0,
    )
    assert result is None


def test_message_with_too_many_inner_breaks_resets_chain():
    """句内に区切りが4つ以上混ざったメッセージはチェーンに加わらないことを確認する。"""
    tracker = ChainTracker()
    comma = Morpheme(surface="、", reading="、", mora=0, start=0, end=1, pos="補助記号")
    noisy = [
        Morpheme(surface="あ", reading="ア", mora=1, start=0, end=1, pos="名詞"),
    ]
    for _ in range(4):
        noisy += [comma, Morpheme(surface="い", reading="イ", mora=1, start=0, end=1, pos="名詞")]
    assert sum(m.mora for m in noisy) == 5
    assert tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="あ、い、い、い、い", morphemes=noisy, now=0.0,
    ) is None
    # チェーンに加わっていないので、続く 7・5 では川柳が成立しない。
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes("蛙飛び込む", 7), now=1.0,
    )
    assert tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes("水の音", 5), now=2.0,
    ) is None


def _noisy_morphemes() -> list[Morpheme]:
    """句内に区切りが4つ混ざり、スコアが MIN_SCORE を下回る5モーラのメッセージを作るテスト用ヘルパー。"""
    comma = Morpheme(surface="、", reading="、", mora=0, start=0, end=1, pos="補助記号")
    noisy = [Morpheme(surface="あ", reading="ア", mora=1, start=0, end=1, pos="名詞")]
    for _ in range(4):
        noisy += [comma, Morpheme(surface="い", reading="イ", mora=1, start=0, end=1, pos="名詞")]
    return noisy


def _ineligible_cases() -> list[tuple[list[Morpheme], str]]:
    """(形態素列, 不適格理由に含まれるべき文言) の組を返す。"""
    return [
        ([], "サニタイズ後のテキストが空です"),
        (_morphemes("こんにちは", 6), "総モーラ数が 5 でも 7 でもありません(総モーラ数: 6)"),
        (_morphemes("とても", 7, pos="助詞"), "先頭の形態素が付属語です(品詞: 助詞)"),
        (
            [
                Morpheme(surface="Vlog", reading="", mora=0, start=0, end=4, pos="名詞"),
                Morpheme(surface="かきくけこさし", reading="", mora=7, start=4, end=11, pos="名詞"),
            ],
            "記号・空白以外で読みが取れない語(未知語)を含みます",
        ),
        (
            [Morpheme(surface="っっっっっ", reading="ッッッッッ", mora=5, start=0, end=5, pos="記号")],
            "促音(ッ)だけで構成されています",
        ),
        (_noisy_morphemes(), "スコア不足です(score=0.20 < MIN_SCORE=0.30)"),
    ]


@pytest.mark.parametrize("morphemes", [_morphemes("古池や", 5), _morphemes("蛙飛び込む", 7)])
def test_chain_ineligibility_reason_is_none_for_eligible_message(morphemes):
    """5モーラ・7モーラの正常なメッセージは適格(None)であることを確認する。"""
    assert chain_ineligibility_reason(morphemes) is None


@pytest.mark.parametrize("morphemes, expected", _ineligible_cases())
def test_chain_ineligibility_reason_returns_first_matching_reason(morphemes, expected):
    """不適格なメッセージでは、判定順で最初に該当した理由が返ることを確認する。"""
    assert chain_ineligibility_reason(morphemes) == expected


@pytest.mark.parametrize(
    "morphemes",
    [_morphemes("古池や", 5), _morphemes("蛙飛び込む", 7)] + [m for m, _ in _ineligible_cases()],
)
def test_chain_ineligibility_reason_matches_process_message_behavior(morphemes):
    """理由が None であることと、空のチェーンに単独で与えたメッセージが保持されることが一致する。"""
    tracker = ChainTracker()
    text = "".join(m.surface for m in morphemes)
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text=text, morphemes=morphemes, now=0.0,
    )
    assert (1 in tracker._chains) == (chain_ineligibility_reason(morphemes) is None)
