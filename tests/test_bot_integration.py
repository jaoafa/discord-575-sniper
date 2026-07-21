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
import time

import discord
import pytest
from discord import app_commands

from src.config_store import ConfigStore
from src.discord_client import create_bot
from src.record_store import RecordStore
from src.senryu.chain import ChainTracker
from src.senryu.praise import PraiseTracker

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
        self.send_calls: list[tuple[str, discord.MessageReference | None]] = []

    async def send(self, content, *, reference=None):
        """channel.send() 呼び出しを記録するスタブ実装。"""
        self.send_calls.append((content, reference))


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
def chain_tracker():
    """テスト用の ChainTracker(チャンネル間で状態を共有しない新規インスタンス)。"""
    return ChainTracker()


@pytest.fixture
def praise_tracker():
    """テスト用の PraiseTracker(チャンネル間で状態を共有しない新規インスタンス)。"""
    return PraiseTracker()


@pytest.fixture
def client(config_store, record_store, chain_tracker, praise_tracker):
    """有効化済みチャンネルを持つ、実際に配線された discord.Client を生成する。"""
    config_store.set_enabled(CHANNEL_ID, True)
    return create_bot(GUILD_ID, config_store, record_store, chain_tracker, praise_tracker)


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
    client = create_bot(GUILD_ID, config_store, record_store, ChainTracker(), PraiseTracker())

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
async def test_on_message_records_app_version(client, records_db_path, monkeypatch):
    """川柳検出時に、稼働中のバージョンが app_version 列として記録されることを確認する。"""
    monkeypatch.setattr("src.discord_client.__version__", "9.9.9-integration-test")
    message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=8001,
    )
    await client.on_message(message)

    conn = sqlite3.connect(records_db_path)
    row = conn.execute("SELECT app_version FROM records").fetchone()
    conn.close()

    assert row == ("9.9.9-integration-test",)


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


@pytest.mark.asyncio
async def test_on_message_detects_dokugin_from_three_messages_same_author(client):
    """同一投稿者が連続投稿した3件の合計が5-7-5になると独吟を検出することを確認する。"""
    author = FakeAuthor(bot=False, author_id=7000)
    texts = ["古池や", "蛙飛び込む", "水の音"]
    last_message = None
    for i, text in enumerate(texts):
        last_message = FakeMessage(
            text, FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8000 + i,
        )
        await client.on_message(last_message)
    assert len(last_message.reply_calls) == 1
    assert last_message.reply_calls[0].startswith("🎋 独吟を検出しました")


@pytest.mark.asyncio
async def test_on_message_detects_renga_from_three_messages_different_authors(client):
    """異なる投稿者が交互に投稿した3件の合計が5-7-5になると連歌を検出することを確認する。"""
    authors = [
        FakeAuthor(bot=False, author_id=1),
        FakeAuthor(bot=False, author_id=2),
        FakeAuthor(bot=False, author_id=1),
    ]
    texts = ["古池や", "蛙飛び込む", "水の音"]
    last_message = None
    for i, (text, author) in enumerate(zip(texts, authors)):
        last_message = FakeMessage(
            text, FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8100 + i,
        )
        await client.on_message(last_message)
    assert len(last_message.reply_calls) == 1
    assert last_message.reply_calls[0].startswith("🎋 連歌を検出しました")


@pytest.mark.asyncio
async def test_on_message_fires_at_third_message_even_if_sequence_continues(client):
    """5-7-5-7-7という並びで5件連投しても、3件目の時点で即座に川柳(独吟)として
    検出・返信され、4件目・5件目では再検出されないことを確認する
    (TANKA_PATTERN の先頭3要素は SENRYU_PATTERN と定義上一致するため、複数
    メッセージ結合による短歌検出は到達不可能。spec の「短歌をスコープ外とする
    理由」参照)。
    """
    author = FakeAuthor(bot=False, author_id=7000)
    texts = ["古池や", "蛙飛び込む", "水の音", "やまぶきのえだ", "うめがかがやく"]
    messages = []
    for i, text in enumerate(texts):
        message = FakeMessage(
            text, FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8200 + i,
        )
        messages.append(message)
        await client.on_message(message)
    assert len(messages[2].reply_calls) == 1
    assert messages[2].reply_calls[0].startswith("🎋 独吟を検出しました")
    assert messages[3].reply_calls == []
    assert messages[4].reply_calls == []


@pytest.mark.asyncio
async def test_on_message_records_chain_detection(client, records_db_path):
    """複数メッセージ結合による検出時に chain_records へ記録されることを確認する。"""
    author = FakeAuthor(bot=False, author_id=7000)
    texts = ["古池や", "蛙飛び込む", "水の音"]
    for i, text in enumerate(texts):
        message = FakeMessage(
            text, FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8300 + i,
        )
        await client.on_message(message)

    conn = sqlite3.connect(records_db_path)
    row = conn.execute(
        "SELECT guild_id, channel_id, kind, pattern FROM chain_records"
    ).fetchone()
    conn.close()
    assert row == (GUILD_ID, CHANNEL_ID, "独吟", "5-7-5")


