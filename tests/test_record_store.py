import json
import sqlite3

import pytest

from src.record_store import RecordStore
from src.senryu.chain import ChainEntry
from src.senryu.tokenizer import Morpheme


def test_add_record_inserts_row(tmp_path):
    """add_record が全カラムを正しい値で INSERT することを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    morphemes = [
        Morpheme(surface="古池", reading="フルイケ", mora=4, start=0, end=2, pos="名詞"),
        Morpheme(surface="や", reading="ヤ", mora=1, start=2, end=3, pos="助詞"),
    ]

    store.add_record(
        guild_id=1000,
        channel_id=2000,
        user_id=3000,
        message_id=4000,
        parts=("古池や", "蛙飛び込む", "水の音"),
        morphemes=morphemes,
        app_version="1.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT guild_id, channel_id, user_id, message_id, part1, part2, part3, "
        "morphemes_json, detected_at, app_version FROM records"
    ).fetchone()
    conn.close()

    assert row is not None
    (
        guild_id, channel_id, user_id, message_id,
        part1, part2, part3, morphemes_json, detected_at, app_version,
    ) = row
    assert guild_id == 1000
    assert channel_id == 2000
    assert user_id == 3000
    assert message_id == 4000
    assert part1 == "古池や"
    assert part2 == "蛙飛び込む"
    assert part3 == "水の音"
    assert detected_at != ""
    assert app_version == "1.0.0"

    decoded = json.loads(morphemes_json)
    assert decoded == [
        {"surface": "古池", "reading": "フルイケ", "pos": "名詞", "mora": 4},
        {"surface": "や", "reading": "ヤ", "pos": "助詞", "mora": 1},
    ]


def test_add_record_multiple_rows_accumulate(tmp_path):
    """複数回 add_record を呼ぶと全件が蓄積されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    for i in range(3):
        store.add_record(
            guild_id=1,
            channel_id=2,
            user_id=3,
            message_id=100 + i,
            parts=("a", "b", "c"),
            morphemes=[],
            app_version="1.0.0",
        )

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    assert count == 3


def test_persists_across_instances(tmp_path):
    """同じ DB ファイルを指す別インスタンスからも記録が引き継がれることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store1 = RecordStore(db_path)
    store1.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=4,
        parts=("a", "b", "c"), morphemes=[], app_version="1.0.0",
    )

    store2 = RecordStore(db_path)
    assert store2 is not None

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    assert count == 1


def test_add_record_inserts_five_part_row_for_tanka(tmp_path):
    """短歌(5パート)を渡した場合に part4/part5 まで正しく INSERT されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    store.add_record(
        guild_id=1000,
        channel_id=2000,
        user_id=3000,
        message_id=4000,
        parts=("古池や", "蛙飛び込む", "水の音", "やまぶきのえだ", "うめがかがやく"),
        morphemes=[],
        app_version="1.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT part1, part2, part3, part4, part5 FROM records"
    ).fetchone()
    conn.close()

    assert row == ("古池や", "蛙飛び込む", "水の音", "やまぶきのえだ", "うめがかがやく")


def test_add_record_sets_part4_and_part5_null_for_senryu(tmp_path):
    """川柳(3パート)を渡した場合は part4/part5 が NULL のまま INSERT されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    store.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=4,
        parts=("古池や", "蛙飛び込む", "水の音"), morphemes=[], app_version="1.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT part4, part5 FROM records").fetchone()
    conn.close()

    assert row == (None, None)


def test_add_record_migrates_legacy_three_column_schema(tmp_path):
    """part4/part5 列がない旧スキーマの DB ファイルを開いても、
    マイグレーションにより5パートの記録が成功することを確認する。
    """
    db_path = str(tmp_path / "records.db")
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        """
        CREATE TABLE records (
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
    legacy_conn.commit()
    legacy_conn.close()

    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=4,
        parts=("あ", "い", "う", "え", "お"), morphemes=[], app_version="1.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT part1, part2, part3, part4, part5 FROM records").fetchone()
    conn.close()
    assert row == ("あ", "い", "う", "え", "お")


