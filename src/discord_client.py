import asyncio
import logging
import time
from dataclasses import dataclass

import discord
from discord import app_commands

from .config_store import ConfigStore
from .record_store import RecordStore
from .senryu.chain import ChainMatch, ChainTracker
from .senryu.finder import Candidate, find_candidates, pick_best
from .senryu.preprocess import sanitize_text
from .senryu.tokenizer import Morpheme, tokenize

logger = logging.getLogger(__name__)

_REPLY_HEADERS: dict[int, str] = {
    3: "🎋 川柳を検出しました！",
    5: "🎋 短歌を検出しました！",
}


def _build_reply_text(candidate: Candidate) -> str:
    """検出した候補のパート数に応じた見出しで返信テキストを組み立てる。"""
    header = _REPLY_HEADERS[len(candidate.parts)]
    lines = "\n".join(f"> {p}" for p in candidate.parts)
    return f"{header}\n{lines}"


def _build_chain_reply_text(match: ChainMatch) -> str:
    """複数メッセージ結合により検出した独吟・連歌の返信テキストを組み立てる。

    連歌の場合は、どの投稿者がどのパートを詠んだか分かるよう各行にメンションを付与する。Client 側で AllowedMentions.none() を設定しているため、これによって実際の通知が発生することはない。
    """
    header = f"🎋 {match.kind}を検出しました！"
    if match.kind == "独吟":
        lines = "\n".join(f"> {p.text}" for p in match.parts)
    else:
        lines = "\n".join(f"> {p.text} (<@{p.user_id}>)" for p in match.parts)
    return f"{header}\n{lines}"


@dataclass
class DetectionResult:
    """川柳検出パイプラインの結果。返信テキストと記録用データの両方を保持する。"""

    reply_text: str
    candidate: Candidate
    morphemes: list[Morpheme]


@dataclass
class TokenizedMessage:
    """1件のメッセージをサニタイズ・形態素解析した結果。"""

    text: str
    morphemes: list[Morpheme]


def _tokenize_message(raw_text: str) -> TokenizedMessage:
    """生テキストをサニタイズし形態素解析する。空文字列になる場合は空リストを返す。"""
    text = sanitize_text(raw_text)
    morphemes = tokenize(text) if text else []
    return TokenizedMessage(text=text, morphemes=morphemes)


def _detect_single_message(tokenized: TokenizedMessage) -> DetectionResult | None:
    """トークナイズ済みの1件のメッセージから単一メッセージ内の5-7-5/5-7-5-7-7検出を行う。"""
    if not tokenized.morphemes:
        return None
    candidates = find_candidates(tokenized.morphemes, tokenized.text)
    best = pick_best(candidates)
    if best is None:
        return None
    reply_text = _build_reply_text(best)
    return DetectionResult(
        reply_text=reply_text,
        candidate=best,
        morphemes=tokenized.morphemes[best.start_idx:best.end_idx],
    )


def _process_message_text(raw_text: str) -> tuple[DetectionResult | None, TokenizedMessage]:
    """1回のトークナイズで、単一メッセージ内検出の結果とトークナイズ結果の両方を返す。

    トークナイズ結果は呼び出し側がチェーン検出(ChainTracker)にも再利用し、
    同じメッセージを二重にトークナイズしないようにする。
    """
    tokenized = _tokenize_message(raw_text)
    detection = _detect_single_message(tokenized)
    return detection, tokenized


def build_reply(raw_text: str) -> DetectionResult | None:
    """生テキストから単一メッセージ内の検出パイプラインを実行する。

    raw_text: Discord から取得した生のテキスト。
    返り値: 検出結果(DetectionResult)、または検出されなかった場合は None。
    """
    return _detect_single_message(_tokenize_message(raw_text))


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


def create_bot(
    guild_id: int,
    config_store: ConfigStore,
    record_store: RecordStore,
    chain_tracker: ChainTracker,
) -> discord.Client:
    """discord.py の Client を組み立て、イベントとスラッシュコマンドを配線する。

    Args:
        guild_id: コマンドを同期する対象ギルドの ID。
        config_store: チャンネルごとの有効/無効設定を保持する ConfigStore。
        record_store: 検出した川柳を記録する RecordStore。
        chain_tracker: 複数メッセージ結合による独吟・連歌検出の状態を保持する ChainTracker。

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
    # to_thread() を経由するため、同一チャンネル宛のイベントが並行実行され得る。
    # チェーン検出はメッセージの到着順に処理される必要があるため、チャンネルごとに
    # ロックを用意して on_message の本体を直列化する。
    channel_locks: dict[int, asyncio.Lock] = {}

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
        lock = channel_locks.setdefault(channel.id, asyncio.Lock())
        async with lock:
            try:
                # 5-7-5・5-7-5-7-7 探索は最悪ケースで形態素数のパート数乗に比例するため、
                # イベントループをブロックしないよう別スレッドで実行する。
                detection, tokenized = await asyncio.to_thread(_process_message_text, message.content)
            except Exception:
                logger.exception("川柳検出処理中に例外が発生したため、このメッセージの処理をスキップします。")
                return
            if detection is not None:
                try:
                    # sqlite3 呼び出しはブロッキングなので to_thread でイベントループの外へ逃がす。
                    # 記録と返信は互いの成否に依存させない(検出した事実自体を残しつつ、
                    # 記録側の障害でユーザーへの返信まで失われないようにするため)。
                    await asyncio.to_thread(
                        record_store.add_record,
                        guild_id=message.guild.id,
                        channel_id=channel.id,
                        user_id=message.author.id,
                        message_id=message.id,
                        parts=detection.candidate.parts,
                        morphemes=detection.morphemes,
                    )
                except Exception:
                    logger.exception("川柳の記録に失敗しました。")
                try:
                    await message.reply(detection.reply_text)
                except Exception:
                    logger.exception("メッセージへの返信に失敗しました。")

            try:
                chain_match = chain_tracker.process_message(
                    channel_id=channel.id,
                    user_id=message.author.id,
                    message_id=message.id,
                    text=tokenized.text,
                    morphemes=tokenized.morphemes,
                    now=time.monotonic(),
                )
            except Exception:
                logger.exception("連歌チェーンの処理中に例外が発生しました。")
                chain_match = None
            if chain_match is not None:
                try:
                    # sqlite3 呼び出しはブロッキングなので to_thread でイベントループの外へ逃がす。
                    await asyncio.to_thread(
                        record_store.add_chain_record,
                        guild_id=message.guild.id,
                        channel_id=channel.id,
                        kind=chain_match.kind,
                        pattern=chain_match.pattern,
                        parts=chain_match.parts,
                    )
                except Exception:
                    logger.exception("連歌の記録に失敗しました。")
                try:
                    await message.reply(_build_chain_reply_text(chain_match))
                except Exception:
                    logger.exception("連歌メッセージへの返信に失敗しました。")

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
