import threading

import pytest

from src.config_store import ConfigStore

THREADS = 8
CALLS_PER_THREAD = 3000


def _run_in_threads(targets):
    """各 target を別スレッドで同時に実行し、発生した例外を全て集めて返す。"""
    errors = []

    def wrap(target):
        def run():
            try:
                target()
            except Exception as e:
                errors.append(repr(e))

        return run

    threads = [threading.Thread(target=wrap(t)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "config.db"
    return ConfigStore(str(db_path))


def test_default_disabled(store):
    """設定を行っていないチャンネルはデフォルトで無効であることを確認する。"""
    assert store.is_enabled(channel_id=111) is False


def test_enable_and_check(store):
    """set_enabled で有効化したチャンネルが is_enabled で True になることを確認する。"""
    store.set_enabled(111, True)
    assert store.is_enabled(channel_id=111) is True


def test_disable_after_enable(store):
    """有効化後に無効化すると is_enabled が False に戻ることを確認する。"""
    store.set_enabled(111, True)
    store.set_enabled(111, False)
    assert store.is_enabled(channel_id=111) is False


def test_thread_inherits_parent_setting(store):
    """スレッド自体に設定がない場合、親チャンネルの有効設定を継承することを確認する。"""
    store.set_enabled(100, True)
    assert store.is_enabled(channel_id=200, parent_id=100) is True


def test_thread_own_setting_overrides_parent(store):
    """スレッド自身に設定がある場合、親チャンネルの設定より優先されることを確認する。"""
    store.set_enabled(100, True)
    store.set_enabled(200, False)
    assert store.is_enabled(channel_id=200, parent_id=100) is False


def test_thread_without_parent_setting_defaults_disabled(store):
    """親チャンネルにも設定がないスレッドはデフォルトで無効であることを確認する。"""
    assert store.is_enabled(channel_id=200, parent_id=999) is False


def test_persists_across_instances(tmp_path):
    """同じ DB ファイルを指す別インスタンスからも設定が引き継がれることを確認する。"""
    db_path = str(tmp_path / "config.db")
    store1 = ConfigStore(db_path)
    store1.set_enabled(111, True)
    store2 = ConfigStore(db_path)
    assert store2.is_enabled(channel_id=111) is True


def test_concurrent_is_enabled_raises_no_error(store):
    """複数スレッドから is_enabled を同時に呼んでも例外が発生しないことを確認する。"""
    store.set_enabled(1, True)

    def reader():
        for _ in range(CALLS_PER_THREAD):
            assert store.is_enabled(1, parent_id=2) is True

    assert _run_in_threads([reader] * THREADS) == []


def test_concurrent_read_and_write_raises_no_error(store):
    """is_enabled と set_enabled を複数スレッドから混在させても例外が発生せず、最後に書いた値が読めることを確認する。"""

    def reader():
        for _ in range(CALLS_PER_THREAD):
            store.is_enabled(1, parent_id=2)

    def writer():
        for i in range(CALLS_PER_THREAD):
            store.set_enabled(1, i % 2 == 0)

    errors = _run_in_threads([reader] * THREADS + [writer])
    assert errors == []

    store.set_enabled(1, True)
    assert store.is_enabled(1) is True