def test_add_chain_record_inserts_senryu_row(tmp_path):
    """add_chain_record が独吟・連歌(川柳パターン)の行を正しい値で INSERT することを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    parts = [
        ChainEntry(text="古池や", user_id=1, message_id=10, mora=5, timestamp=0.0),
        ChainEntry(text="蛙飛び込む", user_id=1, message_id=11, mora=7, timestamp=1.0),
        ChainEntry(text="水の音", user_id=1, message_id=12, mora=5, timestamp=2.0),
    ]

    store.add_chain_record(
        guild_id=1000, channel_id=2000, kind="独吟", pattern=(5, 7, 5), parts=parts,
        app_version="1.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT guild_id, channel_id, kind, pattern, parts_json, detected_at FROM chain_records"
    ).fetchone()
    conn.close()

    assert row is not None
    guild_id, channel_id, kind, pattern, parts_json, detected_at = row
    assert guild_id == 1000
    assert channel_id == 2000
    assert kind == "独吟"
    assert pattern == "5-7-5"
    assert detected_at != ""
    decoded = json.loads(parts_json)
    assert decoded == [
        {"text": "古池や", "user_id": 1, "message_id": 10, "mora": 5},
        {"text": "蛙飛び込む", "user_id": 1, "message_id": 11, "mora": 7},
        {"text": "水の音", "user_id": 1, "message_id": 12, "mora": 5},
    ]


def test_add_chain_record_formats_arbitrary_pattern_tuple_as_string(tmp_path):
    """pattern 引数に渡した任意長のタプルが "-" 区切りの文字列として保存されることを
    確認する(add_chain_record 自体はパターンの長さに依存しない汎用実装であることの
    確認。ChainTracker からは現時点では (5, 7, 5) のみが渡される)。
    """
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    parts = [
        ChainEntry(text=f"part{i}", user_id=1, message_id=i, mora=m, timestamp=float(i))
        for i, m in enumerate([5, 7, 5, 7, 7])
    ]

    store.add_chain_record(
        guild_id=1, channel_id=2, kind="連歌", pattern=(5, 7, 5, 7, 7), parts=parts,
        app_version="1.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT pattern FROM chain_records").fetchone()
    conn.close()
    assert row == ("5-7-5-7-7",)


def test_add_chain_record_multiple_rows_accumulate(tmp_path):
    """複数回 add_chain_record を呼ぶと全件が蓄積されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    parts = [
        ChainEntry(text="a", user_id=1, message_id=1, mora=5, timestamp=0.0),
        ChainEntry(text="b", user_id=1, message_id=2, mora=7, timestamp=1.0),
        ChainEntry(text="c", user_id=1, message_id=3, mora=5, timestamp=2.0),
    ]
    for _ in range(3):
        store.add_chain_record(
            guild_id=1, channel_id=2, kind="独吟", pattern=(5, 7, 5), parts=parts,
            app_version="1.0.0",
        )

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM chain_records").fetchone()[0]
    conn.close()
    assert count == 3


def test_pick_random_part_returns_none_when_no_records(tmp_path):
    """対象チャンネルにレコードが1件も無ければ None を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    result = store.pick_random_part(channel_id=2000, column="part1")

    assert result is None


def test_pick_random_part_returns_text_and_user_id(tmp_path):
    """レコードが存在する場合、指定列のテキストと投稿者 user_id を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=2000, user_id=9999, message_id=1,
        parts=("古池や", "蛙飛び込む", "水の音"), morphemes=[], app_version="1.0.0",
    )

    result = store.pick_random_part(channel_id=2000, column="part1")

    assert result == ("古池や", 9999)


