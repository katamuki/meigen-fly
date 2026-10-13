# 運用runbook

更新日: 2026-10-08（フェーズ6準備の実機確認を反映）。単一Machine・単一Volume、短い停止を許容する。

**実機検証済みは§1、§2.1の一部、§3の手動PUT・取得、§4.1の手動・定期実行、§5.1、§6の初回DB配置、§7のR2復旧演習**。Fly Machineへの初回デプロイ、Tunnel connectorの接続、内部healthz、手元DBの配置、localhostと一時的な`trycloudflare.com`での画面表示を確認した。R2バケットとLifecycleを設定し、バックアップの保存・取得・復元を確認した。Cloudflare zone・API token、GitHubの操作は未検証。定期ジョブのUptimeRobot Heartbeatは使用しない。公式資料で仕様を確認した箇所にはリンクを付けた。

実行順は **§1 → §2.1 → §3 → §4.1 → §5.1（secrets・初回デプロイ）**。切替時は **旧書き込み凍結・§6 → §2.2〜2.6 → §4.2 → §5.2**。§7・§8は障害時に使う。コマンドはリポジトリ直下から実行する。`<...>`は管理者が得た値に置換し、秘密の実値を資料・Git・ログへ貼らない。

2026-10-07に既存`www`を維持したままFlyの非公開プレビューと一時的な外部プレビューを実施した。残作業は[次回セッション指示](next-session.md#次の開始地点)に記載した。

DNS切替までは `www.meigensyu.com` と `meigensyu.com` が旧Next.jsサイトを指す。zone全体の変更は旧サイトにも効くので、Cache Rules・Redirect Ruleも**切替時に作成する**。切替前にpublic hostnameをTunnelへ付けない。WAF・Access・外形監視も切替時に行う。

## 1. 初回セットアップ（Fly.io、切替前）

**検証済み（2026-10-06）**。`meigensyu` appは既に`katamuki-org`に存在し、Image・Machine・Volumeはなかった。非対話の`fly apps create meigensyu`はorg slugの指定を要求して終了したため、既存appを管理者の確認を得て使用した。`data` Volumeを`nrt`に1つ作成し、`fly volumes list`で確認した（ID `vol_v3gkk0wjyy2137o4`、1GB、encrypted）。この時点ではMachineはない。

管理者の手元にflyctlを導入し `fly auth login` する。`fly launch` は既存設定を書き換えるため使わない。

```bash
fly apps create meigensyu --org <org-slug>
fly volumes create data --app meigensyu --region nrt --size 1
```

名前が取得できなければ別名でappを作り、`fly.toml`の`app`だけを変更する。本書の`--app meigensyu`もその名前へ置き換える。リージョン・512MB・マウント・restart設定は変更しない。`<org-slug>`には管理者が選んだorgを指定する。既存appがあれば重複作成せず、owner・Machine・Volumeの状態を確認する。

まだデプロイしない。次は§2.1でTunnelを作り、§3・§4.1を順に設定してから§5.1へ進む。

## 2. Cloudflare

### 2.1 切替前: Tunnelと資格情報だけを準備

**一部検証済み（2026-10-08）**。`meigensyu` Tunnelを作成し、connector tokenを管理者が保管した。公開アプリケーションrouteは空。初回デプロイ後、`fly logs`で`Registered tunnel connection`を4本確認した。2026-10-08にCloudflareのTunnel一覧で状態「正常」、レプリカ1、ルートなしを確認。team domainを管理者が控え、Google IdPを追加して`Your connection works!`を確認した。Googleアカウントのセキュリティ画面では2段階認証プロセスが有効と確認した。Access経由の実ログインは切替時に確認する。Zone IDとCache Purge tokenは未取得。

**実機差分**: `meigensyu.com`はまだCloudflareのDomainsに追加されていない。2026-10-07に公開DNSを確認した時点の権威ネームサーバーは`dns1`〜`dns5.name-services.com`、`www`はVercel向けCNAMEだった。Zone IDはCloudflare zoneを追加するまで取得できない。切替前にzoneを追加する場合も、旧サイト稼働中はドメイン登録先のネームサーバーを変更しない。既存DNSレコードをすべて確認・反映してから切替日に委任を変更する。FreeプランのzoneはPending Nameserver Updateが28日を超えると削除されるため、作成日と切替日を管理する。[公式Pending zone](https://developers.cloudflare.com/dns/zone-setups/troubleshooting/pending-nameservers/)・[公式Zone ID](https://developers.cloudflare.com/fundamentals/account/find-account-and-zone-ids/)

**2026-10-08再確認**: 公開DNSの権威NSは引き続き`dns1`〜`dns5.name-services.com`、apexのAレコードは`216.150.1.1`、`www`は`28f6898fa39e0d09.vercel-dns-017.com`へのCNAME（問い合わせ時のTTLはともに3600秒）。Cloudflare Free zoneを切替前に追加して委任を保留する場合、Pendingの28日期限を切替予定日と照合する。切替日が未定ならzone追加・Zone ID・Cache Purge token取得を切替に近い時期へ回せる。R2バックアップとHeartbeatはそれらの設定なしで検証可能で、ランキング再計算のキャッシュ削除は設定がなければスキップされる。

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

**未検証**。2026-10-07時点ではCloudflareへのzone追加とネームサーバー委任が未実施。切替時は`www`だけでなく、apex・メールなど既存DNSレコードの移行と権威ネームサーバー変更が必要になる。Cloudflareに取り込まれたレコードを現行DNSと照合してから委任を変更する。以下の`www`切替手順は、この前提を満たした後に実施する。

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

**手動実行を検証済み（2026-10-08）**。CloudflareのR2初期画面で、バケット作成前にR2サブスクリプションの追加が必要と判明した。管理者が追加を完了し、契約完了画面で有効化を確認した。非公開バケット`meigensyu-backups`をアジア太平洋・Standardで作成。カスタムドメインは未割当、パブリック開発URLは無効。Lifecycle `daily-30-days`はprefix `daily/`、30日後にオブジェクト削除、Enabledを画面で確認した。既定の7日後multipart中止ルールもEnabledのまま。管理者がバケット限定Object Read & WriteのAccount APIトークンを作成し、S3 Access Key IDとSecret Access Keyを手元に保管した。手動PUTの成功ログと、dashboardから取得したオブジェクトのサイズ・SQLite整合性を確認した。定期実行は2026-10-13に確認済み（§4.1）。

**2026-10-08手動PUT**: `backup_sqlite.py`が終了コード0で、`backup succeeded key=daily/app-20261008T034608Z.db bytes=3059712 duration_seconds=1.038`を出した。管理者がR2 dashboardから同オブジェクトを取得し、3,059,712バイトのSQLiteとして整合性を確認した。§7で復元済み。

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
flock -n /tmp/backup_sqlite.lock timeout 600 /app/.venv/bin/python /app/scripts/backup_sqlite.py
```

成功ログのキー・バイト数・所要時間と、R2 dashboardに `daily/app-<UTC日時>.db` があることを確認する。これが実R2 PUTの最初の確認。以後は§4.1の手順で最新オブジェクトを確認する。

## 4. UptimeRobot

### 4.1 切替前: 定期ジョブの結果確認

**方針変更（2026-10-08、手動実行を検証済み）**。管理者は定期ジョブの実行結果を手動確認できればよいと判断し、UptimeRobotの有料Heartbeat契約を行わない。`UPTIMEROBOT_BACKUP_HEARTBEAT_URL`・`UPTIMEROBOT_RANKING_HEARTBEAT_URL`は登録しない。両ジョブはURL未設定ならHeartbeatをスキップして通常どおり動く。自動通知はなく、未実行・失敗は確認時に見つける。

**2026-10-08手動実行**: バックアップとランキングをlock・timeout付きで実行し、どちらも終了コード0。ランキングは`quotes=1831 authors=755 categories=53`、`refreshed_at=2026-10-08T03:46:19.321958+00:00`。DBの`quote_ranking_scores`も1,831件、最大更新時刻は同時刻だった。両ジョブのHeartbeatは設定なしとしてスキップされた。

**2026-10-13定期実行の確認**: R2 dashboardの`daily/`に、2026-10-08〜10-12の18:00 UTC分の`app-<UTC日時>.db`5件（各3.22MB）と手動PUT分が揃っていた。取得できたFlyログは2026-10-12 15:00 UTC以降で、その範囲のランキング2回（10-12 15:00・10-13 03:00 UTC）とバックアップ1回（10-12 18:00 UTC、`daily/app-20261012T180002Z.db`・3,223,552バイト）が`job succeeded`、失敗・エラーの記録はなかった。ランキングはCloudflare未設定のためpurgeをスキップする。DBの`quote_ranking_scores`は1,831件、`max(refreshed_at)`は`2026-10-13T03:00:02.389093Z`。R2のオブジェクトのContent-Typeは`application/x-www-form-urlencoded`と表示されるが、§7の取得・復元には影響しない。

supercronicの予定時刻はバックアップが毎日18:00 UTC（03:00 JST）、ランキング再計算が03:00・15:00 UTC（12:00・00:00 JST）。手動実行時と定期実行後に`fly logs --app meigensyu`で`backup succeeded key=...`と`ranking refresh succeeded ... refreshed_at=...`を確認する。バックアップはR2 dashboardの`daily/`に最新の`app-<UTC日時>.db`があることを確かめる。ランキングはMachine内のSQLiteで次を実行し、`refreshed_at`が予定した実行時刻に更新されていることを確かめる。ログは後から取得できる期間に限りがあるため、保存先の状態も確認する。

```bash
fly ssh console --app meigensyu
```

コンテナ内で:

```sh
/app/.venv/bin/python - <<'PY'
import sqlite3
with sqlite3.connect('file:/data/app.db?mode=ro', uri=True) as db:
    print(db.execute('SELECT count(*), max(refreshed_at) FROM quote_ranking_scores').fetchone())
PY
```

ランキング対象が0件なら`max(refreshed_at)`はNULLになるため、手動実行の終了コードと成功ログで判定する。初回配置のquotesは1,831件ある。

### 4.2 切替時: HTTP外形監視

URL `https://www.meigensyu.com/healthz`、HTTP method **GET**（HEADは405）、間隔 **5分**でmonitorを作り、同じPush・メール通知先を設定する。200・本文 `{"status":"ok"}` とcache bypassを確認する。Bot Fight Modeで監視がchallengeされる場合はSecurity Eventsで原因を確認する（FreeのBot Fight Modeはcustom ruleでskipできない）。[公式GETの案内](https://uptimerobot.com/help/monitor-status-is-wrong/)

## 5. デプロイとsmoke test

### 5.1 切替前: secretsと初回デプロイ

**一部検証済み（2026-10-07）**。`TUNNEL_TOKEN`と`SECRET_KEY`を`--stage`で登録。最初のビルドは成功したが、`katamuki-org`の支払い情報未登録でMachine作成に失敗した。管理者が支払い方法を登録後、同じdeployコマンドで`nrt`にMachine `185173db303928`を1台作成した（イメージ363MB、Volume `vol_v3gkk0wjyy2137o4`を接続）。`fly ips list`は空、Machine設定にpublic serviceはない。内部`/healthz`は正しいHostで200、Hostなしで400、SQLiteはWAL。`uvicorn`・`cloudflared`の起動とTunnel接続を確認した。R2資格情報が未設定のため`supervisorctl stop supercronic`で定期ジョブを停止中。Machine再起動時には再度起動するため、残りの設定前に再起動した場合は再停止する。残りのsecrets・ジョブ結果確認は未検証。

**2026-10-08再確認**: Gitは`main`が`origin/main`より1コミット先（`50687b8`）、作業開始時の作業ツリーはクリーン。Flyは同じMachine 1台と暗号化Volume 1つが`nrt`で接続・起動中。`fly secrets list`には`TUNNEL_TOKEN`と`SECRET_KEY`だけがあり、`fly ips list`は空、Machineの表示設定にserviceはない。`supervisorctl status`では`cloudflared`・`uvicorn`がRUNNING、`supercronic`がSTOPPED（停止中プロセスがあるためコマンド終了コードは3）。

**2026-10-08 secrets追加後**: 残りの6件を一度に`--stage`登録し、名前を確認して`fly secrets deploy --app meigensyu`で反映した。8件すべてDeployed。Machine `185173db303928`はversion 3で再起動し、`cloudflared`・`supercronic`・`uvicorn`がRUNNING。Machine 1台、暗号化Volume 1つ、public IP・serviceなし。内部healthzは正しいHostで200、Hostなしで400。

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
| `UPTIMEROBOT_BACKUP_HEARTBEAT_URL` | §4.1の方針変更により登録しない | はい |
| `UPTIMEROBOT_RANKING_HEARTBEAT_URL` | §4.1の方針変更により登録しない | はい |
| `GA_MEASUREMENT_ID` | 未導入のため登録しない | いいえ |
| `ADSENSE_PUBLISHER_ID` | 未導入のため登録しない | いいえ |
| `ADMIN_DEV_EMAIL` | 開発専用。**本番で設定しない** | メールアドレス |

初回は`CF_ACCESS_AUD`・`GA_MEASUREMENT_ID`・`ADSENSE_PUBLISHER_ID`・`ADMIN_DEV_EMAIL`・2つの`UPTIMEROBOT_*_HEARTBEAT_URL`を除く。zone追加を保留する間は`CF_ZONE_ID`・`CF_API_TOKEN`も除く。標準入力からの登録には`fly secrets import`を使う。`--stage`でMachineへの反映を延期し、必要な全変数を登録後にデプロイする。既存Machineへ残りのsecretsを追加するときも、すべて`--stage`で登録してから名前を確認し、`fly secrets deploy --app meigensyu`で現在のリリースへまとめて反映する。これで登録ごとのMachine再起動を避け、未設定のまま`supercronic`が再起動する時間を作らない。秘密をコマンド引数やshell historyへ書かない。1件ずつなら手元のbashで非表示入力する。複数件をまとめる場合はリポジトリ外の一時ファイルを権限600で作り、`NAME=VALUE`を1行ずつ保存して`fly secrets import --app meigensyu --stage < ファイル名`で読み込ませ、成功後に削除する。デバッグ出力（`set -x`）は使わない。[公式secrets import](https://docs.fly.io/flyctl/cmd/fly_secrets_import)・[公式secrets](https://fly.io/docs/apps/secrets/)

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

既存Machineへの追加分だけを反映する場合、上の`fly deploy`ではなく`fly secrets deploy --app meigensyu`を使う。反映後にMachine 1台・public IPなし・serviceなしを再確認する。

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
flock -n /tmp/refresh_rankings.lock timeout 300 /app/.venv/bin/python /app/scripts/refresh_rankings.py
```

healthzは200、Hostなしは400。ログとstatusでUvicorn・cloudflared・supercronicの3つを確認し、`Registered tunnel connection`とZero TrustのHEALTHYを確認する。public hostnameはまだ付けない。§3のbackupとランキングを手動実行し、§4.1の結果確認を行う。

#### 切替前の一時プレビュー（2026-10-07検証済み）

手元DBを§6で配置した後、Machine内で`PUBLIC_ORIGIN=http://localhost:8000`のUvicornを一時的にIPv6の8001番で起動し、手元の`fly proxy 8000:8001 --app meigensyu`から`http://localhost:8000/quotes`を確認した。`/healthz`・`/quotes`・静的CSS/JS/画像が200。通常のUvicorn（8000番）と`fly.toml`の`PUBLIC_ORIGIN`は変えていない。

管理者の希望で一時的な外部プレビューも実施した。Machine内で別の`cloudflared tunnel --url http://127.0.0.1:8002`を起動し、発行された`trycloudflare.com`のURLを`PUBLIC_ORIGIN`に指定した一時Uvicornを8002番で起動した。外部HTTPSから`/healthz`・`/quotes`・静的ファイルが200、`/admin`が403、管理者のブラウザでも表示を確認した。Quick Tunnelと一時Uvicornを停止後、URLは530になった。**Quick TunnelはURLを知る人がアクセスできる**ため、確認中だけ起動する。[公式Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

どちらの一時プレビューも終了済み。Flyのpublic IP/service、既存`www`とDNSは変更していない。

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

**初回配置を検証済み（2026-10-07）**。手元の`data/app.db`を`fly ssh sftp put data/app.db /data/app-incoming.db --app meigensyu`で転送し、SHA-256の一致を確認した。空DBと入れ替えてrevision `0002`、integrity `ok`、authors 774件、quotes 1,831件、内部`/quotes` 200・名言カードありを確認。手元DBのランキング3テーブルは0件で、初回プレビューのRanking表示は集計前。最終移行時には旧環境から最新データを再取得して置き換える。

**実機差分**: `fly ssh console`の対話シェルでは仮想環境が`PATH`に入らず、`alembic`が見つからなかった。以下は`/app/.venv/bin/`を明示する。`set -e`中の`supervisorctl status`は停止中のプロセスがあると非0で終了するため、表示目的なら`|| true`を付ける。

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
/app/.venv/bin/alembic upgrade head
/app/.venv/bin/python - <<'PY'
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
/app/.venv/bin/python - <<'PY'
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

**実機検証済み（2026-10-08）**。R2の`daily/app-20261008T034608Z.db`を管理者がダウンロードし、`data/restore.db`にコピーした。サイズ3,059,712バイト、`integrity_check=ok`、revision `0002`、authors 774件・quotes 1,831件・quote_likes 7,942件を確認。`/data/app-incoming.db`へSFTP転送し、手元とFly上のSHA-256一致を確認した。§6の共通入れ替え手順で旧DB/WAL/SHMを`/data/retired-20261008T041600Z/`へ退避して復元。復元後も同じrevision・件数で、内部`/healthz`と`/quotes`は200、名言カードあり、3プロセスRUNNING。バックアップは手動ランキング再計算の直前に作られたためsnapshot 3表は0件だったが、復元後に手動再計算し、`quote_ranking_scores` 1,831件・`refreshed_at=2026-10-08T04:16:53.309627Z`を確認した。旧サイトの最新データは切替直前に再移行する。

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

以降は**§6の共通入れ替え手順**をそのまま実施する。healthz・主要件数・公開ページを確認し、Access公開後なら管理更新も確認する。切替前は`CF_ACCESS_AUD`未設定のため管理更新を試せない。本番停止中はキャッシュHITで古い公開ページが見えることがあるため、内部確認とno-storeのhealthzを使う。復元確認は初回リリース前・大きな変更後・四半期を目安に行う。バックアップ時点でランキングsnapshotが空なら復元後にランキングを再計算する。

## 8. Tunnel tokenが漏れた場合

Zero Trustの対象Tunnelでtokenを更新し、§5.1の非表示入力・標準入力方式で、登録コマンドを `fly secrets import --app meigensyu`（`--stage`なし）として新しい `TUNNEL_TOKEN`を登録する（Machineが再起動する）。Zero Trust dashboardから旧tokenの確立済みconnectionを切断し、`fly logs --app meigensyu`の接続登録、dashboardのHEALTHY、外部GET healthzを確認する。tokenはログやチケットに貼らない。[公式token更新](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/remote-tunnel-permissions/)
