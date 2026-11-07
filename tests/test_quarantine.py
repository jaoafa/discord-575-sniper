import json
import sqlite3

from src import quarantine
from src.record_store import RecordStore
from src.senryu.tokenizer import Morpheme


def _m(surface: str, mora: int, reading: str = "", pos: str = "名詞") -> Morpheme:
    return Morpheme(surface=surface, reading=reading, mora=mora, start=0, end=0, pos=pos)


def _plain(tag: str) -> tuple[tuple[str, ...], list[Morpheme]]:
    """tag で区別できる 5-7-5 の詠み (tag が同じなら同一テキスト)。"""
    first = f"あいうえ{tag}"
    parts = (first, "かきくけこさし", "たちつてと")
    return parts, [_m(first, 5), _m("かきくけこさし", 7), _m("たちつてと", 5)]


def _sokuon() -> tuple[tuple[str, ...], list[Morpheme]]:
    first = "っっっっっ"
    parts = (first, "かきくけこさし", "たちつてと")
    return parts, [_m(first, 5, reading="ッッッッッ"), _m("かきくけこさし", 7), _m("たちつてと", 5)]


def _inner_sokuon() -> tuple[tuple[str, ...], list[Morpheme]]:
    first = "きっぷあい"
    parts = (first, "かきくけこさし", "たちつてと")
    return parts, [
        _m("きっぷ", 3, reading="キップ"), _m("あい", 2), _m("かきくけこさし", 7), _m("たちつてと", 5),
    ]


def _no_candidate(tag: str) -> tuple[tuple[str, ...], list[Morpheme]]:
    """先頭が助詞で始まるため、現行ロジックでは候補が見つからない詠み。"""
    parts, morphemes = _plain(tag)
    return parts, [_m(morphemes[0].surface, 5, pos="助詞"), *morphemes[1:]]


def _tanka(tag: str) -> tuple[tuple[str, ...], list[Morpheme]]:
    parts, morphemes = _plain(tag)
    parts += ("なにぬねのはひ", "ふへほまみむめ")
    return parts, morphemes + [_m("なにぬねのはひ", 7), _m("ふへほまみむめ", 7)]


def _add(store: RecordStore, parts_and_morphemes, *, score=None) -> int:
    parts, morphemes = parts_and_morphemes
    return store.add_record(
        guild_id=1, channel_id=2, user_id=10, message_id=3000, parts=parts,
        morphemes=morphemes, app_version="test", overall_match=1.0, score=score,
    )


def _snapshot(db_path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )]
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in tables}
    finally:
        conn.close()


def _tables(db_path) -> set[str]:
    return set(_snapshot(db_path))


def _make_db(tmp_path):
    """id 1 通常 / 2 重複 / 3 促音のみ / 4 👎 付き / 5 低スコア / 6 通常。"""
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    _add(store, _plain("あ"))
    _add(store, _sokuon())
    _add(store, _plain("い"))
    _add(store, _plain("う"), score=0.3)
    _add(store, _plain("え"), score=0.9)
    store.register_disapproval(source="record", source_id=4, user_id=1)
    return path, store


def _run(path, *extra):
    return quarantine.main(["--db", str(path), *extra])


def _restore(path, *extra):
    return quarantine.main(["restore", "--db", str(path), *extra])


def _backups(path):
    return sorted(p for p in path.parent.iterdir() if ".bak-" in p.name)


def _ids(path, table):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute(f"SELECT id FROM {table} ORDER BY id")]
    finally:
        conn.close()


