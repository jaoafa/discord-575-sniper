import pytest

from src.config_store import ConfigStore


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
