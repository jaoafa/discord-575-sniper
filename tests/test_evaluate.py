import subprocess
import sys
from pathlib import Path

import pytest

from src import evaluate
from src.record_store import RecordStore
from src.senryu.chain import ChainEntry
from src.senryu.finder import MIN_SCORE, score_candidate
from src.senryu.tokenizer import Morpheme

REPO_ROOT = Path(__file__).resolve().parent.parent

PLAIN_PARTS = ("あいうえお", "かきくけこさし", "たちつてと")
TANKA_PARTS = ("あいうえお", "かきくけこさし", "たちつてと", "なにぬねのはひ", "ふへほまみむめ")


def _m(surface: str, mora: int, pos: str = "名詞") -> Morpheme:
    return Morpheme(surface=surface, reading="", mora=mora, start=0, end=0, pos=pos)


def _plain_morphemes() -> list[Morpheme]:
    return [_m("あいうえお", 5), _m("かきくけこさし", 7), _m("たちつてと", 5)]


def _tanka_morphemes() -> list[Morpheme]:
    return _plain_morphemes() + [_m("なにぬねのはひ", 7), _m("ふへほまみむめ", 7)]


def _broken_morphemes() -> list[Morpheme]:
    """第 1 パートの途中に読点が 2 つ入った 5-7-5(境界は名詞同士にならない)。"""
    comma = _m("、", 0, pos="補助記号")
    return [
        _m("あ", 1), comma, _m("い", 1), comma, _m("うえお", 3, pos="動詞"),
        _m("かきくけこさし", 7, pos="動詞"), _m("たちつてと", 5),
    ]


def _add_record(store, *, user_id=100, parts=PLAIN_PARTS, morphemes=None, overall_match=1.0):
    return store.add_record(
        guild_id=1, channel_id=2, user_id=user_id, message_id=3000 + user_id,
        parts=parts, morphemes=morphemes if morphemes is not None else _plain_morphemes(),
        app_version="test", overall_match=overall_match,
    )


def _add_chain(store, user_ids):
    parts = [
        ChainEntry(text=t, user_id=u, message_id=9000 + i, mora=m, timestamp=float(i))
        for i, (t, u, m) in enumerate(zip(("古池や", "蛙飛び込む", "水の音"), user_ids, (5, 7, 5)))
    ]
    return store.add_chain_record(
        guild_id=1, channel_id=2, kind="連歌", pattern=(5, 7, 5), parts=parts, app_version="test",
    )


def _report(db_path, *extra):
    return evaluate.main(["--db", str(db_path), *extra])


def test_excluded_fixture_really_falls_below_min_score():
    """除外ケースの fixture が、現行の score_candidate で MIN_SCORE 未満になることを確認する。"""
    morphemes = _broken_morphemes()
    span = sum(m.mora for m in morphemes)
    score, _ = score_candidate(morphemes, [(0, 5), (5, 6), (6, 7)], total_mora=round(span / 0.5))
    assert score < MIN_SCORE


