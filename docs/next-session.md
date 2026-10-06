# 次回以降セッション作業指示: フェーズ5（デプロイ・インフラ）

> 本ファイルはセッション間の引き継ぎメモ。各回の完了時に「進め方」の表を更新する。フェーズ5完了時は、残す価値のある申し送りを計画書・ADR・runbookへ移してから削除する。
> 作成日: 2026-10-05（フェーズ4完了を受けて作成）

## 目的

[`docs/project-plan.md`](project-plan.md) §8 フェーズ5（デプロイ・インフラ）のうち、**リポジトリの中で完結する部分**を完了する。成果物は次の3つ。

1. ローカルの`docker build`・`docker run`で動作を確かめた本番用コンテナ一式
2. 定期ジョブ（日次バックアップ・ランキング再計算）と、その成功通知
3. 管理者が外部サービスを設定・運用するためのrunbookと、CIのworkflow

## このフェーズでやらないこと

Fly.io・Cloudflare・R2・UptimeRobot・GitHubの**アカウントに対する操作は行わない**。作業環境には`flyctl`も`cloudflared`も入っておらず、資格情報も渡さない。これらは管理者がrunbookを見て手で行う。実際の本番デプロイ・DNS切替・最終データ移行はフェーズ6である。

したがって、外部サービスに依存する項目は「設定ファイルと手順書を用意し、ローカルで確かめられる範囲を確かめた」ところまでを完了とする。実機で確かめていないことを、確かめたように書かない。

## 現状（2026-10-05確認）

- フェーズ0〜4は完了。作業ツリーはclean、`uv run pytest`は263件すべて成功
- `Dockerfile`・`fly.toml`・`.dockerignore`・`.github/`はまだ無い
- 定期ジョブはランキング再計算CLI `scripts/refresh_rankings.py` だけがある。バックアップのスクリプトとHeartbeat送信はまだ無い
- GitHubのリポジトリは`git@github.com:katamuki/meigen-fly.git`（remote `origin`）。pushとGitHub側の設定（secretsなど）は管理者が行う
- ローカルのDockerは使える（Docker 29.5）
- exact Host検証（`app/middleware.py`の`ExactHostMiddleware`、許可値は`PUBLIC_ORIGIN`から導出）、`/healthz`、SQLiteのPRAGMA（`app/db.py`）、キャッシュヘッダーは実装済み。確認するだけで作り直さない

## 設計の正本（この順で優先）

1. ADR: [001 全体構成](decisions/001-architecture-cloudflare-fly-sqlite.md)（§6〜§10・§14）、[003 バックアップ](decisions/003-sqlite-daily-backup.md)、[005 定期ジョブ](decisions/005-uvicorn-supercronic-jobs.md)、[013 オリジン保護](decisions/013-cloudflare-tunnel-origin-protection.md)、[018 OG画像](decisions/018-og-image-generation.md)「フォント」、[015 検索](decisions/015-search-rate-limits.md)（IPと検索語をログに残さない）、[004 migration](decisions/004-alembic-migrations.md)
2. [`docs/project-plan.md`](project-plan.md) §8 フェーズ5・フェーズ6のチェックリスト
3. `AGENTS.md`（小規模な個人サイトに見合う最小の実装を選ぶ）

ADRと本ファイルが食い違う場合はADRを優先し、食い違いを報告する。ADRの例示（`fly.toml`の断片など）が現行のFly.io・Cloudflareの仕様と合わない場合は、公式ドキュメントを確かめて現行仕様に合わせ、ADRへ追記する。

## フェーズ5の決定事項（2026-10-05）

次の5点は着手前に決めた。実装中に成り立たないと分かった場合は、黙って別案へ切り替えず、理由を報告する。

1. **プロセス監督**: `supervisord`でUvicorn・`cloudflared`・supercronicの3つを動かす（ADR 013）。コンテナのentrypointは、最初に`alembic upgrade head`を1回実行し、成功したら`supervisord`をexecする。migrationが失敗したらUvicornを起動せずに非ゼロで終了する。Flyの`release_command`は使わない（Volumeがマウントされないため。ADR 001 §9）
2. **アクセスログ**: Uvicornは`--no-access-log`で起動する。Uvicornは既定で`127.0.0.1`からの`X-Forwarded-For`を信頼するので、アクセスログを残すとTunnel経由で送信元IPとqueryが出る。書式を加工するより、出さないほうが単純で確実である。通信量はCloudflare Analyticsで見る
3. **OG画像のフォント**: `fonts-noto-cjk`に加えて`fonts-noto-cjk-extra`を入れ、`NotoSerifCJK-SemiBold.ttc`を使う。デザインの太さ600に合わせるためで、代償はイメージが数百MB大きくなることである。ビルドして`fonts-noto-cjk-extra`にSemiBoldが無いと分かった場合は、Boldを許容する側へ切り替え、ADR 018へ理由を追記する
4. **R2へのアップロード**: 依存を増やさず、標準ライブラリ（`hashlib`・`hmac`・`urllib.request`）でSigV4署名した単一のPUTを送る。フェーズ4でパージ要求を標準`urllib.request`で作ったのと同じ方針である。DBは数MBなのでmultipartは要らない。`boto3`は入れない
5. **デプロイの起動方法**: GitHub Actionsのデプロイは手動実行（`workflow_dispatch`）にする。単一Machineで、起動時にmigrationが走り、短い停止を伴うため、pushのたびに自動で本番を入れ替えない。テストはpushとpull requestで自動実行する

