# アーキテクチャ決定記録: CSPとHTMX実装規約

## ステータス

**確定: evalを使うHTMX機能を禁止し、公開ページ限定GA4とroute別CSPを採用する**（2026-07-14決定・同日GA4境界を改訂）

## コンテキスト

本サイトはFastAPI + Jinja2によるSSRをCloudflareでキャッシュし、HTMXは検索・いいね・一覧の部分更新に限定して使う。HTMLやHTMX断片へ攻撃者が制御する属性・タグが混入した場合、`hx-on`、イベントフィルタ、`js:`式、swapされた`script`をHTMXが実行すると、通常のテンプレートXSS対策をすり抜ける実行経路になり得る。

一方、ページごとのnonceを全レスポンスへ導入すると、テンプレート、CSPヘッダー、CloudflareのHTMLキャッシュを常に同じ値で扱う必要がある。キャッシュされたHTMLではオリジンが生成したnonceが複数の閲覧レスポンスで再利用されるため、「レスポンスごとに推測困難な値」というnonceの前提とも相性が悪い。現時点では、実行可能なインラインコード自体をなくす方が単純である。

HTMXの現行安定版ドキュメントでは、`allowEval=false`にするとイベントフィルタ、`hx-on:*`、`hx-vals` / `hx-headers`の`js:`評価を無効化でき、`allowScriptTags=false`にすると取得したHTML内の`script`処理を無効化できる。`hx-csp`は現行安定版の公式extension一覧にはなく、HTMX 4のbetaサイト（確認時点では`4.0.0-beta5`）にだけ掲載されている。初期リリースでbeta版と全HTMX要素への`hx-nonce`付与を持ち込まない。

GA4は検索改善や公開ページの効果測定に利用価値がある。一方、既定実装のままでは`_ga` cookieによるclient ID、URL query / referrer、自動page viewや拡張計測が意図せず送られ得る。アプリ独自の識別Cookieを使わず公開HTMLを共有キャッシュする方針と、利用者の同意後にbrowser側だけでAnalytics cookieを使うことは分離できるため、GA4を全面禁止せず、計測route・送信値・同意・CSPを限定して導入する。一方、AdSenseの公式CSP手順は、変動する配信ドメインの固定allowlistをサポートせず、nonce、`strict-dynamic`、`unsafe-eval`等を含むstrict CSPだけをサポートする。通常ページと同じ安全性・キャッシュ方式のままAdSenseだけを追加できるとは扱わない。

## 決定

### 1. 基本CSP

本番では次を**基本CSP**としてHTTPレスポンスヘッダーへ適用する。開発環境でも可能な限り同じポリシーを使い、開発サーバーの都合で本番CSPを緩めない。GA4を配置できる公開フルページだけは後述のAnalytics追加許可を加え、管理・認証・API・HTMX断片・error responseへ波及させない。

```text
default-src 'self';
base-uri 'none';
object-src 'none';
frame-ancestors 'none';
form-action 'self';
script-src 'self';
script-src-attr 'none';
style-src 'self';
img-src 'self' data:;
font-src 'self';
connect-src 'self';
frame-src 'none';
media-src 'self';
worker-src 'self';
manifest-src 'self';
upgrade-insecure-requests
```

- HTMX、アプリJS、CSS、fontはバージョンまたは内容ハッシュを固定した`/static/*`から配信する。通常稼働時にCDNのJavaScriptを直接読み込まない。
- 実行可能なインラインJavaScript、`onclick`等のDOMイベント属性、`javascript:` URLを全面禁止する。テンプレート内の非実行データであるJSON-LDはこの禁止対象ではないが、`tojson`相当で安全に直列化し、実行可能な式やユーザー入力済みHTMLを入れない。
- `unsafe-inline`、`unsafe-eval`、`unsafe-hashes`は基本CSPへ入れない。nonce/hashも基本CSPでは使わない。静的JSへ移せない固定インラインコードが将来1個だけ必要になった場合はhashを候補に再評価し、動的値を含むコードのためにhash一覧を運用しない。
- インラインstyle属性も禁止し、CSS classへ移す。例外が必要ならCSPと本ADRを同時に更新する。HTMX標準のindicator style注入を止め、同等のCSSを`/static/*`へ置く。
- CSPはXSS対策の補助であり、Jinja2のautoescape、URL/属性コンテキストに応じたエスケープ、ユーザー入力をHTMLとして描画しない規約を省略しない。やむを得ず信頼できないHTMLを表示する領域はサニタイズした上で`hx-disable`を親に付ける。

