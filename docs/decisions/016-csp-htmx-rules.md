# アーキテクチャ決定記録: CSPとHTMX実装規約

## ステータス

**確定: 管理・検索は厳格CSP、閲覧ページはAdSense互換の最小CSP + Report-Onlyとする**（2026-07-14決定・同日GA4/AdSense境界を改訂）

## コンテキスト

本サイトはFastAPI + Jinja2によるSSRをCloudflareでキャッシュし、HTMXは検索・いいね・一覧の部分更新に限定して使う。HTMLやHTMX断片へ攻撃者が制御する属性・タグが混入した場合、`hx-on`、イベントフィルタ、`js:`式、swapされた`script`をHTMXが実行すると、通常のテンプレートXSS対策をすり抜ける実行経路になり得る。

一方、ページごとのnonceを全レスポンスへ導入すると、テンプレート、CSPヘッダー、CloudflareのHTMLキャッシュを常に同じ値で扱う必要がある。キャッシュされたHTMLではオリジンが生成したnonceが複数の閲覧レスポンスで再利用されるため、「レスポンスごとに推測困難な値」というnonceの前提とも相性が悪い。本サイトは公開ユーザーがHTML本文を投稿せず、公開ページの大半が閲覧専用であるため、初期は全ページへ同じ強度を要求せず、管理・検索の厳格CSPと一般閲覧ページの低運用コストな方針を分ける。

HTMXの現行安定版ドキュメントでは、`allowEval=false`にするとイベントフィルタ、`hx-on:*`、`hx-vals` / `hx-headers`の`js:`評価を無効化でき、`allowScriptTags=false`にすると取得したHTML内の`script`処理を無効化できる。`hx-csp`は現行安定版の公式extension一覧にはなく、HTMX 4のbetaサイト（確認時点では`4.0.0-beta5`）にだけ掲載されている。初期リリースでbeta版と全HTMX要素への`hx-nonce`付与を持ち込まない。

GA4は検索改善や公開ページの効果測定に利用価値がある。一方、既定実装のままでは`_ga` cookieによるclient ID、URL query / referrer、自動page viewや拡張計測が意図せず送られ得る。アプリ独自の識別Cookieを使わず公開HTMLを共有キャッシュする方針と、利用者の同意後にbrowser側だけでAnalytics cookieを使うことは分離できるため、計測route・送信値・同意・CSPを限定して導入する。AdSenseは固定ドメインallowlistを公式サポートせず、厳格CSPではレスポンスごとのnonce等を要求する。初期は広告対象の閲覧ページでresource読み込みをEnforceせず、通常のAuto Adsコードと共有HTMLキャッシュを優先する。

## 決定

### 1. route別CSP

#### 厳格Enforce profile

`/admin`と全配下、`/login`、`/403`、完全HTMLの`/search`、HTML error responseには、次を`Content-Security-Policy`として適用する。開発環境でも可能な限り同じポリシーを使う。

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

- HTMX、アプリJS、CSS、fontはバージョンまたは内容ハッシュを固定した`/static/*`から配信する。厳格profileではCDNのJavaScriptを直接読み込まない。
- アプリが生成する実行可能なインラインJavaScript、`onclick`等のDOMイベント属性、`javascript:` URLを禁止する。テンプレート内の非実行データであるJSON-LDはこの禁止対象ではないが、`tojson`相当で安全に直列化し、実行可能な式やユーザー入力済みHTMLを入れない。
- `unsafe-inline`、`unsafe-eval`、`unsafe-hashes`は厳格profileへ入れない。nonce/hashも初期採用しない。静的JSへ移せない固定インラインコードが将来1個だけ必要になった場合はhashを候補に再評価する。
- インラインstyle属性も禁止し、CSS classへ移す。例外が必要ならCSPと本ADRを同時に更新する。HTMX標準のindicator style注入を止め、同等のCSSを`/static/*`へ置く。
- CSPはXSS対策の補助であり、Jinja2のautoescape、URL/属性コンテキストに応じたエスケープ、ユーザー入力をHTMLとして描画しない規約を省略しない。やむを得ず信頼できないHTMLを表示する領域はサニタイズした上で`hx-disable`を親に付ける。