## 進め方（3分割・この順で実施）

| 回 | 内容 | 状態 |
|---|---|---|
| 5-A | コンテナ一式（Dockerfile・supervisord・entrypoint・fly.toml・フォント・アクセスログ） | 完了（2026-10-05） |
| 5-B | 定期ジョブ（日次バックアップ・Heartbeat・crontab） | 完了（2026-10-06） |
| 5-C | 運用runbook・CI workflow・計画書の更新 | 完了（2026-10-06。外部設定・実通信は管理者の残作業） |

各回の終わりに、`docs/project-plan.md`のフェーズ5チェックボックスへ反映し、上の表の「状態」を更新してコミットする（実装1コミット、レビュー修正があれば別コミット）。1回で3つとも終えてよいが、コミットは回ごとに分ける。

チェックボックスは、リポジトリ側の作業だけで完結する項目だけを`[x]`にする。管理者の外部設定が残る項目は`[ ]`のままにし、「リポジトリ側は完了、残りはrunbook §n」のように残作業を書き添える。

## 全回共通の規約

- 追加する依存・設定項目・ファイルは必要最小限にする。将来のための切り替えスイッチや抽象化を入れない
- 秘密情報（`TUNNEL_TOKEN`・R2の鍵・Heartbeat URL・`SECRET_KEY`・`CF_API_TOKEN`）をリポジトリ・イメージ・ログへ出さない。Heartbeat URLはそれ自体が秘密なので、ログへはジョブ名だけを書く
- 外から取得するバイナリ（`cloudflared`・supercronic）はバージョンを固定し、チェックサムを検証する。自動更新は使わない
- 環境変数の名前はADR 001 §10に合わせる。読み取りは`app/config.py`の既存の`get_*`関数の流儀に揃える
- 既存のテストを壊さない。追加するテストは既存と同じ流儀（一時DB、外部通信はしない）で書く
- `uv run ruff check`・`uv run ruff format --check`・`uv run pytest`を各回の最後に通す

### 5-A. コンテナ一式

**作るもの**

- `Dockerfile`: `python:3.14-slim`（free-threaded版は使わない）。依存は`uv.lock`どおりに入れ、開発用の依存は入れない。`cloudflared`・supercronic・supervisord・フォント・`fontconfig`を含める
- `.dockerignore`: `.venv`・`data/`・`.git`・`tests/`・キャッシュ類・`docs/`を除く
- entrypointとsupervisordの設定（決定事項1）。3つのプロセスの標準出力・標準エラーはコンテナの標準出力へ流し、`fly logs`で読めるようにする。子プロセスが異常終了したら再起動する
- Uvicornの起動は`--host 127.0.0.1 --port 8000 --workers 1 --no-access-log`
- `fly.toml`: アプリ名`meigensyu`、`primary_region = "nrt"`、`shared-cpu-1x`・512MB、Volume `data`を`/data`へマウント、restart policyは`always`。`[http_service]`と`[[services]]`は**定義しない**（ADR 013）。秘密でない環境変数（`DATABASE_URL=sqlite:////data/app.db`、`PUBLIC_ORIGIN=https://www.meigensyu.com`）は`[env]`に書く

**フォントの検査（ADR 018）**

- ビルド中に、`app/services/og_image.py`の`FONT_CANDIDATES`から実際に選ばれるファイルとフェイス名を検査する。期待と違えばビルドを失敗させる。`fc-match`で日本語明朝が解決できることも同じ箇所で確かめる
- 検査は`og_image.py`の既存の選択処理を呼んで行い、選択ロジックを別の場所へ複製しない
- ビルドしたイメージの中でOG画像を1枚生成し、文字が豆腐（□）になっていないことを目で確かめる。確認に使った画像はコミットしない

**アクセスログ（ADR 015）**

- アプリ自身のログ（操作ログ・レート制限・パージ・OG生成失敗など）に、送信元IPと検索語が出ていないことをコードを読んで確かめる。出ている箇所があれば直し、報告する
- `app/routers/public.py`の送信元IP取得は`cf-connecting-ip`を優先している。この挙動は変えない

**ローカルでの確かめ方**

Uvicornはコンテナ内の`127.0.0.1`だけで待ち受けるので、ポートを公開しても外からは届かない。`docker exec`でコンテナの中から確かめる。`TUNNEL_TOKEN`が無いローカルでは`cloudflared`は起動に失敗し続けるが、それでUvicornとsupercronicが止まらないことを確かめる。

- 空のVolume相当（空のディレクトリを`/data`へマウント）で起動し、migrationが走ってから`/healthz`が200を返す
- `Host`が`PUBLIC_ORIGIN`と違う要求は拒否される
- 再起動してもmigrationが二重適用で失敗しない
- 一般ページと検索を数回たたき、コンテナのログに送信元IPとqueryが出ていない
- `PRAGMA journal_mode`が`wal`である
- Uvicornのプロセスを中で殺すと、supervisordが再起動する

### 5-B. 定期ジョブ

**この回の成果物**

本番コンテナの中で、日次バックアップとランキング再計算がsupercronicから決まった時刻に1回ずつ動き、成功したときだけUptimeRobotへHeartbeatを送る状態にする。R2とUptimeRobotのアカウント側の設定は5-Cのrunbookに回し、この回では行わない。

**着手時の状態（5-A完了時点）**

