# 提案B「墨（藍）× 宵」（確定）

名言集.com デザイン刷新 — Light=墨/accent 藍、Dark=宵/accent 金。

## 構成
```
b/
  tokens.css        デザイントークン（色/タイポ/余白/角丸/レイアウト、Light藍+Dark金）
  components.css     コンポーネント（色の直値なし・tokens.css 参照のみ）
  templates/         Jinja2 + HTMX 本番テンプレート
    base.html            ベース（head/OGP/CSS読込/HTMX）
    index.html           トップ（注目名言＋人気＋カテゴリ＋新着）
    quote_detail.html    名言個別（最重要・OG動的画像・いいね・共有・関連）
    quote_list.html      名言一覧（ソート＋グリッド＋ページング）
    author_detail.html   著者詳細（プロフィール＋その著者の名言）
    category_list.html   カテゴリ一覧（2階層）
    ranking.html         ランキング（タブ＋上位3メダル＋順位リスト）
    search.html          検索ページ（インクリメンタル）
    partials/
      header.html · footer.html · tabbar.html
      quote_card.html · like_button.html · pagination.html
      search_results.html   ← HTMX差し替えターゲット
  og/                OG画像の視覚仕様・実寸プレビュー（本番HTMLテンプレートではない）
  render-check.html   静的レンダー確認用（本番不要）
  preview.html        Light/Dark コンポーネント一覧（本番不要）
```

## テーマはトークンだけで切替
テンプレート・コンポーネントは `var(--accent)` 参照なので**テーマ非依存**。
`proposals/a/tokens.css`（朱）に差し替えれば同じテンプレートがA案になる。

## URL（ADR 008 互換）
- 名言個別は **`/quotes/{slug または q{id}}`**（`quote.slug or 'q' ~ quote.id`）。数値 id 直リンクは使わない。
- 一覧・ナビ・カテゴリ等の内部リンクは**末尾スラッシュなし**（現行契約）。
- OG画像は canonical と同一の識別子で `/quotes/{slug または q{id}}/og.png`。

## HTMX / JS方針（CSP対応・インラインscript禁止）
- **検索**：`hx-get="/search/partial" hx-trigger="keyup changed delay:500ms"`（ADR 015）で `#search-results` を差し替え。JS無効時は通常GETで `/search` に遷移して成立。
- **いいね**：`<form method="post" action="/api/likes/{id}">`（ADR 006 経路）を `hx-post` + `hx-swap="outerHTML"` でフォーム自身を差し替え。JS無効時はフォームの通常POSTで成立（client_uuid なしのbest-effort）。`client_uuid` は外部JSが `htmx:configRequest` で付与する（`js:`付き hx-vals は使わない）。
- **ハイライト**：サーバ側で結果に `<mark>` を挿入（`highlighted|safe`）。
- **ページング/ソート**：すべて通常リンク・`aria-current`。JS不要。
- **テーマ**：OS追従は `prefers-color-scheme`。手動切替はヘッダーのボタン＋外部JS `theme.js`（下記）。

## テーマ切替（手動）— `static/js/theme.js` の仕様
D8決定は「OS追従＋手動切替の両対応」。CSP `script-src 'self'` に従い**外部静的JSのみ**、インラインscript禁止。`base.html` の `<head>` で **defer なし同期読込**し、初回描画前に `data-theme` を復元してFOUCを防ぐ。

必要な挙動（実装は約15行で足りる）:
1. 読込直後（DOM構築前）：`localStorage.getItem('theme')` が `'dark'` / `'light'` なら `document.documentElement.setAttribute('data-theme', v)` で復元。未設定なら何もせずOS追従に委ねる。
2. `DOMContentLoaded` 後：`.mg-theme-toggle` に `click` リスナ（`addEventListener`。ADR 016）を付け、現在の実効テーマを反転→`data-theme` を更新→`localStorage.setItem('theme', ...)` で保存。
3. 実効テーマの判定は `data-theme` 属性優先、無ければ `matchMedia('(prefers-color-scheme: dark)')`。

## サーバ側で用意が必要なもの
- Jinjaフィルタ `comma`（3桁区切り）、ヘルパ `static()` / `absolute_url()`。
- 名言レコードの `slug`（nullable。未設定時は `q{id}` にフォールバック）。
- いいねエンドポイント `POST /api/likes/{quote_id}`（ADR 006。`private, no-store` + Cloudflare Bypass）。
- 検索フラグメント `GET /search/partial`（`HX-Request` 応答。`Vary: HX-Request`）。
- 静的JS `static/js/theme.js`（上記仕様）、`static/js/htmx.min.js`。
- OG画像：サイトの表示テーマとは切り離し、Light（和紙×墨×藍）を固定デザインとする。名言は `/quotes/{slug または q{id}}/og.png`、著者は `/authors/{slug}/og.png` でPillowによりオンデマンド生成する。`og/og.html` は画像化用の本番テンプレートではなく、Pillow実装の視覚仕様。文字量とキャッシュの詳細はADR 018。

## A との差分
Light の `--accent` のみ（朱→藍）。Dark(宵) と構造・タイポ・余白は A と共通。
