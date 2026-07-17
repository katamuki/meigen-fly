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
  render-check.html   静的レンダー確認用（本番不要）
  preview.html        Light/Dark コンポーネント一覧（本番不要）
```

## テーマはトークンだけで切替
テンプレート・コンポーネントは `var(--accent)` 参照なので**テーマ非依存**。
`proposals/a/tokens.css`（朱）に差し替えれば同じテンプレートがA案になる。

## HTMX / JS方針（CSP対応・インラインscript禁止）
- **検索**：`hx-get="/search/partial/" hx-trigger="keyup changed delay:200ms"` で `#search-results` を差し替え。JS無効時は通常GETで `/search/` に遷移して成立。
- **いいね**：`hx-post=".../like/" hx-swap="outerHTML"` でボタン自身を差し替え。JS無効時は通常POST。
- **ハイライト**：サーバ側で結果に `<mark>` を挿入（`highlighted|safe`）。
- **ページング/ソート/テーマ**：すべて通常リンク・`aria-current`。JS不要。
- OS のダークは `prefers-color-scheme`、手動は `<html data-theme>` で。

## サーバ側で用意が必要なもの
- Jinjaフィルタ `comma`（3桁区切り）、ヘルパ `static()` / `absolute_url()`。
- 名言個別 OG画像：`/quotes/<id>/og.png` を宵ベースで動的生成（別途 og テンプレートを用意予定）。

## A との差分
Light の `--accent` のみ（朱→藍）。Dark(宵) と構造・タイポ・余白は A と共通。