`/search`でGA4が有効な場合だけ、§3の非広告用GA4 originを厳格profileへ追加する。管理・認証・error responseへは追加しない。

#### 一般閲覧ページ profile

`/`、名言・著者・カテゴリ等の一般閲覧ページ、`/ranking`、`/random`、`/about`、`/privacy`、`/terms`では、AdSenseとCloudflare共有HTMLキャッシュを優先する。次の非resource制約だけを`Content-Security-Policy`でEnforceし、`script-src`、`style-src`、`img-src`、`connect-src`、`frame-src`は初期Enforceしない。

```text
object-src 'none';
base-uri 'none';
frame-ancestors 'none';
form-action 'self';
upgrade-insecure-requests
```

同時に、外部resourceの利用状況を把握するため次の緩い監視policyを`Content-Security-Policy-Report-Only`で配信する。これはXSSをブロックするものではなく、将来の厳格化に向けたinventoryと想定外schemeの検出を目的とする。

```text
default-src 'self' https: data: blob:;
object-src 'none';
base-uri 'none';
frame-ancestors 'none';
form-action 'self';
script-src 'self' https: 'unsafe-inline' 'unsafe-eval';
style-src 'self' https: 'unsafe-inline';
img-src 'self' https: data:;
font-src 'self' https: data:;
connect-src 'self' https:;
frame-src https:;
report-to csp;
report-uri /api/csp-report
```

このReport-Only policyは、HTTPS上の悪意ある外部scriptを阻止する防御ではない。公開閲覧ページの安全性は、Jinja2 autoescape、入力をHTMLとして描画しないこと、静的アプリJS、`hx-on` / eval禁止、依存管理、XSSテストを正本とする。JSON API、OG画像等の非HTMLレスポンスにはHTML用CSPを付けない。

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
- HTMXリクエストは同一オリジンに限定する。`selfRequestsOnly=true`を全ページで維持し、厳格profileでは`connect-src 'self'`も防御層とする。cross-origin endpointを追加するときはCSPだけでなくCSRF、認証情報、レスポンス信頼境界を再評価する。
- HTMX属性値へユーザー入力を連結しない。パスやqueryを属性へ描画する場合もテンプレートの属性コンテキストでescapeし、サーバー側で許可するroute・parameterを検証する。

`hx-csp`は採用しない。理由は、確認時点でHTMX 4 beta専用であり、安定版の保守対象として判断できず、全要素のnonce付与とTrusted Typesまで初期導入する運用負担が大きいためである。HTMX 4の安定版へ更新する際に、安定版extensionとして残っているか、移行コストと実際の脅威に見合うかを再評価する。

### 3. GA4は公開ページに限定して導入

`GA_MEASUREMENT_ID`が設定されたstaging・本番だけでGA4を有効化する。開発・テストまたは未設定環境では、GA4 script、測定ID、Google向け通信、Analytics追加CSPを一切出力しない。GTM containerは使わず、`/static/analytics.js`からGoogle tag (`gtag.js`) を直接読み込む。

#### 計測routeとCSP

GA4を配置できるのは、次の**完全HTML文書を200で返す公開route**だけとする。

- `/`、`/quotes*`、`/authors*`、`/categories*`、`/characters*`
- `/professions*`、`/sources*`、`/ranking`、`/random`
- `/search`、`/about`、`/privacy`、`/terms`

route名によるdefault-deny判定を使い、新しいrouteは明示追加するまで計測しない。`/admin`と全配下、`/login`、`/403`、`/api/*`、`/healthz`、redirect、404/5xx等のerror response、非HTML、`HX-Request: true`のHTMX断片では、測定ID、Analytics用meta / `data-*`、scriptを出さず、各routeに対応するGA4なしのCSPだけを返す。

厳格CSPをEnforceする`/search`では、Google公式のGA4非広告用途に必要な次のoriginだけを追加する。一般閲覧ページはresource directiveをEnforceせず、Report-Only profileの`https:`内でGA4通信を観測する。

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