def test_report_separates_self_and_other_disapprovals(tmp_path, capsys):
    """本人の 👎 と他者の 👎 が、records・chain_records それぞれ別に集計されることを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    both = _add_record(store, user_id=100)
    self_only = _add_record(store, user_id=101)
    _add_record(store, user_id=102)
    store.register_disapproval(source="record", source_id=both, user_id=100)
    store.register_disapproval(source="record", source_id=both, user_id=200)
    store.register_disapproval(source="record", source_id=self_only, user_id=101)
    chain = _add_chain(store, (1, 2, 1))
    store.register_disapproval(source="chain_record", source_id=chain, user_id=2)
    store.register_disapproval(source="chain_record", source_id=chain, user_id=3)

    assert _report(db) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "== 評価サマリ (単位: レコード) =="
    assert out[1:4] == [
        "records: 3 件 (overall_match あり 3 件)",
        "  あっぱれ付き: 0 件 / 他者👎付き: 1 件 / 本人のみ👎: 1 件",
        "  👎 票: 他者 1 / 本人 2",
    ]
    assert out[4:7] == [
        "chain_records: 1 件",
        "  あっぱれ付き: 0 件 / 他者👎付き: 1 件 / 本人のみ👎: 0 件",
        "  👎 票: 他者 1 / 本人 1",
    ]


def test_report_replay_breaks_down_outcomes_by_rating(tmp_path, capsys):
    """再現結果が 維持・別候補に変更・除外 に分かれ、あっぱれ・👎 の内訳が合うことを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    kept = _add_record(store, user_id=100)
    changed = _add_record(store, user_id=101, parts=PLAIN_PARTS, morphemes=_tanka_morphemes())
    excluded_praised = _add_record(
        store, user_id=102, morphemes=_broken_morphemes(), overall_match=0.5
    )
    excluded_disliked = _add_record(
        store, user_id=103, morphemes=_broken_morphemes(), overall_match=0.5
    )
    store.register_praise(source="record", source_id=kept, user_id=900)
    store.register_disapproval(source="record", source_id=changed, user_id=900)
    store.register_praise(source="record", source_id=excluded_praised, user_id=900)
    store.register_disapproval(source="record", source_id=excluded_disliked, user_id=103)

    assert _report(db) == 0

    out = capsys.readouterr().out.splitlines()
    table = out[out.index("== 再現結果 (現行ロジック、records のみ) ==") + 1:]
    assert table == [
        "区分\t件数\tあっぱれ\t他者👎\t本人のみ👎",
        "維持\t1\t1\t0\t0",
        "別候補に変更\t1\t0\t1\t0",
        "除外\t2\t1\t0\t1",
        "復元不可: 0 件",
    ]


def test_replay_without_overall_match_uses_the_section_only(tmp_path, capsys):
    """overall_match が NULL のレコードは、区間だけで coverage を計算して再現されることを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    _add_record(store, morphemes=_broken_morphemes(), overall_match=None)

    assert _report(db) == 0

    out = capsys.readouterr().out
    assert "records: 1 件 (overall_match あり 0 件)" in out
    assert "維持\t1\t0\t0\t0" in out


def test_unique_merges_same_text_and_ors_flags(tmp_path, capsys):
    """--unique で同一テキストが 1 件にまとまり、評価フラグが OR・票数が合算されることを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    first = _add_record(store, user_id=100)
    second = _add_record(store, user_id=100)
    _add_record(store, user_id=100, parts=("さしすせそ", "かきくけこさし", "たちつてと"))
    store.register_praise(source="record", source_id=first, user_id=900)
    store.register_disapproval(source="record", source_id=second, user_id=200)
    store.register_disapproval(source="record", source_id=second, user_id=100)
    chain_a = _add_chain(store, (1, 2, 3))
    chain_b = _add_chain(store, (1, 2, 3))
    store.register_disapproval(source="chain_record", source_id=chain_a, user_id=1)
    store.register_praise(source="chain_record", source_id=chain_b, user_id=900)

    assert _report(db, "--unique") == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "== 評価サマリ (単位: ユニークテキスト) =="
    assert out[1:4] == [
        "records: 2 件 (overall_match あり 2 件)",
        "  あっぱれ付き: 1 件 / 他者👎付き: 1 件 / 本人のみ👎: 0 件",
        "  👎 票: 他者 1 / 本人 1",
    ]
    assert out[4:7] == [
        "chain_records: 1 件",
        "  あっぱれ付き: 1 件 / 他者👎付き: 0 件 / 本人のみ👎: 1 件",
        "  👎 票: 他者 0 / 本人 1",
    ]


def test_unique_self_only_disapproval_yields_to_other_disapproval_on_the_same_text(
    tmp_path, capsys
):
    """--unique では、同一テキストの別レコードに他者の 👎 があれば本人のみ👎 には数えないことを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    self_only = _add_record(store, user_id=100)
    with_other = _add_record(store, user_id=100)
    store.register_disapproval(source="record", source_id=self_only, user_id=100)
    store.register_disapproval(source="record", source_id=with_other, user_id=200)

    assert _report(db, "--unique") == 0

    out = capsys.readouterr().out.splitlines()
    assert out[1:4] == [
        "records: 1 件 (overall_match あり 1 件)",
        "  あっぱれ付き: 0 件 / 他者👎付き: 1 件 / 本人のみ👎: 0 件",
        "  👎 票: 他者 1 / 本人 1",
    ]


def test_unique_replays_the_latest_record_of_each_text(tmp_path, capsys):
    """--unique の再現は、同一テキストのうち id が最大のレコードで行われることを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    _add_record(store, morphemes=_broken_morphemes(), overall_match=0.5)
    _add_record(store, morphemes=_plain_morphemes(), overall_match=1.0)

    assert _report(db, "--unique") == 0

    out = capsys.readouterr().out
    assert "維持\t1\t0\t0\t0" in out
    assert "除外\t0\t0\t0\t0" in out