`base-uri 'none'`のため`<base>`要素は使わない。外部iframeが必要になった場合も`frame-src`へその都度追加し、`default-src`や`https:`全体を緩めない。管理画面を別サイトからframe表示する要件はないため、`frame-ancestors 'none'`を全ページ共通とする。

### 2. HTMX実装規約

全ページの`head`でJavaScriptを実行せずに次のmeta設定を行う。

```html
<meta name="htmx-config"
      content='{"allowEval":false,"allowScriptTags":false,"selfRequestsOnly":true,"includeIndicatorStyles":false}'>
```

規約は次の通りとする。

- **`hx-on:*` / `data-hx-on-*`は禁止**する。計画書にあった「原則`hx-on`」は誤りであり、「`hx-on`禁止」に統一する。イベント処理が必要なら`/static/*`のJSで`addEventListener`を使い、HTMXのイベントAPIへ接続する。
- `hx-trigger="keyup[条件]"`のような**角括弧のイベントフィルタは禁止**する。`changed`、`delay:500ms`、`once`、`from:`、`target:`、`queue:`等の式評価を伴わない宣言的modifierは許可する。複雑な条件は静的JSで判定してcustom eventを発火する。
- `hx-vals`と`hx-headers`は静的な正しいJSONだけを許可し、`js:` / `javascript:` prefixを禁止する。動的値は通常のform input、サーバー描画、または静的JSの`htmx:configRequest` listenerで加える。
- HTMXレスポンス断片に`script`タグを含めない。`allowScriptTags=false`を防御層とし、swap後の初期化はイベント委譲または`htmx:afterSwap` / `htmx:load`を静的JSで処理する。断片内の`script`が動かないことへ依存するだけでなく、サーバー側でも生成を禁止する。
- `htmx.config.allowEval`と`allowScriptTags`を実行時に`true`へ戻すコードを禁止する。`inlineScriptNonce` / `inlineStyleNonce`は設定しない。
- HTMXリクエストは同一オリジンに限定する。`selfRequestsOnly=true`と`connect-src 'self'`を両方維持し、cross-origin endpointを追加するときはCSPだけでなくCSRF、認証情報、レスポンス信頼境界を再評価する。
- HTMX属性値へユーザー入力を連結しない。パスやqueryを属性へ描画する場合もテンプレートの属性コンテキストでescapeし、サーバー側で許可するroute・parameterを検証する。

`hx-csp`は採用しない。理由は、確認時点でHTMX 4 beta専用であり、安定版の保守対象として判断できず、全要素のnonce付与とTrusted Typesまで初期導入する運用負担が大きいためである。HTMX 4の安定版へ更新する際に、安定版extensionとして残っているか、移行コストと実際の脅威に見合うかを再評価する。

### 3. GA4は公開ページに限定して導入

`GA_MEASUREMENT_ID`が設定されたstaging・本番だけでGA4を有効化する。開発・テストまたは未設定環境では、GA4 script、測定ID、Google向け通信、Analytics追加CSPを一切出力しない。GTM containerは使わず、`/static/analytics.js`からGoogle tag (`gtag.js`) を直接読み込む。

#### 計測routeとCSP

GA4を配置できるのは、次の**完全HTML文書を200で返す公開route**だけとする。

- `/`、`/quotes*`、`/authors*`、`/categories*`、`/characters*`
- `/professions*`、`/sources*`、`/ranking`、`/random`
- `/search`、`/about`、`/privacy`、`/terms`

route名によるdefault-deny判定を使い、新しいrouteは明示追加するまで計測しない。`/admin`と全配下、`/login`、`/403`、`/api/*`、`/healthz`、redirect、404/5xx等のerror response、非HTML、`HX-Request: true`のHTMX断片では、測定ID、Analytics用meta / `data-*`、scriptを出さず、基本CSPだけを返す。

