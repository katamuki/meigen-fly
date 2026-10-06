# 運用runbook

更新日: 2026-10-06（フェーズ5-C）。単一Machine・単一Volume、短い停止を許容する。

**外部サービスの操作は全章未検証**。Fly・Cloudflare・R2・UptimeRobot・GitHubはこの作業では操作していない。公式資料で仕様を確認した箇所にはリンクを付けた。§6のコンテナ内DB入れ替えだけはローカルで演習済み（R2取得は手元のDBで代用）。

実行順は **§1 → §2.1 → §3 → §4.1 → §5.1（secrets・初回デプロイ）**。切替時は **旧書き込み凍結・§6 → §2.2〜2.6 → §4.2 → §5.2**。§7・§8は障害時に使う。コマンドはリポジトリ直下から実行する。`<...>`は管理者が得た値に置換し、秘密の実値を資料・Git・ログへ貼らない。

DNS切替までは `www.meigensyu.com` と `meigensyu.com` が旧Next.jsサイトを指す。zone全体の変更は旧サイトにも効くので、Cache Rules・Redirect Ruleも**切替時に作成する**。切替前にpublic hostnameをTunnelへ付けない。WAF・Access・外形監視も切替時に行う。

## 1. 初回セットアップ（Fly.io、切替前）

管理者の手元にflyctlを導入し `fly auth login` する。`fly launch` は既存設定を書き換えるため使わない。

```bash
fly apps create meigensyu
fly volumes create data --app meigensyu --region nrt --size 1
```

名前が取得できなければ別名でappを作り、`fly.toml`の`app`だけを変更する。本書の`--app meigensyu`もその名前へ置き換える。リージョン・512MB・マウント・restart設定は変更しない。

まだデプロイしない。次は§2.1でTunnelを作り、§3・§4.1を順に設定してから§5.1へ進む。

## 2. Cloudflare

### 2.1 切替前: Tunnelと資格情報だけを準備

Zero TrustのNetworks / Connectors / Cloudflare Tunnelsからremotely-managed Tunnel（名前 `meigensyu`、connector `cloudflared`）を作る。表示されたconnector tokenを`TUNNEL_TOKEN`用に保管する。インストールコマンドは実行せず、既存イメージのcloudflaredを使う。**Published application / public hostnameは空のまま**とする。[公式Tunnel作成手順](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)

Zero Trustのteam domainを `https://<team>.cloudflareaccess.com`（末尾slashなし）として控える。Google IdPはZero Trustの認証設定で準備し、Google側でMFAを有効にする。Access applicationは§2.2まで作らない。

Cloudflareのzone OverviewからZone IDを控える。My Profile / API TokensでCustom tokenを作り、permissionは **Zone / Cache Purge / Purgeだけ**、resourceは `meigensyu.com` のzoneだけに限定する。値を`CF_API_TOKEN`、Zone IDを`CF_ZONE_ID`用に保管する。[公式権限一覧](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)

次は§3へ進む。

### 2.2 切替時: Access（Tunnel route公開前）

§6の最終移行が終わり、旧環境の書き込みが止まった状態で実施する。ここからは旧サイトにも設定が効く。

Zero Trust / Access controls / ApplicationsでSelf-hosted applicationを作る。public hostnameを `www.meigensyu.com`、pathを `/admin`（配下も保護）とする。`/login`やサイト全体は含めない。Allow policyのIncludeは **Emails: 管理者メール1件の完全一致**。IdPはGoogleだけを選び、他のAllow・Bypass policyは追加しない。アプリのAUD tagを控える。[公式Access設定](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)

§5.1の非表示入力・標準入力方式を使い、登録コマンドを `fly secrets import --app meigensyu`（`--stage`なし）として `CF_ACCESS_AUD`を登録する。Machineが再起動して実AUDが反映されたことを確認してからrouteを公開する。`CF_ACCESS_TEAM_DOMAIN`も確認する。`/login`はアプリ側で`/admin`へ302する。

`CF_ACCESS_AUD`はAccess applicationを作るこの段階で初めて登録する。切替前は未設定とし、ADR 012の設定不足時の拒否により管理画面は403になる。`ADMIN_DEV_EMAIL`は本番で設定しない。