def test_unrestorable_morphemes_are_counted_and_do_not_stop_the_report(tmp_path, capsys):
    """morphemes_json が壊れた行は「復元不可」に数えられ、集計は続行されることを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    broken_id = _add_record(store, user_id=100)
    _add_record(store, user_id=101)
    store._conn.execute(
        "UPDATE records SET morphemes_json = ? WHERE id = ?", ("not json", broken_id)
    )
    store._conn.commit()
    store.register_praise(source="record", source_id=broken_id, user_id=900)

    assert _report(db) == 0

    out = capsys.readouterr().out
    assert "  あっぱれ付き: 1 件 / 他者👎付き: 0 件 / 本人のみ👎: 0 件" in out
    assert "維持\t1\t0\t0\t0" in out
    assert out.splitlines()[-1] == "復元不可: 1 件"


def test_empty_db_reports_zero_and_exits_zero(tmp_path, capsys):
    """レコードが 0 件の DB でも 0 件として正常終了することを確認する。"""
    db = tmp_path / "records.db"
    RecordStore(str(db))

    assert _report(db) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[1] == "records: 0 件 (overall_match あり 0 件)"
    assert out[-1] == "復元不可: 0 件"


def test_evaluation_does_not_modify_the_db(tmp_path):
    """評価の実行前後で DB ファイルの内容が変わらないことを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    record_id = _add_record(store)
    store.register_disapproval(source="record", source_id=record_id, user_id=200)
    store._conn.close()
    before = db.read_bytes()

    assert _report(db) == 0
    assert _report(db, "--unique") == 0

    assert db.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["records.db"]


def test_missing_db_exits_one_without_creating_it(tmp_path, capsys):
    """存在しない DB パスは終了コード 1 で、ファイルを新規作成しないことを確認する。"""
    db = tmp_path / "nothing.db"

    assert _report(db) == 1

    assert f"エラー: DB ファイルが見つかりません: {db}" in capsys.readouterr().err
    assert not db.exists()


def test_non_sqlite_file_exits_one(tmp_path, capsys):
    """SQLite でないファイルは終了コード 1 で、エラーが標準エラーに出ることを確認する。"""
    db = tmp_path / "records.db"
    db.write_text("this is not a database" * 100)

    assert _report(db) == 1

    assert f"エラー: DB を読み取れませんでした ({db})" in capsys.readouterr().err


def test_old_schema_exits_one_and_names_missing_columns(tmp_path, capsys):
    """必要な列が無い旧スキーマの DB は終了コード 1 で、不足を示すことを確認する。"""
    import sqlite3

    db = tmp_path / "records.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, user_id INTEGER)")
    conn.commit()
    conn.close()

    assert _report(db) == 1

    err = capsys.readouterr().err
    assert err.startswith("エラー: DB のスキーマが古いため評価できません。不足: ")
    assert "records.overall_match" in err
    assert "disapprovals.user_id" in err


def test_module_runs_as_a_single_command(tmp_path):
    """python -m src.evaluate が 1 コマンドで動き、見出しを出力することを確認する。"""
    db = tmp_path / "records.db"
    store = RecordStore(str(db))
    _add_record(store)
    store._conn.close()

    result = subprocess.run(
        [sys.executable, "-m", "src.evaluate", "--db", str(db)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "== 評価サマリ (単位: レコード) =="
    assert "維持\t1\t0\t0\t0" in result.stdout


@pytest.mark.parametrize("flag", [[], ["--unique"]])
def test_default_db_path_is_data_records_db(flag, tmp_path, monkeypatch, capsys):
    """--db を省略すると data/records.db を読むことを確認する。"""
    monkeypatch.chdir(tmp_path)

    assert evaluate.main(flag) == 1

    assert "DB ファイルが見つかりません: data/records.db" in capsys.readouterr().err
