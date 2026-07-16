# 第2部: アプリからの利用状況

作成日: 2026-07-16

## 1. 範囲、調査方法、制約

本書は、`/Users/sonoda/prj/meigensyu` の現行アプリコードが、第1部で確定したDB objectをどう利用しているかを記録するフェーズ2成果物である。維持・廃止の判断、SQLite向けの再設計、実装提案は扱わない。

### 1.1 調査方法

次を読み取り専用で確認した。

- `src/` のservice/data access、公開page、管理画面、API route。Supabase clientの `.from()` / `.rpc()`、生成型を起点に呼出し元まで追跡した。
- tracked 43件の `scripts/`。既知の秘密情報保有可能性がある `scripts/backup_via_copy.sh` は本文を表示せず、残る42件についてobject名、SQL、RPC呼出しを検索した。
- ranking、view/MV、function、trigger、RLS、index、cronは、アプリからの直接呼出しだけでなく、呼び出したRPC・書込みtableからのDB内部の間接経路も追った。
- 完全名、短縮名、`.from()`、`.rpc()`、SQL文字列、生成型、migration定義を `rg` で検索した。型・DDL・migrationへの定義だけの一致は、runtime利用とは区別した。

「利用箇所あり」は、(a) アプリの直接アクセス、(b) アプリが呼ぶDB objectからの間接利用、(c) 検証・運用scriptの利用、のいずれかである。「リポジトリ内で利用箇所なし」は、本番で未使用という意味ではない。

### 1.2 role / keyの前提

- 公開のstatic clientはanon key: `src/lib/supabase/server-static.ts:15-22`。
- cookie付きserver clientは、未ログイン時anon、session成立時authenticated: `src/lib/supabase/server.ts:31-39`。
- いいね書込みと管理CRUDはservice role client: `src/services/supabase/service-client.ts:27-36`, `src/lib/supabase/admin.ts:9-30`。
- 管理者確認だけはauthenticated sessionで`admin_users`のown rowを読む: `src/lib/auth/admin-check.ts:14-82`, `src/lib/auth/server.ts:41-82`, `src/middleware.ts:112-142`。

service roleはRLSをbypassするため、そのアクセスをpolicyの「利用あり」には数えていない。policyはanon/authenticated経路で実際に適用対象となるものだけを利用ありとした。

### 1.3 確度ラベルと制約

- **リポジトリ内で一致**: コードとDB定義または複数コード箇所が一致する。
- **リポジトリから推定**: SQL plannerのindex選択など、経路はあるが実行時挙動をrepositoryだけでは確定できない。
- **本番確認待ち**: job実在、実行履歴、実効権限、データ状態など本番確認が必要。

本番DB接続、SQL実行、Supabase操作は行っていない。`.env`、接続文字列、key等の秘密値は読んでおらず、`scripts/backup_via_copy.sh`の本文も表示・転記していない。`meigensyu`は変更していない。

## 2. 母集団のカバー状況

第1部の全objectを個別に§4で記録した。件数は次のとおり。

| object種別 | 母集団 | 利用箇所あり | リポジトリ内で利用箇所なし | 備考 |
|---|---:|---:|---:|---|
| table | 20 | 20 | 0 | `legacy_votes`はranking MV経由の間接利用を含む |
| view | 3 | 1 | 2 | 管理KPI view 2件はruntime参照なし |
| materialized view | 4 | 4 | 0 | `quote_ranking_scores_mv`はrefresh chain経由 |
| function signature | 26 | 22 | 4 | 24名称、overload 2組をsignature別に集計 |
| trigger | 14 | 10 | 4 | 発火条件を満たすrepository内writeの有無で集計 |
| RLS policy | 57 | 19 | 38 | service role bypassはpolicy利用に含めない |
| PGroonga index | 5 | 3 | 2 | 3件も実際のplanner採用は本番確認待ち |
| pg_cron想定job | 2 | 直接 0 | 2 | rankingはCLI/admin代替あり、category MVはmigration外代替なし |

## 3. 機能とDB objectの対応

以下はすべて **リポジトリ内で一致**。object欄は主要な直接・間接利用を示す。

