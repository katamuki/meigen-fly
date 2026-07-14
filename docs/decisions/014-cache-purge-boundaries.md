# アーキテクチャ決定記録: Cloudflareキャッシュパージの境界

## ステータス

**確定: 個別URL、依存タグ、TTLによる自然失効を更新規模に応じて使い分ける**（2026-07-14決定）

## コンテキスト

公開HTMLはCloudflareでキャッシュし、ADR 001の`Cache-Control`を正本とする。更新直後の個別ページは速やかに反映したい一方、一覧の全ページ番号を列挙したり、外部キューを導入したりする運用コストは個人開発の初期リリースには見合わない。本ADRは、ADR 001 §5のタグ名例とパージ対象表を置き換える。ADR 001は`Cache-Control`とcache eligibilityについて引き続き正本とする。

Cloudflareの公式仕様を2026-07-14に確認した。FreeプランでもURL、Hostname、Tag、Prefix、Purge Everythingを利用できる。URLパージは1要求100 URL、800 URL/秒で、Tag・Hostname・Purge Everythingは1要求100操作、5要求/分、token bucket 25である。Prefixは概要ページでは最大100操作とされる一方、方式別ページに最大30 prefix/要求とあるため、保守的に**30 prefix/要求**で実装する。APIは`POST /zones/{zone_id}/purge_cache`へ、URLなら完全なURLを`{"files": [...]}`、タグなら`{"tags": [...]}`として送る。URLパージはquery stringを含むキャッシュキー単位であり、独自cache keyを導入した場合はその構成ヘッダーも要求に含める必要がある。本サイトは初期リリースでは端末・地域・言語による独自cache keyを作らない。

## 決定

### 基本境界

- **URLパージ**は、管理画面の通常CRUDで変更対象を有限個の完全URLとして特定できる名言詳細、entity詳細、OG画像、`/sitemap.xml`に使う。slug変更時は旧URLと新URLの両方を対象にする。削除時も旧URLを対象にする。
- **タグパージ**は、一覧、ページング、トップ、ランキング、および関連entityを表示する複数ページに使う。全ページ番号を列挙しない。
- **Prefixパージ**と**Purge Everything**は通常処理では使わない。誤配信・秘密情報混入など緊急の全体無効化、タグ付与漏れの復旧、キャッシュ規約変更時だけ管理者がCLIから実行する。通常の一括登録を理由に使わない。Prefixを使う場合は最大30件ずつ送る。
- いいね追加ごとのパージはADR 006どおり行わない。いいね数を含むHTMLは最大約10分のTTLで更新し、ランキングへ反映するのはランキング再計算後とする。
- DB更新とパージAPI成功を同一transactionにはしない。DB更新を正本とし、Cloudflare障害時も管理更新自体は成功させる。

### `Cache-Tag`命名規則と付与規則

タグは小文字ASCIIの`^[a-z0-9][a-z0-9-]{0,63}$`に統一し、IDはDBの不変な数値IDを使う。表示名や変更可能なslugは使わない。Cloudflareではタグの大文字小文字が区別されず、スペースが許可されず、レスポンスの`Cache-Tag`ヘッダー合計が16 KBまでであるため、短い名前に限定する。

| 種別 | タグ | 用途 |
|---|---|---|
| 個体 | `quote-{id}`, `author-{id}`, `category-{id}`, `character-{id}`, `source-{id}`, `profession-{id}` | そのentityの値または関連を表示する全レスポンス |
| 一覧 | `quotes-list`, `authors-list`, `categories-list`, `characters-list`, `sources-list`, `professions-list` | 一覧の先頭、全ページング、latest等、その集合から生成するレスポンス |
| 派生 | `home`, `ranking` | トップ、ランキング結果またはランキング値を表示するレスポンス |
| 画像 | `og`, `quote-{id}`等 | OG画像全体と、画像が依存するentity |

各レスポンスには「そのURLの種類」だけでなく、実際に描画したentityの個体タグも付ける。例えば、名言カードを20件描画した`/quotes/page/2`には`quotes-list`と20件の`quote-{id}`、表示した著者名に対応する`author-{id}`を付ける。著者詳細に職業を表示するなら`author-{id}`と該当`profession-{id}`を付ける。これによりentity名や関連付けの変更を、その値を実際に表示するページだけへ波及できる。レスポンス当たりの描画件数を通常のページサイズに制限し、ヘッダー16 KBへ近づく場合はテストを失敗させる。

