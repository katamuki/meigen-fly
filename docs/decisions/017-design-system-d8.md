# アーキテクチャ決定記録: デザイン刷新の範囲とデザインシステム（D8）

## ステータス

**確定: 提案B「墨（藍）× 宵」を採用し、デザインガイドを正本とする**（2026-07-17決定）

## コンテキスト

D8はサイト全面のデザイン刷新。閲覧主体・SEO流入が中心で、ユーザー操作は「いいね」と検索のみ。日本語の名言（引用文）の可読性と、情報密度・表示速度を最優先する。実装はFastAPI + Jinja2 + HTMXのSSR（[project-plan.md](../project-plan.md) §6）で、CSPとHTMX規約（[ADR 016](016-csp-htmx-rules.md)）、URL互換（[ADR 008](008-url-compatibility.md)）、いいね経路（[ADR 006](006-like-count-cache-strategy.md)）、検索UI（[ADR 015](015-search-rate-limits.md)）に整合させる必要がある。

Claude Design（`meigensyu-redesign`）でA案「墨（朱）× 宵」/ B案「墨（藍）× 宵」の2案を作成し、実データ入りのA/B比較プロトタイプをPC/スマホ実寸でレンダリング検証した。

## 決定

- **提案B「墨（藍）× 宵」を採用する**。Light=和紙地に墨色文字＋**藍**アクセント、Dark（宵）=夜の地色＋**金**アクセント。構造・タイポ・余白はテーマ非依存で、色トークンだけが切り替わる。
- デザインの**正本は [`docs/design/design-guide.md`](../design/design-guide.md)**とする。トークン・コンポーネント・ページ構成・技術制約はガイドに集約し、実物は `docs/design/proposal-b/`（`tokens.css` / `components.css` / `templates/`）を素材とする。矛盾があれば実ファイル→ガイドの順で優先し、本ADRは決定の記録に徹する。
- 実装取り込み時に、CSP・インラインコード禁止（[ADR 016](016-csp-htmx-rules.md)）、URL互換（[ADR 008](008-url-compatibility.md)）、いいねフォームのJSなしフォールバック（[ADR 006](006-like-count-cache-strategy.md)）、検索debounce 500ms（[ADR 015](015-search-rate-limits.md)）に合わせる。テンプレートのインラインstyleは `--sp-*` 参照のユーティリティクラスへ置換済み。

### A案（朱）を採用しなかった理由

- A案とB案の違いは **Light のアクセント色のみ（朱→藍）**で、Dark（宵×金）・構造・タイポ・余白は共通。
- 朱は視覚的な主張が強く、名言本文（主役）より先にアクセントへ視線が向きやすい。藍の方が墨色の本文と調和し、静かな読み物としての可読性・落ち着きに優る。リンク・いいねが藍だと、金（Dark）との明暗のペアも自然。
- 情報密度の高い一覧・ランキングでも、藍は多用してもうるさくならず、SEOサイトのスキャンしやすさを損なわない。

### テーマ切替の判断

- **OS追従（`prefers-color-scheme`）＋手動切替（`data-theme` + `localStorage`）の両対応**とする。ヘッダーの切替ボタンは**残す**。
- 手動切替は[ADR 016](016-csp-htmx-rules.md)に従い**外部静的JS `static/js/theme.js` のみ**で実装し、インラインscriptは使わない。`<head>` で同期読込して初回描画前に `data-theme` を復元し、FOUCを防ぐ。仕様はデザインガイド §3 に記す。
- 「OS追従のみ・ボタン削除」も候補だったが、手動切替はトークン側が既に対応済みで追加コストが小さく、外部JS化でCSPとも両立するため、利用者が明示的に選べる利点を採る。

## 検証

- 実データ入りA/B比較プロトタイプをPC/モバイル実寸でレンダリング比較し、B案を選定（モバイル390pxはiframeラッパー、Light差分の確認はOSダーク設定に注意）。
- 修正後の `proposal-b/` をヘッドレスChromeでLight/Dark・PC/モバイル390px再検証し、レイアウト崩れがないことを確認した（ユーティリティ `.mg-page` がページネーション用クラスと衝突していた不具合を `.mg-page-body` へ改名して解消）。

## 再検討条件

- 掲載内容や導線が大きく変わり、現行のページ構成・コンポーネントで表現しきれなくなった場合。
- 日本語Webフォントの本文導入など、フォント方針（system-ui前提）を変える必要が生じた場合。
- GA4/AdSense等の外部タグ導入で、CSPや配色・レイアウトに制約が加わった場合。

## 参考

- [`docs/design/design-guide.md`](../design/design-guide.md)（正本）、[`docs/design/README.md`](../design/README.md)（作業経緯）、[`docs/design/proposal-b/`](../design/proposal-b/)（素材）
- 関連ADR: [008 URL互換](008-url-compatibility.md) / [006 いいね](006-like-count-cache-strategy.md) / [015 検索](015-search-rate-limits.md) / [016 CSP・HTMX](016-csp-htmx-rules.md)