対象公開フルページのCSPには、Google公式のGA4非広告用途に必要な次のoriginだけを追加する。

```text
script-src  ... https://*.googletagmanager.com;
img-src     ... https://*.google-analytics.com https://*.googletagmanager.com;
connect-src ... https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com;
```

Google Ads連携、Advertising Features、Google Signals、GTM、DoubleClickは初期利用せず、`*.doubleclick.net`、`*.google.com`、`pagead2.googlesyndication.com`、`frame-src`のGoogle originは追加しない。Google tagの変更で通信先が増えた場合は、CSPを都度緩めず実通信と公式資料を確認して本ADRを更新する。

#### 同意とCookie

- GA4 scriptは利用者がアクセス解析へ明示的に同意するまで読み込まない。同意前・拒否後はGoogleへcookieless pingも送らない。
- 同意状態は`localStorage`で`granted | denied`として保持し、サーバーへ送らない。公開HTMLは同意状態やAnalytics cookieで出し分けず、`Vary: Cookie`も付けないため、Cloudflareの共有キャッシュを維持する。
- 同意後はGA4標準のfirst-party cookie (`_ga`, `_ga_<id>`) を利用できる。アプリ独自のユーザーID、`client_uuid`、`ip_hash`、管理者IDをGA4へ設定しない。
- `/privacy`から同意を変更・撤回できるようにし、撤回時はAnalytics storageをdenyへ更新し、自サイトで設定したGA4 cookieを削除して以後tagを読み込まない。
- 有効化前にPrivacy Policyへ、Google Analyticsの利用目的、Googleへの外部送信、送信項目、cookie名と保持期間、検索語の取扱い、拒否・撤回方法、Googleのprivacy情報へのリンクを記載する。法令適合性の最終確認はリリース前タスクとする。

#### page viewと検索イベント

- GA4 propertyのEnhanced Measurementは初期OFFとし、履歴変更、site search、scroll、outbound click等を自動収集しない。`send_page_view: false`を毎回の`config`で指定する。
- `config`より前に、サーバーがrouteから生成した正規化済みpathを使って`page_location = PUBLIC_ORIGIN + path`、`page_referrer = ""`、`ignore_referrer = true`を全event scopeへ設定する。`document.location`、`document.referrer`、Host header、raw URL、query string、fragmentから計測値を作らない。
- 同意済みの対象公開フルページでは、正規化pathだけを持つ`page_view`を1回送る。HTMX swap、検索custom event、history操作からpage viewを追加送信しない。
- 検索結果が正常表示されたときだけ、Googleの推奨event `view_search_results`を明示送信し、D15と同じ空白正規化・最大100 Unicodeコードポイントを適用した`search_term`と数値の`result_count`だけを含める。空文字、入力不正、429、5xxでは送らず、同一ページ内の同じ正規化語は重複送信しない。
- email addressや電話番号に明確に一致する検索語は送信せず、UIとPrivacy Policyで検索欄へ個人情報を入力しないよう案内する。GoogleのPII禁止方針に照らし、完全な自動判定はできないことを残余リスクとして扱う。
- event名・parameterは上記に限定し、User-ID、user property、custom dimension、広告personalization、管理画面情報、`client_uuid`、`ip_hash`、いいねAPIの`quote_id`を送らない。

この方式はAnalytics cookieの利用を明示的に許可するが、アプリのレスポンスやキャッシュをユーザー別に変えることは許可しない。検索語の送信は効果測定のための限定的な例外であり、URL queryの自動収集を許可するものではない。

### 4. AdSenseとその他の外部サービス

**初期リリースではAdSenseを無効とし、AdSenseコードも許可先も配信しない。** AdSense用の有効化flagやpublisher ID設定自体をアプリへ実装しない。Googleの公式手順が固定ドメインallowlistをサポートせず、次を含むポリシーを要求しているためである。

```text
script-src 'nonce-{random}' 'unsafe-inline' 'unsafe-eval' 'strict-dynamic' https: http:
```

これは基本方針の`unsafe-eval`禁止、HTTP不許可、外部scriptの最小許可、およびCloudflareでキャッシュするSSR HTMLのnonce一意性と衝突する。「AdSenseの既知ドメインを何個か追加して動けばよい」という非公式allowlistは採用しない。

