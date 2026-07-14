# www.meigensyu.com 作り変え 構成書

## 1. 全体構成

```
[User / Bot]
     │
     ▼
[Cloudflare (CDN + WAF)]   ← エッジキャッシュ・DDoS対策・Bot対策
     │
     ▼ Cloudflare Tunnel（outbound-only）
[Fly.io (cloudflared + FastAPI + Uvicorn)]
     │
     ▼
[SQLite (単一 Fly Volume、WAL)]
     │
     └─ 日次 Online Backup API → Cloudflare R2
```

- **フロント**: FastAPI + Jinja2 テンプレートで HTML を返す SSR 構成
- **DB**: SQLite。書き込みは**原則 Admin のみ**（例外は匿名いいねの専用書き込み経路）、読み取り中心
- **CDN**: Cloudflare（無料プランで十分）
- **ホスティング**: Fly.io（東京リージョン `nrt` 推奨）
- **公開ホスト**: `https://www.meigensyu.com/`（Fly.ioの公開IP/serviceは持たない）
- **バックアップ**: 毎日03:00 JSTに整合したSQLiteバックアップをR2へ保存し、30日Lifecycleを設定

## 2. キャッシュ戦略の基本方針

- **キャッシュ可能な公開ページは Cloudflare のエッジキャッシュを効かせる**（※HTMLはデフォルト非キャッシュのため Cache Rules で明示。§8参照）
- **検索ページと Admin ページは絶対にキャッシュしない**
- **`/random` は現行のランダム20件一覧・シャッフルを維持し、`private, no-store`とCloudflare Bypassを適用する**（[ADR 010](010-random-page-cache.md)）
- **更新時は該当URL/タグを Cloudflare API でパージする**（個別=URL、広範=タグ。§5参照）
- ブラウザキャッシュ（`max-age`）は短め、エッジキャッシュ（`s-maxage`）は長めにする
  - 誤った内容を配信した場合、パージすればエッジは即座に更新できるが、ブラウザは強制更新できないため

## 3. パスごとの Cache-Control 設計

| パス | Cache-Control | 想定TTL |
|---|---|---|
| `/`（トップ） | `public, s-maxage=300, max-age=60` | 5分 / 1分 |
| `/quotes*`（一覧・ページング・latest） | `public, s-maxage=600, max-age=60` | 10分 / 1分 |
| `/quotes/{id}`（個別名言） | `public, s-maxage=600, max-age=60` | 10分 / 1分（いいね数を含む） |
| `/authors`（一覧） | `public, s-maxage=3600, max-age=300` | 1時間 / 5分 |
| `/authors/{slug}`（著者詳細） | `public, s-maxage=86400, max-age=3600` | 1日 / 1時間 |
| `/categories`, `/categories/{slug}` | `public, s-maxage=3600, max-age=600` | 1時間 / 10分 |
| `/professions`, `/sources`, `/characters` | `public, s-maxage=3600, max-age=600` | 1時間 / 10分 |
| `/ranking` | `public, s-maxage=600, max-age=60` | 10分 / 1分 |
| `/about`, `/privacy`, `/terms` | `public, s-maxage=604800, max-age=86400` | 1週間 / 1日 |
| `/api/og?*`（OG画像） | `public, s-maxage=2592000, max-age=86400` | 30日 / 1日 |
| **`/random`** | `private, no-store` | 現行20件一覧を維持し、ランダム固定化を防ぐ |
| **`/search`** | `private, no-store` | キャッシュしない |
| **`/admin`, `/admin/*`, `/login`** | `private, no-store` | 管理認証フローをキャッシュしない |
| **`POST /api/likes/*`** | `private, no-store` | キャッシュしない |
| **`/healthz`** | `private, no-store` | Tunnelからoriginまでの外形監視。CloudflareでもBypass |
| `/static/*`（CSS/JS/画像） | `public, max-age=31536000, immutable` | 1年（ファイル名にハッシュ付与） |

## 4. FastAPI 実装ポイント

### 4.1 レスポンスヘッダーの一元管理