| 機能 | 利用object | コード上の根拠・補足 |
|---|---|---|
| 名言一覧・詳細 | `quotes`, `authors`, `author_professions`, `professions`, `sources`, `characters`, `quote_categories`, `categories`, `quote_ranking_scores`; category/profession filter | `src/services/quotes.service.ts:20-78,120-171,206-255,328-420`; `src/services/quotes/quote-query-helpers.ts:12-121` |
| 著者一覧・詳細 | `list_authors`, `list_popular_authors`, `authors`, `quotes`, `author_professions`, `professions`, `author_country`, `countries`, `profession_author_counts`, `country_author_counts`, `author_rankings` | `src/services/authors.service.ts:309-342,390-471,477-590,599-644` |
| カテゴリ階層 | `categories`, `categories_with_counts`, `quote_categories`, `get_quote_rankings` | `src/services/categories.service.ts:257-341,396-506,795-1083`; tree/cache組立はアプリ側 |
| 登場人物 | `characters_with_quote_counts`, `characters`, `sources`, `quotes` | `src/services/characters-listing.service.ts:98-230`; `src/services/characters.service.ts:57-116` |
| 出典・出典種別 | `get_sources_with_quote_counts` 7引数版、`sources`, `source_type_assignments`, `source_types`, `authors`, `quotes` | `src/services/sources.service.ts:21-30,98-175,180-260,326-353` |
| 職業 | `list_professions_overview`, `professions`, `profession_author_counts`, `author_professions`, `authors`, `quotes` | `src/services/professions.service.ts:201-316` |
| 国籍・生誕国 | `countries`, `author_country`, `country_author_counts`, `authors`, `quotes` | `src/services/countries.service.ts:12-54`; author filter/countは`src/services/authors.service.ts:477-590` |
| ランキング | `get_quote_rankings`, `quote_ranking_scores`, `category_rankings`, `author_rankings`; refresh時は`ranking_parameters`, `quote_likes`, `legacy_votes`, `quote_ranking_scores_mv`, `ranking_refresh_logs` | `src/services/ranking.service.ts:122-154,204-230,275-385`; DB内chainは§4.3 |
| 検索 | `search_quotes`, `search_authors`; `quotes`/`sources`のPGroonga経路 | `src/services/search.repository.ts:159-219`; `/api/quotes`にも`src/app/api/quotes/route.ts:265` |
| 匿名いいね | `quote_likes`, `quotes`, `ranking_parameters` | `src/app/api/quote-likes/route.ts:7-110`; `src/services/likes-write.service.ts:46-150`。validation、IP hash、rate limitはアプリ側 |
| 各種件数集計 | 各listing RPC、`categories_with_counts`, `characters_with_quote_counts`, `profession_author_counts`, `country_author_counts`, `quote_ranking_scores` | 各一覧serviceの上記根拠。件数の一部はservice内集計・fallback |
| ランダム名言 | `get_random_quotes` → `quotes`, ranking/関連object | `src/app/(site)/random/page.tsx:66-75` → `src/services/quotes.service.ts:241-258` |
| トップページの注目名言 | `get_featured_quotes_light` → `quotes`, `quote_ranking_scores`等 | `src/services/homepage.service.ts:211-238` |
| sitemap | `quotes`, `authors`, `sources`, `categories` | `src/services/sitemap.service.ts:29-178`; path/date/XML組立はDB外 |
| 管理画面のCRUD | `authors`, `author_country`, `author_professions`, `categories`, `quote_categories`, `characters`, `countries`, `quotes`, `sources`, `source_type_assignments`, `professions`; `source_types`はread-only参照 | authors `src/app/api/admin/authors/route.ts:191-292`, `src/app/api/admin/authors/[id]/route.ts:148-350`; categories `src/app/api/admin/categories/route.ts:105-179`, `src/app/api/admin/categories/[id]/route.ts:78-281`; characters `src/app/api/admin/characters/route.ts:49-67`, `src/app/api/admin/characters/[id]/route.ts:72-186`; countries `src/app/api/admin/countries/route.ts:43-61`, `src/app/api/admin/countries/[id]/route.ts:12-135`; quotes `src/app/api/admin/quotes/route.ts:167-438`, `src/app/api/admin/quotes/[id]/route.ts:174-375`; sources `src/app/api/admin/sources/route.ts:165-225`, `src/app/api/admin/sources/[id]/route.ts:102-239`; professions `src/services/admin/professions.service.ts:111-189` |
| 一括登録 | `quotes`および関連master、`authors`, `author_country`, `author_professions`, `professions`, `countries` | quotes `src/app/api/admin/quotes/bulk/route.ts:61-162`; authors validation `src/app/api/admin/authors/bulk/validate/route.ts:107-275`, 実行・疑似rollback `src/app/api/admin/authors/bulk/route.ts:208-400` |
| 管理画面のKPI | 管理viewは使わず、ranking更新時刻のみ`get_quote_rankings` | `src/app/(admin)/admin/page.tsx:9-14,28-53`。KPI値は固定値で、`view_admin_kpi_counts` / `view_admin_ranking_refresh_logs`はruntime参照なし |
| ランキング再計算 | `refresh_quote_ranking_scores(text)` → internal function → MV、score table、category/author rankings、log | 管理 `src/services/admin/ranking.service.ts:30-71`; CLI `scripts/rankings-refresh.ts:10-34,57-63,146-180`; `package.json:47` |
| キャッシュ再検証に関係する更新 | 上記管理CRUD対象table | CRUD成功後に主にadmin pathをrevalidate。手動quote cacheは`src/components/admin/quotes/quote-cache-refresh-button.tsx:24-31` → `src/app/api/admin/revalidate/quotes/[id]/route.ts:28-53`。一部関連更新にはrevalidateなし |

補足: 公開`/api/quotes`は`enable`未指定時に公開限定を加えない (`src/app/api/quotes/route.ts:69,159-162`)。通常公開page/serviceの公開名言経路との差異という事実だけを記録し、是非は本フェーズで判断しない。

## 4. object別利用状況

以下の利用・発火・access経路は、個別に別の確度ラベルを付けた箇所を除き **リポジトリ内で一致**。SQL plannerのindex選択、runtimeの外部状態、本番DBの実在・稼働状態は、それぞれ **リポジトリから推定** または **本番確認待ち** と明記する。

### 4.1 table（20 / 20 利用あり）

