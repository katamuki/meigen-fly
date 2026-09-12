# URL契約表

> [ADR 008](decisions/008-url-compatibility.md) が求める「slug/`qXXXX`の扱い、`page/1`の正規化、主要リダイレクトを一覧にした簡単なURL契約表」。
> リリース前チェックの正本として使う。実装は `app/services/redirects.py`、`app/routers/public.py`、`app/middleware.py`。
> 作成日: 2026-09-10（フェーズ3-E）

## 1. ホストとcanonical

| 項目 | 値 |
|---|---|
| 公開オリジン / canonical host | `https://www.meigensyu.com/` |
| alias | `https://meigensyu.com/` → path・queryを保って`www`へ1 hop 301（Cloudflare側で設定。フェーズ5） |
| それ以外のHost | リダイレクトせず400（`ExactHostMiddleware`、ADR 013） |
| 末尾スラッシュ | 内部リンクは末尾スラッシュなし。`/` 以外の末尾スラッシュ付きURLは301で除去形へ送る（下記） |

canonicalの絶対URLは環境変数 `PUBLIC_ORIGIN` から組み立てる（`app/config.py`）。テンプレートの `site_origin` がその値。

末尾スラッシュの除去は、旧Next.jsの既定（308で除去）を移植したもの（`app/services/redirects.py`）。

- GET/HEADで `/` 以外の末尾スラッシュ付きパスは、末尾の`/`を除いた形へ**301**で送る。Locationは相対パスで、queryは維持する。
- 除去した形が§4の旧URL規則に当たる場合は、その行き先へ直接送る（`/tools/` → `/`、`/quotes/page/1/` → `/quotes`、`/search/quotations/?q=…` → `/search?q=…`）。queryの扱いは各規則に従う。
- DBを引いてリダイレクトする形（`/quotes/{4桁数字}/`、slugを持つ名言の `/quotes/q{id}/`）は、除去 → 解決の**2 hop**になる。旧サイトも「308 → リダイレクト」の2 hopだったため許容する。
- GET/HEAD以外はStarletteの `redirect_slashes`（307）のまま。

## 2. 名言のURL解決（slug / qid）

| 入力 | 応答 |
|---|---|
| `/quotes/{slug}`（公開） | 200。canonicalは自身 |
| `/quotes/q{id}`（slugあり） | 301 → `/quotes/{slug}` |
| `/quotes/q{id}`（slugなし） | 200。canonicalは `/quotes/q{id}` |
| `/quotes/{4桁数字}` | 301 → その名言のcanonical（`/quotes/{slug}` または `/quotes/q{id}`） |
| `q{id}` の非厳密形（`Q1`・`q01`・`q0`・空） | slugとして解決を試み、無ければ404 |
| 非公開（`enable = 0`）・存在しないID | 404 |

- `q{id}` の厳密parseは `app/services/quotes.py:parse_qid`（先頭が`1-9`の十進数のみ）。
- canonicalパスの組み立ては `quote_path()` 一箇所。sitemap・OG画像URL・リダイレクト先はすべてこれを使う。

## 3. ページングの正規化

- パス型ページング: `/quotes/page/{n}`、`/quotes/latest/page/{n}`、`/authors/{slug}/page/{n}`、`/categories/{slug}/page/{n}`、`/sources/{slug}/page/{n}`、`/characters/{slug}/page/{n}`
- クエリ型ページング: `/authors?page={n}`、`/sources?page={n}`、`/characters?page={n}`、`/authors/places/{slug}?page={n}`、`/professions/{slug}/quotes?page={n}`
- **`/page/1` で終わるパスは常に301でその接頭辞へ正規化する**（queryは維持）。旧サイトの5本の`page/1`ルールを1つの規則にまとめたもので、旧サイトに無かった`/sources/{slug}/page/1`も同じ扱いになる。
- `page` が2未満・非数値・範囲外のパス型ページは404（`_parse_paginated_page`）。
- canonicalは常に「現在のパス＋内容を決めるquery（filterと`page`）」。したがって `/quotes/page/2` は自己canonical、`/authors?page=1` は `/authors`。

例外的に1つのcanonicalへまとめているもの:

| URL | canonical | 理由 |
|---|---|---|
| `/ranking/quotes` | `/ranking` | 同一内容の入口が2つあるため |
| `/professions/{slug}/quotes`（1ページ目） | `/professions/{slug}` | 内部リンクは `/professions/{slug}` を使う |

## 4. 静的リダイレクト（旧`next.config.js` 23本）

すべて301。`:path*` は「その接頭辞自身と配下すべて」を意味する。**行き先が固定のページであるリダイレクトはqueryを引き継がない**（旧Next.jsは引き継いだが、`/` や一覧へ運んでも意味がないため）。