AdSenseを有効化する前に、最新の公式手順を再確認し、次のいずれかを別ADRで明示的に選ぶ。その際は`script-src`だけで完結すると仮定せず、広告markupのstyle、iframe、画像、beaconを含む`style-src`、`frame-src`、`img-src`、`connect-src`も最新の公式要件と実通信から確定する。

1. 広告対象ページをHTMLキャッシュ対象外にし、レスポンスごとの暗号学的乱数nonceとGoogleの対応ポリシーを適用して、`unsafe-eval`を広告対象の公開ページだけで受容する。
2. エッジでHTMLとCSPを同時に書き換えてレスポンスごとのnonceを発行する。ただし個人運用には実装・障害対応コストが高い。
3. CSPを維持してAdSenseを使わない。

収益要件が具体化するまでは3を採用する。基本CSP全体を広告のために緩めたり、管理画面・検索・いいねAPIへ広告用ポリシーを波及させたりしない。この決定だけでは計画書フェーズ3の「広告配置」は完了せず、AdSenseを有効化する前の別ADR・実装・検証タスクとして未完のまま残す。

D9でTurnstileは初期不採用のため、`challenges.cloudflare.com`をどのdirectiveにも加えない。将来導入時はCloudflareの最新公式CSP要件を確認し、通常構成では同originを`script-src`と`frame-src`へだけ追加する。pre-clearance利用時の通信も同一オリジンのsiteverify endpointへ行う限り、既存の`connect-src 'self'`で足りる。Turnstileを表示するrouteだけのポリシー変更として本ADRを更新し、不要な`connect-src`許可を先回りで足さない。

OG画像生成エンドポイント`/api/og?...`は同一オリジンの画像レスポンスであり、それ自体へHTML用CSPを付ける必要はない。`<meta property="og:image" content="...">`はブラウザが文書内resourceとして画像を読み込む指定ではなく、SNS crawlerがURLを別途取得するため、外部SNS originをCSPへ許可しない。ページ本文でも同じOG画像を`<img>`表示する場合は`img-src 'self'`で足りる。将来、画像をR2の別公開host等から配信するときだけ、その画像originを`img-src`へ追加する。

## 脅威モデルと境界

主に防ぐのは、テンプレートescape漏れ、保存済みコンテンツ、HTMX断片、query表示等を足場にしたスクリプト実行と、意図しない外部originへのデータ送信である。禁止規約により、攻撃者が`hx-on`や`js:`属性を注入してもHTMXのeval経路が無効で、断片へ`script`を混ぜてもHTMXは処理しない。CSPはインライン実行と許可外originをさらに遮断する。

ただし、次はCSPだけでは防げない。

- 自サイト配下の許可済みJavaScript自体の脆弱性や改ざん
- 許可済みのGA4 originへ、正規アプリJSやGoogle tagが契約外の値を誤送信すること
- HTML属性やURLのescape不備による、スクリプト実行を伴わない表示・遷移の改ざん
- サーバー側の認可、CSRF、SQL injection、キャッシュキー混同

静的assetは内容ハッシュ付きファイル名で配信し、依存更新時にHTMXの変更履歴とCSP関連設定を確認する。検索query、Access JWT、CSRF token、IPや`ip_hash`等をCSP違反ログへ保存しない。

## 段階導入と違反監視

1. stagingで`Content-Security-Policy-Report-Only`を有効にし、主要route（トップ、一覧、詳細、検索、いいね、管理画面、OG）を手動またはE2Eで確認する。
2. 本番でも48時間を目安にReport-Onlyで観測する。違反を見てoriginを無条件に追加せず、必要なresourceか、バグ・browser extension・攻撃試行かを分類する。
3. 必要な修正後、同じポリシーを`Content-Security-Policy`へ切り替える。大きな外部タグ変更時だけ、現行Enforceを維持したまま変更候補をReport-Onlyで併送する。