| table | 状況 | 利用経路と根拠 |
|---|---|---|
| `admin_users` | 利用あり | authenticated管理者確認: `src/lib/auth/admin-check.ts:14-82` |
| `author_country` | 利用あり | author filter/detailと管理更新: `src/services/authors.service.ts:477-590`; `src/app/api/admin/authors/[id]/route.ts:148-350` |
| `author_professions` | 利用あり | quote/author/profession表示と管理更新: `src/services/quotes/quote-query-helpers.ts:12-121`; `src/app/api/admin/authors/[id]/route.ts:148-350` |
| `author_rankings` | 利用あり | ranking取得・refresh chain: `src/services/ranking.service.ts:122-154`; `supabase/migrations/20251026022432_category-author-rankings.sql:517-547` |
| `authors` | 利用あり | author/quote/source/sitemap/管理: `src/services/authors.service.ts:309-644`; `src/services/sitemap.service.ts:29-178` |
| `categories` | 利用あり | category tree/filter/管理: `src/services/categories.service.ts:257-506,795-1083`; `src/app/api/admin/categories/[id]/route.ts:78-281` |
| `quote_categories` | 利用あり | quote/category filterと管理割当: `src/services/quotes/quote-query-helpers.ts:12-121`; `src/app/api/admin/quotes/[id]/route.ts:174-375` |
| `quotes` | 利用あり | 公開機能全般、管理、sitemap: `src/services/quotes.service.ts:20-420`; `src/app/api/admin/quotes/route.ts:167-438` |
| `category_rankings` | 利用あり | ranking取得・refresh chain: `src/services/ranking.service.ts:204-230`; `supabase/migrations/20251026022432_category-author-rankings.sql:430-464` |
| `characters` | 利用あり | character detailと管理: `src/services/characters.service.ts:57-116`; `src/app/api/admin/characters/[id]/route.ts:72-186` |
| `source_type_assignments` | 利用あり | source表示/管理割当: `src/services/sources.service.ts:98-175`; `src/app/api/admin/sources/[id]/route.ts:102-239` |
| `source_types` | 利用あり | source filter/表示と管理補助read: `src/services/sources.service.ts:21-30,98-175,326-353` |
| `sources` | 利用あり | source一覧/詳細、quote、管理、sitemap: `src/services/sources.service.ts:98-260`; `src/services/sitemap.service.ts:29-178` |
| `countries` | 利用あり | country一覧、author filter、管理: `src/services/countries.service.ts:12-54`; `src/app/api/admin/countries/[id]/route.ts:12-135` |
| `legacy_votes` | 利用あり（DB内部間接） | ranking MVのscore入力: `supabase/migrations/20260111163755_add-legacy-votes-to-ranking.sql:29-66` |
| `professions` | 利用あり | profession/author/quote、管理: `src/services/professions.service.ts:201-316`; `src/services/admin/professions.service.ts:111-189` |
| `quote_likes` | 利用あり | service roleで重複確認・insert・count: `src/services/likes-write.service.ts:46-150` |
| `quote_ranking_scores` | 利用あり | rankingと各light/listing RPCの参照: `src/services/ranking.service.ts:275-385`; DB chainは§4.3 |
| `ranking_parameters` | 利用あり | likes rate-limit fallbackとranking refresh: `src/services/likes-write.service.ts:46-150`; `scripts/rankings-refresh.ts:57-63` |
| `ranking_refresh_logs` | 利用あり | CLIが実行logを直接確認: `scripts/rankings-refresh.ts:146-180`; refresh chainもwrite |

### 4.2 view / materialized view（5 / 7 利用あり）

| object | 種別 | 状況 | 根拠 |
|---|---|---|---|
| `characters_with_quote_counts` | view | 利用あり | `.from()`参照: `src/services/characters-listing.service.ts:98-105` |
| `view_admin_kpi_counts` | view | リポジトリ内で利用箇所なし | 完全名を`src/`, `scripts/`で検索。生成型・migration・文書の定義一致のみ。dashboardは固定値: `src/app/(admin)/admin/page.tsx:28-53` |
| `view_admin_ranking_refresh_logs` | view | リポジトリ内で利用箇所なし | 完全名と短縮`ranking_refresh_logs`を検索。view名は生成型・migration・文書の定義一致のみ。scriptはbase tableを直接参照 |
| `categories_with_counts` | MV | 利用あり | category service: `src/services/categories.service.ts:147,257-341` |
| `country_author_counts` | MV | 利用あり | author filter count: `src/services/authors.service.ts:565` |
| `profession_author_counts` | MV | 利用あり | author filter count: `src/services/authors.service.ts:523` |
| `quote_ranking_scores_mv` | MV | 利用あり（DB内部間接） | text引数refresh chain: `supabase/migrations/20251026022432_category-author-rankings.sql:328-361` |

### 4.3 function / RPC（22 / 26 利用あり）

overloadは引数で区別した。defaultを持つため名称だけの検索では判別できず、call parameterと定義の引数数を突合した。