@pytest.mark.asyncio
async def test_on_message_does_not_chain_across_180_seconds(client, monkeypatch):
    """180秒を超えて間隔が空くとチェーンがリセットされ検出されないことを確認する。"""
    author = FakeAuthor(bot=False, author_id=7000)
    clock = {"value": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["value"])

    message1 = FakeMessage(
        "古池や", FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8400,
    )
    await client.on_message(message1)

    clock["value"] = 200.0
    message2 = FakeMessage(
        "蛙飛び込む", FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8401,
    )
    await client.on_message(message2)

    clock["value"] = 201.0
    message3 = FakeMessage(
        "水の音", FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=8402,
    )
    await client.on_message(message3)

    assert message3.reply_calls == []


@pytest.mark.asyncio
async def test_senryu_delete_command_is_registered(client):
    """/senryu delete サブコマンドがコマンドツリーに登録されていることを確認する。"""
    senryu_group = client.tree.get_command("senryu", guild=discord.Object(id=GUILD_ID))

    assert senryu_group is not None
    assert any(cmd.name == "delete" for cmd in senryu_group.commands)


class FakeCommandResponse:
    """/senryu delete コマンドの interaction.response の代わりに使うスタブ。"""

    def __init__(self):
        """呼び出し記録用のリストを初期化する。"""
        self.send_message_calls = []

    async def send_message(self, *args, **kwargs):
        """send_message 呼び出しの引数を記録する。"""
        self.send_message_calls.append((args, kwargs))


class FakeCommandInteraction:
    """/senryu delete コマンドのコールバックへ直接渡すためのスタブ。"""

    def __init__(self, channel_id: int, user_id: int):
        """channel_id・user_id を受け取り、関連するスタブ群を組み立てる。"""
        self.channel_id = channel_id
        self.user = FakeAuthor(author_id=user_id)
        self.response = FakeCommandResponse()


@pytest.mark.asyncio
async def test_senryu_delete_command_reports_error_when_list_fails(client, record_store, monkeypatch):
    """記録取得が失敗した場合、フレンドリーなエラーメッセージを ephemeral で返すことを確認する。"""

    def raise_error(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(record_store, "count_records_by_user", raise_error)
    senryu_group = client.tree.get_command("senryu", guild=discord.Object(id=GUILD_ID))
    delete_command = next(cmd for cmd in senryu_group.commands if cmd.name == "delete")
    interaction = FakeCommandInteraction(channel_id=CHANNEL_ID, user_id=5000)

    await delete_command.callback(interaction, keyword=None)

    assert len(interaction.response.send_message_calls) == 1
    args, kwargs = interaction.response.send_message_calls[0]
    assert "取得に失敗" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_on_message_replies_appare_after_senryu_detected(client):
    """川柳検出直後に「あっぱれ」を送ると、あっぱれ頂きました(1)と返信されることを確認する。"""
    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9100,
    )
    await client.on_message(detect_message)

    appare_message = FakeMessage(
        "あっぱれ",
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=8000),
        detect_message.channel,
        message_id=9101,
    )
    await client.on_message(appare_message)

    assert len(detect_message.channel.send_calls) == 1
    content, reference = detect_message.channel.send_calls[0]
    assert content == "あっぱれ頂きました！(1)"
    assert reference.message_id == 9100
    assert reference.channel_id == CHANNEL_ID


@pytest.mark.asyncio
async def test_on_message_replies_appare_with_leading_text(client):
    """「あっぱれ」の前に任意の文字列があっても末尾一致すれば反応することを確認する。"""
    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9150,
    )
    await client.on_message(detect_message)

    appare_message = FakeMessage(
        "本当にあっぱれ",
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=8000),
        detect_message.channel,
        message_id=9151,
    )
    await client.on_message(appare_message)

    assert len(detect_message.channel.send_calls) == 1
    content, reference = detect_message.channel.send_calls[0]
    assert content == "あっぱれ頂きました！(1)"
    assert reference.message_id == 9150
    assert reference.channel_id == CHANNEL_ID