- `docker/crontab`はコメント1行だけで、ジョブは未登録。supercronicは`docker/supervisord.conf`の`[program:supercronic]`から`/etc/supercronic/crontab`を読んで起動済み
- イメージの`PATH`には`/app/.venv/bin`が入っており、作業ディレクトリは`/app`。`flock`（util-linux）と`timeout`（coreutils）は`python:3.14-slim`に最初から入っているので、パッケージを足さない
- `scripts/refresh_rankings.py`は再計算のあとcache purgeを行う。Heartbeatはまだ無い。テストは`tests/test_refresh_rankings_cli.py`
- `app/services/cache_purge.py`が、標準`urllib.request`で外部へ要求を送る既存の例である。timeout・例外の拾い方・ログの出し方と、`tests/test_cache_purge.py`の`urlopen`差し替えによるテストの書き方を、この回のコードでも踏襲する
- 環境変数は`app/config.py`の`get_*`関数で読む。`.dockerignore`は`tests/`と`docs/`を除くが、`scripts/`はイメージに入る

**作るもの・変えるもの**

| ファイル | 内容 |
|---|---|
| `app/config.py` | R2の5変数とHeartbeat URL 2変数の`get_*`関数を足す |
| `app/services/heartbeat.py`（新設） | Heartbeatを送る小さな関数1つ |
| `scripts/backup_sqlite.py`（新設） | 日次バックアップのCLI。SigV4署名とPUTもこのファイルに置く |
| `scripts/refresh_rankings.py` | Heartbeatの呼び出しを足す |
| `docker/crontab` | ジョブ2行 |
| `tests/` | `test_backup_sqlite.py`・`test_heartbeat.py`を新設、`test_refresh_rankings_cli.py`へ追記 |
| `docs/project-plan.md`・本ファイル | チェックボックスと「進め方」の表の更新 |

ファイルの分け方は目安である。より小さく収まるなら変えてよいが、Heartbeatの関数を2つのCLIで共有することと、署名の関数をテストから単体で呼べることは守る。`Dockerfile`と`supervisord.conf`は、下の確認で必要と分かった場合だけ変える。

**環境変数（ADR 001 §10）**

| 変数 | 既定 | 備考 |
|---|---|---|
| `BACKUP_R2_ENDPOINT` | なし | `https://<account_id>.r2.cloudflarestorage.com`。末尾のslashは有無どちらでも受ける |
| `BACKUP_R2_BUCKET` | なし | |
| `BACKUP_R2_PREFIX` | `daily/` | 未設定のときだけ既定値を使う |
| `BACKUP_R2_ACCESS_KEY_ID` | なし | |
| `BACKUP_R2_SECRET_ACCESS_KEY` | なし | 秘密 |
| `UPTIMEROBOT_BACKUP_HEARTBEAT_URL` | なし | 秘密。未設定なら送らない |
| `UPTIMEROBOT_RANKING_HEARTBEAT_URL` | なし | 秘密。未設定なら送らない |

**日次バックアップ（ADR 003）**

`scripts/backup_sqlite.py`を新設する。`scripts/refresh_rankings.py`と同じ形（`main() -> int`、`logging`を標準エラーへ、`raise SystemExit(main())`）にする。処理は次の順で、どこかで失敗したら原因をログへ出して非ゼロで終了し、Heartbeatを送らない。

1. R2の設定を読む。`BACKUP_R2_PREFIX`以外の4変数のうち1つでも欠けていれば、欠けている変数名をすべて示して非ゼロで終了する。黙って何もせずに終わらせない。本番で設定漏れに気づけるようにするためで、コピーを作る前に判定する
2. `DATABASE_URL`からDBファイルのパスを得て、`sqlite3.Connection.backup()`で一時ファイルへ一貫したコピーを作る。稼働中のDBファイルを単純にコピーしない。元のDBは読み取り専用で開き、ファイルが無いときは空のDBを新しく作らずに失敗させる（`sqlite3.connect()`は既定では無いファイルを作ってしまう）
3. 一時ファイルへ`PRAGMA integrity_check`を実行し、結果が`ok`の1行以外なら失敗にする
4. R2へ単一のPUTを送る（決定事項4）。200番台以外の応答・timeout・通信エラーは失敗にする
5. 成功を1行でログに出す。内容はオブジェクトのキー・バイト数・所要秒数（最新の成功時刻をログで確かめられるようにするため）
6. `UPTIMEROBOT_BACKUP_HEARTBEAT_URL`へpingする
7. 一時ファイルを消す。途中で失敗した場合も消す（`tempfile.TemporaryDirectory`を使えば足りる）

- キーは`{BACKUP_R2_PREFIX}app-{UTC日時}.db`の形にする（例: `daily/app-20261005T180000Z.db`）。秒まで含めれば日次とオンデマンドの実行が衝突しないので、存在確認や条件付きPUTは足さない
- 圧縮・暗号化・世代管理はしない。DBは数MBで、復旧時にそのまま開けるほうが価値がある。30日後の削除はR2のLifecycleで行い、スクリプトで古いオブジェクトを消さない
- 再試行は作らない。失敗すればHeartbeatが届かず、UptimeRobotが通知する
- 失敗時のログに、秘密鍵・`Authorization`ヘッダー・署名の値を出さない

**R2へのPUT（SigV4）**

