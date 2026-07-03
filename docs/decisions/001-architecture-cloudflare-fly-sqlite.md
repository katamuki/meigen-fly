# meigensyu.com 作り変え 構成書

## 1. 全体構成

```
[User / Bot]
     │
     ▼
[Cloudflare (CDN + WAF)]   ← エッジキャッシュ・DDoS対策・Bot対策
     │
     ▼
[Fly.io (FastAPI + Uvicorn)]
     │
     ▼
[SQLite (LiteFS or Litestream で永続化・レプリカ)]
```

- **フロント**: FastAPI + Jinja2 テンプレートで HTML を返す SSR 構成
- **DB**: SQLite。書き込みは**原則 Admin のみ**（例外は匿名いいねの専用書き込み経路）、読み取り中心
- **CDN**: Cloudflare（無料プランで十分）
- **ホスティング**: Fly.io（東京リージョン `nrt` 推奨）

## 2. キャッシュ戦略の基本方針

- **公開ページはすべて Cloudflare のエッジキャッシュを効かせる**（※HTMLはデフォルト非キャッシュのため Cache Rules で明示。§8参照）
- **検索ページと Admin ページは絶対にキャッシュしない**
- **`/random` は通常の公開HTMLキャッシュ対象に含めない**。`no-store` またはランダムな個別ページへの302方式を実装前に確定する
- **更新時は該当URL/タグを Cloudflare API でパージする**（個別=URL、広範=タグ。§5参照）
- ブラウザキャッシュ（`max-age`）は短め、エッジキャッシュ（`s-maxage`）は長めにする
  - 誤った内容を配信した場合、パージすればエッジは即座に更新できるが、ブラウザは強制更新できないため

## 3. パスごとの Cache-Control 設計

| パス | Cache-Control | 想定TTL |
|---|---|---|
| `/`（トップ） | `public, s-maxage=300, max-age=60` | 5分 / 1分 |
| `/quotes`（一覧） | `public, s-maxage=600, max-age=60` | 10分 / 1分 |
| `/quotes/{id}`（個別名言） | `public, s-maxage=86400, max-age=3600` | 1日 / 1時間 |
| `/authors`（一覧） | `public, s-maxage=3600, max-age=300` | 1時間 / 5分 |
| `/authors/{slug}`（著者詳細） | `public, s-maxage=86400, max-age=3600` | 1日 / 1時間 |
| `/categories`, `/categories/{slug}` | `public, s-maxage=3600, max-age=600` | 1時間 / 10分 |
| `/professions`, `/sources`, `/characters` | `public, s-maxage=3600, max-age=600` | 1時間 / 10分 |
| `/ranking` | `public, s-maxage=600, max-age=60` | 10分 / 1分 |
| `/about`, `/privacy`, `/terms` | `public, s-maxage=604800, max-age=86400` | 1週間 / 1日 |
| `/api/og?*`（OG画像） | `public, s-maxage=2592000, max-age=86400` | 30日 / 1日 |
| **`/random`** | **要決定**: `private, no-store` または 302 | ランダム固定化を防ぐ |
| **`/search`** | `private, no-store` | キャッシュしない |
| **`/admin/*`** | `private, no-store` | キャッシュしない |
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
    # /admin, /search は必ず no-store
    if path.startswith(("/admin", "/search")):
        response.headers["Cache-Control"] = "private, no-store"
        return response
    # /random はD13未決。no-store方式を採用する場合はここで除外する。
    # 302方式を採用する場合は、この分岐ではなくルート側で個別名言へリダイレクトする。
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

個別名言・著者ページは `updated_at` から ETag を生成し、`If-None-Match` 一致時は 304 を返す。Cloudflare も ETag を尊重するため転送量削減に有効。

### 4.3 Vary ヘッダー

- 言語切替やABテストを行わないなら `Vary` は付けない（キャッシュヒット率が下がる）
- Cookie でセッションを持つのは Admin のみに限定する（公開ページに Cookie を付けない）
- 匿名いいねの `client_uuid` は localStorage 管理を基本とし、公開ページに識別Cookieを載せない

### 4.4 検索ページ

- `GET /search?q=...` のパターン
- `no-store` にする。もしくは、頻出クエリだけアプリ内 TTLCache で軽く受ける
- SQLite の FTS5 で全文検索（`quotes_fts` 仮想テーブル）

### 4.5 Admin ページ

- `/admin/*` は Basic認証 or セッション認証
- Cookie 必須 → キャッシュ不可
- CSRF 対策必須
- CloudflareのIP制限だけに依存しない。`*.fly.dev` やオリジンIP直撃でWAF/IP制限を迂回されないよう、Authenticated Origin Pulls、Hostヘッダ検証、Cloudflare IPレンジ検証のいずれかを組み合わせる

