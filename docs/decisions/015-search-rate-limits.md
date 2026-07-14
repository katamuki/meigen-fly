# アーキテクチャ決定記録: 検索UIとレート制限

## ステータス

**確定: 1文字から500ms debounceで検索し、アプリ側IP制限を正本とする**（2026-07-14決定）

## コンテキスト

`/search`はCloudflareでキャッシュしないHTMXインクリメンタル検索であり、入力のたびにSQLite FTS5を実行すると、通常利用でもリクエスト数が増え、単一Fly Machineへ直接負荷がかかる。一方、日本語は「愛」「夢」のように1文字でも有効な検索語がある。ADR 002はFTS5 + アプリ側bigramを採用し、1文字だけ`LIKE`で補助する方針のため、一律2文字以上にすると既存の検索契約と日本語UXを損なう。

初期構成は個人運用、Uvicorn 1 worker、約3,000件規模である。Redis、Turnstile、分散カウンターを追加せず、通常利用を妨げない範囲で過剰リクエストを抑える。

## 決定

### 入力と検索実行

- 検索開始の最小文字数は、後述の空白正規化後で**1文字**とする。1文字の日本語検索を許可し、ADR 002どおり1文字だけ上限付き`LIKE`、2文字以上はFTS5 + アプリ側bigramを使う。1文字だけを理由にエラーや追加認証を出さない。
- 入力値は先頭・末尾のUnicode空白を除去し、連続するUnicode空白をASCII 1個へ畳む。この正規化後の値を表示、文字数判定、検索、同一値判定に共通利用する。Unicode正規化や大文字小文字変換はこのADRでは追加しない。
- インクリメンタルUIでは、正規化後0文字ならDB検索もHTTPリクエストも行わず、結果領域を空の初期表示へ戻す。上限は100 Unicodeコードポイントとし、超過時は検索せず入力欄付近へ案内する。サーバーも同じ正規化・0〜100文字の検証を行い、0文字は初期表示を返してDB検索しないため、クライアント判定はセキュリティ境界にしない。
- インクリメンタル検索は最後の確定入力から**500ms**のtrailing debounceとする。300msよりリクエストを抑えつつ、検索UIとして待ち時間を認識しにくい値である。
- 本ADRはADR 002にある`keyup changed delay:300ms`の実装例を上書きする。統合時にADR 002の例を本ADRへの参照へ置き換え、debounceとイベント方式の正本を本ADRへ一本化する。
- `keyup`を起点にしない。外部の静的JavaScriptが`input`、`compositionstart`、`compositionend`を監視し、IME composition中はタイマーを停止する。確定後の現在値に対して500msを計り、前回送信した正規化値と異なる場合だけ`search:changed`カスタムイベントをdispatchする。HTMLは概ね`hx-get="/search"`、`hx-trigger="search:changed queue:last"`、`hx-include`、`hx-target`で現在の入力値を送る。イベントフィルタや`hx-on`へJavaScript式を書かない。
- Enterまたは検索ボタンによる通常のGET form submitはdebounceを待たず実行する。JavaScript無効時もこの通常ページ検索を利用できる。HTMXの実行中に新しい確定値が来た場合は`queue:last`で最新1件だけを後続実行し、中間値を全件queueしない。

### `/search`のHTTP契約

- 通常の`GET /search?q=...`は検索フォームを含む完全なHTML文書を返す。`HX-Request: true`の同じGETは、同じ正規化、検証、検索、結果順、件数上限を使い、結果領域用HTML fragmentだけを返す。クライアントが送る`HX-Request`は表現選択にだけ使い、レート制限の回避や権限判定には使わない。
- 通常ページとfragmentを同じIPカウンターで評価する。成功、空文字、入力不正を含む`GET /search`を、検索実行より前に制限対象とする。これにより空クエリ連打で制限を回避できない。
- 全応答に`Cache-Control: private, no-store`を付け、Cloudflare Cache Rulesでも`/search`をBypassする。表現が`HX-Request`で変わるため`Vary: HX-Request`も返す。ADR 001の非キャッシュ方針を変更しない。
- 本番のIPキーは、ADR 013のTunnel境界を前提に、単一かつ妥当なIPv4/IPv6の`CF-Connecting-IP`から得る。欠落、重複、カンマ区切り、不正値では`X-Forwarded-For`やsocket peerへfallbackせず400にする。開発・テストは明示した非本番設定でテストIPを注入し、本番fallbackを作らない。

