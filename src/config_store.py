import sqlite3


class ConfigStore:
    """チャンネルごとの senryu 検出の有効/無効設定を SQLite で管理するクラス。

    thread チャンネルは親チャンネルの設定を継承し、
    独自の設定を持つ場合はそれを優先する。
    """

    def __init__(self, db_path: str):
        """ConfigStore を初期化し、SQLite データベースを作成・接続する。

        Args:
            db_path: SQLite データベースファイルのパス。
        """
        # check_same_thread=False: 呼び出し側で asyncio.to_thread を使い、
        # イベントループをブロックしないよう別スレッドから呼び出すため。
        # 呼び出しは常に await で直列化されており、同時アクセスは発生しない。
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_settings (
                channel_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def is_enabled(self, channel_id: int, parent_id: int | None = None) -> bool:
        """指定されたチャンネルで senryu 検出が有効か判定する。

        チャンネル自身の設定がある場合はそれを返す。
        ない場合で parent_id が指定されていれば親チャンネルの設定を返す。
        どちらもない場合は False（無効）を返す。

        Args:
            channel_id: 対象のチャンネル ID。
            parent_id: 親チャンネル ID（thread チャンネルの場合）。

        Returns:
            True なら有効、False なら無効。
        """
        own = self._get_raw(channel_id)
        if own is not None:
            return own
        if parent_id is not None:
            parent = self._get_raw(parent_id)
            if parent is not None:
                return parent
        return False

    def set_enabled(self, channel_id: int, enabled: bool) -> None:
        """指定されたチャンネルの senryu 検出有効状態を設定する。

        Args:
            channel_id: 対象のチャンネル ID。
            enabled: True なら有効、False なら無効。
        """
        self._conn.execute(
            """
            INSERT INTO channel_settings (channel_id, enabled) VALUES (?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET enabled = excluded.enabled
            """,
            (channel_id, int(enabled)),
        )
        self._conn.commit()

    def _get_raw(self, channel_id: int) -> bool | None:
        """指定されたチャンネルの設定値を直接取得する。

        Args:
            channel_id: 対象のチャンネル ID。

        Returns:
            設定値が存在する場合はその値、存在しない場合は None。
        """
        row = self._conn.execute(
            "SELECT enabled FROM channel_settings WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        if row is None:
            return None
        return bool(row[0])
