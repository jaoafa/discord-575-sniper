import discord
import pytest

from src.config_store import ConfigStore
from src.discord_client import (
    _DeleteBaseView,
    _format_record_option_label,
    _format_record_preview,
    build_reply,
    handle_delete_execute,
    handle_delete_list,
    handle_disable,
    handle_enable,
    handle_remix,
    handle_status,
)
from src.record_store import RecordStore, RecordSummary


def test_build_reply_detects_575_famous_example():
    """有名な五七五の句を渡すと DetectionResult が返り、各句を含む返信文が生成されることを確認する。"""
    # 「古池や(5)/蛙飛び込む(7)/水の音(5)」= 17モーラの有名な句
    text = "古池や蛙飛び込む水の音"
    result = build_reply(text)
    assert result is not None
    assert result.reply_text.startswith("🎋")
    assert "古池や" in result.reply_text
    assert "蛙飛び込む" in result.reply_text
    assert "水の音" in result.reply_text
    assert result.candidate.parts == ("古池や", "蛙飛び込む", "水の音")
    assert len(result.morphemes) == result.candidate.end_idx - result.candidate.start_idx


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


@pytest.fixture
def record_store(tmp_path):
    """テスト用の一時 SQLite ファイルを使う RecordStore を生成する。"""
    return RecordStore(str(tmp_path / "records.db"))


@pytest.mark.asyncio
async def test_handle_remix_composes_tanka_from_records(record_store):
    """5句すべての素材が揃っている場合、5行構成の短歌が合成され、
    各行に投稿者メンションが含まれることを確認する。
    """
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う", "え", "お"), morphemes=[],
        app_version="1.0.0",
    )

    message = await handle_remix(record_store, channel_id=111)

    assert message.startswith("🎋")
    assert "あ" in message
    assert "い" in message
    assert "う" in message
    assert "え" in message
    assert "お" in message
    assert "<@42>" in message
    assert message.count("\n") == 5  # 見出し1行 + 句5行


@pytest.mark.asyncio
async def test_handle_remix_reports_shortage_when_no_records(record_store):
    """対象チャンネルに records が1件も無い場合、素材不足のエラーメッセージを返すことを確認する。"""
    message = await handle_remix(record_store, channel_id=111)

    assert "足り" in message


@pytest.mark.asyncio
async def test_handle_remix_reports_shortage_when_no_tanka_records(record_store):
    """part4/part5 に使える短歌由来レコードが無い場合(川柳由来レコードしか無い場合)、
    素材不足のエラーメッセージを返すことを確認する。
    """
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=1, message_id=1,
        parts=("あ", "い", "う"), morphemes=[],
        app_version="1.0.0",
    )

    message = await handle_remix(record_store, channel_id=111)

    assert "足り" in message


@pytest.mark.asyncio
async def test_handle_delete_list_returns_empty_when_no_records(record_store):
    """該当レコードが1件も無い場合、空リストと件数0を返すことを確認する。"""
    records, total_count = await handle_delete_list(
        record_store, channel_id=111, user_id=42, keyword=None, offset=0,
    )

    assert records == []
    assert total_count == 0


@pytest.mark.asyncio
async def test_handle_delete_list_returns_own_records_newest_first(record_store):
    """実行者自身のレコードを新しい順に返すことを確認する。"""
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=2,
        parts=("か", "き", "く"), morphemes=[], app_version="1.0.0",
    )
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=999, message_id=3,
        parts=("さ", "し", "す"), morphemes=[], app_version="1.0.0",
    )

    records, total_count = await handle_delete_list(
        record_store, channel_id=111, user_id=42, keyword=None, offset=0,
    )

    assert total_count == 2
    assert [r.part1 for r in records] == ["か", "あ"]


@pytest.mark.asyncio
async def test_handle_delete_execute_deletes_own_record(record_store):
    """実行者自身のレコードを削除し True を返すことを確認する。"""
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    record = record_store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)[0]

    deleted = await handle_delete_execute(record_store, record_id=record.id, user_id=42)

    assert deleted is True