パスごとの Cache-Control を Middleware または依存関数で一元管理する。個別ルートに直書きしない。

> ⚠️ **注意（prefixマッチのバグ）**: `startswith` による prefix マッチでは、`"/"` は**あらゆるパスにマッチ**する。dict の挿入順で先頭一致 break すると、`"/"` が先頭にある限り**全パスがトップページのルールに落ちる**。実装では次のいずれかで回避すること。
> - **最長prefix優先**: キーを長さ降順にソートしてから評価し、`"/"` はフォールバック（完全一致 or 最後）として扱う。
> - **完全一致 + prefix の使い分け**: `"/"` は**完全一致のみ**、それ以外は prefix、と規則を分ける。
> - **正規表現ルール**でパスを判定する。

```python
# キーは「長い（具体的な）prefix ほど先」に評価する。"/" はフォールバック。
CACHE_RULES = {
    "/quotes": "public, s-maxage=600, max-age=60",
    # ... 他の具体的パスを列挙 ...
}
ROOT_RULE = "public, s-maxage=300, max-age=60"  # "/" 完全一致用

# 長さ降順で評価して最長prefix優先にする
_SORTED_RULES = sorted(CACHE_RULES.items(), key=lambda kv: len(kv[0]), reverse=True)

@app.middleware("http")
async def cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    # /adminとその配下、/searchとその配下、/login、/healthzは必ずno-store
    if (
        path in ("/admin", "/search", "/login", "/healthz")
        or path.startswith(("/admin/", "/search/"))
    ):
        response.headers["Cache-Control"] = "private, no-store"
        return response
    # /random は現行のランダム一覧を維持し、常にキャッシュ対象外にする。
    if path == "/random":
        response.headers["Cache-Control"] = "private, no-store"
        return response
    # トップは完全一致で判定（prefix マッチの巻き込みを防ぐ）
    if path == "/":
        response.headers.setdefault("Cache-Control", ROOT_RULE)
        return response
    # 最長prefix優先
    for prefix, value in _SORTED_RULES:
        if path.startswith(prefix):
            response.headers.setdefault("Cache-Control", value)
            break
    return response
```

### 4.2 ETag / 304 対応

名言・著者ページは関連データを含む合成HTMLであり、単一行の `updated_at` だけでは表現全体のETagにならない。独自ETagによる条件付き再検証は使わず、TTLとAdmin更新時のパージで更新する。

### 4.3 Vary ヘッダー

- 言語切替やABテストを行わないなら `Vary` は付けない（キャッシュヒット率が下がる）
- 管理者認証CookieはCloudflare Accessだけが発行し、アプリ独自のログインCookieは発行しない。公開HTMLの内容・cache key・cache可否をアプリの利用者識別Cookieで変えない
- 匿名いいねの`client_uuid`はlocalStorage管理とし、Cookieへ移さない。GA4のfirst-party cookieはADR 016の同意後に限って許可するが、サーバーは参照せず`Vary: Cookie`も付けない

### 4.4 検索ページ

- `GET /search?q=...` のパターン
- `no-store` にする。もしくは、頻出クエリだけアプリ内 TTLCache で軽く受ける
- SQLiteの`LIKE`による部分一致検索。性能上必要になった場合だけFTS5を再検討する

### 4.5 Admin ページ

- `/admin`とその全配下はCloudflare Access + 外部IdPで保護し、管理者emailを完全一致で許可する。MFAはIdP側で有効化する
- FastAPIでもAccess JWTの署名・`iss`・`aud`・有効期限・emailを検証する。単一管理者の初期段階ではアプリ内role・identity表を作らない（[ADR 012](012-admin-auth-cloudflare-access.md)）
- Access session cookieを伴うためキャッシュ不可。`/admin`とその全配下、および`/login`は`private, no-store`とする
- 状態変更にはCSRF token、環境ごとの`PUBLIC_ORIGIN`との完全一致`Origin`、Fetch Metadata検証を必須とする。本番の`PUBLIC_ORIGIN`は`https://www.meigensyu.com`に固定する
- 管理画面のJWT検証とは別に、サイト全体のCloudflare迂回をCloudflare TunnelとFlyの公開IP/service削除で防ぐ（[ADR 013](013-cloudflare-tunnel-origin-protection.md)）

