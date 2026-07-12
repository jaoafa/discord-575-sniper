"""create_bot() が組み立てる discord.Client の on_message 配線を検証する統合テスト。

fauxcord (github.com/tomacheese/fauxcord) は Bot トークン・Webhook どちらで
投稿したメッセージも author.bot を常に true にしてしまうため、本 Bot が正しく
実装している `if message.author.bot: return`(Bot 間ループ防止のための正しい
挙動であり、テストのために弱めるべきではない)により、fauxcord の公開API経由で
投稿したメッセージは検出ロジックに到達せず、真の E2E テストが構築できない。

そのため、実ネットワーク I/O・Docker・fauxcord を一切使わず、discord.py の
Client を実際に組み立てた上でスタブの discord.Message 相当オブジェクトを
`on_message` ハンドラへ直接渡すことで、
「ギルド/送信者/チャンネル有効判定 → build_reply → message.reply」という
配線全体を検証する。
"""

import sqlite3

import pytest
from discord import app_commands

from src.config_store import ConfigStore
from src.discord_client import create_bot
from src.record_store import RecordStore

GUILD_ID = 1000
CHANNEL_ID = 2000
OTHER_GUILD_ID = 9999
THREAD_ID = 3000
PARENT_CHANNEL_ID = 2001


class FakeGuild:
    """テスト用のギルドスタブ。"""

    def __init__(self, guild_id: int):
        self.id = guild_id


class FakeAuthor:
    """テスト用の送信者スタブ。"""

    def __init__(self, bot: bool = False, author_id: int = 5000):
        self.bot = bot
        self.id = author_id


class FakeChannel:
    """テスト用のチャンネルスタブ。parent_id を省略するとスレッドではない通常チャンネルになる。"""

    def __init__(self, channel_id: int, parent_id: int | None = None):
        self.id = channel_id
        if parent_id is not None:
            self.parent_id = parent_id


class FakeMessage:
    """discord.Message の代わりに on_message へ渡すスタブオブジェクト。"""

    def __init__(self, content, guild, author, channel, message_id: int = 9000):
        self.content = content
        self.guild = guild
        self.author = author
        self.channel = channel
        self.id = message_id
        self.reply_calls = []

    async def reply(self, text):
        """message.reply() 呼び出しを記録するスタブ実装。"""
        self.reply_calls.append(text)


SENRYU_TEXT = "古池や蛙飛び込む水の音"
TANKA_TEXT = "古池や蛙飛び込む水の音やまぶきのえだうめがかがやく"
NON_SENRYU_TEXT = "こんにちは"


@pytest.fixture
def config_store(tmp_path):
    """テスト用の一時 SQLite ファイルを使う ConfigStore を生成する。"""
    return ConfigStore(str(tmp_path / "config.db"))


@pytest.fixture
def records_db_path(tmp_path):
    """テスト用の一時 SQLite ファイルパス(RecordStore 用)。"""
    return str(tmp_path / "records.db")


@pytest.fixture
def record_store(records_db_path):
    """テスト用の一時 SQLite ファイルを使う RecordStore を生成する。"""
    return RecordStore(records_db_path)


@pytest.fixture
def client(config_store, record_store):
    """有効化済みチャンネルを持つ、実際に配線された discord.Client を生成する。"""
    config_store.set_enabled(CHANNEL_ID, True)
    return create_bot(GUILD_ID, config_store, record_store)


@pytest.mark.asyncio
async def test_on_message_replies_to_senryu_on_enabled_channel(client):
    """有効化済みチャンネルで川柳を検知すると 🎋 で始まる返信をすることを確認する。"""
    message = FakeMessage(
        SENRYU_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=False), FakeChannel(CHANNEL_ID)
    )
    await client.on_message(message)
    assert len(message.reply_calls) == 1
    assert message.reply_calls[0].startswith("🎋")


@pytest.mark.asyncio
async def test_on_ready_syncs_command_tree_only_once(monkeypatch, config_store, record_store):
    """on_ready が複数回発火しても tree.sync が2回目以降は実行されないことを確認する
    (再接続のたびに同期レートリミットを消費しないため)。
    """
    sync_calls = []

    async def fake_sync(self, *, guild=None):
        sync_calls.append(guild)
        return []

    monkeypatch.setattr(app_commands.CommandTree, "sync", fake_sync)
    client = create_bot(GUILD_ID, config_store, record_store)

    await client.on_ready()
    await client.on_ready()

    assert len(sync_calls) == 1


@pytest.mark.asyncio
async def test_on_message_does_not_reply_on_disabled_channel(client):
    """無効なチャンネルでは川柳を含むメッセージでも返信しないことを確認する。"""
    message = FakeMessage(
        SENRYU_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=False), FakeChannel(9001)
    )
    await client.on_message(message)
    assert message.reply_calls == []