| # | signature | 状況 | 根拠 |
|---:|---|---|---|
| 1 | `_refresh_quote_ranking_scores_internal(trigger_source text='unknown')` | 利用あり（間接） | text版refresh wrapperが呼ぶ: `supabase/migrations/20251026022432_category-author-rankings.sql:574-599`（callは588行） |
| 2 | `build_author_jsonb(p_author_id integer)` | 利用あり（間接） | `get_quote_rankings`内: `supabase/migrations/20260113181640_fix-get-quote-rankings-refreshed-at-timestamptz.sql:183-186` |
| 3 | `build_categories_jsonb(p_quote_id integer)` | 利用あり（間接） | `get_quote_rankings`内: `supabase/migrations/20260113181640_fix-get-quote-rankings-refreshed-at-timestamptz.sql:183-186` |
| 4 | `build_character_jsonb(p_character_id integer)` | 利用あり（間接） | `get_quote_rankings`内: `supabase/migrations/20260113181640_fix-get-quote-rankings-refreshed-at-timestamptz.sql:183-186` |
| 5 | `build_source_jsonb(p_source_id integer)` | 利用あり（間接） | `get_quote_rankings`内: `supabase/migrations/20260113181640_fix-get-quote-rankings-refreshed-at-timestamptz.sql:183-186` |
| 6 | `check_display_order_sequence()` | リポジトリ内で利用箇所なし | function名、trigger接続名をmigration/dump/`src`/`scripts`で検索。定義のみで、dump上もtrigger未接続 |
| 7 | `ensure_category_parent_level()` | 利用あり（trigger） | category INSERT/UPDATE経路: `src/app/api/admin/categories/route.ts:105-179`, `src/app/api/admin/categories/[id]/route.ts:78-281` |
| 8 | `ensure_quote_categories_level2()` | 利用あり（trigger） | quote-category INSERT/UPDATE経路: `src/app/api/admin/quotes/route.ts:167-438`, `src/app/api/admin/quotes/[id]/route.ts:174-375` |
| 9 | `get_category_quotes_light(integer,integer,integer)` | リポジトリ内で利用箇所なし | 完全名と`category_quotes_light`を検索。生成型/migration定義のみ。category詳細は別service/RPC経路 |
| 10 | `get_featured_quotes_light(integer)` | 利用あり | `src/services/homepage.service.ts:211-238` |
| 11 | `get_quote_rankings(13引数)` | 利用あり | `src/services/ranking.service.ts:343-385`; 管理KPI timestamp `src/app/(admin)/admin/page.tsx:9-14` |
| 12 | `get_random_quotes(6引数)` | 利用あり | `src/services/quotes.service.ts:241-258` |
| 13 | `get_sources_with_quote_counts(5引数)` | 利用あり（検証script） | `scripts/verify-sources-rpc.mjs:52-58`; `scripts/load-test-sources.mjs:58-71` |
| 14 | `get_sources_with_quote_counts(7引数)` | 利用あり（runtime） | `include_empty`, `search_query`を渡す: `src/services/sources.service.ts:98-175` |
| 15 | `is_admin()` | リポジトリ内で利用箇所なし | `.rpc('is_admin')`、function名を検索。runtime管理認証は`admin_users`直接照合、管理CRUDはservice role。policy定義内の参照だけ |
| 16 | `list_authors(7引数)` | 利用あり | `src/services/authors.service.ts:390-471` |
| 17 | `list_popular_authors(integer)` | 利用あり | `src/services/authors.service.ts:456-471` |
| 18 | `list_professions_overview(5引数)` | 利用あり | `src/services/professions.service.ts:201-316` |
| 19 | `refresh_quote_ranking_scores()` | リポジトリ内で利用箇所なし | 引数なしcallを`src`/`scripts`で検索。定義・生成型とUI表示文字列 (`src/components/admin/rankings/ranking-refresh-card.tsx:119`) はあるが、実callはすべて`trigger_source`付きtext版。MVだけをrefreshするsignature |
| 20 | `refresh_quote_ranking_scores(trigger_source text='unknown')` | 利用あり | `trigger_source`を渡す管理/CLI: `src/services/admin/ranking.service.ts:30-71`; `scripts/rankings-refresh.ts:57-63`; cron migrationもtext引数 |
| 21 | `refresh_sources_search_document_after_author_delete()` | 利用あり（trigger） | author DELETE: `src/app/api/admin/authors/[id]/route.ts:148-350` |
| 22 | `refresh_sources_search_document_for_author()` | 利用あり（trigger） | author nameを含むUPDATE: `src/app/api/admin/authors/[id]/route.ts:148-350` |
| 23 | `search_authors(text,integer,integer,boolean)` | 利用あり | `src/services/search.repository.ts:196-219`; `src/app/api/authors/route.ts:92` |
| 24 | `search_quotes(text,integer,integer,boolean,boolean)` | 利用あり | `src/services/search.repository.ts:159-190`; `src/app/api/quotes/route.ts:265` |
| 25 | `set_source_search_document()` | 利用あり（trigger） | source INSERT/UPDATE: `src/app/api/admin/sources/route.ts:165-225`, `src/app/api/admin/sources/[id]/route.ts:102-239` |
| 26 | `update_updated_at_column()` | 利用あり（trigger） | §4.4の5 tableへのUPDATE経路 |

text引数版のchainは、管理panel / CLI / migration上のscheduler意図 → `_refresh_quote_ranking_scores_internal` (`supabase/migrations/20251026022432_category-author-rankings.sql:574-599`) → `quote_ranking_scores_mv` refresh・`quote_ranking_scores`同期 (`supabase/migrations/20251026022432_category-author-rankings.sql:328-361`) → `category_rankings`更新 (`supabase/migrations/20251026022432_category-author-rankings.sql:430-464`) → `author_rankings`更新 (`supabase/migrations/20251026022432_category-author-rankings.sql:517-547`) → `ranking_refresh_logs`記録である。引数なし版はMV refreshだけだが、repository内runtime callは見つからなかった。

### 4.4 trigger（10 / 14 発火経路あり）

