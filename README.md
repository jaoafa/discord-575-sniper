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
- `/senryu remix` — このチャンネルで過去に検出された川柳・短歌の各句をランダムに選び直し、新しい短歌を合成して表示する(権限不要。素材となるレコードが足りない場合はエラーメッセージを返す)
- `/senryu delete [keyword]` — このチャンネルで自分が投稿した記録を一覧から選んで削除する(権限不要。他人の記録は一覧・削除の対象外。`keyword` を指定すると部分一致するものだけに絞り込める)

スレッドチャンネルは、そのスレッド自身に設定がなければ親チャンネルの設定を継承する。

## 検出ロジックについて

- 形態素解析(SudachiPy)によって単語境界を求め、その境界でのみ5-7-5または5-7-5-7-7に
  分割できる部分を検出する
- メッセージ全体だけでなく、長文メッセージ中の部分文字列が5-7-5または5-7-5-7-7になっていれば検出する
- 5-7-5(川柳)と5-7-5-7-7(短歌)は同一の候補プールから統合して探索し、`pick_best()` で
  最も良いもの1件のみを選出する(両方見つかった場合に2通リプライすることはない)
- 返信文言はパート数に応じて「川柳」「短歌」を切り替える(実装は `src/discord_client.py` の
  `_build_reply_text()`)
- 末尾が「あっぱれ」のメッセージは、返信(リプライ)でなければ直前に検出した詠みから1時間以内のものが、
  返信であれば返信先の詠み(Bot の検出返信、または詠み元メッセージ)が対象になる(返信の場合は時間制限なし。
  返信先が詠みでなければ何もしない)
- 各パート(5音・7音・5音)の先頭が助詞・助動詞・接尾辞などの付属語である候補は、
  文節の途中でぶった切っただけの不自然な区切りとして除外する
  (実装は `src/senryu/finder.py` の `can_start_part()`。単一メッセージ内検出・
  複数メッセージ結合検出の両方から共通で使われる)
- 「っ」だけで音数を満たす句(例: 「っっっっっ」)は発音として成立しないため候補にしない。
  「きっぷ」「コップ」のように語中に促音を含む語のモーラ数は変わらない
  (実装は `src/senryu/finder.py` の `has_substantive_mora()`。複数メッセージ結合検出にも適用)
- 各候補には質を表すスコア(`score_candidate()`)を付ける。改行・句読点、メッセージ全体との
  一致度、句末の位置はあくまでソフトな手掛かりで、候補を一律に禁止はしない:
  - メッセージ全体に占める割合(全体一致度)が高いほど加点
  - 候補の先頭・末尾が文頭・文末や改行・句読点・空白に揃っていれば加点(句末の自然さ)
  - 句(パート)の途中に句読点・改行が入っているごとに減点(パート末尾側に付くものは減点しない)
  - 助詞・助動詞で終わる候補も減点しない(詩的表現にも使われるため)
  - スコアが閾値(`MIN_SCORE`)未満の候補は採用しない。句内の区切りがちょうど1つだけの候補は、
    それだけでは閾値を下回らない。重み・閾値は `src/senryu/finder.py` の定数で、評価データを
    見て調整する
- 複数候補が見つかった場合は「最も上手にできた川柳」1件のみをリプライする。ただし
  「川柳としての面白さ」自体を決定論的に判定する方法はないため、以下を代用指標として使う
  (実装は `src/senryu/finder.py` の `pick_best()`。優先順位を変更する場合は両方を更新すること):
  1. スコアが高い順
  2. 同点なら一致した元テキストの文字列長が長い順
  3. それでも同点なら使用形態素数が少ない順
  4. それでも同点ならメッセージ中での出現位置が早い順
- 検出に成功した川柳・短歌は `data/records.db` に記録される(検出日時・ギルド・投稿者・
  チャンネル・元メッセージ ID・各パート・該当区間の形態素解析結果を保存)。短歌の場合のみ
  使用する `part4`/`part5` 列は、川柳(3パート)では NULL のまま保存される。
  記録と Discord への返信は互いの成否に依存しない。記録の一覧をそのまま閲覧するコマンドは
  現時点では未実装だが、記録済みの各句をランダムに組み合わせて新しい短歌を合成する
  `/senryu remix` コマンドは実装されている(このチャンネルの記録のみが対象。
  実装は `src/discord_client.py` の `handle_remix()` と `src/record_store.py` の
  `RecordStore.pick_random_part()`)。