Report-OnlyはHTTPヘッダーで配信する（metaでは配信できない）。`Reporting-Endpoints: csp="<PUBLIC_ORIGIN>/api/csp-report"`とCSPの`report-to csp`を使い、移行中は旧browser向けの`report-uri /api/csp-report`も併記する。`PUBLIC_ORIGIN`はADR 012・013と同じ環境別の完全一致origin（本番は`https://www.meigensyu.com`、stagingはその検証host）であり、reporting endpointは常に基本CSPの`connect-src 'self'`内に収まる。

初期の違反受信はこのsame-origin endpoint 1つへ集約し、`private, no-store`、小さいbody上限、`application/reports+json`と`application/csp-report`のcontent type確認、IP単位の緩いrate limitを設け、認証や同期DB書き込みを要求しない。個人運用では構造化アプリログへ記録し、公開直後48時間は日次、その後はデプロイ時に件数・新規directive/originだけを見る。ログは7日で削除し、完全な文書URL・query・referrer・sampleコードを保存しない。ノイズが多い場合は無制限に保存せず、samplingまたは集計だけにする。恒久的な週次手動確認や外部SaaS導入は必須にしない。

## 実装・検証

### リリース必須

- 全HTMLレスポンスで環境に対応したCSPヘッダーが1つだけ返り、HTMX断片・error responseにも基本ポリシーが付くことをテストする。画像等の非HTMLレスポンスへ同じHTMLポリシーを無意味に複製しない。
- template / static sourceを検査し、`hx-on`、イベントフィルタ、`hx-vals` / `hx-headers`の`js:` / `javascript:`、実行可能なインラインscript、DOMイベント属性、`javascript:` URL、HTMX断片内scriptを検出したらCIを失敗させる。唯一のinline `script`例外は、完全HTML文書内の`<script type="application/ld+json">`で、安全なJSON serializerを通した構造化データだけを内容とし、`src`、nonce、event属性、実行可能なMIME typeを持たないものとする。HTMX断片ではJSON-LDも禁止する。この例外と、通常のinline scriptが拒否されることをCI fixtureで検証し、JSON中の通常文字列等の誤検知は限定的な明示除外にする。
- browser testで`htmx.config.allowEval === false`、`allowScriptTags === false`、`selfRequestsOnly === true`を確認し、禁止した`hx-on` / event filter / `js:`が動作せず、通常の検索debounce、いいね、swap後の静的listenerが動くことを確認する。
- `GA_MEASUREMENT_ID`未設定時は全routeでGA4コード・Google追加CSP・Google通信・Analytics cookieがないことを確認する。設定時も除外route、HTMX断片、error responseには測定ID・script・追加CSPがないことをroute testで確認する。
- 同意前・拒否後にGoogle通信とAnalytics cookieがなく、同意後の対象公開フルページだけがGoogle tagを読み込み、正規化pathの`page_view`を1回送ることをbrowser testで確認する。全GA4 request payloadにraw query、fragment、referrer、除外route、アプリ識別子がないことを確認する。
- 1文字・複数語・0件の正常検索で`view_search_results`が正規化済み`search_term`と`result_count`だけを送り、同一語の重複、空文字、email/電話番号形式、429、5xxでは送らないことを確認する。
- AdSenseとTurnstileのコード・frame・許可先が出力されないことを確認する。
- stagingと本番のReport-Only期間に主要導線を確認してからEnforceへ移す。

### 導入後または機能追加時の推奨確認

- CSPの負のE2Eとして、nonceなしinline script、event属性、`eval()`、外部script、cross-origin `fetch`、swap内scriptがブロックされることを確認する。
- OG URLをSNS debugger相当または直接GETで確認し、CSPへSNS hostを足さずに取得できることを確認する。

## 既存文書との同期（2026-07-14完了）

本ADRをD16の正本とする。2026-07-14に所有元の文書を次のとおり同期した。今後方針を変える場合も同じ文書を同時に更新する。

- `docs/project-plan.md`のD16を確定済みとし、`hx-on`禁止、`allowEval=false`、公開ページ限定GA4、AdSense初期OFF、本ADR参照へ統一した。フェーズ3のGA4・Privacy Policy・広告配置は実装タスクとして残した。
- `docs/decisions/001-architecture-cloudflare-fly-sqlite.md`のCSP/HTMX規約、Cookie境界、初期環境変数を本ADRへ同期した。

