# アーキテクチャ決定記録: 現行URLの互換性

## ステータス

**確定: 現行のユーザー可視URL・URLの意味・canonicalを維持する**（2026-07-13決定）

## コンテキスト

本リニューアルはアプリとインフラの置換であり、URL変更による検索評価、被リンク、利用者のブックマークへの影響を避ける必要がある。

## 決定

- 本番の公開オリジンおよびcanonical hostは **`https://www.meigensyu.com/`** とする。管理下の本番公開alias `https://meigensyu.com/` は、pathとqueryを維持して`www`のHTTPS URLへ1 hopで恒久リダイレクトする。`new.meigensyu.com`など明示した検証環境は対象外とし、`*.fly.dev`や未知のHostはリダイレクトせずD14の方針に従って拒否する。
- 現行で200を返す公開URLは、同じpath/queryで同等コンテンツを返す。
- 現行のcanonical、ページング、フィルタ、ソート、末尾slash、範囲外ページの404をURL契約として維持する。
- 既存の恒久リダイレクトは最終canonicalへ1 hopの301または308で移植し、リダイレクトチェーンを作らない。
- 現行`next.config.js`の静的リダイレクトは手作業で記録した20本ではなく、実装から確認した**23本**を対象とする。
- middlewareの`/quotations/view/[id].html`からslugまたは`q{id}`への動的301も移植する。
- slugと`qXXXX`の扱い、`page/1`の正規化、query parameter、404/410を含むURL契約表を作り、旧環境と新環境の比較テストの正本にする。
- URL契約表はルート実装だけでなく、現行sitemap、アクセスログ、Search Console、被リンクも参照して補完する。

## 検証

- URL契約fixtureにmethod、path、query、期待status、Location、canonical、indexabilityを記録する。
- 新旧比較、redirect chain/loop、内部リンク、sitemap、self-canonicalを自動検査する。管理下の本番公開alias `https://meigensyu.com/`から`https://www.meigensyu.com/`へのhost正規化と、検証環境・未知Hostを正規化対象にしないことも契約fixtureに含める。