@pytest.mark.asyncio
async def test_handle_delete_execute_rejects_other_users_record(record_store):
    """他人のレコードは削除できず False を返すことを確認する。"""
    record_store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    record = record_store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)[0]

    deleted = await handle_delete_execute(record_store, record_id=record.id, user_id=999)

    assert deleted is False


class FakeUser:
    """discord.abc.User の代わりに使うスタブ。"""

    def __init__(self, user_id: int):
        self.id = user_id


class FakeResponse:
    """discord.InteractionResponse の代わりに使うスタブ。呼び出し内容を記録する。"""

    def __init__(self):
        self.edit_message_calls = []
        self.send_message_calls = []

    async def edit_message(self, **kwargs):
        """edit_message 呼び出しの引数を記録する。"""
        self.edit_message_calls.append(kwargs)

    async def send_message(self, **kwargs):
        """send_message 呼び出しの引数を記録する。"""
        self.send_message_calls.append(kwargs)


class FakeInteractionMessage:
    """discord.Message の代わりに使うスタブ。edit 呼び出しを記録する。"""

    def __init__(self):
        self.edit_calls = []

    async def edit(self, **kwargs):
        """edit 呼び出しの引数を記録する。"""
        self.edit_calls.append(kwargs)


class FakeInteraction:
    """discord.Interaction の代わりに使うスタブ。"""

    def __init__(self, user_id: int):
        self.user = FakeUser(user_id)
        self.response = FakeResponse()
        self.message = FakeInteractionMessage()


def test_format_record_option_label_joins_parts_with_slash():
    """複数パートを " / " 区切りで連結したラベルを組み立てることを確認する。"""
    record = RecordSummary(
        id=1, part1="あ", part2="い", part3="う", part4=None, part5=None,
        detected_at="2026-01-01T00:00:00+00:00",
    )

    label = _format_record_option_label(record)

    assert label == "あ / い / う"


def test_format_record_option_label_truncates_when_too_long():
    """100文字を超える場合、末尾を切り詰め省略記号を付与することを確認する。"""
    record = RecordSummary(
        id=1, part1="あ" * 60, part2="い" * 60, part3="う", part4=None, part5=None,
        detected_at="2026-01-01T00:00:00+00:00",
    )

    label = _format_record_option_label(record)

    assert len(label) == 100
    assert label.endswith("…")


def test_format_record_preview_includes_all_parts():
    """5パート(短歌)すべてがプレビュー本文に含まれることを確認する。"""
    record = RecordSummary(
        id=1, part1="あ", part2="い", part3="う", part4="え", part5="お",
        detected_at="2026-01-01T00:00:00+00:00",
    )

    preview = _format_record_preview(record)

    assert "あ" in preview
    assert "い" in preview
    assert "う" in preview
    assert "え" in preview
    assert "お" in preview


@pytest.mark.asyncio
async def test_delete_base_view_interaction_check_rejects_other_user():
    """コマンド実行者以外の操作を拒否することを確認する。"""
    view = _DeleteBaseView(user_id=42)
    interaction = FakeInteraction(user_id=999)

    allowed = await view.interaction_check(interaction)

    assert allowed is False
    assert len(interaction.response.send_message_calls) == 1


@pytest.mark.asyncio
async def test_delete_base_view_interaction_check_allows_same_user():
    """コマンド実行者本人の操作を許可することを確認する。"""
    view = _DeleteBaseView(user_id=42)
    interaction = FakeInteraction(user_id=42)

    allowed = await view.interaction_check(interaction)

    assert allowed is True
    assert len(interaction.response.send_message_calls) == 0


@pytest.mark.asyncio
async def test_delete_base_view_on_timeout_disables_items_and_edits_message():
    """タイムアウト時に全コンポーネントを無効化し、メッセージを更新することを確認する。"""
    view = _DeleteBaseView(user_id=42)
    button = discord.ui.Button(label="テスト", disabled=False)
    view.add_item(button)
    message = FakeInteractionMessage()
    view.message = message

    await view.on_timeout()

    assert button.disabled is True
    assert len(message.edit_calls) == 1
    assert "タイムアウト" in message.edit_calls[0]["content"]