def test_pick_random_part_filters_by_channel_id(tmp_path):
    """他チャンネルのレコードは対象にならないことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=3000, user_id=1, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )

    result = store.pick_random_part(channel_id=2000, column="part1")

    assert result is None


def test_pick_random_part_without_require_tanka_includes_senryu_records(tmp_path):
    """require_tanka=False(デフォルト)では川柳由来レコード(part4 が NULL)も
    part1〜part3 の取得対象に含まれることを確認する。
    """
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=2000, user_id=1, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )

    result = store.pick_random_part(channel_id=2000, column="part2")

    assert result == ("い", 1)


def test_pick_random_part_require_tanka_excludes_senryu_records(tmp_path):
    """require_tanka=True では川柳由来レコード(part4 が NULL)が除外されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=2000, user_id=1, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )

    result = store.pick_random_part(channel_id=2000, column="part4", require_tanka=True)

    assert result is None


def test_pick_random_part_require_tanka_includes_tanka_records(tmp_path):
    """require_tanka=True では短歌由来レコード(part4/part5 が NOT NULL)から
    part4/part5 を取得できることを確認する。
    """
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=2000, user_id=42, message_id=1,
        parts=("あ", "い", "う", "え", "お"), morphemes=[], app_version="1.0.0",
    )

    result = store.pick_random_part(channel_id=2000, column="part4", require_tanka=True)

    assert result == ("え", 42)


def test_pick_random_part_rejects_invalid_column(tmp_path):
    """許可外の列名を渡すと ValueError を送出することを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    with pytest.raises(ValueError):
        store.pick_random_part(channel_id=2000, column="part6")


def test_add_chain_record_inserts_app_version(tmp_path):
    """add_chain_record が app_version を正しく保存することを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    parts = [
        ChainEntry(text="古池や", user_id=1, message_id=10, mora=5, timestamp=0.0),
        ChainEntry(text="蛙飛び込む", user_id=1, message_id=11, mora=7, timestamp=1.0),
        ChainEntry(text="水の音", user_id=1, message_id=12, mora=5, timestamp=2.0),
    ]

    store.add_chain_record(
        guild_id=1000, channel_id=2000, kind="独吟", pattern=(5, 7, 5), parts=parts,
        app_version="2.0.0",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT app_version FROM chain_records").fetchone()
    conn.close()
    assert row == ("2.0.0",)


def test_add_record_migrates_legacy_schema_without_app_version_column(tmp_path):
    """app_version 列がない旧スキーマの DB ファイルを開いても、records・chain_records
    両テーブルへのマイグレーションにより app_version 付きの記録が成功することを確認する。
    """
    db_path = str(tmp_path / "records.db")
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        """
        CREATE TABLE records (
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
    legacy_conn.execute(
        """
        CREATE TABLE chain_records (
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
    legacy_conn.commit()
    legacy_conn.close()

    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=4,
        parts=("あ", "い", "う"), morphemes=[], app_version="3.0.0",
    )
    store.add_chain_record(
        guild_id=1, channel_id=2, kind="独吟", pattern=(5, 7, 5),
        parts=[ChainEntry(text="あ", user_id=3, message_id=4, mora=5, timestamp=0.0)],
        app_version="3.0.0",
    )

    conn = sqlite3.connect(db_path)
    records_row = conn.execute("SELECT app_version FROM records").fetchone()
    chain_records_row = conn.execute("SELECT app_version FROM chain_records").fetchone()
    conn.close()
    assert records_row == ("3.0.0",)
    assert chain_records_row == ("3.0.0",)


def test_add_record_leaves_pre_migration_rows_app_version_null(tmp_path):
    """マイグレーション前に挿入された既存レコードの app_version は
    NULL のまま残ることを確認する(遡及付与はスコープ外)。
    """
    db_path = str(tmp_path / "records.db")
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        """
        CREATE TABLE records (
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
    legacy_conn.execute(
        "INSERT INTO records (detected_at, guild_id, channel_id, user_id, message_id, "
        "part1, part2, part3, morphemes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2020-01-01T00:00:00+00:00", 1, 2, 3, 4, "あ", "い", "う", "[]"),
    )
    legacy_conn.commit()
    legacy_conn.close()

    # RecordStore を開くだけでマイグレーションが走る(add_record は呼ばない)。
    RecordStore(db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT app_version FROM records WHERE message_id = 4").fetchone()
    conn.close()
    assert row == (None,)


def test_count_records_by_user_returns_zero_when_no_records(tmp_path):
    """該当レコードが1件も無い場合、0件と数えることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    count = store.count_records_by_user(channel_id=111, user_id=42)

    assert count == 0


def test_count_records_by_user_filters_by_channel_and_user(tmp_path):
    """channel_id と user_id の両方が一致するレコードのみを数えることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    store.add_record(
        guild_id=1, channel_id=111, user_id=999, message_id=2,
        parts=("か", "き", "く"), morphemes=[], app_version="1.0.0",
    )
    store.add_record(
        guild_id=1, channel_id=222, user_id=42, message_id=3,
        parts=("さ", "し", "す"), morphemes=[], app_version="1.0.0",
    )

    count = store.count_records_by_user(channel_id=111, user_id=42)

    assert count == 1


def test_count_records_by_user_filters_by_keyword(tmp_path):
    """keyword を指定した場合、いずれかの part に部分一致するレコードのみを数えることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("古池や", "蛙飛び込む", "水の音"), morphemes=[], app_version="1.0.0",
    )
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=2,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )

    count = store.count_records_by_user(channel_id=111, user_id=42, keyword="蛙")

    assert count == 1


