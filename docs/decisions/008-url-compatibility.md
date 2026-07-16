# アーキテクチャ決定記録: 現行URLの互換性

## ステータス

**確定: 現行のユーザー可視URL・URLの意味・canonicalを維持する**（2026-07-13決定）

## コンテキスト

本リニューアルはアプリとインフラの置換であり、URL変更による検索評価、被リンク、利用者のブックマークへの影響を避ける必要がある。

## 決定

- 本番の公開オリジンおよびcanonical hostは **`https://www.meigensyu.com/`** とする。管理下の本番公開alias `https://meigensyu.com/` は、pathとqueryを維持して`www`のHTTPS URLへ1 hopで恒久リダイレクトする。専用の検証環境は設けない。`*.fly.dev`や未知のHostはリダイレクトせず、Cloudflare Tunnelとexact Host検証を定めたD14（[ADR 013](013-cloudflare-tunnel-origin-protection.md)）に従って拒否する。
- 現行で200を返す公開URLは、同じpath/queryで同等コンテンツを返す。
- 現行のcanonical、ページング、フィルタ、ソート、末尾slash、範囲外ページの404をURL契約として維持する。
- 既存の恒久リダイレクトは最終canonicalへ1 hopの301または308で移植し、リダイレクトチェーンを作らない。
- 現行`next.config.js`の静的リダイレクトは手作業で記録した20本ではなく、実装から確認した**23本**を対象とする。
- middlewareの`/quotations/view/[id].html`からslugまたは`q{id}`への動的301も移植する。
- slugと`qXXXX`の扱い、`page/1`の正規化、主要リダイレクトを一覧にした簡単なURL契約表を作り、リリース前チェックの正本にする。現行sitemapとSearch Consoleの主要URLで補完する。

## リリース前確認

- 静的リダイレクト23本と`/quotations/view/[id].html`の動的301が、最終canonicalへ1 hopで到達する。
- sitemap・アクセス上位の主要URLが200または301で同等コンテンツへ到達し、self-canonicalが正しい。
- `meigensyu.com`から`www.meigensyu.com`へのhost正規化が機能する。

確認はスクリプトまたは手動`curl`でよく、fixture化した新旧自動比較は必須としない。