| trigger（発火table / event） | 状況 | repository内write経路 |
|---|---|---|
| `categories_validate_hierarchy` (`categories`, INSERT/UPDATE) | 発火経路あり | category CRUD/seed: `src/app/api/admin/categories/route.ts:105-179`, `src/app/api/admin/categories/[id]/route.ts:78-281`, `src/app/api/admin/seed-categories/route.ts:7-103` |
| `quote_categories_validate_level` (`quote_categories`, INSERT/UPDATE) | 発火経路あり | quote CRUD/bulk: `src/app/api/admin/quotes/route.ts:167-438`, `src/app/api/admin/quotes/[id]/route.ts:174-375`, `src/app/api/admin/quotes/bulk/route.ts:61-162` |
| `refresh_sources_search_document_after_author_delete` (`authors`, DELETE) | 発火経路あり | `src/app/api/admin/authors/[id]/route.ts:148-350` |
| `refresh_sources_search_document_for_author` (`authors.name`, UPDATE) | 発火経路あり | `src/app/api/admin/authors/[id]/route.ts:148-350` |
| `set_source_search_document` (`sources`, INSERT/UPDATE) | 発火経路あり | source CRUD: `src/app/api/admin/sources/route.ts:165-225`, `src/app/api/admin/sources/[id]/route.ts:102-239`; author削除前の参照解除: `src/app/api/admin/authors/[id]/route.ts:327-351` |
| `update_authors_updated_at` (`authors`, UPDATE) | 発火経路あり | `src/app/api/admin/authors/[id]/route.ts:148-350` |
| `update_characters_updated_at` (`characters`, UPDATE) | 発火経路あり | character CRUD: `src/app/api/admin/characters/[id]/route.ts:72-186`; source削除前の参照解除: `src/app/api/admin/sources/[id]/route.ts:206-240` |
| `update_countries_updated_at` (`countries`, UPDATE) | 発火経路あり | `src/app/api/admin/countries/[id]/route.ts:12-135` |
| `update_quotes_updated_at` (`quotes`, UPDATE) | 発火経路あり | quote CRUD: `src/app/api/admin/quotes/[id]/route.ts:174-375`; author/character/source削除前の参照解除: `src/app/api/admin/authors/[id]/route.ts:327-351`, `src/app/api/admin/characters/[id]/route.ts:163-187`, `src/app/api/admin/sources/[id]/route.ts:206-240` |
| `update_sources_updated_at` (`sources`, UPDATE) | 発火経路あり | source CRUD: `src/app/api/admin/sources/[id]/route.ts:102-239`; author削除前の参照解除: `src/app/api/admin/authors/[id]/route.ts:327-351` |
| `update_admin_users_updated_at` (`admin_users`, UPDATE) | リポジトリ内で発火writeなし | `admin_users`完全名と`.from()`を検索。runtimeはSELECTのみ。`scripts/create-admin-user.ts:81`にINSERTがあるが、triggerはUPDATE発火のため該当しない |
| `update_ranking_parameters_updated_at` (`ranking_parameters`, UPDATE) | リポジトリ内で発火writeなし | 完全名と`.from()`/SQLを検索。runtime/scriptはSELECTのみ |
| `update_source_type_assignments_updated_at` (`source_type_assignments`, UPDATE) | リポジトリ内で発火writeなし | 管理経路は割当をDELETE/INSERTし、UPDATEなし |
| `update_source_types_updated_at` (`source_types`, UPDATE) | リポジトリ内で発火writeなし | 管理runtimeはread-only補助API。UPDATE経路なし |

### 4.5 RLS policy（19 / 57 適用経路あり）

「利用あり」のroleはpolicyを通るroleである。service role経路はbypassなので利用なし欄に分離した。

#### 適用経路あり（19件）

| table / policy | 適用role/keyと経路 |
|---|---|
| `admin_users.admin_users_read_own` | authenticated。管理者own-row確認: `src/lib/auth/admin-check.ts:14-82` |
| `author_country.author_country_read_all` | anon/authenticated。author listing/detail filter: `src/services/authors.service.ts:477-590` |
| `author_professions.Author professions are viewable by everyone` | anon/authenticated。quote/author/profession表示 |
| `author_rankings.author_rankings_select_public` | anon/authenticated。ranking/author表示 |
| `authors.authors_read_all` | anon/authenticated。公開一覧・詳細・sitemap |
| `categories.Allow public read` | anon/authenticated。category/quote公開参照 |
| `categories.categories_select_all` | anon/authenticated。上記SELECTに併存適用 |
| `category_rankings.category_rankings_select_public` | anon/authenticated。ranking/category表示 |
| `characters.characters_read_all` | anon/authenticated。character公開参照 |
| `countries.countries_read_all` | anon/authenticated。country/author filter |
| `professions.Professions are viewable by everyone` | anon/authenticated。profession公開参照 |
| `quote_categories.Allow public read` | anon/authenticated。quote/category関連参照 |
| `quote_categories.quote_categories_select_all` | anon/authenticated。上記SELECTに併存適用 |
| `quote_ranking_scores.quote_ranking_scores_select_public` | anon/authenticated。ranking/一覧RPC経路 |
| `quotes.Allow public read` | anon/authenticated。公開名言参照 |
| `quotes.quotes_select_all` | anon/authenticated。上記SELECTに併存適用 |
| `source_type_assignments.source_type_assignments_select_all` | anon/authenticated。source type表示/filter |
| `source_types.source_types_select_all` | anon/authenticated。source type表示/filter |
| `sources.sources_read_all` | anon/authenticated。source/quote/sitemap参照 |

公開clientの根拠は`src/lib/supabase/server-static.ts:15-22`、cookie clientは`src/lib/supabase/server.ts:31-39`。各objectのconsumerは§3・§4.1に記載した。

#### リポジトリ内でpolicy適用経路なし（38件）

