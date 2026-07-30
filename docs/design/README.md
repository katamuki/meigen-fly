# デザイン刷新（D8）資料

## 経緯

- `claude-design-brief.md` の依頼文を起点に、Claude Design（claude.ai/design プロジェクト `meigensyu-redesign`）でA案「墨（朱）×宵」/ B案「墨（藍）×宵」を作成。
- 実データ入りA/B比較プロトタイプ（PC/スマホ実寸レンダリング検証済み）の結果、**B案「墨（藍）× 宵」に決定**（2026-07-17）。
- D8の決定記録は [`../decisions/017-design-system-d8.md`](../decisions/017-design-system-d8.md)、実装仕様の正本は [`design-guide.md`](design-guide.md)。
- `proposal-b/` はClaude Designエクスポートを、ADR 006・008・015・016とD8決定へ整合するよう修正した実装素材・確認用プロトタイプ。実装時はデザインガイドと各ADRを優先する。

## proposal-b の内容

- `tokens.css` — デザイントークン（Light=墨/藍、Dark=宵/金。OS追従 + `data-theme` 切替）
- `components.css` — コンポーネント（トークン参照ベース）
- `templates/` — Jinja2 + HTMX テンプレート（base / トップ / 名言個別 / 名言一覧 / 著者詳細 / カテゴリ / ランキング / 検索 + partials）
- `og/og.html` — 名言個別OG画像の視覚仕様（1200×630、短/中/長文3段階）。本番はHTML画像化せずPillowで再現
- `preview.html` / `render-check*.html` — 確認用（本番不要）

## 確定済みの実装方針

- インラインstyleはトークン参照のクラスへ置換済み。検索は500ms debounce、いいねは通常POST可能な`form`、URLはADR 008へ整合済み。
- テーマはOS追従＋外部`theme.js`による手動切替の両対応（ADR 017）。
- OG画像は名言・著者をPillowでオンデマンド生成し、Cloudflareで30日キャッシュする。名言は表示幅20/40/80で文字サイズを切り替え、80超は`…`で省略する。フォントは本番コンテナへ`fonts-noto-cjk`と`fontconfig`を導入する（[ADR 018](../decisions/018-og-image-generation.md)）。
