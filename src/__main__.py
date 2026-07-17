import os

from dotenv import load_dotenv

from .config_store import ConfigStore
from .discord_client import create_bot
from .record_store import RecordStore
from .senryu.chain import ChainTracker


def main() -> None:
    """環境変数を読み込み、Discord ボットを初期化して起動する。"""
    load_dotenv()
    token = os.environ["DISCORD_TOKEN"]
    guild_id = int(os.environ["GUILD_ID"])
    os.makedirs("data", exist_ok=True)
    config_store = ConfigStore("data/config.db")
    record_store = RecordStore("data/records.db")
    chain_tracker = ChainTracker()
    client = create_bot(guild_id, config_store, record_store, chain_tracker)
    client.run(token)


if __name__ == "__main__":
    main()
