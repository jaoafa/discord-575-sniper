import pytest

from src.config_store import ConfigStore
from src.discord_client import (
    build_reply,
    handle_disable,
    handle_enable,
    handle_status,
)


def test_build_reply_detects_575_famous_example():
    """有名な五七五の句を渡すと各句を含む返信文が生成されることを確認する。"""
    # 「古池や(5)/蛙飛び込む(7)/水の音(5)」= 17モーラの有名な句
    text = "古池や蛙飛び込む水の音"
    reply = build_reply(text)
    assert reply is not None
    assert reply.startswith("🎋")
    assert "古池や" in reply
    assert "蛙飛び込む" in reply
    assert "水の音" in reply


def test_build_reply_no_match_returns_none():
    """五七五にならない文字列では None が返ることを確認する。"""
    reply = build_reply("こんにちは")
    assert reply is None


def test_build_reply_empty_text_returns_none():
    """サニタイズ後に空文字列になる入力では None が返ることを確認する。"""
    reply = build_reply("<@123456789>")
    assert reply is None


def test_build_reply_punctuation_only_returns_none():
    """句読点のみの文字列では None が返ることを確認する。"""
    text = "。。。。。、、、、、、、。。。。。"
    assert build_reply(text) is None


@pytest.fixture
def config_store(tmp_path):
    """テスト用の一時 SQLite ファイルを使う ConfigStore を生成する。"""
    return ConfigStore(str(tmp_path / "config.db"))


@pytest.mark.asyncio
async def test_handle_enable_sets_channel_enabled(config_store):
    """handle_enable がチャンネルを有効化し、有効を示すメッセージを返すことを確認する。"""
    message = await handle_enable(config_store, channel_id=111)
    assert "有効" in message
    assert config_store.is_enabled(channel_id=111) is True


@pytest.mark.asyncio
async def test_handle_disable_sets_channel_disabled(config_store):
    """handle_disable がチャンネルを無効化し、無効を示すメッセージを返すことを確認する。"""
    config_store.set_enabled(111, True)
    message = await handle_disable(config_store, channel_id=111)
    assert "無効" in message
    assert config_store.is_enabled(channel_id=111) is False


@pytest.mark.asyncio
async def test_handle_status_reports_enabled(config_store):
    """有効化済みチャンネルで handle_status が有効を示すメッセージを返すことを確認する。"""
    config_store.set_enabled(111, True)
    message = await handle_status(config_store, channel_id=111, parent_id=None)
    assert "有効" in message


@pytest.mark.asyncio
async def test_handle_status_reports_disabled_by_default(config_store):
    """未設定のチャンネルで handle_status が無効を示すメッセージを返すことを確認する。"""
    message = await handle_status(config_store, channel_id=111, parent_id=None)
    assert "無効" in message