| table | policy（個別名） | 検索結果・理由 |
|---|---|---|
| `author_country` | `author_country_admin_write` | 管理writeはservice role bypass |
| `author_professions` | `author_professions_admin_write` | 同上 |
| `author_rankings` | `author_rankings_service_rw` | refreshはSECURITY DEFINER/service role。policy利用に数えない |
| `authors` | `authors_admin_write` | 管理writeはservice role bypass |
| `categories` | `Allow authenticated write`; `categories_admin_delete`; `categories_admin_insert`; `categories_admin_update` | 管理writeはservice role bypass |
| `category_rankings` | `category_rankings_service_rw` | refresh chain。service role/policy適用呼出しなし |
| `characters` | `characters_admin_delete`; `characters_admin_insert`; `characters_admin_update` | 管理writeはservice role bypass |
| `countries` | `countries_admin_write` | 管理writeはservice role bypass |
| `legacy_votes` | `legacy_votes_select_public`; `legacy_votes_service_rw` | アプリ直接accessなし。ranking MV内部参照のみ |
| `quote_categories` | `Allow authenticated write`; `quote_categories_admin_delete`; `quote_categories_admin_insert`; `quote_categories_admin_update` | 管理writeはservice role bypass |
| `quote_likes` | `Allow service role select`; `quote_likes_insert_for_service`; `quote_likes_no_delete_for_clients`; `quote_likes_no_update_for_clients` | likes serviceはservice role bypass。client UPDATE/DELETEなし |
| `quote_ranking_scores` | `quote_ranking_scores_service_rw` | 公開SELECT policyは利用するがwriteはrefresh chain/service role |
| `quotes` | `Allow authenticated write`; `quotes_admin_delete`; `quotes_admin_insert`; `quotes_admin_update` | 管理writeはservice role bypass |
| `ranking_parameters` | `ranking_parameters_select_policy` | runtime/script accessはservice roleまたはSECURITY DEFINER経路 |
| `source_type_assignments` | `source_type_assignments_admin_delete`; `source_type_assignments_admin_insert`; `source_type_assignments_admin_update` | 管理writeはservice role bypass |
| `source_types` | `source_types_admin_delete`; `source_types_admin_insert`; `source_types_admin_update` | runtimeはread-only、管理writeなし |
| `sources` | `sources_admin_delete`; `sources_admin_insert`; `sources_admin_update` | 管理writeはservice role bypass |

上表はpolicy名完全一致、tableアクセス、client生成元を突合した結果である。`ranking_refresh_logs`はRLS有効だがpolicyが0件なので、57件のpolicy母集団には行を持たない。実効権限全体は **本番確認待ち**。

### 4.6 PGroonga index（3 / 5 利用経路あり）

| index | 状況 | 根拠 |
|---|---|---|
| `idx_quotes_pgroonga` | 利用経路あり（planner採用は本番確認待ち） | `search_quotes` / `get_quote_rankings`のquote検索。呼出し: `src/services/search.repository.ts:159-190`, `src/services/ranking.service.ts:275-385` |
| `idx_quotes_text_en_pgroonga` | 利用経路あり（planner採用は本番確認待ち） | 同じquote検索の`text_en`対象 |
| `idx_sources_search_document_pgroonga` | 利用経路あり（planner採用は本番確認待ち） | 7引数source RPCの検索。`src/services/sources.service.ts:98-175` |
| `idx_categories_pgroonga` | リポジトリ内で利用箇所なし | index名、PGroonga operator、category検索SQLを検索。定義のみでcategory検索consumerなし |
| `pgroonga_professions_name_index` | リポジトリ内で利用箇所なし | profession overviewは`ILIKE`: `supabase/migrations/20251201044404_professions-pagination.sql:85-86` |

indexを使いうるSQL経路と、実行時にplannerが実際に選択することは別である。後者はrepositoryだけでは確定しない。

補足(レビューで追加): `QuotesService.getQuotes`にはPGroonga operatorを直接使う検索分岐がある(`text.pgroonga.` / `context_note.pgroonga.` / `author.name.pgroonga.`: `src/services/quotes.service.ts:234-238`)。ただし、repository内に`search`引数を渡す呼び出し元は見つからず、公開検索は`search_quotes` RPC経由である。また`author.name`にはPGroonga indexが存在しない(第1部の5本に含まれない)ため、この分岐が実行された場合のauthor name照合はindexなしのPGroonga operator評価になる **[リポジトリ内で一致 / planner挙動は本番確認待ち]**。

### 4.7 pg_cron想定job（直接利用 0 / 2）

| migration上のjob意図 | 状況 | 代替経路 |
|---|---|---|
| `refresh_quote_ranking_scores_scheduler` | アプリ直接呼出しなし。job実在/active/historyは本番確認待ち | migration意図: `supabase/migrations/20251023143524_ranking-refresh-logs.sql:100-113`; CLI `package.json:47`, `scripts/rankings-refresh.ts:10-34,57-63`; 管理POSTは`src/services/admin/ranking.service.ts:30-71` |
| `refresh_categories_with_counts_scheduler` | アプリ直接呼出しなし。job実在/active/historyは本番確認待ち | migration意図: `supabase/migrations/20251223023053_fix_hierarchy_count_distinct.sql:100-113`; repository内にmigration外のrefresh代替経路なし |

## 5. 「リポジトリ内で利用箇所なし」の要約と検索根拠

object別の個別結果は§4に記載した。該当objectは次のとおり。

- view 2件: `view_admin_kpi_counts`, `view_admin_ranking_refresh_logs`。
- function 4 signature: `check_display_order_sequence()`, `get_category_quotes_light(integer,integer,integer)`, `is_admin()`, `refresh_quote_ranking_scores()`（引数なし）。
- trigger 4件: `update_admin_users_updated_at`, `update_ranking_parameters_updated_at`, `update_source_type_assignments_updated_at`, `update_source_types_updated_at`。
- RLS policy 38件: §4.5の全個別名。
- PGroonga index 2件: `idx_categories_pgroonga`, `pgroonga_professions_name_index`。
- cron想定job 2件: repository内からcron自体を直接使う経路なし。rankingにはCLI/admin代替があり、category MVにはmigration外代替なし。