`sitemap`は単一URLを確実に指定できるためタグを設けず、`/sitemap.xml`をURLパージする。静的ファイルとして生成する場合も、生成物のatomic replace完了後に同じURLをパージする。

### 更新操作ごとのパージ対象

下表の「個体タグ」は、そのタグが付いた詳細だけでなく、そのentityを描画した一覧・関連ページも対象にする。「一覧タグ」は先頭から末尾までの全ページングを含む。初期実装では変更列ごとの細かな判定を作らず、**公開済みentityのCRUDでは表の対象を安全側に常時パージする**。非公開データだけの変更は対象外とする。

| 更新操作 | URLパージ | タグパージ | sitemap・ランキング |
|---|---|---|---|
| `quotes`追加 | 新しい`/quotes/{id}`と既知のOG URL | `quote-{id}`, `quotes-list`, `home`、関連する`author/category/character/source`個体タグ | `/sitemap.xml`をURLパージ。`ranking`は再計算前には落とさない |
| `quotes`本文・表示言語・公開状態・関連FKの編集 | 旧/新の詳細URLと既知の旧/新OG URL | `quote-{id}`, `quotes-list`, `home`、変更前後の関連entity個体タグ | `/sitemap.xml`をURLパージ。順位入力値を直接変えた場合も、再計算完了後に`ranking`を落とす |
| `quotes`削除 | 旧詳細URLと既知のOG URL | `quote-{id}`, `quotes-list`, `home`、削除前の関連entity個体タグ | `/sitemap.xml`をURLパージ。再計算完了後に`ranking` |
| `authors`追加・編集・削除 | 旧/新の`/authors/{slug}`と既知のOG URL | `author-{id}`, `authors-list`, `home`。削除時は削除前に参照関係を取得する | `/sitemap.xml`。再計算結果に影響する場合は完了後に`ranking` |
| `categories`追加・編集・削除 | 旧/新の`/categories/{slug}`と既知のOG URL | `category-{id}`, `categories-list`, `home` | `/sitemap.xml`。カテゴリランキング再計算完了後に`ranking` |
| `characters`追加・編集・削除 | 旧/新の`/characters/{slug}`と既知のOG URL | `character-{id}`, `characters-list` | `/sitemap.xml`。ランキング依存がある場合だけ完了後に`ranking` |
| `sources`追加・編集・削除 | 旧/新の`/sources/{slug}`と既知のOG URL | `source-{id}`, `sources-list` | `/sitemap.xml`。ランキング依存がある場合だけ完了後に`ranking` |
| `professions`追加・編集・削除 | 旧/新の`/professions/{slug}`と既知のOG URL | `profession-{id}`, `professions-list`, `authors-list` | `/sitemap.xml`。著者ランキングへ影響する場合は完了後に`ranking` |
| 名言とcategory/character/sourceの関連付け | 名言詳細と既知の名言OG URL | `quote-{id}`, `quotes-list`、変更前後の`category/character/source-{id}`、必要なら各一覧タグ | `/sitemap.xml`。再計算完了後にのみ`ranking` |
| 著者とprofessionの関連付け | 著者詳細と既知の著者OG URL | `author-{id}`, `profession-{id}`, `authors-list`, `professions-list` | `/sitemap.xml`。再計算完了後にのみ`ranking` |
| ランキングパラメータ変更・手動/定期再計算 | なし | **DB transactionが成功して新ランキングが読める状態になってから**`ranking`, `home` | sitemapは落とさない。順位を表示する一覧がある場合、そのレスポンスには`ranking`タグを付けるため全ページへ波及する |

関連付け変更では変更前のIDも必要なので、更新前に関連IDを読み、更新後IDとの和集合をoutboxへ登録する。外部キー削除のcascade後に推測しない。`countries`や`source_types`等、表にないentityを公開HTMLへ表示する場合も同じ「不変IDの個体タグ＋集合の一覧タグ」の規則を適用する。

### ページング・sitemap・ランキングへの波及