`ADSENSE_PUBLISHER_ID`が設定されたstaging・本番では、初期リリースから**Auto Ads**を一般閲覧ページへ導入できる。未設定環境ではAdSense code、publisher ID、広告通信を一切出力しない。

AdSenseを配置できるrouteは、完全HTMLを200で返す次の一般閲覧ページに限定する。

- `/`、`/quotes*`、`/authors*`、`/categories*`、`/characters*`
- `/professions*`、`/sources*`、`/ranking`、`/random`

`/search`、`/admin`と全配下、`/login`、`/403`、`/api/*`、`/healthz`、`/about`、`/privacy`、`/terms`、HTMX断片、redirect、error response、非HTMLにはAdSense codeを出さない。route名によるdefault-denyとし、新しいrouteへ自動継承しない。

初期はGoogle公式のAuto Ads外部loaderだけを`head`へ配置し、アプリ独自のinline scriptは追加しない。手動広告ユニットのinline `adsbygoogle.push({})`、広告配置最適化用の独自inline code、GTM経由のAdSenseは初期スコープ外とする。

Googleは、AdSenseが利用するdomainは変動するため固定domain allowlistを公式サポートせず、厳格CSPを使う場合はレスポンスごとのrandom nonce、`strict-dynamic`、`unsafe-eval`等を含む方式だけをサポートしている。初期リリースでは広告ページのresource CSPをEnforceしないためnonceを導入せず、Cloudflareの共有HTMLキャッシュを維持する。これはAdSenseのためにサイト全体のCSPを緩める判断ではなく、広告対象の閲覧ページだけCSPによるXSS補助防御を受容的に弱くする判断である。

AdSense有効化前にPrivacy Policy、広告cookie・外部送信、拒否手段を記載し、対象地域とGoogleの最新要件に応じた同意管理を完了する。GA4の同意だけでAdSenseの同意要件を満たすとは扱わない。

将来、広告ページでもresource CSPをEnforceする必要が生じた場合は、次のいずれかを別ADRで選ぶ。

1. 広告対象ページをHTMLキャッシュ対象外にし、originでレスポンスごとのnonceを生成する。
2. nonceなしHTMLを共有キャッシュし、Cloudflare Workerで配信ごとにHTMLとCSPへ同じnonceを注入する。
3. AdSenseを停止して厳格CSPへ戻す。

固定nonceを含むHTMLの共有キャッシュや、非公式な固定domain allowlistは採用しない。

D9でTurnstileは初期不採用のため、`challenges.cloudflare.com`をどのdirectiveにも加えない。将来導入時はCloudflareの最新公式CSP要件を確認し、通常構成では同originを`script-src`と`frame-src`へだけ追加する。pre-clearance利用時の通信も同一オリジンのsiteverify endpointへ行う限り、既存の`connect-src 'self'`で足りる。Turnstileを表示するrouteだけのポリシー変更として本ADRを更新し、不要な`connect-src`許可を先回りで足さない。

OG画像生成エンドポイント`/api/og?...`は同一オリジンの画像レスポンスであり、それ自体へHTML用CSPを付ける必要はない。`<meta property="og:image" content="...">`はブラウザが文書内resourceとして画像を読み込む指定ではなく、SNS crawlerがURLを別途取得するため、外部SNS originをCSPへ許可しない。厳格profileのページ本文で同じOG画像を`<img>`表示する場合も`img-src 'self'`で足りる。

## 脅威モデルと境界

主に防ぐのは、テンプレートescape漏れ、保存済みコンテンツ、HTMX断片、query表示等を足場にしたスクリプト実行と、意図しない外部originへのデータ送信である。禁止規約により、攻撃者が`hx-on`や`js:`属性を注入してもHTMXのeval経路が無効で、断片へ`script`を混ぜてもHTMXは処理しない。厳格profileではCSPがインライン実行と許可外originをさらに遮断する。一般閲覧ページではresource CSPをEnforceしないため、この最後の防御層が弱いことを受容する。

ただし、次はCSPだけでは防げない。

