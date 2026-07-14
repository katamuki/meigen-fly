# アーキテクチャ決定記録: 匿名いいね数の表示・キャッシュ方式

## ステータス

**採用**（表示・キャッシュ方式: 2026-07-13決定、不正対策: 2026-07-14決定）

## コンテキスト

ページ本体をCloudflareでキャッシュしても、いいね数を毎PVで非キャッシュAPIから取得すると、全ページビューがFly.ioとSQLiteへ到達し、オリジン負荷削減効果を相殺する。

現状のアクセス規模では厳密なリアルタイム件数より、単純な構成とキャッシュヒット率を優先する。

## 決定

- 名言詳細と名言一覧（`/quotes/{id}`、`/quotes`、`/quotes/page/*`、`/quotes/latest`、`/quotes/latest/page/*`）は、SSR時に各名言の `like_count` をHTMLへ含める。
- いいね数を取得する毎PVのGET APIやHTMX断片APIは作らない。
- 名言詳細・一覧は `Cache-Control: public, s-maxage=600, max-age=60` とし、いいね数は最大約10分の遅延を許容する。
- 他の公開ページでいいね数を表示する場合も10分以下のedge TTLにする。既存TTLを維持したいページではいいね数を表示しない。
- いいね登録は公開HTMLとは別prefixの `POST /api/likes/{quote_id}` とし、`Cache-Control: private, no-store`、Cloudflare Bypassを必須にする。GETのいいねAPIは提供しない。
- POST成功時は最新件数を含むHTML断片またはJSONを返し、押した本人のDOMだけ即時更新する。いいねごとのCloudflareパージは行わない。
- TTL内の再読込ではキャッシュ済みの古い件数へ一時的に戻り得ることを受容する。「いいね済み」状態はlocalStorageから復元する。
- 公開ページにユーザー識別Cookieを付けない。`client_uuid`はlocalStorageで管理する。
- いいね数を含む名言HTMLは `quote.updated_at` だけでは正しいETagを作れないため、名言詳細ではETagによる条件付き再検証を行わずTTLで更新する。

## 公開書き込みの前提

- Cloudflare Tunnelを唯一の公開HTTP経路にしてFlyのpublic IP/serviceを削除するD14（[ADR 013](013-cloudflare-tunnel-origin-protection.md)）の実装を、公開いいねのリリース前提とする。匿名いいねPOSTでは単一かつ妥当なIPv4/IPv6の`CF-Connecting-IP`だけを受け入れ、`X-Forwarded-For`等へfallbackしない。
- exact `Origin`、Fetch Metadata、Content-Typeを検証し、Cloudflareとアプリの両方でレート制限する。Origin/Refererだけをbot対策とはみなさない。
- `(quote_id, client_uuid)` をDBの一意制約にし、`ip_hash`は共有NATを考慮して即時の一律拒否ではなく、レート制限・不正検知の補助信号とする。これはbest-effortの多重抑制であり、強い本人認証ではない。
- INSERT、重複判定、最新件数取得は短い単一transactionで行う。重複は冪等な成功応答、レート超過は429、SQLite競合をretry後も解消できない場合は503とする。
- 生IPはアプリDBへ保存せず、IPを認証identityや「一人一票」の根拠にしない。

## 多重投票・レート制限

初期リリースでは専用の外部レート制限基盤を増やさない。Cloudflareを短時間の粗い洪水防止、単一Machine上のアプリ内TTLカウンターを長めの窓と複合キーの判定、DB一意制約を確定的な重複抑止に使う。上限超過時は`Retry-After`を付けた429を返す。再起動でアプリ内カウンターが消えることはbest-effort対策として受容し、DB一意制約は消えない。

構文、`Origin`、Fetch Metadata、Content-Type、`CF-Connecting-IP`を検証できたPOSTを、重複を含めて次の各窓へ加算する。不正形式はDB処理前に拒否する。

| 判定単位 | 初期値 | 動作と意図 |
| --- | --- | --- |
| Cloudflareの送信元IP | 30回/1分 | 超過後1分間block。明らかなburstをorigin到達前に止める |
| アプリの`ip_hash` | 60回/10分、300回/24時間 | 超過は429。共有NATを考慮した高めの洪水防止上限であり、投票重複判定には使わない |
| `client_uuid` | 10回/10分、100回/24時間 | 超過は429。値はUUID形式・最大長を検証し、任意文字列でカウンターを増殖させない |
| `quote_id` | 600回/10分 | 超過は429。特定名言への集中でSQLiteが圧迫される場合の全体安全弁 |
| `ip_hash` + `quote_id` | 20回/10分 | **これ単独では拒否しない**。共有NATの誤判定を避け、Turnstile判断と不正調査の集計信号にだけ使う |
| `client_uuid` + `quote_id` | 成功1回（期限なし） | DBの一意制約で保証。再送は件数を増やさず、最新件数を返す冪等な成功とする |