- `/quotes`、`/quotes/page/N`、`/quotes/latest`、`/quotes/latest/page/N`はすべて`quotes-list`を持つ。他entityの全ページングも対応する`*-list`を持つ。追加・削除・並び順変更は後続ページの境界をすべて変え得るため、一覧タグ1個で全ページをパージする。
- 公開済みentityのCRUDでは、列ごとの依存判定を保守する複雑さを避け、表に記載した個体タグと一覧タグを常時パージする。タグ要求数は少なく、Freeプランの制限内で安全側に倒せる。将来パージ量が問題になった場合だけ変更列による絞り込みを検討する。
- 公開済みentityのCRUDでは`lastmod`も更新されるため、表どおり`/sitemap.xml`を常時URLパージする。ランキング再計算だけではパージしない。sitemapのedge TTLは最大1時間とする。
- ランキング入力が変わるCRUDでは、古い計算結果のまま`ranking`を先にパージしない。再計算CLIのDB transaction成功後に`ranking`と`home`を登録する。再計算失敗時は既存ランキングを配信し続ける。

### 3秒集約とSQLite outbox

通常CRUDでは、同一DB transaction内で更新と必要なpurge itemを`cache_purge_outbox`へ登録する。UvicornはADR 005どおり初期は1 workerとし、最初のitem登録時にだけ起動するイベント駆動の軽量flusherが**3秒**だけ待って重複を除去し、URLとタグをそれぞれ最大100件へ分割して送る。これは定期ジョブをFastAPIのstartup/lifespanで起動するものではない。管理画面のHTTP応答はCloudflare APIを待たない。

outboxは`id`、`kind`（`url`または`tag`）、`value`、`state`（`pending|inflight|failed`）、`not_before`、`attempts`（実送信回数）、`lease_until`、`last_error`、`created_at`を持つ小さなSQLiteテーブルとする。`pending`行だけの`(kind, value)`部分一意indexにより、同じ3秒窓の更新をupsertで集約する。送信者は短い`BEGIN IMMEDIATE`でdueな行を`inflight`へclaimし、API timeout 10秒より十分長い**60秒lease**を設定する。API通信はtransaction外で行い、成功時はclaimした`id`だけを削除する。送信中に同じ値の更新が来た場合は別の`pending`行を作れるため、古い送信のackで新しい要求を消さない。

失敗またはlease切れの`inflight`行を戻す際、同じ`(kind, value)`の`pending`行がなければ、その行を`pending`へ戻して`attempts`を維持し、`not_before`をretry時刻にする。新しい`pending`行が既にあれば、1回の将来purgeが両更新を包含するため古い行を削除し、新しい行を残す。新しい行の`created_at`、`attempts`、`not_before`は変更せず、古い失敗は構造化ログだけに残す。この競合解消も短い`BEGIN IMMEDIATE`内で行う。

専用Redis、Cloudflare Queues、Celeryは導入しない。プロセス停止中の再送用に、同じdrain処理を行うCLIを起動時、デプロイ後、一括処理完了後、および既存supercronicから1分間隔で実行できるようにする。CLIとアプリflusherは上記のclaimにより同じ行を同時送信しない。

### API失敗時のretry・再送・TTL fallback

- 成功はHTTP 2xxかつレスポンスJSONの`success: true`の両方で判定する。purgeは冪等なので同じURL/タグを再送してよい。
- timeout、接続失敗、HTTP 429、5xxは再送する。429に`Retry-After`があれば従い、なければfull jitter付きで概ね5秒、30秒、2分、10分、30分後に、**初回送信に加えて最大5回**再試行する。
- 401/403とその他の恒久的な4xxは無限再試行せず、`last_error`へCloudflareのrequest ID・error codeを秘密情報なしで記録し、管理者へ通知する。通知はADR 005のジョブ失敗通知経路を共用し、未整備のローカル・初期環境では構造化error logとCLIの非ゼロ終了を最低要件とする。新しい監視サービスはD12のためだけに導入しない。tokenや要求Authorization headerはログへ出さない。
- 初回＋5回の計6回に失敗、または最初の登録から24時間経過したitemは`failed`として通知し、自動送信を止める。CLIで原因修正後に再queueできる。失敗レコードは7日保持する。
- 通常更新の最終fallbackはADR 001のedge TTLによる自然失効である。目安は名言詳細・一覧・ランキング10分、entity一覧1時間、著者詳細1日、OG画像30日である。sitemapは上記の1時間以内とする。

法的要請、秘密情報混入、その他TTL待ちを許容できない緊急削除には、通常outboxとは別の**critical CLI経路**を使う。DB更新直後に完全URLまたはタグを同期送信し、最初の失敗で直ちに通知する。対象を列挙できる限りURL/タグを再送し、列挙不能なら待たずにPrefixまたはPurge Everythingへ手動で拡大する。Cloudflareのパージ対象はedge cacheであり、利用者のブラウザへ既に保存された`max-age`中のコピーは無効化できない。公開済みの秘密情報を完全に回収できる仕組みとはみなさず、必要に応じて元のcredential等も直ちに失効させる。

