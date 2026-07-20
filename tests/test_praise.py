from src.senryu.praise import PraiseTracker


def test_get_target_returns_none_when_nothing_recorded():
    """何も記録されていないチャンネルでは None を返すことを確認する。"""
    tracker = PraiseTracker()
    assert tracker.get_target(channel_id=1, now=0.0) is None


def test_get_target_returns_recorded_entry_within_window():
    """検出から5分以内であれば記録した内容を返すことを確認する。"""
    tracker = PraiseTracker()
    tracker.record_detection(
        channel_id=1, source="record", source_id=10,
        reply_message_id=100, author_user_ids=frozenset({7000}), now=0.0,
    )
    target = tracker.get_target(channel_id=1, now=299.0)
    assert target is not None
    assert target.source == "record"
    assert target.source_id == 10
    assert target.reply_message_id == 100
    assert target.author_user_ids == frozenset({7000})


def test_get_target_returns_none_after_300_seconds():
    """検出から300秒ちょうどは有効だが、300秒を超えると None を返すことを確認する。"""
    tracker = PraiseTracker()
    tracker.record_detection(
        channel_id=1, source="record", source_id=10,
        reply_message_id=100, author_user_ids=frozenset({7000}), now=0.0,
    )
    assert tracker.get_target(channel_id=1, now=300.0) is not None
    assert tracker.get_target(channel_id=1, now=300.01) is None


def test_get_target_is_independent_per_channel():
    """チャンネルごとに「直前の詠み」が独立して保持されることを確認する。"""
    tracker = PraiseTracker()
    tracker.record_detection(
        channel_id=1, source="record", source_id=10,
        reply_message_id=100, author_user_ids=frozenset({7000}), now=0.0,
    )
    assert tracker.get_target(channel_id=2, now=0.0) is None


def test_record_detection_overwrites_previous_entry():
    """新しい検出があると、同じチャンネルの「直前の詠み」が上書きされることを確認する。"""
    tracker = PraiseTracker()
    tracker.record_detection(
        channel_id=1, source="record", source_id=10,
        reply_message_id=100, author_user_ids=frozenset({7000}), now=0.0,
    )
    tracker.record_detection(
        channel_id=1, source="chain_record", source_id=20,
        reply_message_id=200, author_user_ids=frozenset({1, 2}), now=1.0,
    )
    target = tracker.get_target(channel_id=1, now=1.0)
    assert target.source == "chain_record"
    assert target.source_id == 20
    assert target.reply_message_id == 200
    assert target.author_user_ids == frozenset({1, 2})
