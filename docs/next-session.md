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
| 5-B | 定期ジョブ（日次バックアップ・Heartbeat・crontab） | 未着手 |
| 5-C | 運用runbook・CI workflow・計画書の更新 | 未着手 |

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

**日次バックアップ（ADR 003）**

`scripts/backup_sqlite.py`を新設する。処理は次の順で、どこかで失敗したら非ゼロで終了し、Heartbeatを送らない。

1. `sqlite3.Connection.backup()`で一時ファイルへ一貫したコピーを作る。稼働中のDBファイルを単純にコピーしない
2. 一時ファイルへ`PRAGMA integrity_check`を実行し、`ok`以外なら失敗にする
3. R2へPUTする（決定事項4）。キーは`{BACKUP_R2_PREFIX}`の下にUTC日時を含む一意な名前とし、同じキーを上書きしない
4. 成功したら`UPTIMEROBOT_BACKUP_HEARTBEAT_URL`へpingする
5. 一時ファイルを消す（失敗時も）

- 成功時は、キー名・サイズ・所要時間を1行でログに出す（最新の成功時刻をログで確かめられるようにするため）
- R2の設定が1つでも欠けていれば、何をせずに終わるのではなく、欠けている変数名を示して非ゼロで終了する。本番で設定漏れに気づけるようにするためである
- 30日後の削除はR2のLifecycleで行う。スクリプトで古いオブジェクトを消さない
- テスト: バックアップしたファイルが開けて元と同じ件数になること、`integrity_check`の失敗とアップロードの失敗でHeartbeatを送らず非ゼロになること、SigV4署名が既知の入力に対して期待どおりの値になること。R2への実通信はテストしない

**ランキング再計算へのHeartbeat追加（ADR 005）**

`scripts/refresh_rankings.py`に、`UPTIMEROBOT_RANKING_HEARTBEAT_URL`へのpingを足す。位置は**transactionの成功後、cache purgeの前**である。purgeの失敗はTTLで回復するので、Heartbeatの条件に含めない。

**Heartbeatの共通の振る舞い**

- URLが未設定なら送らずに続ける（ローカル用）
- 送信に失敗しても、ジョブ自体は成功として扱い、警告をログに出す。pingが届かなければUptimeRobotが通知するので、再試行は作らない
- 短いtimeoutを付ける。バックアップとランキングで同じ小さな関数を使う

**crontab（supercronic）**

- バックアップ: 毎日03:00 JST。コンテナの時刻帯はUTCなので`0 18 * * *`
- ランキング: `0 3,15 * * *`（UTC。旧環境のpg_cronと同じ）
- どちらも`flock -n`で多重起動を防ぎ、`timeout`で最大実行時間を切る。lockファイルはジョブごとに分ける
- ジョブはコンテナの環境変数（Fly secrets）を読めること。supervisord経由で環境変数が引き継がれることをローカルで確かめる

**ローカルでの確かめ方**

- コンテナの中で2つのCLIを手で実行し、終了コードとログを確かめる（R2未設定ではバックアップが変数名を示して失敗すること、ランキングが成功すること）
- 同じジョブを同時に2つ起動し、後のほうが`flock`でスキップされること
- crontabがsupercronicの検査（`supercronic -test`）を通ること

### 5-C. 運用runbook・CI・計画書

**runbook**

`docs/operations-runbook.md`を1ファイルで作る。管理者がこの順に実行すれば外部設定が終わるように、コマンドと設定値を具体的に書く。確かめていない手順には「未検証」と明記する。

1. 初回セットアップ: Fly appとVolumeの作成、secretsの一覧と設定コマンド（ADR 001 §10の変数と、どれが秘密か）、初回デプロイ。public IPが割り当てられていないことを`fly ips list`で確かめ、あれば解放する手順（ADR 013）
2. Cloudflare: remotely-managed Tunnelの作成と`www`のroute、apexの`192.0.2.0`とRedirect Rule、Cache Rulesの具体的な式と順序（Bypassを後に置く。`*/og.png`・`/sitemap.xml`・`/robots.txt`もキャッシュ対象にする）、WAF（Bot Fight Mode、いいねPOSTのRate limiting）、Access application。値はADR 001 §8・ADR 012・ADR 013から引く
3. R2: バケット、30日のLifecycle、バケット限定の資格情報
4. UptimeRobot: `/healthz`の外形監視（**GET**で行う。HEADは405になる）、ジョブ2つのHeartbeat監視と猶予時間、アプリPushとメールの通知先
5. デプロイとsmoke test: 手動デプロイの手順、`fly ssh console`からの内部確認（`Host`ヘッダーを付けて`127.0.0.1:8000/healthz`）、`https://www.meigensyu.com/healthz`の確認、rollbackの判断（ADR 013「ヘルスチェック・デプロイ」）
6. SQLiteファイルの配置と入れ替え: フェーズ6の最終移行で、再構築したDBをVolumeへ置く手順
7. R2からの復旧: ADR 003「復旧手順」を、実際のコマンドに落とす。`integrity_check`・Alembic revision・主要件数の確認を含める
8. Tunnel tokenが漏れた場合の対応（ADR 013「プロセス・秘密情報」）

復旧手順のうち、バックアップファイルを検証してDBを差し替える部分は、ローカルのコンテナで実際に通して確かめる（R2からの取得だけは代わりにローカルのファイルを使う）。

**CI（GitHub Actions）**

- テスト用workflow: pushとpull requestで、`ruff check`・`ruff format --check`・`pytest`を実行する。Alembicのheadが1つであること、空DBへの`alembic upgrade head`が成功することも確かめる（ADR 004。既存のテストで足りていれば追加しない）
- デプロイ用workflow: `workflow_dispatch`で`flyctl deploy`を実行し、続けて`https://www.meigensyu.com/healthz`をsmoke testする。必要なsecretは`FLY_API_TOKEN`だけにする
- DNS切替より前は`www.meigensyu.com`が旧サイトを指しているので、このsmoke testは通らない。切替前のデプロイは手元の`flyctl`で行い、workflowは切替後から使う。この前提をrunbookに書く
- Actionは公式のものに限り、バージョンを固定する

**ドキュメントの更新**

- `docs/project-plan.md`: フェーズ5のチェックボックス、更新日、§12「次のアクション」
- `README.md`: コンテナのビルドとローカルでの確かめ方を短く足す
- ADR: 決定事項1〜5のうち、ADRに無い内容（アクセスログを出さない、R2への標準ライブラリによるPUT、手動デプロイ、採用したフォントのパッケージ）を該当ADRへ追記する。新しいADRは作らない

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