### 4.6 いいね数の表示

ページ本体をエッジキャッシュしつつ、いいね数だけ毎PVで非キャッシュ取得すると、オリジン負荷削減効果を相殺する。D9で次のどちらかを優先候補として確定する。

- HTMLへいいね数を焼き込み、短TTL/タグパージで鮮度を許容する
- 断片APIをページ単位でバッチ化し、`s-maxage=10..60` 程度でエッジキャッシュする

「押した」状態は localStorage でクライアント表示する。

## 5. キャッシュパージ

Admin から更新した際、Cloudflare API で **該当 URL（個別ページ）とタグ（一覧など広範）を併用**してパージする。

> ✅ **Cloudflare Free でも各種パージが使える**（公式ドキュメント「Purge cache」Availability and limits, 2026-04-16更新で確認）: **URL / Hostname / Tag（`tags`）/ Prefix（`prefixes`）/ Purge Everything すべて Free プランで利用可能**。※旧記述の「タグ/prefixはEnterprise限定」は**誤りのため訂正**。
> ⚠️ ただし Free の **Tag/Prefix/Hostname/全パージのレート制限は 5リクエスト/分・1リクエスト最大100オペレーション**（バケット25）。URL単位パージは別枠で上限が高い。運用方針は次の通り（[`project-plan.md`](../project-plan.md) §5・D12）:
> - **個別詳細ページ・OG画像 → URLパージ**で即時反映（高上限）。
> - **一覧・著者/カテゴリ・ランキング等の広範な無効化 → `Cache-Tag` を付与してタグパージ**でまとめて落とす（5req/分に収まるようバッチ集約）。
> - 制約に収まらない範囲は**短めの `s-maxage` で自然失効に委ねる**。

```python
import httpx, os

CF_ZONE = os.environ["CF_ZONE_ID"]
CF_TOKEN = os.environ["CF_API_TOKEN"]

async def _purge(payload: dict):
    async with httpx.AsyncClient() as c:
        await c.post(
            f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/purge_cache",
            headers={"Authorization": f"Bearer {CF_TOKEN}"},
            json=payload,
            timeout=10.0,
        )

async def purge_urls(urls: list[str]):        # 個別ページ（高上限）: 1リクエスト最大100URL
    await _purge({"files": urls})

async def purge_tags(tags: list[str]):        # 広範な無効化: Freeは5req/分・最大100タグ/req
    await _purge({"tags": tags})

async def purge_prefixes(prefixes: list[str]):  # パス配下一括: Freeは5req/分
    await _purge({"prefixes": prefixes})
```

各レスポンスに `Cache-Tag` ヘッダーを付与しておくと、タグパージでまとめて無効化できる（例: 個別名言に `quote-{id}`、一覧系ページに `quotes-list` / `author-{id}` / `category-{slug}`）。Cloudflare は visitor へ返す前に `Cache-Tag` ヘッダーを除去する（利用者からは見えない）。