@pytest.mark.asyncio
async def test_on_message_ignores_appare_without_prior_senryu(client):
    """直前に検出された詠みが無いチャンネルでは、あっぱれメッセージに反応しないことを確認する。"""
    appare_message = FakeMessage(
        "あっぱれ",
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=8000),
        FakeChannel(CHANNEL_ID),
        message_id=9200,
    )
    await client.on_message(appare_message)
    assert appare_message.channel.send_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_appare_after_praise_window_expires(client, monkeypatch):
    """直前の詠みの検出から300秒を超えて経過すると、あっぱれメッセージに反応しないことを確認する。"""
    clock = {"value": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["value"])

    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9300,
    )
    await client.on_message(detect_message)

    clock["value"] = 300.01
    appare_message = FakeMessage(
        "あっぱれ",
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=8000),
        detect_message.channel,
        message_id=9301,
    )
    await client.on_message(appare_message)

    assert detect_message.channel.send_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_duplicate_appare_from_same_user(client):
    """同じユーザーが同じ詠みに2回あっぱれを送っても、2回目は反応しないことを確認する。"""
    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9400,
    )
    await client.on_message(detect_message)

    praiser = FakeAuthor(bot=False, author_id=8000)
    first_appare = FakeMessage(
        "あっぱれ", FakeGuild(GUILD_ID), praiser, detect_message.channel, message_id=9401,
    )
    await client.on_message(first_appare)
    second_appare = FakeMessage(
        "あっぱれ", FakeGuild(GUILD_ID), praiser, detect_message.channel, message_id=9402,
    )
    await client.on_message(second_appare)

    assert len(detect_message.channel.send_calls) == 1


@pytest.mark.asyncio
async def test_on_message_ignores_self_appare_from_original_author(client):
    """詠みの投稿者本人が自分の詠みにあっぱれを送っても反応しないことを確認する。"""
    author = FakeAuthor(bot=False, author_id=7000)
    detect_message = FakeMessage(
        SENRYU_TEXT, FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=9500,
    )
    await client.on_message(detect_message)

    self_appare = FakeMessage(
        "あっぱれ", FakeGuild(GUILD_ID), author, detect_message.channel, message_id=9501,
    )
    await client.on_message(self_appare)

    assert detect_message.channel.send_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_appare_from_any_renga_contributor(client):
    """連歌の場合、寄与したいずれのユーザーが自分であっぱれを送っても反応しないことを確認する。"""
    authors = [
        FakeAuthor(bot=False, author_id=1),
        FakeAuthor(bot=False, author_id=2),
        FakeAuthor(bot=False, author_id=1),
    ]
    texts = ["古池や", "蛙飛び込む", "水の音"]
    last_message = None
    for i, (text, author) in enumerate(zip(texts, authors)):
        last_message = FakeMessage(
            text, FakeGuild(GUILD_ID), author, FakeChannel(CHANNEL_ID), message_id=9600 + i,
        )
        await client.on_message(last_message)

    appare_from_contributor = FakeMessage(
        "あっぱれ", FakeGuild(GUILD_ID), FakeAuthor(bot=False, author_id=2),
        last_message.channel, message_id=9610,
    )
    await client.on_message(appare_from_contributor)

    assert last_message.channel.send_calls == []


@pytest.mark.asyncio
async def test_on_message_ignores_appare_from_other_bot(client):
    """自 Bot 以外の Bot から送られたあっぱれメッセージには反応しないことを確認する。"""
    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9700,
    )
    await client.on_message(detect_message)

    appare_from_bot = FakeMessage(
        "あっぱれ", FakeGuild(GUILD_ID), FakeAuthor(bot=True, author_id=8000),
        detect_message.channel, message_id=9701,
    )
    await client.on_message(appare_from_bot)

    assert detect_message.channel.send_calls == []


@pytest.mark.asyncio
async def test_on_message_allows_appare_from_self_bot(client):
    """自 Bot(575 sniper)自身が送信したメッセージも、あっぱれ判定の対象になることを確認する
    (他 Bot からのメッセージは除外されるが、自 Bot は対象外条件から除外されないため)。
    """
    self_bot_id = 6000
    client._connection.user = FakeAuthor(bot=True, author_id=self_bot_id)

    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9800,
    )
    await client.on_message(detect_message)

    self_bot_appare = FakeMessage(
        "あっぱれ",
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=True, author_id=self_bot_id),
        detect_message.channel,
        message_id=9801,
    )
    await client.on_message(self_bot_appare)

    assert len(detect_message.channel.send_calls) == 1
    content, reference = detect_message.channel.send_calls[0]
    assert content == "あっぱれ頂きました！(1)"
    assert reference.message_id == 9800
    assert reference.channel_id == CHANNEL_ID


@pytest.mark.asyncio
async def test_on_message_ignores_message_not_ending_with_appare(client):
    """「あっぱれ」で終わらないメッセージには反応しないことを確認する。"""
    detect_message = FakeMessage(
        SENRYU_TEXT,
        FakeGuild(GUILD_ID),
        FakeAuthor(bot=False, author_id=7000),
        FakeChannel(CHANNEL_ID),
        message_id=9900,
    )
    await client.on_message(detect_message)

    non_matching = FakeMessage(
        "あっぱれです", FakeGuild(GUILD_ID), FakeAuthor(bot=False, author_id=8000),
        detect_message.channel, message_id=9901,
    )
    await client.on_message(non_matching)

    assert detect_message.channel.send_calls == []