10分窓は1分bucketを10個、24時間窓は1時間bucketを24個合計する近似sliding windowとし、`Retry-After`は超過を解消する最古bucketの失効までとする。全dimension合計で最大50,000キーのTTL付きLRU cacheとし、期限切れを優先削除する。満杯時に未失効キーをevictした場合は制限が一時的に弱まることをbest-effortとして受容し、件数を通知する（攻撃者が任意キーで503を起こせるfail closedにはしない）。CloudflareのIP制限とDB一意制約は継続する。`client_uuid`は利用者が変更できるため強い端末識別ではなく、フィンガープリントは追加しない。閾値、最大キー数、bucket幅は設定値としてコードから分離するが、初期段階では管理画面や動的設定サービスを作らない。

### 共有NATの扱い

- 同一IPから別の`client_uuid`が同じ名言へ投票しても、IP一致だけでは重複扱いしない。
- IP単位の上限はorigin保護の高い上限に限定し、低い「1 IP = 1票」制約、IPv4 subnet単位の拒否、IPv6 prefixへの独自丸めは行わない。
- `ip_hash + quote_id`超過は記録するだけとし、拒否には端末上限、IP全体上限、名言全体上限のいずれかの超過を必要とする。
- 429件数と、1 IP配下の異なる`client_uuid`数を日次ジョブで集計する。正当な共有NATの可能性がある429が1日5件以上なら通知し、確認できた場合はIP上限を緩和して端末・全体上限を維持する。平常日の人手確認は行わない。

## `ip_hash`のライフサイクル

- `CF-Connecting-IP`をIP parserで検証し、IPv4/IPv6を区別する1 byteのfamily markerと、ネットワークバイト順のpacked address（IPv4は4 bytes、IPv6は16 bytes）を連結した値から`HMAC-SHA-256(secret, family || packed_address)`を生成する。入力文字列を直接hashせず、IPv6の圧縮・ゼロ埋め・大文字小文字が違っても同じhashにする。文書・環境変数名では既存の`RANKING_IP_HASH_SALT`を維持できるが、実体は32 bytes以上の暗号学的乱数による秘密鍵とする。DBにはhashと鍵世代だけを保存する。
- 稼働DBの`ip_hash`列はnullableとし、作成から**30日**で`NULL`化する。日次cleanupで期限切れを処理し、匿名いいねレコードと`client_uuid`による一意性、集計済みの件数は残す。稼働DBでは期限後にIP横断分析を再現できる情報を残さない。
- 秘密鍵は**30日ごと**にローテーションする。自動的な外部KMSは導入せず、秘密設定に`current`、`previous`、世代IDを保持し、運用チェックリストに沿って更新する。
- 更新後24時間は、読み取り・レート判定時にcurrentとpreviousの両hashを照合し、新規書き込みはcurrentだけを使う。全インスタンス（初期は1台）がcurrentへ移行したことを確認してからpreviousを削除し、previous世代のDB hashも`NULL`化する。したがってローテーション境界では30日未満のhashが早く消える場合があるが、プライバシーを優先して受容する。旧鍵をさらに保持して連続追跡しない。
- cleanup失敗時はエラーを通知し、次の日次実行で再送する。48時間を超えて未削除なら公開書き込みを止める必要はないが手動対応する。ローテーションに失敗した場合は旧currentを継続し、半端な世代変更を行わず通知する。秘密鍵の欠落・不正時は生IPや無鍵hashへfallbackせず、POSTを503にしてfail closedとする。
- ADR 003の日次バックアップには取得時点のhashが含まれ、30日のバックアップ保持により稼働DBからの`NULL`化後も最大30日残り得る（作成から最大約60日）。復旧時は、30日を超えたhashと復旧環境のcurrent/previousに存在しない鍵世代のhashを`NULL`化し、検証が終わるまでアプリを起動せず公開書き込みを再開しない。ADR 003の復旧手順にもこのgateを反映する。バックアップだけを編集する仕組みや別の暗号基盤は初期導入せず、この限定された追加保持をPrivacy Policyへ明記する。
- アプリケーションログへ生IP、`ip_hash`、`client_uuid`を通常出力しない。調査用集計は件数だけとし、30日より長く識別子を含むデバッグログを保持しない。

## Turnstileの導入境界

初期リリースではTurnstileを載せない。supercronicの日次ジョブで、いいねPOST総数、成功、冪等重複、各レート制限キーの429、`ip_hash + quote_id`のsoft超過、5xx、p95応答時間、手動取消件数を集計する。識別子を含まない日次件数だけをSQLiteへ90日保持し、次の条件到達時だけ通知する。条件2は保持中のいいねレコードを日次ジョブで集計し、該当hash自体は通知・日次集計へ残さない。専用監視基盤や平常時の日次目視は追加しない。次のいずれかを満たしたら、単に閾値を厳しくする前にTurnstileのmanaged widgetを**全いいねPOST**へ導入する。