### 4.6 いいね数の表示

名言詳細と一覧（`/quotes*`、`/quotes/latest*`）のSSR HTMLへいいね数を含め、`s-maxage=600, max-age=60` でキャッシュする。毎PVで件数を取得するGET/HTMX断片APIは作らず、いいねごとのCloudflareパージも行わない。

登録は公開HTMLと分離した `POST /api/likes/{quote_id}` で受け、`private, no-store` とCloudflare Bypassを必須にする。成功応答で最新件数を返し、押した本人のDOMだけ即時更新する。TTL内の再読込で一時的に古い件数へ戻ることは許容する。重複抑止は`client_uuid`の一意制約と単純な短時間IP制限に留め、IP hashは保存しない（[`006-like-count-cache-strategy.md`](006-like-count-cache-strategy.md)）。

## 5. キャッシュパージ

管理更新後に少数の関連URLまたは集合タグを同期パージする。失敗時は管理者へ表示してログへ残し、TTLによる自然失効を待つ。outbox、自動retry、非同期flusherは作らない。大量更新時は集合タグ、手動Purge Everything、またはTTLへ委任する。詳細は [`014-cache-purge-boundaries.md`](014-cache-purge-boundaries.md) を正本とする。

## 6. SQLite 構成

### 6.1 永続化・バックアップ・復旧（確定）

**単一 Fly Machine + Fly Volume + 日次SQLiteオンラインバックアップ**を採用する（ADR 003）。初期構成ではLiteFS/Litestreamを使わず、継続レプリケーションと自動フェイルオーバーは行わない。

- 稼働中のSQLiteファイルを単純に `cp` しない。Python `sqlite3.Connection.backup()`（SQLite Online Backup API）で一貫した一時DBを生成する。
- 毎日03:00 JSTに、Uvicorn workerとは独立した専用 `supercronic` プロセスから単一ジョブを実行する。
- 一時DBを`integrity_check`後にCloudflare R2へアップロードする。
- 失敗時は通知し、最新成功時刻をログで確認できるようにする。
- R2の`daily/` prefixへUTC日時を含む一意な名前で上書きせず保存し、Lifecycleで30日後に削除する。Bucket Lockと追加snapshotは初期必須としない。
- 正常に日次ジョブが動いている場合のRPOは約24時間、RTOは30分〜数時間を暫定目標とする。ジョブ失敗・未検知時はRPOを超過する。
- 大きなデータ移行または破壊的migration前にはオンデマンドバックアップを取得する。

復旧時はR2のバックアップを別パスへ取得し、`integrity_check`、Alembic revision、主要件数を検証してからDBを切り替える。復元確認は初回リリース前、大きな変更後、または四半期を目安に行う。詳細は [`003-sqlite-daily-backup.md`](003-sqlite-daily-backup.md) を参照。

### 6.2 SQLite 設定

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;   -- 64MB
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

### 6.3 検索

初期リリースは単純な`LIKE`部分一致を使用する（決定記録002）。約3,000行では追加インデックスなしでも十分なため、FTS5、bigram派生列、生成スクリプトを持たない。入力を正規化し、bind parameter、結果件数上限、必要最小限の順位付けを使用する。性能または検索品質の問題が実測された場合だけFTS5等を再評価する。

## 7. Fly.io 構成

### 7.1 fly.toml の要点

```toml
app = "meigensyu"
primary_region = "nrt"

[build]
  dockerfile = "Dockerfile"

# Cloudflare Tunnelからlocalhostへ接続するため、
# [http_service] / [[services]] は定義しない。

[[restart]]
  policy = "always"
  processes = ["app"]

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"

[mounts]
  source = "data"
  destination = "/data"
```

