import json
import sqlite3
import threading
from datetime import datetime, timezone

from .senryu.tokenizer import Morpheme


class RecordStore:
    """検出した川柳を SQLite に永続化するクラス。

    件数・期間の制限は設けず、全件を永続的に保存する
    (削除・ローテーションは今回のスコープ外)。
    """

    def __init__(self, db_path: str):
        """RecordStore を初期化し、SQLite データベースを作成・接続する。

        Args:
            db_path: SQLite データベースファイルのパス。
        """
        # check_same_thread=False: 呼び出し側で asyncio.to_thread を使い、
        # イベントループをブロックしないよう別スレッドから呼び出すため。
        # ただし sqlite3 コネクションは複数スレッドからの同時アクセスに対して
        # 安全ではないため、_lock で書き込みを直列化する。
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                part1 TEXT NOT NULL,
                part2 TEXT NOT NULL,
                part3 TEXT NOT NULL,
                morphemes_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def add_record(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        message_id: int,
        parts: tuple[str, str, str],
        morphemes: list[Morpheme],
    ) -> None:
        """検出した川柳を1件記録する。

        Args:
            guild_id: 検出元メッセージが投稿されたギルドの ID。
            channel_id: 検出元メッセージが投稿されたチャンネルの ID。
            user_id: 検出元メッセージの投稿者 ID。
            message_id: 検出元メッセージの ID。
            parts: 5-7-5 の各パートのテキスト。
            morphemes: 採用された川柳部分に対応する形態素のリスト。
        """
        detected_at = datetime.now(timezone.utc).isoformat()
        morphemes_json = json.dumps(
            [
                {
                    "surface": m.surface,
                    "reading": m.reading,
                    "pos": m.pos,
                    "mora": m.mora,
                }
                for m in morphemes
            ],
            ensure_ascii=False,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO records (
                    detected_at, guild_id, channel_id, user_id, message_id,
                    part1, part2, part3, morphemes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detected_at,
                    guild_id,
                    channel_id,
                    user_id,
                    message_id,
                    parts[0],
                    parts[1],
                    parts[2],
                    morphemes_json,
                ),
            )
            self._conn.commit()
