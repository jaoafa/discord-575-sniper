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
                morphemes_json TEXT NOT NULL,
                app_version TEXT
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
                parts_json TEXT NOT NULL,
                app_version TEXT
            )
            """
        )
        self._migrate_add_tanka_columns()
        self._migrate_add_app_version_column()
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

    def _migrate_add_app_version_column(self) -> None:
        """app_version 列が無い時代に作成された既存 DB に app_version 列を追加する。

        CREATE TABLE IF NOT EXISTS は既存テーブルに新規列を追加しないため、
        旧スキーマの DB ファイルに対してはこのマイグレーションが必要。
        マイグレーション前に挿入された既存レコードの app_version は
        NULL のままとなる(遡及付与はスコープ外)。
        """
        records_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "app_version" not in records_columns:
            self._conn.execute("ALTER TABLE records ADD COLUMN app_version TEXT")
        chain_records_columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(chain_records)")
        }
        if "app_version" not in chain_records_columns:
            self._conn.execute("ALTER TABLE chain_records ADD COLUMN app_version TEXT")

    def add_record(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        message_id: int,
        parts: tuple[str, ...],
        morphemes: list[Morpheme],
        app_version: str,
    ) -> None:
        """検出した川柳・短歌を1件記録する。

        Args:
            guild_id: 検出元メッセージが投稿されたギルドの ID。
            channel_id: 検出元メッセージが投稿されたチャンネルの ID。
            user_id: 検出元メッセージの投稿者 ID。
            message_id: 検出元メッセージの ID。
            parts: 各パートのテキスト。川柳(3要素)または短歌(5要素)。
            morphemes: 採用された部分に対応する形態素のリスト。
            app_version: 検出時に稼働していた discord-575-sniper のバージョン。
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
                    part1, part2, part3, part4, part5, morphemes_json, app_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    app_version,
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
        app_version: str,
    ) -> None:
        """複数メッセージ結合により検出した川柳(独吟・連歌)を1件記録する。

        Args:
            guild_id: 検出元メッセージ群が投稿されたギルドの ID。
            channel_id: 検出元メッセージ群が投稿されたチャンネルの ID。
            kind: "独吟" または "連歌"。
            pattern: 一致したモーラ数パターン(現時点では常に (5, 7, 5)。
                将来の拡張に備え固定値ではなく引数として受け取る)。
            parts: 一致した各パート(ChainEntry のリスト、3件)。
            app_version: 検出時に稼働していた discord-575-sniper のバージョン。
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
                    detected_at, guild_id, channel_id, kind, pattern, parts_json, app_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (detected_at, guild_id, channel_id, kind, pattern_str, parts_json, app_version),
            )
            self._conn.commit()

    _PICKABLE_COLUMNS = frozenset({"part1", "part2", "part3", "part4", "part5"})

    def pick_random_part(
        self, *, channel_id: int, column: str, require_tanka: bool = False
    ) -> tuple[str, int] | None:
        """指定チャンネルの records からランダムに1句を選ぶ。

        Args:
            channel_id: 対象チャンネルの ID。
            column: 取得する列名(_PICKABLE_COLUMNS のいずれか)。
            require_tanka: True の場合、part4 が NOT NULL のレコード
                (短歌として検出されたレコード)のみを対象にする。

        Returns:
            (句のテキスト, 投稿者 user_id) のタプル。対象レコードが
            1件も無い場合は None。

        Raises:
            ValueError: column が許可された列名集合に含まれない場合。
        """
        if column not in self._PICKABLE_COLUMNS:
            raise ValueError(f"invalid column: {column!r}")
        # column 自体も NOT NULL 条件に含める: part4/part5 は本来常に両方
        # NULL か両方非 NULL のはずだが、その前提が将来崩れても
        # (句のテキスト, user_id) の非 NULL 保証(戻り値の型)を守るため。
        query = f"SELECT {column}, user_id FROM records WHERE channel_id = ? AND {column} IS NOT NULL"
        params: list[object] = [channel_id]
        if require_tanka:
            query += " AND part4 IS NOT NULL"
        query += " ORDER BY RANDOM() LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        if row is None:
            return None
        return (row[0], row[1])