## 影響

- インライン処理を静的JSへ集約するため、挙動の検索・テスト・依存更新が容易になる。
- `hx-on`の短い記述やevent filterは使えないが、本サイトのHTMX利用範囲では少量のevent listenerで代替できる。
- nonce/hashの生成・テンプレート注入・キャッシュ整合を初期実装から除外できる。
- GA4の対象route、同意、cookie、送信値を限定し、公開HTMLの共有キャッシュを維持しながらページ・検索の効果測定ができる。
- AdSense収益化は初期リリース後の明示的な再判断となる。広告を急いで有効化するためにサイト全体のCSPを暗黙に弱めない。

## 再検討条件

- GA4で広告機能、自動計測、GTM、追加event、同意方式の変更を行うとき
- HTMX 4安定版へ更新し、`hx-csp`が安定版の保守対象になったとき
- 信頼できないHTMLをサニタイズして表示する要件、cross-origin HTMX、iframe埋め込みが生じたとき
- CSP違反で基本機能が維持できず、静的JSへの移動では解決できないとき
- Cloudflare Worker等を既に運用し、edgeでのnonce注入を低コストに実現できるようになったとき

## 採用しなかった選択肢

- **原則`hx-on`**: `allowEval=false`と矛盾し、HTML属性を実行コードとして扱う経路を残すため不採用。
- **`unsafe-eval`を通常許可**: HTMXのeval依存機能は静的JSで代替でき、文字列からのコード生成をサイト全体で許可する理由がないため不採用。
- **全ページnonce**: Cloudflare HTMLキャッシュとの整合、nonce再利用、テンプレート運用のコストが現時点の機能に見合わないため不採用。
- **`hx-csp`を先行採用**: HTMX 4 betaに依存し、全要素へのnonce付与等が必要になるため不採用。
- **GA4を全routeへ共通挿入**: 管理・認証・APIのURLや識別情報を送る危険があり、不要なrouteのCSPも広げるため不採用。
- **GA4 Enhanced Measurementによるsite search自動計測**: raw URL queryと自動eventを制御しにくいため不採用。検索語は明示eventだけで送る。
- **同意前のConsent Mode ping**: 初期実装では同意前の外部送信をなくす方が説明・検証しやすいため不採用。

## 公式資料（2026-07-14確認）

- [HTMX Documentation: Security Tools / CSP / Configuration](https://htmx.org/docs/)
- [HTMX: `hx-on` attribute](https://htmx.org/attributes/hx-on/)
- [HTMX: `hx-trigger` attribute](https://htmx.org/attributes/hx-trigger/)
- [HTMX: `hx-vals` attribute](https://htmx.org/attributes/hx-vals/)
- [HTMX: `hx-headers` attribute](https://htmx.org/attributes/hx-headers/)
- [HTMX stable extensions](https://htmx.org/extensions/)
- [HTMX 4 beta: `hx-csp`](https://four.htmx.org/extensions/hx-csp)
- [MDN: Content Security Policy guide](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
- [MDN: `script-src`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/script-src)
- [Google: Use Tag Manager with a Content Security Policy（GA4の許可先を含む）](https://developers.google.com/tag-platform/security/guides/csp)
- [Google Analytics: Measure pageviews](https://developers.google.com/analytics/devguides/collection/ga4/views)
- [Google Analytics: Configuration fields](https://developers.google.com/analytics/devguides/collection/ga4/reference/config)
- [Google Analytics: Recommended events](https://developers.google.com/analytics/devguides/collection/ga4/reference/events)
- [Google Analytics: Data collection / client ID cookie](https://support.google.com/analytics/answer/11593727?hl=en)
- [Google Analytics: Avoid sending PII](https://support.google.com/analytics/answer/6366371?hl=en)
- [Google Analytics: Consent types](https://support.google.com/analytics/answer/12334711?hl=en)
- [Google AdSense: Integrate the ad code with a CSP](https://support.google.com/adsense/answer/16283098?hl=en)
- [Cloudflare Turnstile: Content Security Policy](https://developers.cloudflare.com/turnstile/reference/content-security-policy/)