- 自サイト配下の許可済みJavaScript自体の脆弱性や改ざん
- 許可済みのGA4 originへ、正規アプリJSやGoogle tagが契約外の値を誤送信すること
- HTML属性やURLのescape不備による、スクリプト実行を伴わない表示・遷移の改ざん
- サーバー側の認可、CSRF、SQL injection、キャッシュキー混同

静的assetは内容ハッシュ付きファイル名で配信し、依存更新時にHTMXの変更履歴とCSP関連設定を確認する。検索query、Access JWT、CSRF token、IPや`ip_hash`等をCSP違反ログへ保存しない。

## 段階導入と違反監視

1. stagingでは、管理・認証・検索の厳格profileをまず`Content-Security-Policy-Report-Only`で確認し、主要導線が動いた後にEnforceする。
2. 一般閲覧ページは最小CSPを最初からEnforceし、resource監視policyはReport-Onlyのまま維持する。AdSense originを見つけるたび固定allowlistへ追加したり、同じpolicyをEnforceへ昇格したりしない。
3. 本番公開直後はAdSense表示、GA4、HTMX、違反件数を確認する。大きな外部タグ変更時も管理・検索の厳格Enforceを緩めず、公開閲覧ページのReport-Onlyだけで影響を観測する。

Report-OnlyはHTTPヘッダーで配信する（metaでは配信できない）。`Reporting-Endpoints: csp="<PUBLIC_ORIGIN>/api/csp-report"`と`report-to csp`を使い、旧browser向けの`report-uri /api/csp-report`も併記する。`PUBLIC_ORIGIN`はADR 012・013と同じ環境別の完全一致originである。

初期の違反受信はこのsame-origin endpoint 1つへ集約し、`private, no-store`、小さいbody上限、`application/reports+json`と`application/csp-report`のcontent type確認、IP単位の緩いrate limitを設け、認証や同期DB書き込みを要求しない。個人運用では構造化アプリログへ記録し、公開直後48時間は日次、その後はデプロイ時に件数・新規directive/originだけを見る。ログは7日で削除し、完全な文書URL・query・referrer・sampleコードを保存しない。ノイズが多い場合は無制限に保存せず、samplingまたは集計だけにする。恒久的な週次手動確認や外部SaaS導入は必須にしない。

## 実装・検証

### リリース必須

- routeごとに、管理・認証・検索・HTML errorは厳格Enforce、一般閲覧ページは最小Enforce + resource Report-Onlyとなることをテストする。HTMX断片へAdSense codeを含めず、画像等の非HTMLレスポンスへHTML用CSPを複製しない。
- template / static sourceを検査し、`hx-on`、イベントフィルタ、`hx-vals` / `hx-headers`の`js:` / `javascript:`、実行可能なインラインscript、DOMイベント属性、`javascript:` URL、HTMX断片内scriptを検出したらCIを失敗させる。唯一のinline `script`例外は、完全HTML文書内の`<script type="application/ld+json">`で、安全なJSON serializerを通した構造化データだけを内容とし、`src`、nonce、event属性、実行可能なMIME typeを持たないものとする。HTMX断片ではJSON-LDも禁止する。この例外と、通常のinline scriptが拒否されることをCI fixtureで検証し、JSON中の通常文字列等の誤検知は限定的な明示除外にする。
- browser testで`htmx.config.allowEval === false`、`allowScriptTags === false`、`selfRequestsOnly === true`を確認し、禁止した`hx-on` / event filter / `js:`が動作せず、通常の検索debounce、いいね、swap後の静的listenerが動くことを確認する。
- `GA_MEASUREMENT_ID`未設定時は全routeでGA4コード・Google追加CSP・Google通信・Analytics cookieがないことを確認する。設定時も除外route、HTMX断片、error responseには測定ID・script・追加CSPがないことをroute testで確認する。
- 同意前・拒否後にGoogle通信とAnalytics cookieがなく、同意後の対象公開フルページだけがGoogle tagを読み込み、正規化pathの`page_view`を1回送ることをbrowser testで確認する。全GA4 request payloadにraw query、fragment、referrer、除外route、アプリ識別子がないことを確認する。
- 1文字・複数語・0件の正常検索で`view_search_results`が正規化済み`search_term`と`result_count`だけを送り、同一語の重複、空文字、email/電話番号形式、429、5xxでは送らないことを確認する。
- `ADSENSE_PUBLISHER_ID`未設定時はAdSense code・publisher ID・広告通信がなく、設定時も対象routeの完全HTMLだけにAuto Ads loaderが出ることを確認する。検索、管理、認証、API、HTMX断片、error responseでは出力しない。
- 広告対象ページでAuto Ads表示・遷移・Cloudflare HITを確認し、管理・検索の厳格CSPがAdSenseの影響を受けないことを確認する。Turnstileは引き続き出力しない。

