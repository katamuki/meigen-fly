# アーキテクチャ決定記録: 匿名いいね数の表示・キャッシュ方式

## ステータス

**表示・キャッシュ方式を確定: いいね数を公開HTMLへ含める**（2026-07-13決定）

多重投票対策の閾値、`ip_hash`の保持期間、salt rotation、Turnstile導入条件はD9の未決事項として別途確定する。

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

- オリジン直撃を拒否するD14の実装を、公開いいねのリリース前提とする。信頼できるCloudflare経路からのみ `CF-Connecting-IP` を受け入れる。
- exact `Origin`、Fetch Metadata、Content-Typeを検証し、Cloudflareとアプリの両方でレート制限する。Origin/Refererだけをbot対策とはみなさない。
- `(quote_id, client_uuid)` をDBの一意制約にし、`ip_hash`は共有NATを考慮して即時の一律拒否ではなく、レート制限・不正検知の補助信号とする。これはbest-effortの多重抑制であり、強い本人認証ではない。
- INSERT、重複判定、最新件数取得は短い単一transactionで行う。重複は冪等な成功応答、レート超過は429、SQLite競合をretry後も解消できない場合は503とする。
- 生IPは保存しない。`ip_hash`の保持期間とsalt rotationはprivacy policyと合わせてD9で確定する。
- 正常利用を妨げない閾値で開始し、bot増加や不正率上昇が観測された場合にTurnstileを追加する。

## 検証

- 名言詳細・一覧の2回目アクセスがCloudflare HITになり、10分TTL後に最新件数へ更新される。
- `POST /api/likes/{quote_id}` が常にno-store/Bypassで、GETは405になる。
- POST成功直後のDOM更新、TTL内のstale表示、TTL後の件数更新をE2Eで確認する。
- localStorage無効・削除、重複client_uuid、共有IP、偽装 `CF-Connecting-IP`、rate limitを確認する。