- 上記の単一メッセージ内検出とは別に、直前最大5件の「読みが5モーラまたは7モーラになり、かつ先頭形態素が付属語でないメッセージ」をチャンネル(スレッドの場合はスレッド自身)ごとに保持し、その並びが5-7-5になった時点でも検出する(実装は `src/senryu/chain.py` の `ChainTracker`)。1件のメッセージが単一メッセージ内検出とこの複数メッセージ結合検出の両方をトリガーし、2件返信されることもある。なお5-7-5-7-7(短歌)の複数メッセージ結合検出は、先頭3件が必ず先に5-7-5として確定してしまうため対象外(単一メッセージ内での短歌検出には影響しない)
- 複数メッセージ結合検出では、一致した各パートの投稿者が全て同一なら「独吟」、1人でも異なれば「連歌」として紹介する
- 直前の保持メッセージから180秒を超えて間隔が空いた場合、または総モーラ数が5でも7でもないメッセージが投稿された場合は、保持していたメッセージ列(チェーン)をリセットする
- 複数メッセージ結合検出で保持しているチェーンはプロセスのメモリ上にのみ存在し、Bot 再起動時に失われる(`ConfigStore`/`RecordStore` と異なり永続化しない)
- 検出時に、候補の全体一致度(`overall_match`)・スコア(`score`)・Bot が送った返信メッセージの ID
  (`reply_message_id`)も `records` に保存する(メッセージ原文は保存しない。これらの列が追加される前の
  レコードは NULL)
- Bot の検出返信に 👎 リアクションを付けると誤検出の指摘(否定評価)として `disapprovals` テーブルに
  記録される(取り消すと削除される。Bot は応答しない)。肯定は従来の「あっぱれ」。
  **無反応は否定とはみなさない**(あっぱれ・👎 がどちらも無い記録が大半を占める)
- 複数メッセージ結合検出で検出した独吟・連歌は `data/records.db` の `chain_records` テーブルに、一致した各パートのテキスト・投稿者 ID・メッセージ ID・モーラ数を JSON として記録する(既存の `records` テーブルとは独立している)

## 検出品質の比較

スコア帯ごとの件数・あっぱれ率・否定率は、`data/records.db` に対して次の SQL で集計できる
(`sqlite3 data/records.db`)。`WHERE r.score < 0.5` のように条件を足せば、閾値をその値に
していた場合に除外されていた記録の評価も見られる。

```sql
SELECT ROUND(r.score, 1) AS score_bucket,
       COUNT(*) AS n,
       AVG(COALESCE(p.count, 0) > 0) AS praise_rate,
       AVG(COALESCE(d.cnt, 0) > 0) AS disapproval_rate
FROM records r
LEFT JOIN praises p ON p.source = 'record' AND p.source_id = r.id
LEFT JOIN (SELECT source_id, COUNT(*) AS cnt FROM disapprovals
           WHERE source = 'record' GROUP BY source_id) d ON d.source_id = r.id
WHERE r.score IS NOT NULL
GROUP BY score_bucket ORDER BY score_bucket;
```

注意:

- 否定率を比べるときは `AND r.reply_message_id IS NOT NULL` を足す(返信に失敗した記録は 👎 の対象外)
- `app_version` をまたぐ比較では、検出ロジックの変更による影響が混ざる
- 閾値未満で棄却された候補は保存されないため、比較できるのは現在の閾値より厳しい側のみ

## テスト

```bash
pytest
```

メッセージ検出→リプライのフローは、実際の Discord/fauxcord への接続は行わず、
`create_bot()` で組み立てた実際の `discord.Client` に対してスタブメッセージを
直接渡す形の統合テスト(`tests/test_bot_integration.py`)で自動検証している。
一方、スラッシュコマンドの応答については、実際の Discord サーバーに対して
手動で動作確認を行う(コマンドツリーへの登録自体は
`tests/test_bot_integration.py` の `test_senryu_delete_command_is_registered`
のように自動テストで検証する場合がある)。