検索では、完全object名、table/functionの短縮名、`.from()`、`.rpc()`、SQL文字列、PGroonga operator、trigger発火event、生成型を確認した。生成型、migration、dump由来文書だけの一致は利用箇所に数えなかった。したがって本節は本番運用上の未使用を断定しない。

## 6. 書込み経路、trigger、role/key

### 6.1 機能別write

| 機能 | write対象 | role/key | trigger/後処理 |
|---|---|---|---|
| 匿名いいね | `quote_likes` INSERT | service role | appでvalidation、duplicate、IP hash、rate limit後にINSERT。RLS bypass |
| 著者CRUD/一括 | `authors`, `author_country`, `author_professions` INSERT/UPDATE/DELETE | service role | author更新時`updated_at`、name更新/削除時source検索文書trigger。bulkはアプリ側疑似rollback |
| category CRUD/seed | `categories` INSERT/UPDATE/DELETE | service role | hierarchy validation trigger、`updated_at` triggerはcategoriesには存在しない |
| character CRUD | `characters` INSERT/UPDATE/DELETE | service role | `updated_at` trigger |
| country CRUD | `countries` INSERT/UPDATE/DELETE | service role | `updated_at` trigger |
| quote CRUD/一括 | `quotes`, `quote_categories` INSERT/UPDATE/DELETE | service role | quote `updated_at`、category level validation trigger |
| source CRUD | `sources`, `source_type_assignments` INSERT/UPDATE/DELETE | service role | source検索文書、source `updated_at`。assignmentはDELETE/INSERTで、assignment UPDATE triggerは発火しない |
| profession CRUD | `professions` INSERT/UPDATE/DELETE | service role | DB triggerなし。Server Action自身には明示guardがなく、親admin layout/middlewareの認証境界に依存: `src/app/(admin)/admin/professions/actions.ts:20-59` |
| ranking再計算 | MV refresh、`quote_ranking_scores`, `category_rankings`, `author_rankings`, `ranking_refresh_logs` | SECURITY DEFINER RPCを管理service role/CLIからcall | text版refresh chain |
| author削除前の参照解除 | `sources.author_id`, `quotes.author_id` UPDATE後に`authors` DELETE | service role | source検索文書・sources `updated_at`・quotes `updated_at` trigger: `src/app/api/admin/authors/[id]/route.ts:327-351` |
| character削除前の参照解除 | `quotes.character_id` UPDATE後に`characters` DELETE | service role | quotes `updated_at` trigger: `src/app/api/admin/characters/[id]/route.ts:163-187` |
| source削除前の参照解除 | `characters.source_id`, `quotes.source_id` UPDATE後に`sources` DELETE | service role | characters / quotes `updated_at` trigger: `src/app/api/admin/sources/[id]/route.ts:206-240` |
| category削除時の関連解除 | 子categoryを含む`quote_categories` DELETE後に`categories` DELETE | service role | `quote_categories_validate_level`はINSERT/UPDATE triggerのためDELETEでは発火しない: `src/app/api/admin/categories/[id]/route.ts:232-281` |

管理CRUDの認証確認はauthenticated経路だが、実データwrite clientはservice roleである。このため、管理write policyがコード上のwriteを許可しているとは数えていない。

### 6.2 revalidate

管理CRUDはtransaction/更新成功後に主として管理画面pathをrevalidateする。quoteの公開cacheには専用手動button/routeがある (`src/components/admin/quotes/quote-cache-refresh-button.tsx:24-31`, `src/app/api/admin/revalidate/quotes/[id]/route.ts:28-53`)。一方、たとえば一部の`author_professions` PUT等にはrevalidate呼出しがない。ここでは現行経路の事実だけを記録する。

## 7. DB外（アプリ側）で実装される関連処理

以下は **リポジトリ内で一致**。

- **qid / URL互換性:** DBにqid列はなく、`quotes.id`から`q{id}`を組み立て、qid/slugを解析する: `src/lib/utils/quote-url.ts:3-42`。詳細pageで解決・canonical redirect: `src/app/(site)/quotes/[slugOrQid]/page.tsx:79-96`。
- **表示言語fallback:** `display_language_preference`と`text/text_en`を解決し、指定側が空なら他方へfallback: `src/lib/utils/quote-text.ts:22-66`。
- **公開状態:** 通常公開service/RPCは`enable`を扱う一方、公開`/api/quotes`は指定なし時に絞らない: `src/app/api/quotes/route.ts:69,159-162`。
- **匿名いいね:** request validation、client UUID検証、IP取得/hash、日次rate limit、duplicateの扱いをAPI/serviceで実装: `src/app/api/quote-likes/route.ts:7-110`, `src/services/likes-write.service.ts:46-150`。
- **ranking間接chain:** アプリはtext版RPCを1回呼び、MV/table/category/author/log更新はDB function内で実施。CLIは開始・結果log確認とerror処理を担う。
- **category:** 2階層tree組立、表示用mapping、cache、fallbackをcategory service側で行う: `src/services/categories.service.ts:257-341,396-506,795-1083`。
- **検索:** query normalization、pagination、RPC結果mapping/fallbackはrepository/API側。DB側PGroonga検索と役割が分かれる: `src/services/search.repository.ts:159-219`。
- **管理validation:** entityごとの入力validation、重複確認、関連master解決をroute/service側で実施。author bulkはtoken、重複検査、逐次処理、失敗時の疑似rollbackをアプリで行う: `src/app/api/admin/authors/bulk/validate/route.ts:107-275`, `src/app/api/admin/authors/bulk/route.ts:208-400`。
- **profession認証境界:** Server Action自身に認証guardはなく、親layout/middleware保護に依存: `src/app/(admin)/admin/professions/actions.ts:20-59`。
- **random/fallback:** RPC呼出し後のmapping、fallback、shuffle/dedupeの一部はquote service/page側。
- **sitemap:** DBから対象を取得した後、path、更新日、XMLをアプリで構築: `src/services/sitemap.service.ts:29-178`。
- **日時:** RPC/tableの日時をserviceでmappingし、sitemap等の表示・serializeへ渡す。base timestamptzとRPC返却型の混在自体は第1部の構造事実で、実値の正規化状態は本番確認待ち。
- **cache revalidation:** DB triggerではなくNext.jsのroute/actionで実施。更新経路によって対象pathが異なる。
- **管理KPI:** DB viewではなくdashboardの固定値を表示し、ranking timestampだけRPC取得: `src/app/(admin)/admin/page.tsx:9-14,28-53`。

