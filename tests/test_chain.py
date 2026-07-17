from src.senryu.chain import ChainTracker
from src.senryu.tokenizer import Morpheme


def _morphemes(total_mora: int, pos: str = "名詞") -> list[Morpheme]:
    """指定した総モーラ数を持つ、単一形態素のリストを作るテスト用ヘルパー。"""
    return [Morpheme(surface="x", reading="", mora=total_mora, start=0, end=1, pos=pos)]


def test_returns_none_before_pattern_completes():
    """1件目のメッセージだけでは検出されないことを確認する。"""
    tracker = ChainTracker()
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    assert result is None


def test_detects_senryu_as_dokugin_when_same_author():
    """同一投稿者が連続して投稿した3件が5-7-5になると独吟として検出することを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes(7), now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes(5), now=2.0,
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
        morphemes=_morphemes(5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=2, message_id=2, text="お前誰だよ",
        morphemes=_morphemes(7), now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=1, message_id=3, text="俺アルファ",
        morphemes=_morphemes(5), now=2.0,
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
        morphemes=_morphemes(5), now=0.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="part1",
        morphemes=_morphemes(7), now=1.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="part2",
        morphemes=_morphemes(5), now=2.0,
    )
    assert result is not None
    assert result.pattern == (5, 7, 5)
    assert len(result.parts) == 3

    # 4件目・5件目(7モーラ)はリセット後のチェーンに積まれるだけで、
    # 5件目までの検出には至らない(チェーンは検出直後に空になっているため)。
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="part3",
        morphemes=_morphemes(7), now=3.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="part4",
        morphemes=_morphemes(7), now=4.0,
    )
    assert result is None


def test_message_starting_with_attached_word_does_not_extend_chain():
    """先頭形態素が助詞などの付属語であるメッセージは、モーラ数が5・7でもチェーンを延長しないことを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="とても",
        morphemes=_morphemes(7, pos="助詞"), now=1.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes(5), now=2.0,
    )
    assert result is None


def test_unqualified_message_resets_chain():
    """総モーラ数が5でも7でもないメッセージが来るとチェーンがリセットされることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="こんにちは",
        morphemes=_morphemes(6), now=1.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="蛙飛び込む",
        morphemes=_morphemes(7), now=2.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="水の音",
        morphemes=_morphemes(5), now=3.0,
    )
    assert result is None


def test_timeout_over_180_seconds_resets_chain():
    """直前の保持メッセージから180秒を超えるとチェーンがリセットされることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes(7), now=180.1,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes(5), now=181.0,
    )
    assert result is None


def test_chain_within_180_seconds_still_matches():
    """180秒以内の間隔であれば検出が成立することを確認する(タイムアウト境界の健全性チェック)。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    tracker.process_message(
        channel_id=1, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes(7), now=179.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="水の音",
        morphemes=_morphemes(5), now=358.0,
    )
    assert result is not None


def test_chain_cleared_completely_after_match():
    """検出後にチェーンが完全にクリアされ、直後の3件では再検出されないことを確認する。"""
    tracker = ChainTracker()
    for i, mora in enumerate([5, 7, 5]):
        tracker.process_message(
            channel_id=1, user_id=100, message_id=i, text=f"part{i}",
            morphemes=_morphemes(mora), now=float(i),
        )
    # 検出直後、まだ2件しか積み上がっていないので None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=10, text="a",
        morphemes=_morphemes(5), now=10.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=11, text="b",
        morphemes=_morphemes(7), now=11.0,
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
            morphemes=_morphemes(7), now=float(i),
        )
        assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=100, text="古池や",
        morphemes=_morphemes(5), now=100.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=101, text="蛙飛び込む",
        morphemes=_morphemes(7), now=101.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=102, text="水の音",
        morphemes=_morphemes(5), now=102.0,
    )
    assert result is not None
    assert result.pattern == (5, 7, 5)
    assert [p.mora for p in result.parts] == [5, 7, 5]


def test_channels_are_isolated():
    """チャンネルが異なればチェーンが独立して管理されることを確認する。"""
    tracker = ChainTracker()
    tracker.process_message(
        channel_id=1, user_id=100, message_id=1, text="古池や",
        morphemes=_morphemes(5), now=0.0,
    )
    tracker.process_message(
        channel_id=2, user_id=100, message_id=2, text="蛙飛び込む",
        morphemes=_morphemes(7), now=1.0,
    )
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=3, text="蛙飛び込む",
        morphemes=_morphemes(7), now=2.0,
    )
    assert result is None
    result = tracker.process_message(
        channel_id=1, user_id=100, message_id=4, text="水の音",
        morphemes=_morphemes(5), now=3.0,
    )
    assert result is not None