@pytest.mark.asyncio
async def test_on_message_does_not_reply_to_non_senryu_message(client):
    """有効なチャンネルでも川柳でないメッセージには返信しないことを確認する。"""
    message = FakeMessage(
        NON_SENRYU_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=False), FakeChannel(CHANNEL_ID)
    )
    await client.on_message(message)
    assert message.reply_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_bot_author(client):
    """送信者が Bot の場合は Bot 間ループ防止のため返信しないことを確認する。"""
    message = FakeMessage(
        SENRYU_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=True), FakeChannel(CHANNEL_ID)
    )
    await client.on_message(message)
    assert message.reply_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_different_guild(client):
    """Bot が紐づくギルドと異なるギルドのメッセージには反応しないことを確認する。"""
    message = FakeMessage(
        SENRYU_TEXT, FakeGuild(OTHER_GUILD_ID), FakeAuthor(bot=False), FakeChannel(CHANNEL_ID)
    )
    await client.on_message(message)
    assert message.reply_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_message_without_guild(client):
    """guild が None のメッセージ (DM等) には反応しないことを確認する。"""
    message = FakeMessage(SENRYU_TEXT, None, FakeAuthor(bot=False), FakeChannel(CHANNEL_ID))
    await client.on_message(message)
    assert message.reply_calls == []


@pytest.mark.asyncio
async def test_on_message_replies_in_thread_inheriting_parent_channel_setting(
    config_store, client
):
    """スレッド自体に設定がなくても親チャンネルの有効設定を継承して返信することを確認する。"""
    # 親チャンネル自体は有効化されているが、スレッドID自体には設定がない状態で、
    # on_message経由でparent_id継承の有効判定が働くことを確認する
    # (ConfigStore単体の継承ロジックはTask 6で既にテスト済み)
    message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False),
        FakeChannel(THREAD_ID, parent_id=CHANNEL_ID),
    )
    await client.on_message(message)
    assert len(message.reply_calls) == 1
    assert message.reply_calls[0].startswith("🎋")


@pytest.mark.asyncio
async def test_on_message_records_detected_senryu(client, records_db_path):
    """川柳検出時に RecordStore へ記録が保存されることを確認する。"""
    message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=8000,
    )
    await client.on_message(message)

    conn = sqlite3.connect(records_db_path)
    row = conn.execute(
        "SELECT guild_id, channel_id, user_id, message_id, part1, part2, part3 FROM records"
    ).fetchone()
    conn.close()

    assert row == (GUILD_ID, CHANNEL_ID, 7000, 8000, "古池や", "蛙飛び込む", "水の音")


@pytest.mark.asyncio
async def test_on_message_records_even_when_reply_fails(client, records_db_path):
    """Discord への返信が失敗しても検出記録は残ることを確認する。"""
    message = FakeMessage(
        SENRYU_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=False), FakeChannel(CHANNEL_ID)
    )

    async def failing_reply(text):
        raise RuntimeError("reply failed")

    message.reply = failing_reply
    await client.on_message(message)

    conn = sqlite3.connect(records_db_path)
    count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    assert count == 1


@pytest.mark.asyncio
async def test_on_message_replies_even_when_recording_fails(client, record_store):
    """RecordStore への記録が失敗しても、検出した川柳への返信は行われることを確認する
    (記録と返信は互いの成否に依存させないため)。
    """
    def failing_add_record(**kwargs):
        raise RuntimeError("db error")

    record_store.add_record = failing_add_record
    message = FakeMessage(
        SENRYU_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=False), FakeChannel(CHANNEL_ID)
    )
    await client.on_message(message)

    assert len(message.reply_calls) == 1
    assert message.reply_calls[0].startswith("🎋")


@pytest.mark.asyncio
async def test_on_message_replies_to_tanka_with_tanka_header(client):
    """短歌(5-7-5-7-7)を検知すると「短歌を検出しました」で始まる返信をすることを確認する。"""
    message = FakeMessage(
        TANKA_TEXT, FakeGuild(GUILD_ID), FakeAuthor(bot=False), FakeChannel(CHANNEL_ID)
    )
    await client.on_message(message)
    assert len(message.reply_calls) == 1
    assert message.reply_calls[0].startswith("🎋 短歌を検出しました！")


@pytest.mark.asyncio
async def test_on_message_records_detected_tanka_with_five_parts(client, records_db_path):
    """短歌検出時に part4/part5 を含む5パートが RecordStore へ記録されることを確認する。"""
    message = FakeMessage(
        TANKA_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=8000,
    )
    await client.on_message(message)

    conn = sqlite3.connect(records_db_path)
    row = conn.execute(
        "SELECT part1, part2, part3, part4, part5 FROM records"
    ).fetchone()
    conn.close()

    assert row == ("古池や", "蛙飛び込む", "水の音", "やまぶきのえだ", "うめがかがやく")