def test_list_records_by_user_returns_empty_list_when_no_records(tmp_path):
    """該当レコードが1件も無い場合、空リストを返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    records = store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)

    assert records == []


def test_list_records_by_user_orders_newest_first(tmp_path):
    """detected_at の新しい順(INSERT の後の行ほど先)に返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    for i in range(3):
        store.add_record(
            guild_id=1, channel_id=111, user_id=42, message_id=100 + i,
            parts=(f"part{i}a", f"part{i}b", f"part{i}c"), morphemes=[],
            app_version="1.0.0",
        )

    records = store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)

    assert [r.part1 for r in records] == ["part2a", "part1a", "part0a"]


def test_list_records_by_user_respects_limit_and_offset(tmp_path):
    """limit/offset によるページングが正しく効くことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    for i in range(5):
        store.add_record(
            guild_id=1, channel_id=111, user_id=42, message_id=100 + i,
            parts=(f"part{i}a", f"part{i}b", f"part{i}c"), morphemes=[],
            app_version="1.0.0",
        )

    page1 = store.list_records_by_user(channel_id=111, user_id=42, limit=2, offset=0)
    page2 = store.list_records_by_user(channel_id=111, user_id=42, limit=2, offset=2)

    assert [r.part1 for r in page1] == ["part4a", "part3a"]
    assert [r.part1 for r in page2] == ["part2a", "part1a"]


def test_list_records_by_user_filters_by_keyword(tmp_path):
    """keyword 指定時、部分一致するレコードのみ返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("古池や", "蛙飛び込む", "水の音"), morphemes=[], app_version="1.0.0",
    )
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=2,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )

    records = store.list_records_by_user(channel_id=111, user_id=42, keyword="蛙", limit=25, offset=0)

    assert len(records) == 1
    assert records[0].part2 == "蛙飛び込む"


def test_list_records_by_user_returns_record_summary_fields(tmp_path):
    """返される RecordSummary の各フィールドが正しく設定されていることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う", "え", "お"), morphemes=[], app_version="1.0.0",
    )

    records = store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)

    assert len(records) == 1
    record = records[0]
    assert isinstance(record.id, int)
    assert record.part1 == "あ"
    assert record.part2 == "い"
    assert record.part3 == "う"
    assert record.part4 == "え"
    assert record.part5 == "お"
    assert record.detected_at != ""


def test_delete_record_removes_matching_row_and_returns_true(tmp_path):
    """record_id と user_id が一致する場合、該当行を削除し True を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    record = store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)[0]

    deleted = store.delete_record(record_id=record.id, user_id=42)

    assert deleted is True
    assert store.count_records_by_user(channel_id=111, user_id=42) == 0