### アプリ側レート制限（正本）

- IPごとのrolling windowをプロセスメモリに持ち、**10秒に30リクエスト**または**60秒に120リクエスト**を超える`GET /search`を429にする。短時間のburstと継続的な走査の両方を抑える。500msのtrailing debounceは入力が続く間タイマーを更新し、確定後の停止時だけ送るため、通常の1入力系列が120回/分へ達することは想定しない。共有NATでは全利用者が同じIPキーになるため、通常利用の観測で誤制限が出たら、先に60秒閾値を上げる。
- 許可判定とカウンター更新は同じロック内で行い、**許可したリクエストだけ**timestampを追加する。拒否リクエストは窓を延長しない。10秒窓が満杯なら30番目に新しい許可timestampが10秒窓を外れるまで、60秒窓が満杯なら120番目に新しい許可timestampが60秒窓を外れるまでを計算し、両方に該当する場合は長い方を切り上げて`Retry-After`とする。IPとtimestampだけを保持し、queryは保持しない。60秒より古いtimestampを捨て、最終アクセスから5分経過したIPエントリーをlazy cleanupする。IPをDBへ永続化せず、通常のアプリログにも生値を追加しない。IPだけを根拠とする永続的なdenylistや手動banは作らず、共有NATを恒久的に検索不能にしない。
- これはUvicorn 1 worker内の**best-effort**制限である。プロセス再起動・デプロイでカウンターが消えることを受容する。カウンター保存のためにSQLiteへ書き込まず、Redisも導入しない。workerを2以上またはMachineを複数へ増やす場合は、各プロセスで制限が倍化するため再設計条件とする。

### Cloudflareの役割

- Cloudflareは大量burstをorigin到達前に落とす補助層、アプリは通常ページとHTMXを同じ契約で確実に扱う正本とする。Cloudflareのカウンターはデータセンター単位で、反映に数秒遅れる場合があり、正確な許可件数を保証しない。
- 2026-07-14確認時点でCloudflare FreeのRate Limiting Rulesはzoneあたり1本、式で使える主な対象はPathとVerified Bot、カウント特性はIP、counting periodとmitigation timeoutはいずれも10秒である。この1枠は不正な書き込みを守るD9へ優先配分するため、**検索用Cloudflareルールは初期リリースの必須条件にしない**。Cloudflare側が未配置・設定失敗でも、アプリの30/10秒・120/60秒制限は動作する。
- Freeの1枠が検索へ利用可能になった場合だけ、verified botを除外して正確なpath `/search`をIPごと**30リクエスト/10秒、Block 10秒、既定429**で保護する。Freeではmethodやqueryを条件にせず、通常ページとHTMXを同じように数える。Cloudflare側の制約やUIが変わっていたら、デプロイ時に公式仕様を再確認する。
- Turnstile、Managed Challenge、Bot Management、有料プランへの移行は初期導入しない。レート制限後も検索によるCPU高騰や可用性低下が実測され、閾値調整では共有NATの誤判定と防御を両立できない場合にだけ再検討する。

### 429とHTMX UI

- アプリが返す429には、次に許可され得るまでの整数秒を`Retry-After`（最低1）で付け、`Cache-Control: private, no-store`と`Vary: HX-Request`も付ける。通常GETには完全なエラーページ、HTMXには小さいエラーfragmentを返す。
- HTMXは既定で4xx本文をswapしないため、外部の静的JavaScriptで`htmx:responseError`（採用版のイベント名をpin時に確認）を処理する。status 429なら既存の検索結果を消さず、`#search-status`の`aria-live="polite"`領域へ「検索が続いています。N秒待ってから再度お試しください」を表示する。Cloudflare生成429/1015などアプリのfragmentでない本文をDOMへ挿入しない。接続失敗は別途`htmx:sendError`、timeoutを設定する場合は`htmx:timeout`も同じ外部JavaScriptで処理する。
- クライアントは`Retry-After`が妥当な整数ならそれを表示に使い、欠落・不正なら10秒を案内する。タイマー表示はしてよいが、期限後の**自動再試行はしない**。自動再試行による再制限を避け、利用者が入力変更、Enter、検索ボタンのいずれかで明示的に再試行する。
- 429以外の4xx/5xxやネットワークエラーは「検索に失敗しました。時間をおいて再度お試しください」とし、レート制限と断定しない。入力欄は無効化せず、古い結果を残す。

