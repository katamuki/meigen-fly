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
- **DB**: SQLite。書き込みは Admin のみ、読み取り中心
- **CDN**: Cloudflare（無料プランで十分）
- **ホスティング**: Fly.io（東京リージョン `nrt` 推奨）

## 2. キャッシュ戦略の基本方針

- **公開ページはすべて Cloudflare のエッジキャッシュを効かせる**
- **検索ページと Admin ページは絶対にキャッシュしない**
- **更新時は該当URLだけ Cloudflare API でパージする**
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
| **`/search`** | `private, no-store` | キャッシュしない |
| **`/admin/*`** | `private, no-store` | キャッシュしない |
| `/static/*`（CSS/JS/画像） | `public, max-age=31536000, immutable` | 1年（ファイル名にハッシュ付与） |

## 4. FastAPI 実装ポイント

### 4.1 レスポンスヘッダーの一元管理

パスごとの Cache-Control を Middleware または依存関数で一元管理する。個別ルートに直書きしない。

```python
CACHE_RULES = {
    "/": "public, s-maxage=300, max-age=60",
    "/quotes": "public, s-maxage=600, max-age=60",
    # ...
}

@app.middleware("http")
async def cache_headers(request, call_next):
    response = await call_next(request)
    # /admin, /search は必ず no-store
    if request.url.path.startswith(("/admin", "/search")):
        response.headers["Cache-Control"] = "private, no-store"
        return response
    # ルールマッチ
    for prefix, value in CACHE_RULES.items():
        if request.url.path.startswith(prefix):
            response.headers.setdefault("Cache-Control", value)
            break
    return response
```

### 4.2 ETag / 304 対応

個別名言・著者ページは `updated_at` から ETag を生成し、`If-None-Match` 一致時は 304 を返す。Cloudflare も ETag を尊重するため転送量削減に有効。

### 4.3 Vary ヘッダー

- 言語切替やABテストを行わないなら `Vary` は付けない（キャッシュヒット率が下がる）
- Cookie でセッションを持つのは Admin のみに限定する（公開ページに Cookie を付けない）

### 4.4 検索ページ

- `GET /search?q=...` のパターン
- `no-store` にする。もしくは、頻出クエリだけアプリ内 TTLCache で軽く受ける
- SQLite の FTS5 で全文検索（`quotes_fts` 仮想テーブル）

### 4.5 Admin ページ

- `/admin/*` は Basic認証 or セッション認証
- Cookie 必須 → キャッシュ不可
- CSRF 対策必須

## 5. キャッシュパージ

Admin から更新した際、Cloudflare API で該当 URL のみパージする。

```python
import httpx, os

CF_ZONE = os.environ["CF_ZONE_ID"]
CF_TOKEN = os.environ["CF_API_TOKEN"]

async def purge(urls: list[str]):
    async with httpx.AsyncClient() as c:
        await c.post(
            f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/purge_cache",
            headers={"Authorization": f"Bearer {CF_TOKEN}"},
            json={"files": urls},
            timeout=10.0,
        )
```

### パージ対象の設計

| 更新操作 | パージすべきURL |
|---|---|
| 名言 追加/編集/削除 | `/quotes/{id}`, `/quotes`, `/authors/{slug}`, `/categories/{slug}`, `/`, `/ranking` |
| 著者 追加/編集 | `/authors/{slug}`, `/authors` |
| カテゴリ 編集 | `/categories/{slug}`, `/categories` |
| 出典/登場人物 編集 | `/sources/*`, `/characters/*` |

- 一括操作時はまとめて1リクエストにする（Cloudflareは最大30URL/リクエスト）
- 完全にリセットしたい場合は `purge_everything: true`（多用しない）

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

```sql
CREATE VIRTUAL TABLE quotes_fts USING fts5(
    text, author, tokenize='trigram'
);
```

日本語のため `trigram` トークナイザ推奨（`icu` があればより良い）。

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

## 8. Cloudflare 設定

- **DNS**: A/AAAA レコードを Fly.io のIPに向ける（proxied = ON）
- **SSL/TLS**: Full (strict)
- **Cache Rules**（ダッシュボードから設定）:
  - `/admin/*`, `/search*` → Bypass cache
  - それ以外 → Standard cache（オリジンの Cache-Control に従う）
- **Page Rules**（必要なら）:
  - `*.meigensyu.com/static/*` → Cache Everything, Edge TTL 1 month
- **WAF**:
  - Bot Fight Mode ON
  - Rate limiting: `/search` に 60req/min など
- **Firewall Rules**:
  - `/admin/*` は特定IPのみ許可（可能なら）

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

## 11. セキュリティ

- Admin: Basic認証 or セッション + IP制限
- CSRF トークン（Admin フォーム）
- `SECURE`, `HTTPONLY`, `SameSite=Lax` の Cookie
- CSP ヘッダー（インラインJS禁止）
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

## 12. 段階的リリース手順

1. Fly.io に新環境をデプロイ（別サブドメイン `new.meigensyu.com`）
2. データ移行（旧DB → 新SQLite）
3. 動作確認・キャッシュヘッダー検証（`curl -I` で確認）
4. Cloudflare を経由させて動作確認
5. DNS を切り替え（TTL を事前に短くしておく）
6. 旧環境は 1〜2週間維持し、問題なければ廃止

## 13. 期待効果

- **TTFB 短縮**: エッジキャッシュヒット時は 20〜50ms
- **オリジン負荷 90%以上削減**: 公開ページはほぼエッジで返る
- **Fly.io 帯域コスト削減**
- **SEO 改善**: Core Web Vitals の LCP/TTFB 向上
- **DDoS / Bot 対策**: Cloudflare のレイヤーで自動対応

## 14. 検収チェックリスト

- [ ] `/quotes/q1342` に `Cache-Control: public, s-maxage=86400...` が付いている
- [ ] `/search?q=test` に `Cache-Control: private, no-store` が付いている
- [ ] `/admin/` に `Cache-Control: private, no-store` が付いている
- [ ] `curl -I` で 2回目に `cf-cache-status: HIT` が返る（公開ページ）
- [ ] Admin から名言更新後、該当URLがパージされ最新内容が返る
- [ ] SQLite が WAL モードで動いている
- [ ] `/healthz` が 200 を返す
- [ ] OG画像 `/api/og?type=quote&id=...` がエッジキャッシュされる