### 導入後または機能追加時の推奨確認

- 管理・認証・検索の負のE2Eとして、nonceなしinline script、event属性、`eval()`、外部script、cross-origin `fetch`、swap内scriptがブロックされることを確認する。一般閲覧ページでは同じブロックを期待しない。
- OG URLをSNS debugger相当または直接GETで確認し、CSPへSNS hostを足さずに取得できることを確認する。

## 既存文書との同期（2026-07-14完了）

本ADRをD16の正本とする。2026-07-14に所有元の文書を次のとおり同期した。今後方針を変える場合も同じ文書を同時に更新する。

- `docs/project-plan.md`のD16を確定済みとし、管理・検索の厳格CSP、一般閲覧ページのReport-Only、公開ページ限定GA4、Auto Ads、本ADR参照へ統一した。フェーズ3のGA4・Privacy Policy・広告配置は実装タスクとして残した。
- `docs/decisions/001-architecture-cloudflare-fly-sqlite.md`のCSP/HTMX規約、Cookie境界、初期環境変数を本ADRへ同期した。

## 影響

- インライン処理を静的JSへ集約するため、挙動の検索・テスト・依存更新が容易になる。
- `hx-on`の短い記述やevent filterは使えないが、本サイトのHTMX利用範囲では少量のevent listenerで代替できる。
- 公開閲覧ページではnonce生成をせず、Cloudflare共有HTMLキャッシュとAuto Adsを両立できる。
- GA4の対象route、同意、cookie、送信値を限定し、公開HTMLの共有キャッシュを維持しながらページ・検索の効果測定ができる。
- AdSenseを初期導入できる一方、公開閲覧ページでは厳格なresource CSPによるXSS補助防御を失う。この残余リスクをautoescape、実装規約、テストで補う。

## 再検討条件

- GA4で広告機能、自動計測、GTM、追加event、同意方式の変更を行うとき
- 手動広告ユニット、独自広告script、広告ページの厳格CSP、Cloudflare Worker nonceを導入するとき
- HTMX 4安定版へ更新し、`hx-csp`が安定版の保守対象になったとき
- 信頼できないHTMLをサニタイズして表示する要件、cross-origin HTMX、iframe埋め込みが生じたとき
- CSP違反で基本機能が維持できず、静的JSへの移動では解決できないとき
- Cloudflare Worker等を既に運用し、edgeでのnonce注入を低コストに実現できるようになったとき

## 採用しなかった選択肢

- **原則`hx-on`**: `allowEval=false`と矛盾し、HTML属性を実行コードとして扱う経路を残すため不採用。
- **`unsafe-eval`を通常許可**: HTMXのeval依存機能は静的JSで代替でき、文字列からのコード生成をサイト全体で許可する理由がないため不採用。
- **全ページnonce**: Cloudflare HTMLキャッシュとの整合、nonce再利用、テンプレート運用のコストが現時点の機能に見合わないため不採用。
- **全公開ページの厳格CSP**: 閲覧中心の初期サイトでは、Auto Adsと共有HTMLキャッシュを犠牲にするコストが補助防御の便益を上回るため不採用。
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
- [Google AdSense: Get and copy the Auto Ads code](https://support.google.com/adsense/answer/9274019?hl=en)
- [Cloudflare Workers: Add CSP nonces with HTMLRewriter](https://developers.cloudflare.com/workers/examples/spa-shell/#add-csp-nonces)
- [Cloudflare Turnstile: Content Security Policy](https://developers.cloudflare.com/turnstile/reference/content-security-policy/)
