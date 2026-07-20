from dataclasses import dataclass

# 「直前の詠み」の有効期限(秒)。あっぱれメッセージの到着時刻との差分が
# この秒数を超えた場合、その「直前の詠み」は対象外(無視)とする。
PRAISE_WINDOW_SECONDS = 300.0


@dataclass
class LastSenryu:
    """チャンネルごとに保持する「直前の詠み」への参照。"""

    source: str
    """詠みの由来。"record"(単一メッセージ検出)または "chain_record"(独吟・連歌検出)。"""
    source_id: int
    """source に対応するテーブル(records/chain_records)の id。"""
    channel_id: int
    reply_message_id: int
    """あっぱれ返信の reply 対象とする元メッセージの ID。"""
    author_user_ids: frozenset[int]
    """その詠みの投稿者(連歌の場合は寄与した全ユーザー)。自己あっぱれ判定に使う。"""
    detected_at: float
    """time.monotonic() による検出時刻。"""


class PraiseTracker:
    """チャンネルごとに「直前の詠み」を保持し、あっぱれ対象判定を行うクラス。

    ChainTracker と同様、プロセスのメモリ上にのみ状態を保持し永続化しない
    (Bot 再起動で「直前の詠み」が失われるのは仕様上許容している)。
    """

    def __init__(self) -> None:
        """チャンネルごとの「直前の詠み」を保持する辞書を空の状態で初期化する。"""
        self._last: dict[int, LastSenryu] = {}

    def record_detection(
        self,
        *,
        channel_id: int,
        source: str,
        source_id: int,
        reply_message_id: int,
        author_user_ids: frozenset[int],
        now: float,
    ) -> None:
        """新たに検出された詠みを、そのチャンネルの「直前の詠み」として記録する。

        既に記録済みの「直前の詠み」があれば上書きする(チャンネルごとに
        常に最大1件のみ保持する)。
        """
        self._last[channel_id] = LastSenryu(
            source=source,
            source_id=source_id,
            channel_id=channel_id,
            reply_message_id=reply_message_id,
            author_user_ids=author_user_ids,
            detected_at=now,
        )

    def get_target(self, *, channel_id: int, now: float) -> LastSenryu | None:
        """有効期限内(PRAISE_WINDOW_SECONDS 以内)の「直前の詠み」があれば返す。

        Args:
            channel_id: 対象チャンネルの ID。
            now: 現在時刻を表す単調増加する秒数(例: time.monotonic())。

        Returns:
            「直前の詠み」が存在せず、または検出時刻から PRAISE_WINDOW_SECONDS を
            超えて経過している場合は None。それ以外は記録済みの LastSenryu。
        """
        entry = self._last.get(channel_id)
        if entry is None:
            return None
        if now - entry.detected_at > PRAISE_WINDOW_SECONDS:
            return None
        return entry
