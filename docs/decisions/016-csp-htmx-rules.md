# アーキテクチャ決定記録: CSP、HTMX、アクセス解析

## ステータス

**確定: 共通の現実的なCSP + HTMXの危険機能無効化を採用**（2026-07-14簡略化）

## コンテキスト

本サイトはJinja2で生成する閲覧主体のHTMLを中心とし、管理画面も機微情報を扱わない。CSPはXSS対策の補助として利用するが、routeごとの複雑なpolicy、独自違反収集、外部タグごとの網羅的E2Eが本体開発を支配しないようにする。

## 基本方針

- Jinja2 autoescape、文脈に応じたescape、利用者入力を安全でないHTMLとして描画しないことを主防御とする。
- 全HTMLへ可能な限り共通のCSPを適用する。管理画面だけ必要に応じてより厳しくしてよいが、初期から多数のroute profileを作らない。
- `X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`frame-ancestors 'none'`または同等のクリックジャッキング対策を設定する。
- CSP Report-Only専用profile、`/api/csp-report`、違反保存・集計基盤は初期実装しない。問題調査時はブラウザ開発者ツールと一時的なReport-Onlyを使う。

初期CSPの例を次に示す。GA4やAdSenseを有効化する場合は、公式要件に必要なoriginだけを追加する。

```text
default-src 'self';
base-uri 'self';
object-src 'none';
frame-ancestors 'none';
form-action 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data: https:;
font-src 'self';
connect-src 'self';
```

インラインstyleを初期段階で全面禁止するための専用改修は行わない。実行可能なインラインJavaScript、DOM event属性、`javascript:` URLは原則使わず、静的JSへ置く。

## HTMX規約

- HTMXとアプリJSはバージョンを固定して`/static/*`から配信する。
- `htmx.config.allowEval = false`、`allowScriptTags = false`、`selfRequestsOnly = true`を設定する。
- `hx-on`、`js:`/`javascript:`付き`hx-vals`や`hx-headers`、swap断片内の`script`は使用しない。
- イベント処理は静的JSの`addEventListener`で実装する。
- HTMX属性へ利用者入力を未escapeで連結しない。

禁止構文を検出する大規模な独自lintや、禁止コードが実行されないことだけを確認する負のbrowser test群は必須としない。通常のレビュー、既存lint、主要導線のテストで確認する。

## GA4

- GA4はサイト本体完成後に任意で導入する。初期リリースの必須条件ではない。
- 導入する場合は公開ページの通常の`page_view`に限定し、管理、認証、API、error responseでは読み込まない。
- 検索語、raw query、fragment、referrer、`client_uuid`、管理者情報、いいね情報を送らない。`view_search_results`等の検索eventは初期導入しない。
- 対象地域と利用形態に応じて必要な同意表示とPrivacy Policyを整備する。独自の同意基盤を作る前に、Googleの提供する仕組みまたは既存の小さな実装を検討する。

## AdSense

- AdSenseもサイト本体完成後の任意機能とし、初期リリースの必須条件ではない。
- 導入時は一般閲覧ページだけに出し、管理、検索、認証、API、HTMX断片、error responseには出さない。
- Googleの最新CSP・同意要件をその時点で確認する。将来の要件を見越したnonce注入やCloudflare Workerは先行実装しない。

## 検証

### リリース必須

- 共通CSPと基本セキュリティヘッダーがHTMLへ付く。
- 主要な閲覧、検索、管理、いいね、HTMX swapが動作する。
- `allowEval`、`allowScriptTags`、`selfRequestsOnly`の設定値を小さなテストで確認する。
- GA4/AdSenseを無効にした環境では関連コードと外部通信がない。

### GA4/AdSense導入時

- 対象ページだけでタグが読み込まれ、管理・APIへ波及しない。
- Privacy Policy、同意、外部送信内容を確認する。
- Cloudflareキャッシュと主要導線が壊れていないことを手動または代表的なbrowser testで確認する。

## 再検討条件

- 信頼できないHTMLを表示する
- cross-origin HTMX、iframe、追加の外部scriptを導入する
- XSSリスクが高い入力・権限・機微情報を扱う
- 実際のCSP違反を継続的に収集する必要が生じる

## 参考

- [HTMX Security](https://htmx.org/docs/)
- [MDN Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
- [Google tag CSP guidance](https://developers.google.com/tag-platform/security/guides/csp)