- URLはpath-styleの`{endpoint}/{bucket}/{key}`。regionは`auto`、serviceは`s3`
- 送るヘッダーは`Host`・`x-amz-date`・`x-amz-content-sha256`（本文のSHA-256の16進）・`Authorization`・`Content-Length`。`Host`・`x-amz-content-sha256`・`x-amz-date`の3つを署名対象にする。数MBなので本文はメモリへ読んでよい
- 署名の計算は、日時・region・ヘッダーを引数で受け取る純粋な関数にして、時刻や環境変数を中で読まない。既知の入力で検算できるようにするためである
- 検算には、AWSの公式ドキュメント「Signature Calculations for the Authorization Header」のPUT Objectの例を使える。次の入力で署名が`98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd`になる（この指示の作成時に標準ライブラリで計算して一致を確かめた）
  - access key `AKIAIOSFODNN7EXAMPLE`、secret key `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`、region `us-east-1`、service `s3`、日時 `20130524T000000Z`
  - `PUT /test%24file.text`、query無し、本文 `Welcome to Amazon S3.`（SHA-256は`44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072`）
  - 署名対象ヘッダー: `date: Fri, 24 May 2013 00:00:00 GMT`、`host: examplebucket.s3.amazonaws.com`、`x-amz-content-sha256`（上の値）、`x-amz-date: 20130524T000000Z`、`x-amz-storage-class: REDUCED_REDUNDANCY`
- キーに使う文字は英数字・`/`・`-`・`.`だけなので、パスのURIエンコードはこの範囲で正しければよい。任意のキーに対応する汎用のS3クライアントにしない

**Heartbeat（ADR 005）**

`app/services/heartbeat.py`に、ジョブ名とURL（または`None`）を受け取る関数を1つ置き、2つのCLIから同じものを呼ぶ。

- URLが`None`なら送らずに戻る（ローカル用）。そのことをinfoで1行出す
- GETを1回、timeoutは10秒。再試行は作らない。pingが届かなければUptimeRobotが通知する
- 送信に失敗しても例外を外へ出さず、警告をログに出す。呼び出し側のジョブは成功として扱う
- **URLはそれ自体が秘密である。** 成功・失敗どちらのログにも、URLとその一部を出さない。出すのはジョブ名と、失敗時のHTTPステータスまたは例外のクラス名までにする。例外の文字列をそのままログへ渡すとURLやホスト名が混ざることがあるので渡さない

**ランキング再計算へのHeartbeat追加**

`scripts/refresh_rankings.py`で、`UPTIMEROBOT_RANKING_HEARTBEAT_URL`へのpingを足す。位置は**再計算の成功ログの後、`purge_cache()`の前**である。purgeの失敗はTTLで回復するので、Heartbeatの条件に含めない。再計算が失敗した経路では送らない。既存の終了コードとログは変えない。

**crontab（supercronic）**

`docker/crontab`のコメントを消し、次の2ジョブを書く。時刻はUTCである（コンテナの時刻帯はUTC）。

| ジョブ | 式 | 最大実行時間 | lockファイル |
|---|---|---|---|
| バックアップ | `0 18 * * *`（毎日03:00 JST） | 600秒 | `/tmp/backup_sqlite.lock` |
| ランキング | `0 3,15 * * *`（旧環境のpg_cronと同じ） | 300秒 | `/tmp/refresh_rankings.lock` |

- 各行は`flock -n <lock> timeout <秒> python /app/scripts/<名前>.py`の形にする。ラッパーのシェルスクリプトは作らない
- lockファイルは`/data`（Volume）に置かない
- `flock -n`でスキップされた実行は非ゼロで終わり、supercronicのログには失敗として出る。それでよい（Heartbeatは先に動いているほうが送る）
- 式の意味が分かるよう、各行の上にJSTでの時刻を1行のコメントで書く

**テスト**

既存の流儀（一時DB、`monkeypatch`で`urlopen`を差し替え、外部通信なし）で書く。環境変数は`monkeypatch.setenv`・`delenv`で明示し、開発者の手元の環境変数に左右されないようにする。

- バックアップ: 作ったファイルが開けて、元のDBと同じ件数になること
- バックアップ: 正常系で、PUTの宛先URL・メソッド・本文が期待どおりで、PUTの後にHeartbeatが1回送られ、終了コードが0になること
- バックアップ: `integrity_check`の失敗とPUTの失敗（HTTPエラー・timeout）のそれぞれで、Heartbeatを送らず非ゼロになること
- バックアップ: R2の変数が欠けていると、欠けている変数名をログに出して非ゼロになり、PUTもHeartbeatも送らないこと
- バックアップ: 成功時も失敗時も一時ファイルが残らないこと
- 署名: 上の公式の例で期待どおりの値になること
- Heartbeat: URL未設定で送らないこと、送信失敗で例外を出さないこと、ログにURLが含まれないこと（`caplog`で確かめる）
- ランキング: 成功時にHeartbeatがpurgeより前に呼ばれること、再計算の失敗時に呼ばれないこと、Heartbeatの失敗でも終了コードが0のままであること

R2とUptimeRobotへの実通信はテストしない。

**ローカルでの確かめ方**

`docker build`し、空のディレクトリを`/data`へマウントして起動する（5-Aと同じ。`TUNNEL_TOKEN`が無いので`cloudflared`は失敗し続けるが、無視してよい）。以下は`docker exec`でコンテナの中から行う。