def test_delete_record_returns_false_when_user_id_mismatches(tmp_path):
    """user_id が一致しない場合、行を削除せず False を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("あ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    record = store.list_records_by_user(channel_id=111, user_id=42, limit=25, offset=0)[0]

    deleted = store.delete_record(record_id=record.id, user_id=999)

    assert deleted is False
    assert store.count_records_by_user(channel_id=111, user_id=42) == 1


def test_delete_record_returns_false_when_record_id_not_found(tmp_path):
    """存在しない record_id を指定した場合、False を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)

    deleted = store.delete_record(record_id=99999, user_id=42)

    assert deleted is False


def test_list_records_by_user_treats_percent_in_keyword_as_literal(tmp_path):
    """keyword に含まれる % がワイルドカードでなくリテラルとして扱われることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=1,
        parts=("50%オフ", "い", "う"), morphemes=[], app_version="1.0.0",
    )
    store.add_record(
        guild_id=1, channel_id=111, user_id=42, message_id=2,
        parts=("50個", "い", "う"), morphemes=[], app_version="1.0.0",
    )

    records = store.list_records_by_user(channel_id=111, user_id=42, keyword="50%", limit=25, offset=0)

    assert [r.part1 for r in records] == ["50%オフ"]


def test_add_record_returns_inserted_row_id(tmp_path):
    """add_record が挿入した行の id を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    first_id = store.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=4,
        parts=("a", "b", "c"), morphemes=[], app_version="1.0.0",
    )
    second_id = store.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=5,
        parts=("a", "b", "c"), morphemes=[], app_version="1.0.0",
    )
    assert isinstance(first_id, int)
    assert second_id == first_id + 1


def test_add_chain_record_returns_inserted_row_id(tmp_path):
    """add_chain_record が挿入した行の id を返すことを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    parts = [
        ChainEntry(text="古池や", user_id=1, message_id=10, mora=5, timestamp=0.0),
        ChainEntry(text="蛙飛び込む", user_id=1, message_id=11, mora=7, timestamp=1.0),
        ChainEntry(text="水の音", user_id=1, message_id=12, mora=5, timestamp=2.0),
    ]
    first_id = store.add_chain_record(
        guild_id=1, channel_id=2, kind="独吟", pattern=(5, 7, 5), parts=parts,
        app_version="1.0.0",
    )
    second_id = store.add_chain_record(
        guild_id=1, channel_id=2, kind="独吟", pattern=(5, 7, 5), parts=parts,
        app_version="1.0.0",
    )
    assert isinstance(first_id, int)
    assert second_id == first_id + 1


def test_register_praise_returns_one_for_first_praise(tmp_path):
    """初めてのあっぱれで、カウントが1になって返ることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    count = store.register_praise(source="record", source_id=1, user_id=100)
    assert count == 1


