# discord-575-sniper

単語(形態素)の区切りを尊重して5-7-5の川柳を検出する Discord Bot。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# .env に DISCORD_TOKEN と GUILD_ID を設定
```

`requirements.txt` は実行に必要な依存のみ、`requirements-dev.txt` はそれに加えてテストに必要な依存(pytest 等)を含む。

Discord Developer Portal の Bot 設定ページで「MESSAGE CONTENT INTENT」(特権インテント)を有効にしておくこと。
これが無効だと `message.content` が空文字で届き、川柳検出が黙って発火しない。

## 起動

```bash
python -m src
```

### Docker での起動

```bash
cp .env.example .env
# .env に DISCORD_TOKEN と GUILD_ID を設定
docker compose up -d --build
```

`data/` ディレクトリ(チャンネル設定 `config.db` と検出履歴 `records.db` を保存する SQLite DB)はボリュームとして永続化される。

## チャンネル設定

対象サーバー内で以下のスラッシュコマンドを使う(実行に `manage_guild` 権限が必要):

- `/senryu enable` — 実行したチャンネルで川柳検出を有効化
- `/senryu disable` — 実行したチャンネルで川柳検出を無効化
- `/senryu status` — 現在のチャンネルの有効/無効を表示(権限不要)

スレッドチャンネルは、そのスレッド自身に設定がなければ親チャンネルの設定を継承する。

## 検出ロジックについて

- 形態素解析(SudachiPy)によって単語境界を求め、その境界でのみ5-7-5または5-7-5-7-7に
  分割できる部分を検出する
- メッセージ全体だけでなく、長文メッセージ中の部分文字列が5-7-5または5-7-5-7-7になっていれば検出する
- 5-7-5(川柳)と5-7-5-7-7(短歌)は同一の候補プールから統合して探索し、`pick_best()` で
  最も良いもの1件のみを選出する(両方見つかった場合に2通リプライすることはない)
- 返信文言はパート数に応じて「川柳」「短歌」を切り替える(実装は `src/discord_client.py` の
  `_build_reply_text()`)
- 各パート(5音・7音・5音)の先頭が助詞・助動詞・接尾辞などの付属語である候補は、
  文節の途中でぶった切っただけの不自然な区切りとして除外する
  (実装は `src/senryu/finder.py` の `_can_start_part()`)
- 複数候補が見つかった場合は「最も上手にできた川柳」1件のみをリプライする。ただし
  「川柳としての面白さ」自体を決定論的に判定する方法はないため、以下を代用指標として使う
  (実装は `src/senryu/finder.py` の `pick_best()`。優先順位を変更する場合は両方を更新すること):
  1. 一致した元テキストの文字列長が長い順
  2. 同点なら使用形態素数が少ない順
  3. それでも同点ならメッセージ中での出現位置が早い順
- 検出に成功した川柳・短歌は `data/records.db` に記録される(検出日時・ギルド・投稿者・
  チャンネル・元メッセージ ID・各パート・該当区間の形態素解析結果を保存)。短歌の場合のみ
  使用する `part4`/`part5` 列は、川柳(3パート)では NULL のまま保存される。
  記録と Discord への返信は互いの成否に依存しない。閲覧用のコマンドは現時点では未実装。

## テスト

```bash
pytest
```

メッセージ検出→リプライのフローは、実際の Discord/fauxcord への接続は行わず、
`create_bot()` で組み立てた実際の `discord.Client` に対してスタブメッセージを
直接渡す形の統合テスト(`tests/test_bot_integration.py`)で自動検証している。
一方、スラッシュコマンドの登録・応答については、実際の Discord サーバーに対して
手動で動作確認を行う。