1. `supercronic -test /etc/supercronic/crontab`が通る
2. R2の変数なしで`python /app/scripts/backup_sqlite.py`を実行すると、欠けている変数名を示して非ゼロで終わる
3. `python /app/scripts/refresh_rankings.py`が0で終わり、Heartbeatを送らなかった旨がログに出る
4. 成功の経路を通す。コンテナの中にPUTとGETを受けて200を返すだけの使い捨てHTTPサーバーを立て（`python -c`の数行で足りる。コミットしない）、`BACKUP_R2_ENDPOINT`と`UPTIMEROBOT_BACKUP_HEARTBEAT_URL`をそこへ向けてバックアップを実行する。PUTがHeartbeatより先に届くこと、受け取った本文がSQLiteとして開けて`integrity_check`が`ok`になること、成功ログにキー・サイズ・所要時間が出てURLが出ないこと、`/tmp`に一時ファイルが残らないことを確かめる。この確認は処理の流れを見るもので、署名が正しいことは確かめられない（署名はテストの検算で担保し、R2への実際のPUTは5-Cのrunbookで管理者が確かめる）
5. 同じサーバーを500を返すようにして実行し、非ゼロで終わってHeartbeatが届かないことを確かめる
6. 同じlockファイルを使って同じジョブを2つ同時に起動し、後のほうが`flock`ですぐ非ゼロで終わる（先のほうは`flock <lock> sleep 30`などで代用してよい）
7. `docker run`に`-e`で渡した環境変数が、supervisord・supercronicを経てジョブまで届く。crontabを一時的に毎分の行へ差し替えたイメージで、変数名を示す失敗が「欠けていない」側へ変わることを見るなど、方法は任せる。確認用の変更はコミットしない
8. supercronicが定刻にジョブを起動することは、7の毎分の行で1回見れば足りる。本番の時刻まで待たない

**完了時に行うこと**

- `uv run ruff check`・`uv run ruff format --check`・`uv run pytest`を通す
- `docs/project-plan.md`のフェーズ5を更新する。「日次SQLiteオンラインバックアップ…」と「ランキング再計算CLI…のsupercronic登録」の2項目は、R2 Lifecycle・UptimeRobotの監視設定・通知先という管理者の作業が残るので、`[ ]`のまま「リポジトリ側は完了（2026-10-05、5-B）、残りは5-Cのrunbook」と書き添える。リポジトリ側だけで完結した部分を別の行へ分けて`[x]`にしてもよい。冒頭の更新日も直す
- 本ファイルの「進め方」の表で5-Bを完了にする
- 決定事項4（標準ライブラリによるPUT）のADRへの追記は5-Cで行う。この回ではADRを変えない。ただしADRと実装が食い違った場合は報告する
- 実装を1コミットにする（例: `feat: add scheduled backup and heartbeat jobs`）。pushはしない

**この回でやらないこと**

- R2・UptimeRobot・Fly.ioのアカウントに対する操作、runbook、CI workflow（5-C）
- 復旧用のスクリプト（復旧は5-Cでrunbookの手順として書く）
- カテゴリ件数再計算など、上の2つ以外のジョブの追加
- `boto3`などの依存の追加、ジョブの状態を返すAPIや管理画面の表示
- `app/`の公開ページ・管理画面の変更

**完了時の報告（5-B分）**

「完了時の報告」の項目に沿って、次を分けて書く。

- 作ったもの・変えたもの（ファイル単位）
- 「ローカルでの確かめ方」1〜8のそれぞれについて、実行したコマンドと結果。実行できなかったものは、できなかったと書く
- 確かめられなかったこと（R2への実際のPUT、UptimeRobotの受信と通知）
- この指示・決定事項・ADRから外れた点と、その理由

### 5-C. 運用runbook・CI・計画書

**この回の成果物**

管理者が外部サービスを上から順に設定できるrunbook 1ファイル、GitHub Actionsのworkflow 2本、そして計画書・README・ADRの更新。これでフェーズ5のリポジトリ側の作業が終わる。

**着手時の状態（5-B完了時点）**

- コンテナ一式（`Dockerfile`・`docker/`・`fly.toml`）と定期ジョブ（`docker/crontab`・`scripts/backup_sqlite.py`・`scripts/refresh_rankings.py`・`app/services/heartbeat.py`）は完成している。`fly.toml`の`[env]`には`DATABASE_URL`と`PUBLIC_ORIGIN`だけがある
- `docker/supervisord.conf`には`[unix_http_server]`・`[supervisorctl]`・`[rpcinterface:supervisor]`が無く、コンテナの中で`supervisorctl`が使えない。DBの入れ替え（下の§6・§7）でUvicornとsupercronicを止める必要があるので、この回で足す
- イメージには`curl`と`sqlite3`モジュール付きのPythonが入っている。`sqlite3`コマンドは入っていないので、コンテナ内の確認はPythonで行う
- `.github/`はまだ無い。`.dockerignore`は`.github/`を除いている
- `tests/test_migrations.py`に`test_single_head`と空DBへの`upgrade head`のテストがあるので、CIにAlembic専用のステップは足さない
- `tests/test_seo.py`はOG画像を実際にPNGへ描画する。`app/services/og_image.py`の`FONT_CANDIDATES`にはSemiBold・Bold・Regularがあるので、GitHubのUbuntu runnerでは`fonts-noto-cjk`を入れれば通る（`fonts-noto-cjk-extra`は要らない）
- 本番相当のDBはフェーズ2で`data/app.db`に再構築済み（約3MB。authors 774・quotes 1,831）。復旧の演習に使える
- ローカルのDB構築手順は`docs/database/migration-runbook.md` §5にある。フェーズ6の最終移行はこの手順を再実行してから、できたファイルをVolumeへ置く

**作るもの・変えるもの**

