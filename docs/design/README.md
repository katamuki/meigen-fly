# デザイン刷新（D8）作業ディレクトリ

## 経緯

- `claude-design-brief.md` の依頼文を起点に、Claude Design（claude.ai/design プロジェクト `meigensyu-redesign`）でA案「墨（朱）×宵」/ B案「墨（藍）×宵」を作成。
- 実データ入りA/B比較プロトタイプ（PC/スマホ実寸レンダリング検証済み）の結果、**B案「墨（藍）× 宵」に決定**（2026-07-17）。
- `proposal-b/` はClaude Designエクスポート（`/Users/sonoda/prj/claude_design_meigen/proposals/b/`）のスナップショット。**未修正の原本**であり、そのまま実装に使ってはいけない（下記の修正が必要）。

## proposal-b の内容

- `tokens.css` — デザイントークン（Light=墨/藍、Dark=宵/金。OS追従 + `data-theme` 切替）
- `components.css` — コンポーネント（トークン参照ベース）
- `templates/` — Jinja2 + HTMX テンプレート（base / トップ / 名言個別 / 名言一覧 / 著者詳細 / カテゴリ / ランキング / 検索 + partials）
- `og/og.html` — 名言個別用OG画像テンプレート（1200×630、短/中/長文3段階。実寸検証済み）
- `preview.html` / `render-check*.html` — 確認用（本番不要）

## 実装取り込み時に必要な修正（検証済みの指摘）

1. テンプレート中の**インラインstyle属性 24箇所**をクラス化（ADR 016 CSP違反）
2. `base.html` に `{% block meta_robots %}` を定義（現状 `search.html` のnoindexが黙って捨てられる）
3. 検索debounceを200ms→**500ms**（ADR 015）
4. いいねボタンを `<form method="post">` ラップしJSなしフォールバックを実体化（ADR 006）
5. URLを ADR 008 の互換方針（`/quotes/[slugまたはqXXXX]`、末尾スラッシュ有無）に合わせる
6. `base.html` 冒頭コメントの「提案A」表記を修正
7. OG: 80字超の名言の扱い（`og--xlong` 追加 or 切り詰め）と文字数閾値をサーバ実装で決定。本番コンテナに Noto Serif JP 導入（D5と一緒に扱う）

## 未決（次回セッションで決定）

- **テーマ切替ボタンの要否**: `header.html` に切替ボタンがあるが、動かすには小さな外部JS＋状態保存が必要。「OS追従のみ（ボタン削除）」か「JS実装込みで採用」か。
- 上記決定後、D8のデザインガイド＋決定記録（ADR）を作成し、`project-plan.md` の D8 を確定に更新する。
