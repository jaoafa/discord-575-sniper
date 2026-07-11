import pytest

from src.__main__ import main


def test_main_raises_when_token_missing(monkeypatch):
    """DISCORD_TOKEN が未設定の場合 main() が KeyError を送出することを確認する。"""
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setenv("GUILD_ID", "123")
    monkeypatch.setattr("src.__main__.load_dotenv", lambda: None)
    with pytest.raises(KeyError):
        main()


def test_main_raises_when_guild_id_missing(monkeypatch):
    """GUILD_ID が未設定の場合 main() が KeyError を送出することを確認する。"""
    monkeypatch.setenv("DISCORD_TOKEN", "dummy-token")
    monkeypatch.delenv("GUILD_ID", raising=False)
    monkeypatch.setattr("src.__main__.load_dotenv", lambda: None)
    with pytest.raises(KeyError):
        main()