| ファイル | 内容 |
|---|---|
| `docs/operations-runbook.md`（新設） | 管理者向けの外部設定・デプロイ・復旧の手順書 |
| `.github/workflows/test.yml`（新設） | push・pull requestで lint・format・pytest |
| `.github/workflows/deploy.yml`（新設） | `workflow_dispatch`で`flyctl deploy`とsmoke test |
| `docker/supervisord.conf` | `supervisorctl`を使えるようにする3セクション |
| `docs/project-plan.md` | フェーズ5のチェックボックス、更新日、§12 |
| `README.md` | コンテナのビルドとローカルでの確かめ方 |
| ADR 001・003・015・018 | 決定事項のうちADRに無い内容の追記 |
| 本ファイル | 「進め方」の表の更新 |

**runbookを書く前の前提: zoneは旧サイトと共用している**

`www.meigensyu.com`と`meigensyu.com`は、DNS切替（フェーズ6）まで旧サイト（Next.js）を指している。Cloudflareの設定の多くはzone単位なので、**設定した瞬間に旧サイトへ効く**。runbookは、各設定を次の2つに分けて書く。

- **切替前に行ってよいもの**: Tunnelの作成（public hostnameはまだ付けない）、R2、UptimeRobotのHeartbeat監視2つ、Fly app・Volume・secrets・初回デプロイ、Tunnelの接続確認（`fly logs`に接続登録が出る、Zero TrustダッシュボードでHEALTHY）
- **切替時（フェーズ6）に行うもの**: Tunnelへの`www`のpublic hostname追加（既存の`www`レコードと衝突するので、旧レコードの削除・置換を含む）、apexの`192.0.2.0`とRedirect Rule、Cache Rules、WAFのRate limiting、Accessのapplication（旧サイトの`/admin`にも効く）、`/healthz`の外形監視

Cache RulesとRedirect Ruleは切替前に**無効の状態で**作っておき、切替時に有効にするのでもよい。どちらにするかはrunbookの中で1つに決め、両論併記しない。この分け方で迷った設定は「切替時」に倒す。

**runbook（`docs/operations-runbook.md`）**

1ファイルで、管理者がこの順に実行すれば終わるように書く。コマンドと設定値は具体的に書き、確かめていない手順には「未検証」と明記する（この回ではFly・Cloudflare・R2・UptimeRobot・GitHubを操作しないので、外部サービスの手順はすべて未検証になる。見出しの近くに一度書けば、項目ごとに繰り返さなくてよい）。公式ドキュメントで確かめられる範囲は確かめ、ADRの記述が現行仕様と合わなければ現行に合わせてADRへ追記する。

章立てと、各章に必ず入れる内容:

1. **初回セットアップ（Fly.io）**
   - `fly launch`は使わない（`fly.toml`を書き換えるため）。`fly apps create meigensyu`・`fly volumes create data --region nrt --size 1`・`fly deploy`の順
   - アプリ名`meigensyu`が取れない場合は別名にし、`fly.toml`の`app`を変える。それ以外の`fly.toml`は変えない
   - secretsの一覧表: ADR 001 §10の変数のうち`[env]`にある2つを除いたすべてを`fly secrets set`で入れる。表の列は「変数名」「値の出どころ（どの章で得るか）」「秘密かどうか」。`ADMIN_DEV_EMAIL`は本番で設定しないと明記する
   - 初回デプロイは`TUNNEL_TOKEN`を含む全secretsを入れてから行う。したがって章の順は、Fly app作成 → Cloudflare Tunnel作成（2章の一部）→ R2（3章）→ UptimeRobot（4章）→ secrets設定 → 初回デプロイ、になる。章を読む順と実行順が食い違わないよう、章の並びをこの順にする
   - デプロイ後に`fly ips list`でpublic IPv4/IPv6が無いことを確かめ、あれば`fly ips release`する（ADR 013）。`fly machine status`でserviceが無いことも見る
2. **Cloudflare**
   - Tunnel: Zero Trustでremotely-managed Tunnelを作り、tokenを`TUNNEL_TOKEN`に入れる。public hostnameは`www.meigensyu.com` → `http://127.0.0.1:8000`の1つだけ。wildcardは使わず、catch-allは404のまま
   - DNS: apex `meigensyu.com`はproxiedのA `192.0.2.0`。Redirect Ruleでpath・queryを維持して`https://www.meigensyu.com`へ301
   - Cache Rules: ADR 001 §8の3ルールを、Cloudflareの式の文字列として書く。対象パスは`app/middleware.py`の`NO_STORE_PATHS`と`docs/url-contract.md`から引き、`*/og.png`・`/sitemap.xml`・`/robots.txt`をキャッシュ対象に含める。順序は「公開HTML → `/static/*` → Bypass」で、Bypassを最後に置く理由（last matching rule wins）を1行書く
   - WAF: Bot Fight Mode ON。Rate limiting 1ルール: `/api/likes/*`のPOST、IP単位10回/10秒、block 10秒（ADR 006・015）
   - Access: Self-hosted application、対象`www.meigensyu.com`の`/admin`配下（`/login`は含めない。`/login`はアプリが`/admin`へ302する）。policyは管理者メールの完全一致、IdPはGoogle。作成後に得られる`aud`を`CF_ACCESS_AUD`に、team domainを`CF_ACCESS_TEAM_DOMAIN`に入れる（ADR 012）
   - API token: Cache Purge権限だけのtokenを`CF_API_TOKEN`に、Zone IDを`CF_ZONE_ID`に入れる（ADR 014）