## 8. scriptsから確認した利用経路

- ranking CLI: `scripts/rankings-refresh.ts:10-34,57-63,146-180`。text引数refreshとbase log tableを使用。
- sequence補正SQL: `scripts/fix-sequences.sql:8-36`。9 sequenceを対象。
- orphan cleanup: `scripts/cleanup-orphaned-relations.sql:6-43`。関連tableを直接検査・修正する運用経路。
- category pipeline: `scripts/category-pipeline/import-categories.sh:130-237`。category/関連データのimport経路。
- source RPC検証/load: `scripts/verify-sources-rpc.mjs:52-58`, `scripts/load-test-sources.mjs:58-71`。5引数overloadの根拠。
- author import、sample import、backup/sync系にもDBアクセスがある。実行実績・現在データへの適用状況は本番確認待ち。

tracked 43件のうち、`backup_via_copy.sh`だけは安全制約により本文検索から除外した。同ファイルの利用objectは本調査で断定しない。

## 9. 本番確認待ち（フェーズ5への引き継ぎ）

1. migrationで意図されたcron job 2件の実在、active、schedule、実行履歴、実際に呼ぶfunction signature。
2. 4 MVのpopulate状態、refresh時刻、特にrepository外代替が見つからない`categories_with_counts`の更新運用。
3. ranking CLI、data修正、import、backup/sync scriptの実行実績と、現在データへの適用状態。
4. 57 policy、GRANT、SECURITY DEFINER、view `security_invoker`を組み合わせた本番の実効権限。repositoryのkey経路だけでは完全には確定しない。
5. PGroonga候補index 3件が実query planで選択されるか、2件の利用なしindexにrepository外queryがないか。
6. 公開`/api/quotes`の`enable`未指定時の実際の利用者・運用意図。
7. `quote_likes`のinvalid化・IP制限について、repository外運用やjobがあるか。実データ分布は第1部の引継ぎ事項。
8. ranking snapshot/MV/logの鮮度と、text版・引数なし版refreshのrepository外呼出し有無。
9. 管理KPI view 2件、未接続function、発火writeなしtrigger、適用経路なしpolicyにrepository外consumerがあるか。
10. `supabase_realtime`等、repository内アプリ検索では確認できないDB/プラットフォーム側consumer。

## 10. フェーズ3への引き継ぎ（事実のみ）

以下は重複・廃止候補の分析材料として目についた事実であり、維持・廃止の判断ではない。

- 管理KPI view 2件はruntime参照が見つからず、dashboardは固定値、ranking timestampだけ別RPCを使う。
- `get_sources_with_quote_counts`は5/7引数overloadが併存し、5引数は検証/load script、7引数はruntime serviceが使う。
- `refresh_quote_ranking_scores`は2 signatureが異なる範囲を更新する。repository runtimeはtext版だけで、引数なし版のcallは見つからない。
- `get_category_quotes_light`, `is_admin`, `check_display_order_sequence`は定義以外の利用箇所が見つからない。`is_admin`を参照するpolicy自体も、管理writeがservice role bypassのためrepository内write経路では適用されない。
- category/quoteにはpublic SELECT policyが重複して適用される構造がある一方、管理writeはservice role clientを使う。
- rankingはtable 5件、MV、複数function、log、migration上cron、CLI/adminが連鎖する。`legacy_votes`はアプリ直接参照ではなくMV score入力として残る。
- `categories_with_counts`はruntime readがあり、migration上cron refresh意図もあるが、migration外のrefresh代替は見つからない。
- PGroongaはquote/source検索経路がある一方、category indexのconsumerは見つからず、profession RPCは`ILIKE`を使う。
- `getQuotes`内にPGroonga operator直接使用の検索分岐があるが、repository内に呼び出し元がなく、`author.name`対象分はindexも存在しない(§4.6補足)。
- source検索文書はアプリが直接組み立てず、3 triggerで保守される。source type assignment更新はDELETE/INSERTで、同tableのUPDATE triggerを発火させる経路はない。
- 公開`/api/quotes`の`enable`扱いが通常公開page/serviceと異なる。
- profession Server Actionの認証はaction内guardではなく親admin境界へ依存する。
- 管理validation、bulk疑似rollback、qid、表示言語fallback、category tree/cache、likes制御、revalidateはDB外処理である。
- timestampの型・正規化はDB/RPC/serviceにまたがる。実値状態は本番確認待ち。

以上をフェーズ3で評価する際も、本番での未使用や廃止を本書だけから確定しない。
