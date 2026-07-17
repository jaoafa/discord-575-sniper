from dataclasses import dataclass

from .finder import SENRYU_PATTERN, can_start_part
from .mora import total_mora
from .tokenizer import Morpheme

# 直前の保持メッセージからこの秒数を超えて間隔が空くと、会話が途切れたとみなしチェーンをリセットする。
CHAIN_TIMEOUT_SECONDS = 180.0

# チェーンが保持する保持メッセージの最大件数。5-7-5 の一致判定は直近3件のみを見るため、
# 5-7-5 が成立しないまま5件を超えて積み上がった場合に古いものから捨てるためのスライディングウィンドウの上限として使う(仕様上の「直前最大5件」)。
MAX_CHAIN_LENGTH = 5


@dataclass
class ChainEntry:
    """チェーンに保持する1件分のメッセージ情報。"""

    text: str
    user_id: int
    message_id: int
    mora: int
    timestamp: float


@dataclass
class ChainMatch:
    """複数メッセージ結合により検出された川柳(独吟・連歌)。"""

    kind: str
    pattern: tuple[int, ...]
    parts: list[ChainEntry]


def _kind_of(parts: list[ChainEntry]) -> str:
    """一致した各パートの投稿者が単一かどうかで「独吟」「連歌」を判定する。"""
    user_ids = {p.user_id for p in parts}
    return "独吟" if len(user_ids) == 1 else "連歌"


def _find_match(chain: list[ChainEntry]) -> ChainMatch | None:
    """チェーン末尾3件が川柳(5, 7, 5)のパターンと一致するか調べる。

    TANKA_PATTERN(5, 7, 5, 7, 7)の先頭3要素は定義上必ず(5, 7, 5)と一致するため、この判定はメッセージが1件追加されるたびに毎回行われる以上、チェーンが3件に達した時点で常に先に川柳として確定する。したがって複数メッセージ結合による短歌の検出は数学的に到達不可能であり、この関数は川柳のみを対象とする。
    """
    if len(chain) >= 3 and tuple(e.mora for e in chain[-3:]) == SENRYU_PATTERN:
        parts = chain[-3:]
        return ChainMatch(kind=_kind_of(parts), pattern=SENRYU_PATTERN, parts=parts)
    return None


class ChainTracker:
    """チャンネルごとに直近の保持メッセージの列(チェーン)を管理するクラス。

    チェーンはプロセスのメモリ上にのみ保持し、永続化しない
    (Bot 再起動でチェーンが失われるのは仕様上許容している)。
    """

    def __init__(self) -> None:
        """チャンネルごとのチェーンを保持する辞書を空の状態で初期化する。"""
        self._chains: dict[int, list[ChainEntry]] = {}

    def _store(self, channel_id: int, chain: list[ChainEntry]) -> None:
        """チェーンを channel_id に紐づけて保存する。

        空リストをそのまま辞書に残すと、作成・アーカイブが繰り返されるスレッドの ID が使われなくなった後も辞書に残り続けてしまうため、空になった時点でキーごと削除しメモリ上に残さないようにする。
        """
        if chain:
            self._chains[channel_id] = chain
        else:
            self._chains.pop(channel_id, None)

    def process_message(
        self,
        *,
        channel_id: int,
        user_id: int,
        message_id: int,
        text: str,
        morphemes: list[Morpheme],
        now: float,
    ) -> ChainMatch | None:
        """メッセージを1件処理し、チェーンを更新する。

        Args:
            channel_id: メッセージが投稿されたチャンネル(またはスレッド)の ID。
            user_id: メッセージ投稿者の ID。
            message_id: メッセージの ID。
            text: サニタイズ済みのメッセージ本文。
            morphemes: text を形態素解析した結果。総モーラ数の算出と、先頭形態素が付属語(助詞・助動詞など)でないかの判定(can_start_part())に使う。
            now: 現在時刻を表す単調増加する秒数(例: time.monotonic())。
                呼び出し側から注入することでテスト時に任意の時刻を扱える。

        Returns:
            5-7-5 が成立した場合は ChainMatch、成立しなかった場合は None(5-7-5-7-7 は数学的に到達不可能なため対象外)。
        """
        chain = self._chains.get(channel_id, [])
        if chain and (now - chain[-1].timestamp) > CHAIN_TIMEOUT_SECONDS:
            chain = []

        mora = total_mora(morphemes)
        if mora not in (5, 7) or not can_start_part(morphemes[0]):
            self._store(channel_id, [])
            return None

        chain = chain + [
            ChainEntry(
                text=text, user_id=user_id, message_id=message_id,
                mora=mora, timestamp=now,
            )
        ]
        if len(chain) > MAX_CHAIN_LENGTH:
            chain = chain[-MAX_CHAIN_LENGTH:]

        match = _find_match(chain)
        self._store(channel_id, [] if match is not None else chain)
        return match