- SQLite は `/data` にマウントされたボリュームに置く
- 初期構成は1 Machineとし、日次ジョブを確実に実行するため常時起動する
- public IPv4/IPv6を解放し、公開serviceを定義しない。デプロイ後はMachine実設定も確認する（[ADR 013](013-cloudflare-tunnel-origin-protection.md)）
- 高可用性や複数リージョンDBが必要になった場合は、SQLiteレプリケーションだけでなくマネージドDBも含めて再設計する

### 7.2 Dockerfile 要点

- `python:3.12-slim` ベース
- 初期は `uvicorn --workers 1 --host 127.0.0.1 --port 8000`
- 固定バージョンの`cloudflared`を同梱し、自動更新は使わない
- PID 1の最小限のプロセス監督でUvicorn、`cloudflared`、supercronicを起動・再起動する。アプリ固有の状態管理は持たせない
- `/healthz`は`private, no-store`とCloudflare Bypassを設定し、外形監視とデプロイ後smoke testに使う

FastAPIのstartup/lifespanでは定期ジョブを起動しない。バックアップ、ランキング、カテゴリ集計はsupercronicからCLIとして実行し、ジョブ別`flock`、timeout、非ゼロ終了、既存経路での失敗通知を使う。独自の共有maintenance lockや鮮度APIは作らない。負荷観測後に必要な場合だけHTTP workerを2へ増やす（[`005-uvicorn-supercronic-jobs.md`](005-uvicorn-supercronic-jobs.md)）。

## 8. Cloudflare 設定

- **DNS/Tunnel**: `www.meigensyu.com`をremotely-managed Cloudflare TunnelのPublished applicationに割り当て、`http://127.0.0.1:8000`へ転送する。wildcard routeは使わず、未一致routeは404にする。apex `meigensyu.com`はproxied placeholder A `192.0.2.0`とRedirect Ruleでpath/queryを維持して`www`へ301または308を返す
- **SSL/TLS**: 利用者とCloudflare間のedge証明書はCloudflareで管理する。TunnelからlocalhostはHTTPとし、専用のorigin証明書は持たない
- **Cache Rules**（ダッシュボードから設定。**Cache Rules は last matching rule wins**）:
  1. 公開HTMLパス（`/`, `/quotes*`, `/authors*`, `/categories*`, `/characters*`, `/professions*`, `/sources*`, `/ranking*`, `/about` 等）→ **Cache eligibility: Eligible for cache（＝Cache Everything 相当）**、Edge TTL は **「Use cache-control header if present」**（オリジンの `s-maxage` を尊重）
  2. `/static/*` → Eligible for cache, Edge TTL 1 month
  3. `/admin`・`/admin/*`・`/login`・`/search*`・`/random`・`/api/likes/*`・`/healthz` → **Bypass cache**（Cookie/動的/公開書き込み/外形監視のため必ず除外）