1. 1日100件以上のPOSTがある日に、429またはsoft超過がPOSTの10%以上となる状態が3日連続する。
2. 同一の`ip_hash + quote_id`から1時間に20個以上の新しい`client_uuid`が現れる事象が、7日間に2回以上ある。
3. 不正いいねを1回50件以上手動取消する事案が30日間に2回以上ある。
4. いいね集中に起因して5xxが15分窓で1%以上、またはp95が1秒以上となる事象が7日間に2回以上ある。

導入時はPrivacy Policyを先に更新し、tokenを各POSTでbackendのSiteverify APIへ送り、`hostname`と`action`も検証する。token不正・期限切れは投票せず再試行UIを返す。Siteverify timeout/障害は投票せず503とし、短いtimeoutと限定回数のretryを行う（レート制限を迂回するfail-openはしない）。秘密鍵をfrontendへ出さない。30日連続で全条件を下回っても、運用変更による再発リスクを確認してから撤去を判断し、自動では切り替えない。

## Privacy Policyへ記載する内容

公開いいねの提供開始前に、少なくとも次を平易に明記する。法的な「匿名化済み」とは断定しない。

- 不正投票防止とサービス保護のため、ブラウザのlocalStorageにランダムな`client_uuid`を保存し、送信元IPから秘密鍵付きhashを作成すること。いいね機能は識別Cookieや端末フィンガープリントを使わないこと。
- `client_uuid`、対象名言、いいね日時、IP hashの利用目的（重複抑止、レート制限、不正調査）と、IP hashを稼働DBでは30日以内に削除すること（鍵ローテーション時はより早く削除する場合がある）。日次バックアップ内では作成から最大約60日残り得るが、災害復旧にだけ利用し、復旧時に期限切れを削除すること。`client_uuid`は利用者がサイトデータを消すまでlocalStorageに残り、DBの匿名いいねレコードと集計件数は対象名言またはサービスを削除するまで保持されること。
- 生IPをいいねDBへ保存しない一方、CloudflareやFly.io等の通信・セキュリティログではIPが処理され得ること。各委託先、保存期間、国外処理等は実際の契約・ログ設定に合わせて別途記載し、IP hashの稼働DB内30日保持と混同しないこと。
- Turnstileを導入する場合は、Cloudflareへ検証token、IP等が送信される目的、Cloudflareが外部処理者であること、関連するポリシーへのリンクを有効化前に追記すること。
- localStorageの削除方法、いいね済み表示が解除され得ること、問い合わせ先。保存済みいいねを特定して削除できると保証する場合は、実際に本人確認・検索できる手段を用意してから記載すること。

## 公式仕様の確認

2026-07-14に次の公式資料を確認した。

- [Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/): `CF-Connecting-IP`はCloudflare edgeからoriginへの通信で付与され、通常は単一IP形式。同一zone Worker subrequestでは値の扱いが変わるため、ADR 013の再評価条件を維持する。
- [Cloudflare Turnstile: Validate the token](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/): server-side Siteverifyが必須で、tokenは5分間有効かつsingle-use。導入時のfail closed、再試行、`hostname`/`action`検証の根拠とする。

## 検証

- 名言詳細・一覧の2回目アクセスがCloudflare HITになり、10分TTL後に最新件数へ更新される。
- `POST /api/likes/{quote_id}` が常にno-store/Bypassで、GETは405になる。
- POST成功直後のDOM更新、TTL内のstale表示、TTL後の件数更新をE2Eで確認する。
- localStorage無効・削除、重複client_uuid、共有IP、偽装 `CF-Connecting-IP`、rate limitを確認する。
- 各キーの窓・境界値（上限ちょうど、上限+1、期限直前/直後）、429の`Retry-After`、カウンター上限とTTL破棄、アプリ再起動後もDB一意制約が維持されることを確認する。
- bucket境界をまたぐ窓、50,000キー到達時の期限切れ優先削除・LRU eviction・通知、eviction後もCloudflare制限とDB一意制約が機能することを確認する。
- IPv6の圧縮・非圧縮、大文字・小文字等の等価表現が同じhashとなり、IPv4とIPv6のfamilyが混同されないことを確認する。
- current/previous両世代での照合、新規書き込みがcurrentだけになること、24時間後の旧鍵削除、30日cleanup、cleanup/rotation失敗時の再送・通知、鍵欠落時503を確認する。バックアップ復旧後・公開再開前に期限切れ・未知鍵世代のhashが`NULL`化されることと、ログに生IP・hash・`client_uuid`が出ないことも確認する。
- Turnstile導入時はテスト用sitekey/secretで成功、不正、期限切れ・再利用、hostname/action不一致、Siteverify timeout/障害時503と再試行UIを確認する。