| # | 旧URL | 新URL |
|---|---|---|
| 1 | `/tools/:path*` | `/` |
| 2 | `/m/:path*` | `/` |
| 3 | `/countries/:path*` | `/` |
| 4 | `/search/quotations?q=…` | `/search?q=…`（`p` は捨てる。`q` が無ければリダイレクトせず404） |
| 5 | `/search/quotations/?q=…` | 同上 |
| 6 | `/jobs/:path*` | `/professions` |
| 7 | `/sources/view/:path*` | `/sources` |
| 8 | `/quotations/latest/:path*` | `/quotes/latest` |
| 9 | `/quotations/ranking/:path*` | `/ranking` |
| 10 | `/quotations/index/:path*` | `/quotes` |
| 11 | `/quotes/{4桁数字}` | その名言のcanonical（§2） |
| 12 | `/tags/view/1104/:path*` | `/categories/friendship` |
| 13 | `/tags/view/1115/:path*` | `/categories/youth` |
| 14 | `/tags/view/1111/:path*` | `/categories/money` |
| 15 | `/tags/view/1130/:path*` | `/categories/hope` |
| 16 | `/authors/view/1976/:path*` | `/authors/mushanokoji-saneatsu` |
| 17 | `/authors/view/:path*` | `/authors` |
| 18 | `/tags/view/:path*` | `/categories` |
| 19 | `/categories/:slug/page/1` | `/categories/:slug` |
| 20 | `/authors/:slug/page/1` | `/authors/:slug` |
| 21 | `/characters/:slug/page/1` | `/characters/:slug` |
| 22 | `/quotes/page/1` | `/quotes` |
| 23 | `/quotes/latest/page/1` | `/quotes/latest` |

評価順は「接頭辞リダイレクト → `/search/quotations` → `/page/1`」。末尾スラッシュ付きのパスは、スラッシュを除いた形でこの順に評価する（§1）。12〜15は18より先に置く。接頭辞を先に見るのは、`/quotations/latest/page/1` が `/quotations/latest` を経由する2 hopにならないようにするため。

## 5. 動的リダイレクト

| 旧URL | 応答 |
|---|---|
| `/quotations/view/{id}.html`（公開名言） | 301 → その名言のcanonical |
| `/quotations/view/{id}.html`（非公開・存在しない・非数値） | 404 |
| `/quotes/{4桁数字}`（公開名言） | 301 → その名言のcanonical |
| `/quotes/{4桁数字}`（該当なし） | 404 |

旧実装との違い（いずれも1 hopで200または404に到達するための変更）:

- 旧middlewareはslugが無いIDを一律 `/quotes/q{id}` へ301していた（存在しないIDは301の先で404）。新実装は先に公開名言の有無を確認し、無ければ直接404を返す。
- 旧`/quotes/{4桁}` は静的に `/quotes/q{id}` へ301していたため、slugがある名言では2 hopになっていた。新実装はDBを引いて最終canonicalへ1 hopで送る。
- 旧middlewareは `id <= 0` を `/404` へ301していた。新実装は404を直接返す。

## 6. リダイレクトの安全性とキャッシュ

- `//` または `/\` で始まるパスはどのリダイレクト規則にも掛けず、そのまま routing へ渡す（結果は404）。`//evil.example/page/1` から `//evil.example` という protocol-relative なLocationを組み立てないため。
- **301・308**の恒久リダイレクト（末尾スラッシュの除去を含む）は `public, s-maxage=86400, max-age=3600`（`app/middleware.py`）。
- `/search`・`/search/` 配下は他の規則より先に `private, no-store` になるため、`/search/quotations` の301はキャッシュされない。

## 7. sitemap と robots

- `/sitemap.xml`: 一覧ページ（`/`、`/quotes`、`/quotes/latest`、`/random`、`/ranking`、`/authors`、`/categories`、`/sources`、`/characters`、`/professions`）＋ 公開quotes・authors・sources・categories。lastmodは `updated_at` のUTC日付。対象4表は[inventory-4 §9.8](database/inventory-4-new-db-design.md)の通りで、characters/professionsの詳細は旧サイトと同じく含めない。
- `/robots.txt`: `Disallow: /admin`、`/api/`、`/search`。`/search` はnoindexであり、断片 `/search/partial` はmetaを持てないためパスごと除外する。`Sitemap:` は `PUBLIC_ORIGIN` から組み立てる。

## 8. OG画像

| URL | 内容 |
|---|---|
| `/quotes/{slug または q{id}}/og.png` | 名言カード（1200×630 PNG） |
| `/authors/{slug}/og.png` | 著者カード |
| `/static/og-default.{hash}.png` | 個別カードを持たないページの共通OG画像 |

識別子は詳細ページのcanonicalと同じものを使う。対象が無い・非公開なら404 + `private, no-store`、描画だけが失敗したら共通画像を `private, no-store` で返す（ADR 018）。

## 9. リリース前チェック

1. 上表の静的23本と動的2種が、最終canonicalへ**1 hop**で到達する。`curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' URL` で301と行き先を確認し、行き先を同じコマンドで叩いて200になること。`curl -I`（HEAD）は使わない。routeはGETのみ受け付けるため、ページとDBを引くリダイレクトが405になる。
2. sitemapとSearch Console上位URLが200または301で同等コンテンツへ到達し、self-canonicalが正しい。
3. `meigensyu.com` → `www.meigensyu.com` のhost正規化が効く。`/quotes/` が301と `Location: /quotes` を返す（末尾スラッシュの除去、§1）。
4. `/robots.txt` の `Sitemap:` が本番オリジンを指す。
5. `/quotes/{slug}/og.png` と `/authors/{slug}/og.png` が1200×630のPNGを返し、Cloudflareで2回目がHITする。

自動比較fixtureは作らない。確認はスクリプトまたは手動`curl`でよい（ADR 008）。