- ⚠️ **重要**: Cache Rules は複数マッチ時に最後の一致ルールが勝つ。旧Page Rulesの「先勝ち」と逆なので、Bypassルールは公開HTMLのEligibleルールより**後（下）**に配置する。
- ⚠️ **重要**: **Cloudflare はデフォルトで HTML/JSON をキャッシュしない**（拡張子ベースでCSS/JS/画像等のみキャッシュ）。オリジンが `Cache-Control: public, s-maxage=...` を返しても、**Cache Rule で明示的に「Eligible for cache」を指定しない限り公開HTMLはキャッシュされない**。SSRのHTMLをエッジキャッシュする本構成では上記1の公開HTML Cache Rule が必須。
  - 参照: [Default cache behavior](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)
  - 参照: [Cache Rules order](https://developers.cloudflare.com/cache/how-to/cache-rules/order/)
- （Page Rules は廃止方向のため **Cache Rules に統一**。旧 Page Rule 相当は上記③でカバー）
- **WAF**:
  - Bot Fight Mode ON
  - Rate limiting: Freeの1ルールは`/api/likes/*`へ優先し、IP単位10回/10秒・10秒blockの粗いburst shieldとする。`/search`用Cloudflare ruleは初期配置せず、アプリ側の30回/10秒・120回/60秒を正本とする。検索は1文字から500ms debounceで実行する（[ADR 006](006-like-count-cache-strategy.md)、[ADR 015](015-search-rate-limits.md)）
- **Admin access**: Cloudflare Access + 外部IdP側MFAとFastAPIでの最小限のAccess JWT検証を使用する（ADR 012）
- **Origin protection（D14・確定）**: Cloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除する。FastAPIでexact Hostを検証し、AOP・CF IP allowlist・独自secret headerは併用しない（[ADR 013](013-cloudflare-tunnel-origin-protection.md)）

## 9. デプロイ・運用

- CI/CD: GitHub Actions → `flyctl deploy`
- マイグレーション: SQLAlchemy Core + `alembic` で管理（ADR 004）。autogenerateは下書きに限定し、必要なトリガー・ビュー・データ変換は手書きrevisionにする
- SQLiteファイルをマウントしないFlyの `release_command` ではmigrationを実行しない。VolumeをマウントしたMachineでUvicorn worker起動前に一度だけ実行する
- migration時は短いmaintenance windowを設け、破壊的変更では事前バックアップを取得して`alembic upgrade head`を実行し、主要ページを確認する
- ログ: Fly.io の標準ログ + Cloudflare Analytics
- 監視: Fly.io メトリクス + UptimeRobot などで外形監視
- バックアップ: SQLite Online Backup APIによる日次R2保存。失敗を通知し、復元確認はリリース前・大きな変更後・四半期を目安に行う

## 10. 環境変数

| 変数名 | 用途 |
|---|---|
| `DATABASE_URL` | SQLite絶対パス（例: `sqlite:////data/app.db`） |
| `PUBLIC_ORIGIN` | 環境ごとの公開オリジン。本番は`https://www.meigensyu.com`（末尾slashなし） |
| `CF_ZONE_ID` | Cloudflare Zone ID |
| `CF_API_TOKEN` | Cloudflare API Token（`Cache Purge` 権限のみ） |
| `TUNNEL_TOKEN` | remotely-managed Cloudflare Tunnelのconnector token（Fly secret） |
| `CF_ACCESS_TEAM_DOMAIN` / `CF_ACCESS_AUD` | Cloudflare Access JWTのissuer・管理画面application audience検証 |
| `SECRET_KEY` | CSRF token等のアプリ署名（管理者パスワードやAccess JWT署名には使わない） |
| `GA_MEASUREMENT_ID` | 本体完成後、GA4を導入する場合だけ設定。未設定時はAnalyticsコードを出さない |
| `ADSENSE_PUBLISHER_ID` | 本体完成後、AdSenseを導入する場合だけ設定。未設定時は広告コードを出さない |
| `BACKUP_R2_ENDPOINT` / `BACKUP_R2_BUCKET` / `BACKUP_R2_PREFIX` | 日次SQLiteバックアップの保存先（prefix初期値: `daily/`） |
| `BACKUP_R2_ACCESS_KEY_ID` / `BACKUP_R2_SECRET_ACCESS_KEY` | バックアップ専用バケットだけに限定した資格情報 |

## 11. セキュリティ

- Admin: Cloudflare Access + 外部IdP側MFA + FastAPIでの最小限のAccess JWT検証。初期は単一管理者を想定する
- CSRF token、公開オリジンとの完全一致`Origin`、Fetch Metadata検証（Adminの状態変更）
- Cloudflare Accessの認証Cookieには`Secure`、`HttpOnly`、適切な`SameSite`属性を要求する
- 全HTMLへ現実的な共通CSPと基本セキュリティヘッダーを適用する。HTMXのeval/script実行を無効化し、独自CSP report endpointは作らない。GA4/AdSenseは本体完成後の任意機能とする（[ADR 016](016-csp-htmx-rules.md)）
- HTMXは`allowEval=false`、`allowScriptTags=false`とし、`hx-on`、イベントフィルタ、`js:`/`javascript:`値、断片内scriptを禁止する。`hx-csp`は初期採用しない（[ADR 016](016-csp-htmx-rules.md)）
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

## 12. 段階的リリース手順

1. Fly.io に新環境をデプロイ（別サブドメイン `new.meigensyu.com`）
2. `new.meigensyu.com` は `noindex` / robots deny を有効化
3. データ移行（旧DB → 新SQLite）
4. 動作確認・キャッシュヘッダー検証（`curl -I` で確認）
5. Cloudflare を経由させて動作確認
6. DNS切替直前に差分再移行、または旧環境のAdmin/いいね書き込みを短時間凍結
7. 検証環境の許可Host・`PUBLIC_ORIGIN`を`www.meigensyu.com`へ、`CF_ACCESS_AUD`を本番Access applicationのaudienceへ変更してデプロイ
8. `www`のDNS/Tunnel routeを切り替え（TTL を事前に短くしておく）
9. 公開ページと管理画面の正常性を確認し、`new.`の一時Tunnel routeとAccess applicationを削除
10. 旧環境は 1〜2週間維持し、問題なければ廃止

## 13. 期待効果

- **TTFB 短縮**: エッジキャッシュヒット時は 20〜50ms
- **オリジン負荷削減**: 公開ページといいね数をまとめてエッジから返し、オリジン到達はキャッシュmissといいねPOST等に限定する
- **Fly.io 帯域コスト削減**
- **SEO 改善**: Core Web Vitals の LCP/TTFB 向上
- **DDoS / Bot 対策**: Cloudflare のレイヤーで自動対応

## 14. 検収チェックリスト

- [ ] `/quotes/q1342`、`/quotes`、`/quotes/page/2`、`/quotes/latest`、`/quotes/latest/page/2` に `Cache-Control: public, s-maxage=600, max-age=60` が付いている
- [ ] `/search?q=test` に `Cache-Control: private, no-store` が付いている
- [ ] `/admin`とその全配下、および`/login`に `Cache-Control: private, no-store` が付き、CloudflareでもBypassされる
- [ ] 共通CSPと基本セキュリティヘッダーが付き、閲覧・検索・管理・HTMXの主要導線が動作する
- [ ] `POST /api/likes/q1342` が `private, no-store` かつCloudflare Bypassで、GETは405を返す
- [ ] `/random` が現行どおり20件のランダム一覧を返し、`private, no-store`かつCloudflare Bypassで、連続取得時に結果がキャッシュ固定化しない
- [ ] `curl -I` で 2回目に `cf-cache-status: HIT` が返る（公開ページ）
- [ ] Admin から名言更新後、該当URLがパージされ最新内容が返る
- [ ] SQLite が WAL モードで動いている
- [ ] 初期構成のUvicorn 1 workerで各定期ジョブが1回だけ実行され、supercronic停止・timeout・失敗を検知できる。2 workerへ変更する場合は同じ回帰確認を行う
- [ ] 日次バックアップがR2へ保存され、失敗時に通知される
- [ ] リリース前または大きな変更後にR2バックアップから復元し、`integrity_check`、Alembic revision、主要件数を確認できる
- [ ] 空DBと本番相当DBの両方で `alembic upgrade head` が成功する
- [ ] `/healthz` が`private, no-store`かつCloudflare Bypassで200を返し、外形監視とデプロイ後smoke testがorigin停止を検知する
- [ ] OG画像 `/api/og?type=quote&id=...` がエッジキャッシュされる
- [ ] `fly ips list`にpublic IPがなくMachine実設定に公開serviceがなく、`*.fly.dev`と旧Anycast IPから到達できない
- [ ] Tunnel routeとFastAPIが`www.meigensyu.com`だけを許可し、未知Hostを拒否する
- [ ] 匿名いいねPOSTが`CF-Connecting-IP`の欠落・重複・カンマ区切り・不正なIPv4/IPv6を拒否する
- [ ] `cloudflared`停止時に迂回経路がなくfail closedになり、public IP削除後もFlyの管理経路から復旧できる
- [ ] `new.` サブドメインがインデックス不可になっている