def test_dry_run_prints_counts_and_ids_without_changing_db(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    before = _snapshot(path)

    assert _run(path) == 0

    assert capsys.readouterr().out == (
        "== 退避対象 (dry-run) ==\n"
        "duplicate: 1 件\n  ID: 2\n"
        "only_sokuon: 1 件\n  ID: 3\n"
        "disapproved: 1 件\n  ID: 4\n"
        "low_score: 1 件\n  ID: 5\n"
        "rejudged: 0 件\n  ID: なし\n"
        "合計: 4 件 / records 全体: 6 件\n"
    )
    assert _snapshot(path) == before
    assert "quarantined_records" not in _tables(path)
    assert _backups(path) == []


def test_missing_db_is_error_and_not_created(tmp_path, capsys):
    path = tmp_path / "none.db"

    assert _run(path) == 1
    assert _run(path, "--apply") == 1
    assert _restore(path, "--all") == 1

    assert capsys.readouterr().err.count(f"エラー: DB ファイルが見つかりません: {path}") == 3
    assert not path.exists()


def test_apply_moves_rows_with_reason_and_keeps_others(tmp_path, capsys):
    path, _ = _make_db(tmp_path)

    assert _run(path, "--apply") == 0

    out = capsys.readouterr().out
    assert out.startswith("== 退避結果 ==\nduplicate: 1 件\n  ID: 2\n")
    assert "合計: 4 件 / records 全体: 6 件\n" in out
    assert _ids(path, "records") == [1, 6]
    conn = sqlite3.connect(str(path))
    rows = conn.execute(
        "SELECT id, quarantine_reason FROM quarantined_records ORDER BY id"
    ).fetchall()
    conn.close()
    assert rows == [(2, "duplicate"), (3, "only_sokuon"), (4, "disapproved"), (5, "low_score")]


def test_first_reason_in_priority_order_is_recorded(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    dup_all = _add(store, _plain("あ"), score=0.1)
    sokuon_dis = _add(store, _sokuon())
    dis_low = _add(store, _plain("い"), score=0.1)
    store.register_disapproval(source="record", source_id=dup_all, user_id=1)
    store.register_disapproval(source="record", source_id=sokuon_dis, user_id=1)
    store.register_disapproval(source="record", source_id=dis_low, user_id=1)

    assert _run(path, "--apply") == 0

    conn = sqlite3.connect(str(path))
    rows = dict(conn.execute("SELECT id, quarantine_reason FROM quarantined_records"))
    conn.close()
    assert rows == {dup_all: "duplicate", sokuon_dis: "only_sokuon", dis_low: "disapproved"}


def test_rejudged_quarantines_records_with_no_candidate_under_current_logic(tmp_path, capsys):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    rejected = _add(store, _no_candidate("い"))

    assert _run(path) == 0
    assert "rejudged: 1 件\n  ID: 2\n合計: 1 件 / records 全体: 2 件\n" in capsys.readouterr().out

    assert _run(path, "--apply") == 0
    assert _ids(path, "records") == [1]
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT id, quarantine_reason FROM quarantined_records").fetchall()
    conn.close()
    assert rows == [(rejected, "rejudged")]


def test_rejudged_comes_after_low_score_in_priority(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    low = _add(store, _no_candidate("い"), score=0.1)

    assert _run(path, "--apply") == 0

    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT id, quarantine_reason FROM quarantined_records").fetchall()
    conn.close()
    assert rows == [(low, "low_score")]


def test_praised_record_is_not_rejudged(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    rid = _add(store, _no_candidate("あ"))
    store.register_praise(source="record", source_id=rid, user_id=99)

    assert _run(path, "--apply") == 0

    assert _ids(path, "records") == [rid]


def test_rejudged_restore_returns_original_id_and_second_apply_is_noop(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    rejected = _add(store, _no_candidate("い"))
    before = _snapshot(path)
    assert _run(path, "--apply") == 0
    after_first = _snapshot(path)
    assert _run(path, "--apply") == 0
    assert _snapshot(path) == after_first

    assert _restore(path, "--id", str(rejected), "--apply") == 0

    assert _snapshot(path)["records"] == before["records"]


def test_praised_records_are_never_quarantined(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    dup = _add(store, _plain("あ"))
    sokuon = _add(store, _sokuon())
    disapproved = _add(store, _plain("い"))
    low = _add(store, _plain("う"), score=0.1)
    store.register_disapproval(source="record", source_id=disapproved, user_id=1)
    for rid in (dup, sokuon, disapproved, low):
        store.register_praise(source="record", source_id=rid, user_id=99)

    assert _run(path, "--apply") == 0

    assert _ids(path, "records") == [1, dup, sokuon, disapproved, low]
    assert "quarantined_records" not in _tables(path) or _ids(path, "quarantined_records") == []


def test_praise_on_chain_record_with_same_id_does_not_exempt(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    dup = _add(store, _plain("あ"))
    store.register_praise(source="chain_record", source_id=dup, user_id=99)

    assert _run(path, "--apply") == 0

    assert _ids(path, "quarantined_records") == [dup]


def test_score_boundary_and_null_are_kept(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"), score=0.5)
    _add(store, _plain("い"), score=None)
    low = _add(store, _plain("う"), score=0.4999)

    assert _run(path, "--apply") == 0

    assert _ids(path, "records") == [1, 2]
    assert _ids(path, "quarantined_records") == [low]


def test_sokuon_inside_word_and_tanka_are_kept(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _inner_sokuon())
    _add(store, _tanka("あ"))

    assert _run(path, "--apply") == 0

    assert _ids(path, "records") == [1, 2]


def test_apply_does_not_touch_rating_tables(tmp_path):
    path, store = _make_db(tmp_path)
    store.register_praise(source="record", source_id=1, user_id=5)
    before = _snapshot(path)

    assert _run(path, "--apply") == 0

    after = _snapshot(path)
    for table in ("praises", "praise_users", "disapprovals", "chain_records"):
        assert after[table] == before[table]


def test_apply_twice_changes_nothing_second_time(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    assert _run(path, "--apply") == 0
    capsys.readouterr()
    after_first = _snapshot(path)
    backups = _backups(path)

    assert _run(path, "--apply") == 0

    assert capsys.readouterr().out.endswith("合計: 0 件 / records 全体: 2 件\n")
    assert _snapshot(path) == after_first
    assert _backups(path) == backups


def test_apply_creates_backup_of_state_before_change(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    before = _snapshot(path)

    assert _run(path, "--apply") == 0

    backups = _backups(path)
    assert len(backups) == 1
    assert capsys.readouterr().out.rstrip("\n").endswith(str(backups[0]))
    assert _snapshot(backups[0]) == before


def test_apply_with_nothing_to_move_makes_no_backup(tmp_path):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))

    assert _run(path, "--apply") == 0

    assert _backups(path) == []
    assert "quarantined_records" not in _tables(path)


def test_invalid_morphemes_abort_with_id_and_leave_db_unchanged(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute("UPDATE records SET morphemes_json = ? WHERE id = 6", ("not json",))
    conn.commit()
    conn.close()
    before = _snapshot(path)

    assert _run(path, "--apply") == 1

    err = capsys.readouterr().err
    assert err.startswith("エラー: records.id=6 の morphemes_json を解釈できません")
    assert _snapshot(path) == before
    assert _backups(path) == []


def test_morpheme_mora_mismatch_aborts_with_id(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    bad = json.dumps([{"surface": "あ", "reading": "", "pos": "名詞", "mora": 1}])
    conn = sqlite3.connect(str(path))
    conn.execute("UPDATE records SET morphemes_json = ? WHERE id = 6", (bad,))
    conn.commit()
    conn.close()

    assert _run(path) == 1

    assert "records.id=6" in capsys.readouterr().err


def test_failure_midway_rolls_back_everything(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TRIGGER fail_delete BEFORE DELETE ON records "
        "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    conn.commit()
    conn.close()
    before = _snapshot(path)

    assert _run(path, "--apply") == 1

    assert "test failure" in capsys.readouterr().err
    assert _snapshot(path) == before


def test_restore_returns_rows_with_original_id_and_values(tmp_path):
    path, _ = _make_db(tmp_path)
    before = _snapshot(path)
    assert _run(path, "--apply") == 0

    assert _restore(path, "--all", "--apply") == 0

    after = _snapshot(path)
    assert after["records"] == before["records"]
    assert after["quarantined_records"] == []
    assert len(_backups(path)) == 2


def test_restore_by_id_restores_only_given_ids(tmp_path):
    path, _ = _make_db(tmp_path)
    assert _run(path, "--apply") == 0

    assert _restore(path, "--id", "2", "--id", "5", "--apply") == 0

    assert _ids(path, "records") == [1, 2, 5, 6]
    assert _ids(path, "quarantined_records") == [3, 4]


def test_restore_dry_run_changes_nothing(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    assert _run(path, "--apply") == 0
    capsys.readouterr()
    before = _snapshot(path)
    backups = _backups(path)

    assert _restore(path, "--all") == 0

    assert capsys.readouterr().out == (
        "== 復元対象 (dry-run) ==\n復元: 4 件\n  ID: 2, 3, 4, 5\n"
    )
    assert _snapshot(path) == before
    assert _backups(path) == backups


def test_restore_unknown_id_is_error_and_leaves_db_unchanged(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    assert _run(path, "--apply") == 0
    capsys.readouterr()
    before = _snapshot(path)

    assert _restore(path, "--id", "2", "--id", "99", "--apply") == 1

    assert capsys.readouterr().err == "エラー: quarantined_records に存在しない id: [99]\n"
    assert _snapshot(path) == before


def test_restore_conflicting_id_is_error(tmp_path, capsys):
    path, _ = _make_db(tmp_path)
    assert _run(path, "--apply") == 0
    capsys.readouterr()
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO records SELECT id, detected_at, guild_id, channel_id, user_id, message_id, "
        "part1, part2, part3, part4, part5, morphemes_json, app_version, overall_match, score, "
        "reply_message_id FROM quarantined_records WHERE id = 2"
    )
    conn.commit()
    conn.close()
    before = _snapshot(path)

    assert _restore(path, "--id", "2", "--apply") == 1

    assert capsys.readouterr().err == "エラー: records に同じ id が既にあります: [2]\n"
    assert _snapshot(path) == before


def test_restore_without_table_is_error(tmp_path, capsys):
    path, _ = _make_db(tmp_path)

    assert _restore(path, "--all") == 1

    assert capsys.readouterr().err == "エラー: quarantined_records テーブルがありません\n"


def test_restore_all_with_empty_table_is_noop(tmp_path, capsys):
    path = tmp_path / "records.db"
    store = RecordStore(str(path))
    _add(store, _plain("あ"))
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE quarantined_records AS SELECT * FROM records WHERE 0")
    conn.commit()
    conn.close()

    assert _restore(path, "--all", "--apply") == 0

    assert capsys.readouterr().out == "== 復元結果 ==\n復元: 0 件\n  ID: なし\n"
    assert _backups(path) == []