### 2.3 切替時: wwwのTunnel route・DNS・SSL

旧 `www` のレコードの種類・値・TTLを控える。Cloudflare DNSの既存`www`レコードがDNS onlyなら、DNS切替前にTTLを短縮し、変更前のTTLの経過を待つ。proxiedならTTLはAutoで変更できないため、短縮は不要。[公式TTL仕様](https://developers.cloudflare.com/dns/manage-dns-records/reference/ttl/) TunnelのPublished applicationに **`www.meigensyu.com` → `http://127.0.0.1:8000`** を1つだけ追加する。既存wwwレコードが衝突するので、旧レコードを削除してTunnelのCNAME（`<tunnel-id>.cfargotunnel.com`、proxied）に置換する。wildcardは作らず、未一致routeのcatch-allは404のまま。HTTP Host Headerの上書きは設定しない。

edge証明書がwwwとapexをカバーし有効であることをSSL/TLS / Edge Certificatesで確認する。TunnelからlocalhostはHTTPなのでorigin証明書は作らない。

### 2.4 切替時: apexの301

旧apexレコードを控えてから、`meigensyu.com`を **A / `192.0.2.0` / proxied** へ置換する（競合する旧A/AAAA/CNAMEも除く）。Rules / Redirect RulesでSingle Redirectを作る。

- 条件: `(http.host eq "meigensyu.com")`
- Dynamic target: `concat("https://www.meigensyu.com", http.request.uri.path)`
- Status: **301**、Preserve query string: **ON**

path・queryを維持する。例えば `/quotes?q=test` が1 hopで `https://www.meigensyu.com/quotes?q=test`へ移ることをGETで確認する。[公式Redirect設定](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/)

### 2.5 切替時: Cache Rules（3ルール）

Rules / Cache Rulesで次の順に作る。既存Page Rules・Cache Rulesと競合しないよう、旧設定を控えて無効化する。Browser TTLはすべてRespect origin、cache keyのqueryは既定のまま。公開HTML・OGのEdge TTLは **Use cache-control header if present, bypass cache if not** とし `s-maxage` を尊重する。

1. 公開HTML・OG・sitemap・robots: Eligible for cache。式:

```text
(http.host eq "www.meigensyu.com" and http.request.method in {"GET" "HEAD"} and (
  http.request.uri.path in {"/" "/quotes" "/authors" "/categories" "/characters" "/professions" "/sources" "/countries" "/ranking" "/about" "/privacy" "/terms" "/sitemap.xml" "/robots.txt"}
  or starts_with(http.request.uri.path, "/quotes/")
  or starts_with(http.request.uri.path, "/authors/")
  or starts_with(http.request.uri.path, "/categories/")
  or starts_with(http.request.uri.path, "/characters/")
  or starts_with(http.request.uri.path, "/professions/")
  or starts_with(http.request.uri.path, "/sources/")
  or starts_with(http.request.uri.path, "/countries/")
  or starts_with(http.request.uri.path, "/ranking/")
))
```

`/quotes/*/og.png`・`/authors/*/og.png`も上のprefixに含まれる。`/countries`はURL契約表の互換リダイレクト経路を含む。

2. 静的ファイル: Eligible for cache、Edge TTLは **Ignore cache-control header and use this TTL: 1 month（2592000秒）**。式:

```text
(http.host eq "www.meigensyu.com" and starts_with(http.request.uri.path, "/static/"))
```

3. Bypass cache。`app/middleware.py`の`NO_STORE_PATHS`・prefixを網羅する。式:

```text
(http.host eq "www.meigensyu.com" and (
  http.request.uri.path in {"/admin" "/login" "/search" "/random" "/healthz"}
  or starts_with(http.request.uri.path, "/admin/")
  or starts_with(http.request.uri.path, "/search/")
  or starts_with(http.request.uri.path, "/api/likes/")
  or not http.request.method in {"GET" "HEAD"}
))
```

同じ設定は **last matching rule wins** のため、Bypassを最後に置く。[公式順序](https://developers.cloudflare.com/cache/how-to/cache-rules/order/)・[公式TTL設定](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/)

### 2.6 切替時: WAF

Security設定でBot Fight ModeをONにする（zone全体に効く）。Rate limitingを1ルールだけ作る。

```text
(starts_with(http.request.uri.path, "/api/likes/"))
```

Characteristics: IP、Requests: **10**、Period: **10 seconds**、Action: **Block**、Duration: **10 seconds**。FreeではHost・Method条件を使えないためpathだけを条件にする。対象pathの全methodをカウントするが、アプリが受け付けるのはPOSTのみ（GETは405）。ADRの「POSTだけ」の例からの仕様補正であり、検索用ルールは作らない。[公式プラン別仕様](https://developers.cloudflare.com/waf/rate-limiting-rules/)

## 3. R2（切替前）

R2 Object Storageで非公開バケット `meigensyu-backups` を作る。Settings / Object Lifecycle Rulesで名前 `daily-30-days`、prefix **`daily/`**、Delete objects after **30 days**、Enabledを設定する。既定のmultipart期限ルールはそのままでよい。[公式Lifecycle](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)

R2のManage API TokensからObject Read & Writeを選び、Specific bucketsを `meigensyu-backups` だけにする。Access Key ID・Secret Access Keyを保管する。管理API token自体ではなく、このS3資格情報をスクリプトへ渡す。[公式R2資格情報](https://developers.cloudflare.com/r2/api/tokens/)

- `BACKUP_R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com`
- `BACKUP_R2_BUCKET=meigensyu-backups`
- `BACKUP_R2_PREFIX=daily/`（実装は末尾slashを補わない）

初回デプロイ後、§5.1の内部確認に続けて次を実行する。ジョブと同じlock・timeoutで重複を避ける。

```bash
fly ssh console --app meigensyu
```

```sh
flock -n /tmp/backup_sqlite.lock timeout 600 python /app/scripts/backup_sqlite.py
```

成功ログのキー・バイト数・所要時間と、R2 dashboardに `daily/app-<UTC日時>.db` があることを確認する。これが実R2 PUTの最初の確認。Heartbeat受信も§4.1で確認する。通知が届くまで監視を放置しない。

## 4. UptimeRobot

### 4.1 切替前: Heartbeat 2つ

Heartbeat monitorを2つ作り、間隔と猶予を以下に固定する。利用プランがHeartbeatとこの間隔を提供することを契約画面で確認する。

| monitor | interval | grace period | supercronicの予定時刻 |
|---|---|---|---|
| SQLite backup | 24時間 | 30分 | 毎日18:00 UTC = 03:00 JST |
| Ranking refresh | 12時間 | 30分 | 03:00・15:00 UTC = 12:00・00:00 JST |

URLをそれぞれ `UPTIMEROBOT_BACKUP_HEARTBEAT_URL`・`UPTIMEROBOT_RANKING_HEARTBEAT_URL`として保管する。URL自体が秘密。間隔監視なので手動pingでも次の期限が更新される。初回デプロイ後、§3と§5.1の手動ジョブで受信を確認し、最初の定期実行後にも受信時刻を確認する。[公式Heartbeat](https://uptimerobot.com/help/heartbeat-monitoring/)

公式アプリを管理者の端末へ導入しPush通知を主通知先、メールを予備に設定し、両monitorに紐付ける。テスト通知を確認する。初回稼働前はmonitorをpauseし、初回デプロイ直後に再開して手動ジョブを実行する。成功pingだけを送り、未着の検知とPush・メールもリリース前に実際に確認する。

### 4.2 切替時: HTTP外形監視

URL `https://www.meigensyu.com/healthz`、HTTP method **GET**（HEADは405）、間隔 **5分**でmonitorを作り、同じPush・メール通知先を設定する。200・本文 `{"status":"ok"}` とcache bypassを確認する。Bot Fight Modeで監視がchallengeされる場合はSecurity Eventsで原因を確認する（FreeのBot Fight Modeはcustom ruleでskipできない）。[公式GETの案内](https://uptimerobot.com/help/monitor-status-is-wrong/)

## 5. デプロイとsmoke test

### 5.1 切替前: secretsと初回デプロイ

§1・§2.1・§3・§4.1を済ませてから行う。`DATABASE_URL`・`PUBLIC_ORIGIN`は`fly.toml`の`[env]`にあるためsecretsに重ねない。

| 変数名 | 値の出どころ | 秘密か |
|---|---|---|
| `TUNNEL_TOKEN` | §2.1 connector token | はい |
| `CF_ZONE_ID` | §2.1 zone Overview | いいえ |
| `CF_API_TOKEN` | §2.1 Cache Purge限定token | はい |
| `CF_ACCESS_TEAM_DOMAIN` | §2.1 `https://<team>.cloudflareaccess.com` | いいえ |
| `CF_ACCESS_AUD` | 初回は登録しない。切替時§2.2でAccess作成後のAUDを登録 | いいえ |
| `SECRET_KEY` | 手元で `openssl rand -hex 32` を生成 | はい |
| `BACKUP_R2_ENDPOINT` | §3 account IDから作るendpoint | いいえ |
| `BACKUP_R2_BUCKET` | §3 `meigensyu-backups` | いいえ |
| `BACKUP_R2_PREFIX` | §3 `daily/` | いいえ |
| `BACKUP_R2_ACCESS_KEY_ID` | §3 S3 Access Key ID | はい |
| `BACKUP_R2_SECRET_ACCESS_KEY` | §3 S3 Secret Access Key | はい |
| `UPTIMEROBOT_BACKUP_HEARTBEAT_URL` | §4.1 backup monitor | はい |
| `UPTIMEROBOT_RANKING_HEARTBEAT_URL` | §4.1 ranking monitor | はい |
| `GA_MEASUREMENT_ID` | 未導入のため登録しない | いいえ |
| `ADSENSE_PUBLISHER_ID` | 未導入のため登録しない | いいえ |
| `ADMIN_DEV_EMAIL` | 開発専用。**本番で設定しない** | メールアドレス |

初回は`CF_ACCESS_AUD`・`GA_MEASUREMENT_ID`・`ADSENSE_PUBLISHER_ID`・`ADMIN_DEV_EMAIL`を除き、以下を変数ごとに繰り返す。標準入力からの登録には`fly secrets import`を使う。初回は`--stage`でMachineへの反映を延期し、必要な全変数を登録後にデプロイする。稼働後に即時反映する場合は`--stage`を付けずにimportする。この場合はMachineが再起動するため停止時間を見込む。秘密をコマンド引数やshell historyへ書かず、手元のbashで非表示入力し標準入力から登録する。デバッグ出力（`set -x`）は使わない。[公式secrets import](https://docs.fly.io/flyctl/cmd/fly_secrets_import)・[公式secrets](https://fly.io/docs/apps/secrets/)

```bash
bash
read -r -p 'Variable name: ' secret_name
read -r -s -p 'Value: ' secret_value
printf '\n'
printf '%s=%s\n' "$secret_name" "$secret_value" | fly secrets import --app meigensyu --stage
unset secret_name secret_value
exit
```

```bash
fly secrets list --app meigensyu
fly deploy --app meigensyu --remote-only --ha=false --no-public-ips
fly machine list --app meigensyu
fly ips list --app meigensyu
fly machine status <machine-id> --app meigensyu --display-config
```

`fly secrets list`に`ADMIN_DEV_EMAIL`が無いことも確認する。Machineが1台だけ、serviceが空、public IPv4/IPv6が無いことを確認する。あれば `fly ips release <IP> --app meigensyu` で解放する。`*.fly.dev`へ公開HTTP入口を作らない。`--ha=false`は予備Machine作成を防ぐ（現在の既定はtrue）。[公式deployオプション](https://fly.io/docs/flyctl/deploy/)

```bash
fly logs --app meigensyu
fly ssh console --app meigensyu
```

コンテナ内で（migrationとUvicornの起動完了後に確認する）:

```sh
cd /app
supervisorctl status
curl --fail -H 'Host: www.meigensyu.com' http://127.0.0.1:8000/healthz
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host:' http://127.0.0.1:8000/healthz
flock -n /tmp/refresh_rankings.lock timeout 300 python /app/scripts/refresh_rankings.py
```

healthzは200、Hostなしは400。ログとstatusでUvicorn・cloudflared・supercronicの3つを確認し、`Registered tunnel connection`とZero TrustのHEALTHYを確認する。public hostnameはまだ付けない。§3のbackup手動実行とHeartbeat受信も確認する。

### 5.2 切替後: 通常デプロイと確認

手元では§5.1の `fly deploy` を使う。破壊的migration前は§3のオンデマンドbackupを取得し、§7の検査まで済ませる。

GitHub Actionsは **DNS切替後から** `deploy.yml`を手動実行する。切替前はwwwが旧サイトを指しsmoke testが失敗するため、手元のflyctlだけを使う。管理者がpushした後、GitHub repositoryのActions secretsに `FLY_API_TOKEN` だけを登録する。手元で `fly tokens create deploy --app meigensyu --name github-actions --expiry 2160h` を実行し、得た**アプリ限定deploy token**を使う。個人の全権tokenは使わず、期限前に更新する。[公式deploy token](https://fly.io/docs/security/tokens/)

GitHub Actions / Deploy / Run workflowは本番用のmainを選ぶ。workflowは同時実行を1つにし、deploy後に以下のGETと本文確認を行う。

```bash
curl --fail --silent --show-error --retry 10 --retry-delay 6 --retry-all-errors https://www.meigensyu.com/healthz
curl -sS -D - -o /dev/null https://www.meigensyu.com/healthz
curl -sS -D - -o /dev/null https://www.meigensyu.com/quotes
curl -sS -D - -o /dev/null https://www.meigensyu.com/quotes
```

healthzは200・`"status":"ok"`、`Cache-Control: private, no-store`、`cf-cache-status`はDYNAMICまたはBYPASS（HIT不可）。quotesは2回目HIT、公開OG・sitemap・robots・staticもHITを確認する。search・random・admin・login・いいねはHITしないことを確認する。Accessの許可メール・拒否メール、JWT検証、管理更新・ランキングからの実パージ、いいね、apexの301、旧URL互換、送信元IPの扱いを[ADR 001 §14](decisions/001-architecture-cloudflare-fly-sqlite.md#14-検収チェックリスト)に従って検収する。

smoke test失敗時は `fly logs` と内部healthzで原因を確認する。DB schemaに後方互換性がある場合だけ直前イメージへ戻す。

```bash
fly releases --app meigensyu --image
fly deploy --app meigensyu --image <直前のイメージ参照> --ha=false --no-public-ips
```

非互換migration後はforward fixを優先し、DB復旧が必要なら対応するアプリ版と§7を使う。イメージrollbackだけではDBは戻らない。切替障害で旧DNSへ戻す場合、新サイトで受けた書き込みを確認し、整合性を確認するまで両サイトの書き込みを止める。

## 6. SQLiteファイルの配置と入れ替え（最終移行）

切替直前に旧Admin・いいね書き込みを短時間凍結し、[migration-runbook §5](database/migration-runbook.md#5-再実行可能な手順取得変換投入検証)を再実行して最新の `data/app.db` を作る。§7と同じ手元検査を行う。稼働中のDBファイルを単純コピーしない。

```bash
fly ssh sftp shell --app meigensyu
```

SFTP shell内で（別名へ配置）:

```text
put data/app.db /data/app-incoming.db
exit
```

### 共通入れ替え手順（§7からもここへ）

```bash
fly ssh console --app meigensyu
```

次のコンテナ内コマンドを順に実行する。エラーが出たら中断し、サービスを再開しない。cloudflaredは止めない。`stop`は実行中のジョブも止めるため、事前にログでbackupの成功・終了を確認する。

```sh
set -eu
cd /app
test -f /data/app-incoming.db
supervisorctl stop uvicorn supercronic
supervisorctl status || true
archive_dir="/data/retired-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$archive_dir"
for db_file in app.db app.db-wal app.db-shm; do
    if [ -f "/data/$db_file" ]; then
        mv "/data/$db_file" "$archive_dir/"
    fi
done
mv /data/app-incoming.db /data/app.db
alembic upgrade head
python - <<'PY'
import sqlite3
with sqlite3.connect('file:/data/app.db?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    print('revision:', db.execute('SELECT version_num FROM alembic_version').fetchall())
    for table in ('authors', 'quotes', 'quote_likes'):
        print(table, db.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
PY
supervisorctl start uvicorn supercronic
```

status表示でuvicorn・supercronicのSTOPPEDを確認する。

数秒後に以下を行う。

```sh
curl --fail -H 'Host: www.meigensyu.com' http://127.0.0.1:8000/healthz
curl --fail -H 'Host: www.meigensyu.com' http://127.0.0.1:8000/quotes -o /tmp/restored-quotes.html
python - <<'PY'
from pathlib import Path
import sqlite3
with sqlite3.connect('file:/data/app.db?mode=ro', uri=True) as db:
    for table in ('authors', 'quotes', 'quote_likes'):
        print(table, db.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
assert '<article class="mg-quote-card' in Path('/tmp/restored-quotes.html').read_text()
print('quote cards: present')
PY
grep -m 2 'class="mg-quote"' /tmp/restored-quotes.html
ls -l "$archive_dir"
```

手元で検査した件数と一致し、公開ページに名言が表示されることをブラウザまたはHTML本文で確認する。退避した旧ファイルを残す。再接続した場合は`$archive_dir`が消えているため、`ls -d /data/retired-*`で対象の退避先を確かめる。失敗時は停止状態で原因を確認し、元DBへ戻すなら新DBのWAL/SHMも別に退避し、退避した**旧DB・旧WAL・旧SHMの組**を元に戻す。新旧のWALを混ぜない。migrationが失敗したDBのままUvicornを起動しない。

## 7. R2からの復旧

R2 dashboardで成功ログに対応するバックアップobjectを選び、管理者の手元へ**ダウンロード**する（この手順ではS3クライアントは使わない）。`data/restore.db`として保存する。Gitへ追加しない。ローカルで:

```bash
uv run alembic heads
uv run python - <<'PY'
import sqlite3
with sqlite3.connect('file:data/restore.db?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    print('revision:', db.execute('SELECT version_num FROM alembic_version').fetchall())
    for table in ('authors', 'quotes', 'quote_likes'):
        print(table, db.execute(f'SELECT count(*) FROM {table}').fetchone()[0])
PY
```

2026-10-06時点のheadは **`0002`**（`migrations/versions/0002_create_application_tables.py`）。現在のコードの `alembic heads` と比較する。古いrevisionなら適用するmigrationを確認し、未知・将来revisionなら対応するアプリ版を用意する。件数はバックアップ時点の成功記録・移行検査結果と比較する（固定の本番件数を期待しない）。5-C演習ではauthors 774・quotes 1,831のローカルDBを使った。

```bash
fly ssh sftp shell --app meigensyu
```

```text
put data/restore.db /data/app-incoming.db
exit
```

以降は**§6の共通入れ替え手順**をそのまま実施する。healthz・主要件数・公開ページ・管理更新を確認する。本番停止中はキャッシュHITで古い公開ページが見えることがあるため、内部確認とno-storeのhealthzを使う。復元確認は初回リリース前・大きな変更後・四半期を目安に行う。R2の取得からの実復旧演習は管理者の残作業。

## 8. Tunnel tokenが漏れた場合

Zero Trustの対象Tunnelでtokenを更新し、§5.1の非表示入力・標準入力方式で、登録コマンドを `fly secrets import --app meigensyu`（`--stage`なし）として新しい `TUNNEL_TOKEN`を登録する（Machineが再起動する）。Zero Trust dashboardから旧tokenの確立済みconnectionを切断し、`fly logs --app meigensyu`の接続登録、dashboardのHEALTHY、外部GET healthzを確認する。tokenはログやチケットに貼らない。[公式token更新](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/remote-tunnel-permissions/)