def test_register_praise_accumulates_count_across_users(tmp_path):
    """複数ユーザーからのあっぱれでカウントが加算されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.register_praise(source="record", source_id=1, user_id=100)
    count = store.register_praise(source="record", source_id=1, user_id=200)
    assert count == 2


def test_register_praise_ignores_duplicate_user(tmp_path):
    """同じユーザーが同じ詠みに2回あっぱれを送っても、2回目は None を返し
    カウントが加算されないことを確認する。
    """
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.register_praise(source="record", source_id=1, user_id=100)
    second = store.register_praise(source="record", source_id=1, user_id=100)
    assert second is None

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT count FROM praises WHERE source = 'record' AND source_id = 1"
    ).fetchone()
    conn.close()
    assert row == (1,)


def test_register_praise_is_independent_per_source(tmp_path):
    """source/source_id が異なる詠み同士は、あっぱれカウントが独立していることを
    確認する(record と chain_record の id 空間が別々でも混同しない)。
    """
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    store.register_praise(source="record", source_id=1, user_id=100)
    count = store.register_praise(source="chain_record", source_id=1, user_id=100)
    assert count == 1


def _add(store, **kwargs):
    return store.add_record(
        guild_id=1, channel_id=2, user_id=3, message_id=4,
        parts=("a", "b", "c"), morphemes=[], app_version="1.0.0", **kwargs,
    )


def test_add_record_stores_evaluation_columns(tmp_path):
    """overall_match・score・reply_message_id が保存され、省略時は NULL になることを確認する。"""
    db_path = str(tmp_path / "records.db")
    store = RecordStore(db_path)
    full_id = _add(store, overall_match=0.5, score=0.75, reply_message_id=999)
    bare_id = _add(store)

    conn = sqlite3.connect(db_path)
    full = conn.execute(
        "SELECT overall_match, score, reply_message_id FROM records WHERE id = ?", (full_id,)
    ).fetchone()
    bare = conn.execute(
        "SELECT overall_match, score, reply_message_id FROM records WHERE id = ?", (bare_id,)
    ).fetchone()
    conn.close()
    assert full == (0.5, 0.75, 999)
    assert bare == (None, None, None)


def test_migrates_old_schema_keeping_existing_rows(tmp_path):
    """新規列・テーブルが無い旧スキーマの DB を開くと、既存行を保持したまま列が NULL で追加されることを確認する。"""
    db_path = str(tmp_path / "records.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, detected_at TEXT NOT NULL,
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL, part1 TEXT NOT NULL, part2 TEXT NOT NULL,
            part3 TEXT NOT NULL, part4 TEXT, part5 TEXT, morphemes_json TEXT NOT NULL,
            app_version TEXT)"""
    )
    conn.execute(
        """CREATE TABLE chain_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, detected_at TEXT NOT NULL,
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, kind TEXT NOT NULL,
            pattern TEXT NOT NULL, parts_json TEXT NOT NULL, app_version TEXT)"""
    )
    conn.execute(
        "INSERT INTO records (detected_at, guild_id, channel_id, user_id, message_id, "
        "part1, part2, part3, morphemes_json) VALUES ('t', 1, 2, 3, 4, 'a', 'b', 'c', '[]')"
    )
    conn.commit()
    conn.close()

    RecordStore(db_path)
    RecordStore(db_path)  # 2回目も冪等

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT part1, overall_match, score, reply_message_id FROM records"
    ).fetchone()
    chain_columns = {r[1] for r in conn.execute("PRAGMA table_info(chain_records)")}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert row == ("a", None, None, None)
    assert "reply_message_id" in chain_columns
    assert "disapprovals" in tables


def test_find_source_by_reply_message_id_searches_both_tables(tmp_path):
    """返信メッセージ ID から records・chain_records の両方を引けることを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    record_id = _add(store, reply_message_id=111)
    entry = ChainEntry(text="x", user_id=1, message_id=2, mora=5, timestamp=0.0)
    chain_id = store.add_chain_record(
        guild_id=1, channel_id=2, kind="独吟", pattern=(5, 7, 5),
        parts=[entry, entry, entry], app_version="1.0.0", reply_message_id=222,
    )
    assert store.find_source_by_reply_message_id(111) == ("record", record_id)
    assert store.find_source_by_reply_message_id(222) == ("chain_record", chain_id)
    assert store.find_source_by_reply_message_id(333) is None


def test_register_and_remove_disapproval(tmp_path):
    """否定評価は同一ユーザーの重複を作らず、取消は存在する場合のみ True になることを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    assert store.register_disapproval(source="record", source_id=1, user_id=10) is True
    assert store.register_disapproval(source="record", source_id=1, user_id=10) is False
    assert store.register_disapproval(source="record", source_id=1, user_id=11) is True
    assert store.remove_disapproval(source="record", source_id=1, user_id=10) is True
    assert store.remove_disapproval(source="record", source_id=1, user_id=10) is False


