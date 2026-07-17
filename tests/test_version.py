import subprocess

from src import version


def test_get_version_prefers_application_version_env(monkeypatch):
    """環境変数 APPLICATION_VERSION が設定されていれば、その値をそのまま返すことを確認する。"""
    monkeypatch.setenv("APPLICATION_VERSION", "1.2.3")

    assert version.get_version() == "1.2.3"


def test_get_version_falls_back_to_git_describe(monkeypatch):
    """環境変数が未設定の場合、git describe の結果から v プレフィックスを除去して返すことを確認する。"""
    monkeypatch.delenv("APPLICATION_VERSION", raising=False)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="v0.5.0-2-gabc1234\n")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    assert version.get_version() == "0.5.0-2-gabc1234"


def test_get_version_falls_back_to_unknown_when_git_unavailable(monkeypatch):
    """環境変数も git describe も利用できない場合、"unknown" を返すことを確認する。"""
    monkeypatch.delenv("APPLICATION_VERSION", raising=False)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git command not found")

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    assert version.get_version() == "unknown"


def test_get_version_falls_back_to_unknown_when_git_describe_fails(monkeypatch):
    """git がインストールされているが対象ディレクトリが Git リポジトリでない場合も
    "unknown" を返すことを確認する。
    """
    monkeypatch.delenv("APPLICATION_VERSION", raising=False)

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=128, cmd=args)

    monkeypatch.setattr(version.subprocess, "run", fake_run)

    assert version.get_version() == "unknown"