> ⚠️ **`Cache-Tag` の制約**（[公式](https://developers.cloudflare.com/cache/how-to/purge-cache/purge-by-tags/)）:
> - **印字可能ASCIIのみ・スペース不可・大文字小文字は区別しない**（`Tag1` と `tag1` は同一）。→ タグ名は `author-123` / `category-slug` のような**短い小文字ASCII**に統一する。
> - レスポンスの `Cache-Tag` ヘッダー合計は **16KB まで（≈1,000タグ）**。API パージ時の1タグは最大 **1,024文字**。
> - 全パージ方式は **2025-04 以降 全プランで利用可能**（Free含む。タグ付け＝Cache-Tagヘッダーも Free で有効）。

### パージ対象の設計

**個別ページは URL パージ（即時・高上限）／一覧など広範な無効化は Tag パージ**で使い分ける。

| 更新操作 | URLパージ（`files`） | タグパージ（`tags`） |
|---|---|---|
| 名言 追加/編集/削除 | `/quotes/{id}`, 該当OG `/api/og?...` | `quotes-list`, `author-{id}`, `category-{slug}`, `ranking`, `home` |
| 著者 追加/編集 | `/authors/{slug}` | `authors-list`, `author-{id}` |
| カテゴリ 編集 | `/categories/{slug}` | `categories-list`, `category-{slug}` |
| 出典/登場人物 編集 | `/sources/{slug}`, `/characters/{slug}` | `sources-list`, `characters-list` |

- **URLパージの上限（Free）**: **800 URLs/秒・1リクエスト最大100URL**（旧記述「最大30URL/リクエスト」は誤りのため訂正）。100超は分割送信する。
- **Tag/Prefixパージの上限（Free）**: **5リクエスト/分・1リクエスト最大100オペレーション**（バケット25）。一括登録など短時間の大量更新はバッチ集約する。
- 広範に落としたい範囲がレート制限に収まらない場合は、短めの `s-maxage` で自然失効に委ねる（§3 のTTL設計）。
- 完全にリセットしたい場合は `purge_everything: true`（多用しない）。

## 6. SQLite 構成

### 6.1 レプリカ戦略（どちらか選択）

- **LiteFS**（推奨）
  - Fly.io 公式、マルチリージョン対応、リアルタイム同期
  - 書き込みはプライマリ、読み取りはローカルレプリカから
- **Litestream**
  - S3 / R2 にストリーミングバックアップ
  - 復旧用途、リアルタイムレプリカではない
  - 単一マシン構成なら十分

### 6.2 SQLite 設定

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;   -- 64MB
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

### 6.3 全文検索

**方式B（FTS5 + アプリ側bigram）で確定**（決定記録002）。`trigram` は2文字語がヒットしないため**不採用**。`unicode61` の FTS5 テーブルへ、アプリ側で2文字ずつ分割（bigram）した検索用テキストを格納する。

```sql
-- 検索用の派生テキスト（bigram化済み）を格納する列を FTS5 で索引化
CREATE VIRTUAL TABLE quotes_fts USING fts5(
    text_bigram,        -- 例: "人生は" → "人生 生は"（アプリ側で生成して INSERT）
    author_bigram,
    tokenize='unicode61'
);
```

```python
def bigrams(s: str) -> str:
    s = s.replace(" ", "")
    return " ".join(s[i:i+2] for i in range(len(s) - 1)) if len(s) >= 2 else s
```

検索時もクエリを `bigrams()` で分割して `MATCH` する。ランキングは FTS5 の `bm25()` ＋補助ソートで現状の重み付けを再現する（決定記録002）。1文字検索のみ `LIKE '%x%'` で補助。

## 7. Fly.io 構成

### 7.1 fly.toml の要点

```toml
app = "meigensyu"
primary_region = "nrt"

[build]
  dockerfile = "Dockerfile"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 1

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"

[mounts]
  source = "data"
  destination = "/data"
```

- SQLite は `/data` にマウントされたボリュームに置く
- 最初は 1 マシンで十分。負荷が上がったら LiteFS でスケール

### 7.2 Dockerfile 要点

- `python:3.12-slim` ベース
- `uvicorn --workers 2 --host 0.0.0.0 --port 8000`
- ヘルスチェック `/healthz` を用意

`uvicorn --workers 2` とアプリ内スケジューラは相性が悪い。同一ジョブが各workerで二重実行され得るため、ランキング/カテゴリ集計の定期再計算は Fly Machines cron、単発ジョブ、外部cron、またはロック付きの専用プロセスで実行する。

## 8. Cloudflare 設定

- **DNS**: A/AAAA レコードを Fly.io のIPに向ける（proxied = ON）
- **SSL/TLS**: Full (strict)
- **Cache Rules**（ダッシュボードから設定。**Cache Rules は last matching rule wins**）:
  1. 公開HTMLパス（`/`, `/quotes*`, `/authors*`, `/categories*`, `/characters*`, `/professions*`, `/sources*`, `/ranking*`, `/about` 等）→ **Cache eligibility: Eligible for cache（＝Cache Everything 相当）**、Edge TTL は **「Use cache-control header if present」**（オリジンの `s-maxage` を尊重）
  2. `/static/*` → Eligible for cache, Edge TTL 1 month
  3. `/admin/*`・`/search*`・`/random`（no-store採用時）・**いいね断片API**（例 `/quotes/*/likes`）→ **Bypass cache**（Cookie/動的のため必ず除外）
- ⚠️ **重要**: Cache Rules は複数マッチ時に最後の一致ルールが勝つ。旧Page Rulesの「先勝ち」と逆なので、Bypassルールは公開HTMLのEligibleルールより**後（下）**に配置する。
- ⚠️ **重要**: **Cloudflare はデフォルトで HTML/JSON をキャッシュしない**（拡張子ベースでCSS/JS/画像等のみキャッシュ）。オリジンが `Cache-Control: public, s-maxage=...` を返しても、**Cache Rule で明示的に「Eligible for cache」を指定しない限り公開HTMLはキャッシュされない**。SSRのHTMLをエッジキャッシュする本構成では上記1の公開HTML Cache Rule が必須。
  - 参照: [Default cache behavior](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)
  - 参照: [Cache Rules order](https://developers.cloudflare.com/cache/how-to/cache-rules/order/)
- （Page Rules は廃止方向のため **Cache Rules に統一**。旧 Page Rule 相当は上記③でカバー）
- **WAF**:
  - Bot Fight Mode ON
  - Rate limiting: `/search` は debounce/最小文字数とセットで閾値を決める（例: 60req/min固定だとインクリメンタル検索で正規ユーザーに当たり得る）
- **Firewall Rules**:
  - `/admin/*` は特定IPのみ許可（可能なら）
- **Origin protection**:
  - Authenticated Origin Pullsを第一候補に、オリジン直撃を拒否する。採用できない場合もHostヘッダ検証またはCloudflare IPレンジ検証を入れる

## 9. デプロイ・運用

- CI/CD: GitHub Actions → `flyctl deploy`
- マイグレーション: `alembic` で管理、デプロイ時に自動実行
- ログ: Fly.io の標準ログ + Cloudflare Analytics
- 監視: Fly.io メトリクス + UptimeRobot などで外形監視
- バックアップ: Litestream で日次バックアップ（LiteFS 使用時も併用推奨）

## 10. 環境変数

| 変数名 | 用途 |
|---|---|
| `DATABASE_URL` | SQLite ファイルパス（例: `sqlite:///data/app.db`） |
| `CF_ZONE_ID` | Cloudflare Zone ID |
| `CF_API_TOKEN` | Cloudflare API Token（`Cache Purge` 権限のみ） |
| `ADMIN_USER` / `ADMIN_PASS` | Admin 認証 |
| `SECRET_KEY` | セッション署名鍵 |
| `RANKING_IP_HASH_SALT` | 匿名いいねの `ip_hash` 生成 |
| `NEXT_PUBLIC_GA_ID` | GA4（採用時） |
| `NEXT_PUBLIC_ADSENSE_PUBLISHER_ID` | AdSense（採用時） |
| `ORIGIN_PROTECTION_*` | AOP/Host/CF IP検証など、方式確定後に定義 |

## 11. セキュリティ

- Admin: Basic認証 or セッション + IP制限
- CSRF トークン（Admin フォーム）
- `SECURE`, `HTTPONLY`, `SameSite=Lax` の Cookie
- CSP ヘッダー（インラインJS禁止）
- HTMX利用時は `hx-on`、イベントフィルタ、`js:`/`javascript:` 値を原則禁止し、`unsafe-eval` なしのCSPと整合させる。必要な場合は hx-csp 等を検討する
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

## 12. 段階的リリース手順

1. Fly.io に新環境をデプロイ（別サブドメイン `new.meigensyu.com`）
2. `new.meigensyu.com` は `noindex` / robots deny を有効化
3. データ移行（旧DB → 新SQLite）
4. 動作確認・キャッシュヘッダー検証（`curl -I` で確認）
5. Cloudflare を経由させて動作確認
6. DNS切替直前に差分再移行、または旧環境のAdmin/いいね書き込みを短時間凍結
7. DNS を切り替え（TTL を事前に短くしておく）
8. 旧環境は 1〜2週間維持し、問題なければ廃止

## 13. 期待効果

- **TTFB 短縮**: エッジキャッシュヒット時は 20〜50ms
- **オリジン負荷削減**: 公開ページはエッジで返す。90%以上削減を狙うには、いいね数取得を毎PV非キャッシュにしない設計（D9）が必要
- **Fly.io 帯域コスト削減**
- **SEO 改善**: Core Web Vitals の LCP/TTFB 向上
- **DDoS / Bot 対策**: Cloudflare のレイヤーで自動対応

## 14. 検収チェックリスト

- [ ] `/quotes/q1342` に `Cache-Control: public, s-maxage=86400...` が付いている
- [ ] `/search?q=test` に `Cache-Control: private, no-store` が付いている
- [ ] `/admin/` に `Cache-Control: private, no-store` が付いている
- [ ] `/random` がD13で決めた方式どおりにキャッシュ固定化しない
- [ ] `curl -I` で 2回目に `cf-cache-status: HIT` が返る（公開ページ）
- [ ] Admin から名言更新後、該当URLがパージされ最新内容が返る
- [ ] SQLite が WAL モードで動いている
- [ ] `/healthz` が 200 を返す
- [ ] OG画像 `/api/og?type=quote&id=...` がエッジキャッシュされる
- [ ] Cloudflareを経由しないオリジン直撃が拒否される
- [ ] `new.` サブドメインがインデックス不可になっている