def _add_record(store, *, channel_id=2000, user_id=3000, message_id=4000, reply_message_id=None):
    return store.add_record(
        guild_id=1000, channel_id=channel_id, user_id=user_id, message_id=message_id,
        parts=("古池や", "蛙飛び込む", "水の音"), morphemes=[], app_version="1.0.0",
        reply_message_id=reply_message_id,
    )


def _add_chain_record(store, *, channel_id=2000, message_ids=(10, 11, 12), user_ids=(1, 2, 1),
                      reply_message_id=None):
    parts = [
        ChainEntry(text=f"part{i}", user_id=u, message_id=m, mora=mora, timestamp=float(i))
        for i, (u, m, mora) in enumerate(zip(user_ids, message_ids, (5, 7, 5)))
    ]
    return store.add_chain_record(
        guild_id=1000, channel_id=channel_id, kind="連歌", pattern=(5, 7, 5), parts=parts,
        app_version="1.0.0", reply_message_id=reply_message_id,
    )


@pytest.mark.parametrize("message_id", [4000, 4100])
def test_find_senryu_by_message_id_matches_record_original_and_bot_reply(tmp_path, message_id):
    """records の詠み元メッセージ ID・Bot の検出返信 ID のどちらでも詠みを引けることを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    record_id = _add_record(store, message_id=4000, reply_message_id=4100)

    found = store.find_senryu_by_message_id(message_id, 2000)

    assert found is not None
    assert found.source == "record"
    assert found.source_id == record_id
    assert found.channel_id == 2000
    assert found.reply_message_id == 4000
    assert found.author_user_ids == frozenset({3000})


@pytest.mark.parametrize("message_id", [10, 11, 12, 900])
def test_find_senryu_by_message_id_matches_chain_part_and_bot_reply(tmp_path, message_id):
    """chain_records の各パートの元メッセージ ID・Bot の検出返信 ID のどれでも詠みを引けることを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    chain_id = _add_chain_record(store, reply_message_id=900)

    found = store.find_senryu_by_message_id(message_id, 2000)

    assert found is not None
    assert found.source == "chain_record"
    assert found.source_id == chain_id
    assert found.channel_id == 2000
    assert found.reply_message_id == 12
    assert found.author_user_ids == frozenset({1, 2})


def test_find_senryu_by_message_id_prefers_records_over_chain_records(tmp_path):
    """records と chain_records の両方に一致する場合は records を返すことを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    record_id = _add_record(store, message_id=10)
    _add_chain_record(store, message_ids=(10, 11, 12))

    found = store.find_senryu_by_message_id(10, 2000)

    assert found is not None
    assert (found.source, found.source_id) == ("record", record_id)


def test_find_senryu_by_message_id_returns_newest_chain_record_among_matches(tmp_path):
    """同一メッセージが複数の chain_records に含まれる場合は id が最大のものを返すことを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    _add_chain_record(store, message_ids=(10, 11, 12))
    newest_id = _add_chain_record(store, message_ids=(12, 13, 14))

    found = store.find_senryu_by_message_id(12, 2000)

    assert found is not None
    assert (found.source, found.source_id) == ("chain_record", newest_id)


def test_find_senryu_by_message_id_returns_none_for_other_channel_or_unknown_id(tmp_path):
    """別チャンネルの ID や該当なしの ID では None を返すことを確認する。"""
    store = RecordStore(str(tmp_path / "records.db"))
    _add_record(store, message_id=4000, reply_message_id=4100)
    _add_chain_record(store, message_ids=(10, 11, 12), reply_message_id=900)

    assert store.find_senryu_by_message_id(4000, 2999) is None
    assert store.find_senryu_by_message_id(11, 2999) is None
    assert store.find_senryu_by_message_id(777, 2000) is None
