"""稼働中の discord-575-sniper のバージョン情報を取得するモジュール。"""

import os
import subprocess
from pathlib import Path

_FALLBACK_VERSION = "unknown"


def _get_git_version() -> str | None:
    """git describe --tags --always --dirty からバージョン文字列を取得する。

    git コマンドが存在しない環境(本番 Docker イメージ等、.git を含めていない
    イメージ)や、対象ディレクトリが Git リポジトリでない場合は None を返す。
    """
    try:
        repo_dir = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    version = result.stdout.strip()
    if version.startswith("v"):
        version = version[1:]
    return version or None


def get_version() -> str:
    """稼働中の discord-575-sniper のバージョン文字列を取得する。

    優先順位:
    1. 環境変数 APPLICATION_VERSION(Docker イメージビルド時に CI から埋め込まれる)
    2. _get_git_version()(ローカル開発環境でのフォールバック)
    3. _FALLBACK_VERSION(どちらも取得できない場合)
    """
    env_version = os.environ.get("APPLICATION_VERSION")
    if env_version:
        return env_version
    git_version = _get_git_version()
    if git_version:
        return git_version
    return _FALLBACK_VERSION


# モジュール読み込み時に一度だけ解決する(呼び出しごとに subprocess を
# 起動しないため)。
__version__ = get_version()