3. **R2**
   - バケット作成、`daily/`プレフィックスへの30日Lifecycle、そのバケットだけに限定したObject Read & Writeのトークン。endpointは`https://<account_id>.r2.cloudflarestorage.com`、`BACKUP_R2_PREFIX`は末尾slash付きの`daily/`（5-Bの実装は末尾slashを補わない）
   - 初回デプロイ後に`fly ssh console`から`python /app/scripts/backup_sqlite.py`を手で実行し、成功ログとR2のオブジェクトを確かめる手順。これがR2への実通信の最初の確認になる
4. **UptimeRobot**
   - Heartbeat監視2つ: バックアップは間隔24時間（03:00 JST）、ランキングは12時間（12:00・00:00 JST）。猶予時間の値を1つ決めて書く。URLを`UPTIMEROBOT_BACKUP_HEARTBEAT_URL`・`UPTIMEROBOT_RANKING_HEARTBEAT_URL`に入れる
   - `/healthz`の外形監視: **GET**（HEADは405）、間隔5分。切替時に作る
   - 通知先: 公式アプリのPushを主、メールを予備
5. **デプロイとsmoke test**
   - 手動デプロイの手順（手元の`flyctl deploy`と、切替後はGitHub Actionsの`deploy.yml`）
   - `fly ssh console`からの内部確認: `curl -H 'Host: www.meigensyu.com' http://127.0.0.1:8000/healthz`が200、`Host`なしが400、`fly logs`で3プロセスが動いている
   - 切替後は`https://www.meigensyu.com/healthz`と`cf-cache-status`の確認
   - rollbackの判断（ADR 013「ヘルスチェック・デプロイ」）: `fly releases`と`fly deploy --image`で直前イメージへ戻す。非互換migration後はforward fix
   - `fly secrets set`はMachineを再起動することを書く
6. **SQLiteファイルの配置と入れ替え（フェーズ6の最終移行）**
   - `migration-runbook.md` §5でローカルに再構築した`data/app.db`を、`fly ssh sftp shell`の`put`で`/data/`の別名へ置く
   - 入れ替えの共通手順（§7と共用）: `fly ssh console` → `supervisorctl stop uvicorn supercronic` → 現行の`app.db`・`app.db-wal`・`app.db-shm`を退避 → 新ファイルを`app.db`へ → `alembic upgrade head` → `supervisorctl start uvicorn supercronic` → `/healthz`と件数の確認。`cloudflared`は止めない
   - 件数の確認はPythonの`sqlite3`で行う（`sqlite3`コマンドは無い）
7. **R2からの復旧**（ADR 003「復旧手順」をコマンドに落とす）
   - R2からの取得は管理者の手元で行う（ダッシュボードのダウンロードか、手元のS3クライアント。どちらかに決める）
   - 手元で`PRAGMA integrity_check`・`alembic_version`の`version_num`・主要件数（authors・quotes・quote_likes）を確かめる。期待するrevisionは`migrations/versions/`のheadを書く
   - 以降は§6の共通手順
8. **Tunnel tokenが漏れた場合**（ADR 013「プロセス・秘密情報」）
   - Zero Trustでtokenを更新 → `fly secrets set TUNNEL_TOKEN=...`（再起動される）→ 旧tokenのconnectionをダッシュボードから切断 → `fly logs`で再接続を確認

**入れ替え手順のローカル演習（必須）**

§6・§7の「入れ替えの共通手順」は、ローカルのコンテナで実際に通す。空の`/data`で起動したコンテナに対し、手元の`data/app.db`を「復旧するファイル」に見立てて、`docker cp`で持ち込み、runbookに書いたコマンドをそのまま実行する。確かめること:

- `supervisorctl stop uvicorn supercronic`が効き、`cloudflared`は影響を受けない
- 入れ替え後に`alembic upgrade head`が何もせず成功し、`/healthz`が200で、authorsとquotesの件数が手元のDBと同じになる
- `supervisorctl start`後にUvicornが新しいDBを読んでいる（公開ページに名言が出る）
- 退避した旧ファイルが残っている

runbookに書いた手順と演習で実行したコマンドが食い違ったら、runbookを直す。R2からの取得だけは手元のファイルで代用し、その旨を報告に書く。

**`docker/supervisord.conf`の変更**

`supervisorctl`のために`[unix_http_server]`（`/tmp/supervisor.sock`、`chmod=0700`）・`[rpcinterface:supervisor]`・`[supervisorctl]`（`serverurl=unix:///tmp/supervisor.sock`）を足す。それ以外は変えない。5-Aの「ローカルでの確かめ方」のうち、起動・`/healthz`・Uvicornの再起動を再確認する。

**CI（`.github/workflows/test.yml`）**

- トリガー: `push`（`main`）と`pull_request`
- 手順: `actions/checkout` → `astral-sh/setup-uv`（`.python-version`の3.14を使う。`uv sync --frozen`）→ `sudo apt-get install --yes --no-install-recommends fonts-noto-cjk` → `uv run ruff check` → `uv run ruff format --check` → `uv run pytest`
- Dockerイメージのビルドはしない（イメージが大きく、デプロイはFlyのremote builderで行う）
- Actionは公式（`actions/*`・`astral-sh/*`・`superfly/*`）に限り、メジャーバージョンのタグで固定する
- `permissions: contents: read`を明示する

**デプロイ（`.github/workflows/deploy.yml`）**