## 実装・検証条件

- 空白のみ、先頭末尾空白、連続空白、1文字日本語、2文字日本語、100文字、101文字で、通常GETとHTMX fragmentの正規化・結果が一致する。
- 遅いIME変換中にリクエストが出ず、`compositionend`後500msで1回だけ送信される。高速入力、値を戻す操作、リクエスト中の追加入力で最新値だけが最終表示になる。
- 同一IPの30/10秒と120/60秒の境界、拒否リクエストが解除時刻を延長しないこと、両方の窓から算出する`Retry-After`、別IPの独立性、時刻境界、lazy cleanupを単調時計を注入した単体テストで確認する。
- 429の`Retry-After`、`no-store`、通常ページ/fragment、aria-live表示、結果維持、自動再試行なしを確認する。Cloudflare生成429相当のHTMLでも本文を結果領域へswapしない。
- 本番相当テストで正しい`CF-Connecting-IP`を受け入れ、欠落、重複、カンマ区切り、不正なIPv4/IPv6を拒否する。
- リリース後は`/search`のリクエスト数、p95、429率、SQLite/CPU負荷を集計する。queryと生IPを追加収集しない。通常利用で429が発生する場合は閾値を上げ、攻撃負荷が残る場合はCloudflare枠の配分または追加対策を再検討する。

## 再検討条件

- Uvicornを複数worker化、Fly Machineを複数台化、または検索を別serviceへ分離する場合
- データ量増加により1文字`LIKE`またはFTS5検索の負荷が、レート制限下でも許容できなくなった場合
- 共有NATから正規利用者の429が継続する場合
- 検索scrapingやDDoSで可用性影響が実測され、Cloudflare Free 1枠の配分やアプリ閾値では抑えられない場合
- HTMXのmajor versionを変更し、イベント名、4xx response handling、`hx-trigger`のqueue/debounce semanticsが変わる場合

## 採用しなかった選択肢

- **2文字以上のみ検索**: DB負荷は下がるが、日本語1文字語を失いADR 002の1文字fallbackとも矛盾するため不採用。
- **300ms debounce**: 通常入力でリクエストが増えやすい。初期の検索体感には500msで十分なため不採用。
- **一律60リクエスト/分**: 500msの連続入力、複数タブ、共有NATを正規利用のまま制限しやすいため不採用。
- **Cloudflareだけで制限**: Freeの1ルール枠をD9と競合し、カウンターもデータセンター単位で厳密ではないため不採用。
- **Redis/SQLite永続カウンター**: 単一workerの初期構成では運用または書き込み負荷に見合わないため不採用。
- **Turnstile/Challengeを常時表示**: 読み取り検索のUXとアクセシビリティを悪化させ、現時点の実害がないため不採用。

## 公式仕様の確認（2026-07-14）

- [Cloudflare Rate limiting rules](https://developers.cloudflare.com/waf/rate-limiting-rules/) — Freeの式、IPカウント、10秒period/mitigation、1ルール、反映遅延を確認。
- [Cloudflare request rate calculation](https://developers.cloudflare.com/waf/rate-limiting-rules/request-rate/) — カウンターがデータセンター単位でありglobalではないことを確認。
- [Cloudflare Error 1015](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1015/) — rate limit時は待ってから再試行し、短時間の反復再試行を避ける案内を確認。
- [htmx `hx-trigger`](https://htmx.org/attributes/hx-trigger/) — `changed`、`delay`、`queue:last`の現行semanticsを確認。本ADRはIME制御とCSP整合のため外部JavaScriptからカスタムイベントをdispatchする。
- [htmx Requests & Responses](https://htmx.org/docs/#requests) / [htmx Events](https://htmx.org/events/) — 既定では4xxをswapせずerror eventにすることを確認。
