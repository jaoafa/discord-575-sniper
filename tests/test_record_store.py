import json
import sqlite3

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
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT guild_id, channel_id, user_id, message_id, part1, part2, part3, "
        "morphemes_json, detected_at FROM records"
    ).fetchone()
    conn.close()

    assert row is not None
    (
        guild_id, channel_id, user_id, message_id,
        part1, part2, part3, morphemes_json, detected_at,
    ) = row
    assert guild_id == 1000
    assert channel_id == 2000
    assert user_id == 3000
    assert message_id == 4000
    assert part1 == "古池や"
    assert part2 == "蛙飛び込む"
    assert part3 == "水の音"
    assert detected_at != ""

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
        parts=("a", "b", "c"), morphemes=[],
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
        parts=("古池や", "蛙飛び込む", "水の音"), morphemes=[],
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
        parts=("あ", "い", "う", "え", "お"), morphemes=[],
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
        )

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM chain_records").fetchone()[0]
    conn.close()
    assert count == 3
