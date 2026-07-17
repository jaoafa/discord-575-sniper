import json
import sqlite3
import threading
from datetime import datetime, timezone

from .senryu.chain import ChainEntry
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
                part4 TEXT,
                part5 TEXT,
                morphemes_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chain_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                pattern TEXT NOT NULL,
                parts_json TEXT NOT NULL
            )
            """
        )
        self._migrate_add_tanka_columns()
        self._conn.commit()

    def _migrate_add_tanka_columns(self) -> None:
        """part1〜part3 の3列時代に作成された既存 DB に part4/part5 列を追加する。

        CREATE TABLE IF NOT EXISTS は既存テーブルに新規列を追加しないため、
        旧スキーマの DB ファイルに対してはこのマイグレーションが必要。
        """
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "part4" not in columns:
            self._conn.execute("ALTER TABLE records ADD COLUMN part4 TEXT")
        if "part5" not in columns:
            self._conn.execute("ALTER TABLE records ADD COLUMN part5 TEXT")

    def add_record(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        message_id: int,
        parts: tuple[str, ...],
        morphemes: list[Morpheme],
    ) -> None:
        """検出した川柳・短歌を1件記録する。

        Args:
            guild_id: 検出元メッセージが投稿されたギルドの ID。
            channel_id: 検出元メッセージが投稿されたチャンネルの ID。
            user_id: 検出元メッセージの投稿者 ID。
            message_id: 検出元メッセージの ID。
            parts: 各パートのテキスト。川柳(3要素)または短歌(5要素)。
            morphemes: 採用された部分に対応する形態素のリスト。
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
        part4 = parts[3] if len(parts) >= 4 else None
        part5 = parts[4] if len(parts) >= 5 else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO records (
                    detected_at, guild_id, channel_id, user_id, message_id,
                    part1, part2, part3, part4, part5, morphemes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    part4,
                    part5,
                    morphemes_json,
                ),
            )
            self._conn.commit()

    def add_chain_record(
        self,
        *,
        guild_id: int,
        channel_id: int,
        kind: str,
        pattern: tuple[int, ...],
        parts: list[ChainEntry],
    ) -> None:
        """複数メッセージ結合により検出した川柳(独吟・連歌)を1件記録する。

        Args:
            guild_id: 検出元メッセージ群が投稿されたギルドの ID。
            channel_id: 検出元メッセージ群が投稿されたチャンネルの ID。
            kind: "独吟" または "連歌"。
            pattern: 一致したモーラ数パターン(現時点では常に (5, 7, 5)。
                将来の拡張に備え固定値ではなく引数として受け取る)。
            parts: 一致した各パート(ChainEntry のリスト、3件)。
        """
        detected_at = datetime.now(timezone.utc).isoformat()
        pattern_str = "-".join(str(n) for n in pattern)
        parts_json = json.dumps(
            [
                {
                    "text": p.text,
                    "user_id": p.user_id,
                    "message_id": p.message_id,
                    "mora": p.mora,
                }
                for p in parts
            ],
            ensure_ascii=False,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chain_records (
                    detected_at, guild_id, channel_id, kind, pattern, parts_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (detected_at, guild_id, channel_id, kind, pattern_str, parts_json),
            )
            self._conn.commit()
