import asyncio
import logging

import discord
from discord import app_commands

from .config_store import ConfigStore
from .senryu.finder import find_candidates, pick_best
from .senryu.preprocess import sanitize_text
from .senryu.tokenizer import tokenize

logger = logging.getLogger(__name__)

REPLY_TEMPLATE = "🎋 川柳を検出しました！\n> {p1}\n> {p2}\n> {p3}"


def build_reply(raw_text: str) -> str | None:
    """生テキストから検出パイプラインを実行し、川柳の返信を構築する。

    raw_text: Discord から取得した生のテキスト。
    返り値: 検出された川柳の返信文字列、または検出されなかった場合は None。
    """
    text = sanitize_text(raw_text)
    if not text:
        return None
    morphemes = tokenize(text)
    if not morphemes:
        return None
    candidates = find_candidates(morphemes, text)
    best = pick_best(candidates)
    if best is None:
        return None
    p1, p2, p3 = best.parts
    return REPLY_TEMPLATE.format(p1=p1, p2=p2, p3=p3)


async def handle_enable(config_store: ConfigStore, channel_id: int) -> str:
    """指定チャンネルの川柳検出を有効化し、通知メッセージを返す。"""
    await asyncio.to_thread(config_store.set_enabled, channel_id, True)
    return "このチャンネルで川柳検出を有効化しました。"


async def handle_disable(config_store: ConfigStore, channel_id: int) -> str:
    """指定チャンネルの川柳検出を無効化し、通知メッセージを返す。"""
    await asyncio.to_thread(config_store.set_enabled, channel_id, False)
    return "このチャンネルで川柳検出を無効化しました。"


async def handle_status(config_store: ConfigStore, channel_id: int, parent_id: int | None) -> str:
    """指定チャンネルの川柳検出の有効/無効状態を報告するメッセージを返す。"""
    enabled = await asyncio.to_thread(config_store.is_enabled, channel_id, parent_id=parent_id)
    state = "有効" if enabled else "無効"
    return f"このチャンネルの川柳検出は現在「{state}」です。"


def create_bot(guild_id: int, config_store: ConfigStore) -> discord.Client:
    """discord.py の Client を組み立て、イベントとスラッシュコマンドを配線する。

    Args:
        guild_id: コマンドを同期する対象ギルドの ID。
        config_store: チャンネルごとの有効/無効設定を保持する ConfigStore。

    Returns:
        イベントハンドラとスラッシュコマンドが登録済みの discord.Client。
    """
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    # allowed_mentions=none() を Client のデフォルトとして設定することで、
    # 検出テキストに @everyone/@here 等が紛れ込んだ場合でも実際の通知としては
    # 発火しなくなる(全メッセージ送信のデフォルト値として継承される)。
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    tree = app_commands.CommandTree(client)
    guild_object = discord.Object(id=guild_id)
    synced = False

    @client.event
    async def on_ready():
        """Bot 起動完了時にスラッシュコマンドを対象ギルドへ同期する(初回のみ)。

        on_ready は再接続(セッション再確立)のたびに再度発火し得るため、
        毎回 sync するとコマンド同期のレートリミットを不必要に消費する。
        """
        nonlocal synced
        if synced:
            return
        await tree.sync(guild=guild_object)
        synced = True

    @client.event
    async def on_message(message: discord.Message):
        """メッセージ受信時に、対象ギルド・有効チャンネルであれば川柳検出を行い返信する。"""
        if message.guild is None:
            return
        if message.guild.id != guild_id:
            return
        if message.author.bot:
            return
        channel = message.channel
        parent_id = getattr(channel, "parent_id", None)
        try:
            # sqlite3 呼び出しはブロッキングなので to_thread でイベントループの外へ逃がす。
            enabled = await asyncio.to_thread(config_store.is_enabled, channel.id, parent_id=parent_id)
        except Exception:
            logger.exception("チャンネル設定の読み込みに失敗したため、このメッセージの処理をスキップします。")
            return
        if not enabled:
            return
        try:
            # 5-7-5 探索は最悪ケースで形態素数の3乗に比例するため、
            # イベントループをブロックしないよう別スレッドで実行する。
            reply = await asyncio.to_thread(build_reply, message.content)
        except Exception:
            logger.exception("川柳検出処理中に例外が発生したため、このメッセージの処理をスキップします。")
            return
        if reply is not None:
            try:
                await message.reply(reply)
            except Exception:
                logger.exception("メッセージへの返信に失敗しました。")

    senryu_group = app_commands.Group(name="senryu", description="川柳検出 Bot のチャンネル設定")

    @senryu_group.command(name="enable", description="このチャンネルで川柳検出を有効化します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable(interaction: discord.Interaction):
        """`/senryu enable` コマンドを処理し、有効化結果を返信する。"""
        if interaction.channel_id is None:
            await interaction.response.send_message(
                "このコマンドはチャンネル内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            message = await handle_enable(config_store, interaction.channel_id)
        except Exception:
            logger.exception("チャンネル設定の更新に失敗しました。")
            await interaction.response.send_message(
                "設定の更新に失敗しました。時間を置いて再度お試しください。", ephemeral=True
            )
            return
        await interaction.response.send_message(message, ephemeral=True)

    @senryu_group.command(name="disable", description="このチャンネルで川柳検出を無効化します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(interaction: discord.Interaction):
        """`/senryu disable` コマンドを処理し、無効化結果を返信する。"""
        if interaction.channel_id is None:
            await interaction.response.send_message(
                "このコマンドはチャンネル内でのみ使用できます。", ephemeral=True
            )
            return
        try:
            message = await handle_disable(config_store, interaction.channel_id)
        except Exception:
            logger.exception("チャンネル設定の更新に失敗しました。")
            await interaction.response.send_message(
                "設定の更新に失敗しました。時間を置いて再度お試しください。", ephemeral=True
            )
            return
        await interaction.response.send_message(message, ephemeral=True)

    @senryu_group.command(name="status", description="このチャンネルの川柳検出設定を表示します")
    async def status(interaction: discord.Interaction):
        """`/senryu status` コマンドを処理し、現在の有効/無効状態を返信する。"""
        if interaction.channel_id is None:
            await interaction.response.send_message(
                "このコマンドはチャンネル内でのみ使用できます。", ephemeral=True
            )
            return
        parent_id = getattr(interaction.channel, "parent_id", None)
        try:
            message = await handle_status(config_store, interaction.channel_id, parent_id)
        except Exception:
            logger.exception("チャンネル設定の読み込みに失敗しました。")
            await interaction.response.send_message(
                "設定の取得に失敗しました。時間を置いて再度お試しください。", ephemeral=True
            )
            return
        await interaction.response.send_message(message, ephemeral=True)

    @tree.error
    async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        """スラッシュコマンド実行時のエラーをログに残し、ユーザーへ簡潔に通知する。"""
        if isinstance(error, app_commands.MissingPermissions):
            logger.info("権限不足によりコマンドが拒否されました: %s", error)
            message = "このコマンドの実行には「サーバー管理」権限が必要です。"
        else:
            logger.exception("スラッシュコマンド処理中に例外が発生しました。", exc_info=error)
            message = "コマンドの処理中にエラーが発生しました。時間を置いて再度お試しください。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    tree.add_command(senryu_group, guild=guild_object)

    return client