### 一括登録の境界

1 transactionまたは1 CLI実行で変更する主entity件数により次のように扱う。

- **100件以下**: 通常CRUDと同じ。個別URL、個体タグ、集合タグをoutboxへ集約し、完了後にdrainする。
- **101〜500件**: 一覧タグ、`home`、`/sitemap.xml`、変更した個別URL/OG URLは即時対象にする。個体タグは必要なものを100件ずつ送る。一括処理中は送らず、transaction成功後にまとめる。
- **501件以上、初期データ移行、全件再生成**: `*-list`、`home`、`ranking`（再計算成功後）、`og`、`/sitemap.xml`だけをパージする。各個別詳細のURL・個体タグは列挙せずTTLへ委任する。公開前の初期投入ではwarm cacheがないためパージ自体を行わない。

件数だけでなく、公開済みの誤情報修正・削除・slug変更は501件以上でも個別URLを優先して100件ずつ送る。逆に非公開データだけの変更はpurge itemを作らない。これらの境界により、通常運用の即時性を保ちつつ、大量更新のための別queue基盤や全キャッシュパージを不要にする。

## 検証

- 各公開routeについて期待する`Cache-Tag`をテストし、16 KB未満、小文字ASCII、スペースなしを検証する。Cloudflare通過後はvisitorへ`Cache-Tag`が露出しないこともstagingで確認する。
- 追加・削除でページ境界が変わるfixtureを使い、先頭だけでなく任意のページングURLが一覧タグのpurge後にMISSになることを確認する。
- slug変更、関連付け解除、cascade deleteで変更前後両方のURL・個体タグがoutboxへ入ることをテストする。
- Cloudflare APIのtimeout、429＋`Retry-After`、5xx、401、`success: false`をstubし、再送、停止、通知、秘密情報非出力を検証する。
- flusherとCLIを同時起動し、claimにより二重処理しないこと、送信中の同値更新を古いackで消さないこと、claim直後のプロセス停止後にlease切れで再送できることを検証する。
- ランキング再計算失敗時は`ranking`をpurgeせず、成功時だけ`ranking`と`home`をpurgeする。
- 一括処理の100/101/500/501件境界と、公開前初期投入でAPIを呼ばないことをテストする。

## 採用しなかった選択肢

- **全更新でPurge Everything**: originへの集中と無関係な静的資産のMISSを招くため不採用。
- **全ページングURLの列挙**: 最終ページ把握、同時更新、route追加への追従が壊れやすいため、一覧タグへ置き換える。
- **すべてタグパージ**: 個別URLパージよりFreeプランの要求レートが低く、slug変更時の旧URLを明示する方が安全なため不採用。
- **Redis/Celery/外部managed queue**: 3秒集約と少量の再送にはSQLite outboxと単一flusherで十分なため不採用。
- **更新リクエスト内の同期retry**: 管理画面の応答をCloudflare障害へ結合するため不採用。
- **通常運用でPrefixパージ**: query stringを含む配下全体を広く落とし、意図しないorigin負荷を生むため不採用。

## 再検討条件

- Uvicornを複数workerまたは複数Machineへ増やす場合
- パージ待ちが継続的に1分を超える、outboxが1,000件を超える、またはFreeプランの制限へ反復して到達する場合
- 独自cache key、言語別variant、Cloudflare Workers、Cache Reserveを導入する場合
- 30日TTLのOG画像で、失敗時の自然失効を待てない更新が通常運用になる場合

## 公式仕様（2026-07-14確認）

- [Cloudflare: Purge cache - availability and limits](https://developers.cloudflare.com/cache/how-to/purge-cache/)
- [Cloudflare API: Purge Cached Content](https://developers.cloudflare.com/api/resources/cache/methods/purge/)
- [Cloudflare: Purge cache by cache-tags](https://developers.cloudflare.com/cache/how-to/purge-cache/purge-by-tags/)
- [Cloudflare: Purge by single-file](https://developers.cloudflare.com/cache/how-to/purge-cache/purge-by-single-file/)
- [Cloudflare: Purge cache by prefix](https://developers.cloudflare.com/cache/how-to/purge-cache/purge_by_prefix/)
- [Cloudflare: Purge everything](https://developers.cloudflare.com/cache/how-to/purge-cache/purge-everything/)