- トリガー: `workflow_dispatch`だけ。`concurrency`で同時実行を1つにする
- 手順: `actions/checkout` → `superfly/flyctl-actions/setup-flyctl` → `flyctl deploy --remote-only` → smoke test
- smoke testは`curl --fail --silent --show-error --retry 10 --retry-delay 6 --retry-all-errors https://www.meigensyu.com/healthz`で、応答本文に`"status":"ok"`があること
- 必要なsecretは`FLY_API_TOKEN`だけ。tokenはdeploy token（アプリ限定）にすることをrunbookに書く
- DNS切替前は`www.meigensyu.com`が旧サイトなのでsmoke testは通らない。切替前のデプロイは手元の`flyctl`で行い、workflowは切替後から使う。この前提をworkflowのコメントとrunbook §5の両方に書く

workflowはこの回では実行できない。YAMLが正しいことだけ、`uv run --with pyyaml python -c 'import yaml, sys; [yaml.safe_load(open(p)) for p in sys.argv[1:]]' .github/workflows/*.yml`などで確かめる。`on`キーがYAMLで`True`に読まれる既知の挙動は問題ではない。

**ドキュメントの更新**

- `docs/project-plan.md`: フェーズ5の各項目を見直す。リポジトリ側で完結したものは`[x]`、管理者の外部設定が残るものは`[ ]`のまま「リポジトリ側は完了（2026-10-0n、5-C）、残りはrunbook §n」と書き添える。更新日と§12「次のアクション」（フェーズ6: runbook 1〜4章の外部設定 → 最終移行 → 切替）を直す。フェーズ6の項目に、runbookの章番号への参照を足す
- `README.md`: 「本番コンテナ」の節を短く足す。`docker build`、空ディレクトリを`/data`にマウントした`docker run`、`docker exec`からの`/healthz`確認、2つのジョブの手動実行。詳細は`docs/operations-runbook.md`へ誘導する
- ADRへの追記（新しいADRは作らない。各ADRの末尾か該当節に日付付きで追記する）:
  - ADR 001 §9: デプロイは`workflow_dispatch`の手動実行とし、pushのたびに自動で本番を入れ替えない（決定事項5）。Uvicornは`--no-access-log`で、通信量はCloudflare Analyticsで見る（決定事項2）
  - ADR 003: R2へのPUTは`boto3`を入れず標準ライブラリのSigV4で行う（決定事項4）。キーは`daily/app-<UTC日時>.db`、圧縮なし、設定不足は非ゼロ終了
  - ADR 015: アクセスログを出さない理由（Uvicornが`127.0.0.1`からの`X-Forwarded-For`を信頼するため、Tunnel経由では送信元IPとqueryが出る）
  - ADR 018「フォント」: `fonts-noto-cjk-extra`を追加し`NotoSerifCJK-SemiBold.ttc`を使うこと、ビルド時に選択結果を検査すること（決定事項3）
- 本ファイル: 「進め方」の表で5-Cを完了にする。**本ファイルの削除はしない**（5-Cのレビュー後、残す価値のある申し送りを移してから別コミットで消す）

**この回でやらないこと**

- Fly・Cloudflare・R2・UptimeRobot・GitHubのアカウントに対する操作、push
- `Dockerfile`・`fly.toml`・`docker/crontab`・各スクリプトの変更（runbookの演習で不具合が見つかった場合だけ直し、報告する）
- 復旧やDB入れ替えを自動化するスクリプト。手順はrunbookの中のコマンド列で足りる
- staging環境、blue-green、複数Machine
- HTMLエラーページ（フェーズ6の判断事項）

**完了条件**

- runbookを上から読めば、管理者が外部設定・初回デプロイ・切替・復旧を実行できる。切替前に行ってよい設定と切替時の設定が分かれている
- DB入れ替えの共通手順をローカルのコンテナで通し、結果を確かめている
- 2つのworkflowがYAMLとして正しく、使うActionが公式でバージョン固定されている
- `uv run ruff check`・`uv run ruff format --check`・`uv run pytest`が通る。`docker build`が成功し、`supervisorctl`が使える
- 計画書のフェーズ5に、済んだ項目と管理者の作業として残る項目が区別して書かれている
- 実装を1コミットにする（例: `docs: add operations runbook and CI workflows`）。pushはしない。着手時点で作業ツリーにある`docs/next-session.md`の未コミット変更（5-B・5-Cの指示）はこのコミットに含めてよい

**完了時の報告（5-C分）**

- 作ったもの・変えたもの（ファイル単位）
- 入れ替え手順の演習で実行したコマンドと結果
- runbookのうち「未検証」とした手順の一覧と、公式ドキュメントで確かめた点・ADRと現行仕様が食い違っていた点
- 管理者が次に行う作業の一覧（runbookの章番号で）
- この指示・決定事項・ADRから外れた点と、その理由

## 完了条件

- `docker build`が成功し、5-A・5-Bの「ローカルでの確かめ方」をすべて実行して結果を確かめている
- `uv run ruff check`・`uv run ruff format --check`・`uv run pytest`が通る
- 外部サービスの設定は、runbookを上から読めば管理者が実行できる
- 計画書のフェーズ5に、済んだ項目と、管理者の作業として残る項目が区別して書かれている

## 完了時の報告

次を分けて報告する。

- 作ったもの・変えたもの（ファイル単位）
- ローカルで実際に確かめたことと、その結果
- 確かめられなかったこと（外部サービスが必要なもの）と、管理者が次に行う作業の一覧
- 決定事項1〜5から外れた点、ADRと現行仕様が食い違っていた点
- 固定した`cloudflared`・supercronicのバージョン、最終的なイメージのサイズ
