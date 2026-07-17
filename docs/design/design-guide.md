# 名言集.com デザインガイド（D8・提案B「墨×藍×宵」）

> 本ガイドは D8（デザイン刷新）の**正本**。実装時のトークン・コンポーネント・制約はここを参照する。
> 実物は [`proposal-b/`](proposal-b/) の `tokens.css` / `components.css` / `templates/`。矛盾があれば実ファイルを優先し、本ガイドを追随修正する。
> 決定の経緯・不採用案は [ADR 017](../decisions/017-design-system-d8.md)、作業経緯は [`README.md`](README.md)。
>
> - 確定日: 2026-07-17
> - 対象: FastAPI + Jinja2 + HTMX のSSRサイト（[project-plan.md](../project-plan.md) §6）

---

## 1. コンセプト — 墨 × 藍 × 宵

日本語の名言（引用文）を主役に据えた、**書画的で静かな読み物**の佇まい。装飾より可読性・情報密度・表示速度を優先する（SEO流入・閲覧主体のサイト）。

- **墨（すみ）**: Light テーマの基調。和紙色の地に墨色の文字。
- **藍（あい）**: Light のアクセント。リンク・いいね・強調・罫線に使う落ち着いた藍。
- **宵（よい）**: Dark テーマ。夜の深い地色に、アクセントは**金**。

Light と Dark は**同一構造・同一タイポ・同一余白**で、色トークンだけが切り替わる。提案A（朱）との違いは Light のアクセント色のみ（朱→藍）で、Dark（宵×金）は共通。

## 2. デザイントークン（`tokens.css`）の使い方

すべての見た目は CSS カスタムプロパティに集約する。**コンポーネント側に色の直値を書かない**（`components.css` は `var(--*)` 参照のみ）。

| 種別 | 主なトークン | 用途 |
|---|---|---|
| 面 | `--bg` `--surface` | ページ地 / カード・ヘッダー面 |
| 文字 | `--ink` `--muted` `--subtle` | 本文 / 補助 / さらに弱い補助 |
| アクセント | `--accent` `--accent-ink` `--accent-soft` `--accent-wash` | リンク・いいね・強調（Light=藍 / Dark=金） |
| 罫線・チップ | `--line` `--chip-bg` `--chip-border` | 区切り線 / チップ地・枠 |
| タイポ | `--font-serif` `--font-sans` `--fs-*` `--lh-*` | 見出し・引用は明朝、UIはsans |
| 余白 | `--sp-1`〜`--sp-16`（4pxグリッド） | 余白は必ずこのスケールで |
| 角丸 | `--r-btn` `--r-card` `--r-pill` | ボタン / カード / ピル |
| レイアウト | `--container-text`(720px) `--container-wide`(1080px) `--gutter` | 本文幅 / 広幅 / モバイル余白 |

**原則**: 新しい余白・色が必要なら、まずトークンで表現できないか確認する。テンプレート内に `style` 属性は書かず、必要な余白は `components.css` のユーティリティ（`.mg-mt-*` `.mg-mb-*` `.mg-page-body` など、いずれも `--sp-*` 参照）を使う（[ADR 016](../decisions/016-csp-htmx-rules.md)・[ADR 017](../decisions/017-design-system-d8.md)）。

## 3. ダークモード適用方式

トークンの切替は**2経路**。テンプレート・コンポーネントは色トークン参照なので、どちらでも自動追従する。

1. **OS追従**: `@media (prefers-color-scheme: dark)` が、`data-theme="light"` が明示されていない限り Dark トークンを適用（`:root:not([data-theme="light"])`）。
2. **手動切替**: `<html data-theme="dark|light">` を最優先。ヘッダーの切替ボタン＋外部静的JS `static/js/theme.js` が付与し、`localStorage` に保存する。

`color-scheme` も各テーマで宣言し、フォームコントロール等のネイティブUIを一致させる。

### `theme.js`（手動切替）の仕様
CSP `script-src 'self'`（[ADR 016](../decisions/016-csp-htmx-rules.md)）に従い**外部静的JSのみ**、インラインscript禁止。`base.html` の `<head>` で **defer なし同期読込**し、初回描画前に `data-theme` を復元して FOUC を防ぐ。

1. 読込直後: `localStorage.getItem('theme')` が `'dark'`/`'light'` なら `document.documentElement` に `data-theme` を復元。未設定は何もせず OS追従に委ねる。
2. `DOMContentLoaded` 後: `.mg-theme-toggle` に `click` リスナ（`addEventListener`）を付け、実効テーマを反転→`data-theme` 更新→`localStorage` へ保存。
3. 実効テーマ判定: `data-theme` 属性優先、無ければ `matchMedia('(prefers-color-scheme: dark)')`。

## 4. コンポーネント一覧（`components.css`）

すべて `mg-` 接頭辞。代表的なもの:

- **ナビ**: `mg-header` / `mg-nav`（PC）/ `mg-tabbar`（モバイル下部固定）/ `mg-footer` / `mg-breadcrumb` / `mg-logo`
- **検索**: `mg-search`（ヘッダー）/ `mg-search--hero`（検索ページ）/ `mg-search__input`
- **名言カード**: `mg-quote-card`（注目）/ `--list`（一覧）/ `--compact`（新着）/ `--gold`（ランキング1位）。本文は `mg-quote`（明朝）
- **いいね**: `mg-like`（素）/ `--pill`（カード）/ `--solid`（名言個別の主役）。`<form>` ラッパは `mg-like-form`（`display:contents`）
- **著者**: `mg-author` / `mg-author-card` / `mg-author-profile` / `mg-avatar`（`--lg`/`--sm`）/ `mg-author-chip`
- **チップ**: `mg-chip`（`--accent` / `--sort-active` / `mg-chips--center`）/ `mg-chips`
- **ランキング**: `mg-rank` / `mg-rank-row` / `mg-rank-num`（`--1`）/ `mg-medal`（`--1`〜`--3`）
- **その他**: `mg-hero`・`mg-hero-band`（名言主役）/ `mg-pagination` `mg-page`（**ページネーション**。ユーティリティの `mg-page-body` とは別）/ `mg-cat-card` / `mg-section-head`（`--end`）/ `mg-grid-2` `mg-grid-3`
- **ユーティリティ**（余白置換）: `mg-page-body`（一覧本文の上下余白）/ `mg-mt-3|4|6|8|12` / `mg-mb-4|6|8` / `mg-my-4` / `mg-pb-12` / `mg-block`。すべて `--sp-*` 参照

Light/Dark の全コンポーネント一覧は `proposal-b/preview.html`、実データ入りの複合確認は `proposal-b/render-check.html` / `render-check-dark.html`。

## 5. ページ構成（`templates/`）

`base.html` を継承する Jinja2 テンプレート。

| テンプレート | ページ | 要点 |
|---|---|---|
| `base.html` | 共通レイアウト | head/OGP/CSS/HTMX/`theme.js`、`{% block meta_robots %}`（検索noindex等） |
| `index.html` | トップ | 注目名言ヒーロー＋人気ランキング抜粋＋カテゴリ＋新着（2カラム） |
| `quote_detail.html` | 名言個別（最重要） | 引用主役・著者カード・いいね（solid）・共有・関連・OG動的画像 |
| `quote_list.html` | 名言一覧 | ソート＋2カラムグリッド＋ページング |
| `author_detail.html` | 著者詳細 | プロフィール＋その著者の名言一覧 |
| `category_list.html` | カテゴリ一覧 | 2階層（大分類カードに小分類チップ） |
| `ranking.html` | ランキング | タブ＋上位3メダルカード＋4位以降リスト |
| `search.html` | 検索 | HTMXインクリメンタル検索（`noindex`） |
| `partials/` | 部品 | header / footer / tabbar / quote_card / like_button / pagination / search_results |

- **URL**: 名言個別は `/quotes/{slug または q{id}}`、内部リンクは**末尾スラッシュなし**（[ADR 008](../decisions/008-url-compatibility.md) 互換）。
- **レスポンシブ**: モバイルファースト。`<=640px` で PCナビを畳み下部タブバーを表示、グリッドを1カラム化。モバイル実寸（390px）検証は iframe ラッパーで行う（ヘッドレスChromeは最小幅約500pxのため）。

## 6. 技術制約（デザインに影響するもの）

- **CSP / インラインコード**（[ADR 016](../decisions/016-csp-htmx-rules.md)）: CSSは外部ファイルのみ。テンプレートに `style` 属性を置かない（余白はユーティリティクラス）。実行可能なインラインJS・DOM event属性・`javascript:` は使わず外部静的JSへ。
- **HTMX**（[ADR 016](../decisions/016-csp-htmx-rules.md)）: バージョン固定で `/static/` 配信。`allowEval=false` / `allowScriptTags=false` / `selfRequestsOnly=true`。イベントは外部JSの `addEventListener`。
  - **検索**: `hx-get="/search/partial" hx-trigger="keyup changed delay:500ms, search"` で `#search-results` を差し替え。JS無効時は `/search` への通常GETで成立（[ADR 015](../decisions/015-search-rate-limits.md)）。
  - **いいね**: `<form method="post" action="/api/likes/{id}">` を `hx-post` + `hx-swap="outerHTML"` でフォーム自身を差し替え。JS無効時はフォームの通常POSTで成立（`client_uuid` なしの best-effort）。`client_uuid` は外部JSが `htmx:configRequest` で付与（[ADR 006](../decisions/006-like-count-cache-strategy.md)）。
- **フォント**: 日本語Webフォントは重いため、**system-ui系スタックを前提**（`--font-sans` / `--font-serif`）。見出し・引用は端末搭載の明朝（`Hiragino Mincho ProN` / `Yu Mincho` 等）にフォールバック。`Noto Serif JP` はスタック末尾に置くのみで、本体では読み込まない。
- **アニメーション**: Cloudflareエッジキャッシュ前提の静的HTML。凝った動きより表示速度・可読性を優先。
- **OG画像**: 名言個別はサイトの表示テーマとは切り離し、Light（和紙×墨×藍）を固定デザインとして `/quotes/{slug または q{id}}/og.png` を生成する（`proposal-b/og/og.html` を 1200×630 に画像化）。文字数閾値・80字超の扱い・本番コンテナへの `Noto Serif JP` 導入は D8では決めず **D5（OG画像生成）**で扱う（[project-plan.md](../project-plan.md) §7）。
