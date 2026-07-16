# 第3部: 歪み、重複、廃止候補

作成日: 2026-07-16

## 1. 判断の前提

### 1.1 範囲と文書の読み方

本書は、第1部の構造事実と第2部の利用状況を根拠に、現行DB objectの扱いを分類するフェーズ3成果物である。ここで扱うのは現行objectを維持・再編・置換・廃止する判断と論点への見解までであり、新DBのテーブル一覧、カラム設計、DDL、migration、実装はフェーズ4以降で扱う。

各表の「事実・根拠」は第1部・第2部で確認済みの事実、「判断・代替」は本フェーズの提案である。`リポジトリ内で利用箇所なし`は本番で未使用という意味ではない。repository外 consumerや運用状態で結論が変わるobjectは、廃止を断定せず「本番確認待ち（廃止候補）」とした。

判断には作業指示書「新DB設計の判断基準」12項目を用いた。特に、必要データとURL互換性を欠損なく守ること、原本と派生を分けること、PostgreSQL/Supabase固有方式を持ち込まないこと、名言約2,100件・著者約890件の規模に比例させることを優先した。ただし、likes・中間表・履歴を含む実行時の総行数は未確認であり、単純SQLの性能は実測事項として残す。

### 1.2 ADR制約と守る対象

フェーズ0メモ§2のADR 001〜016を制約とする。特に次を変更しない。

- ADR 002: 初期検索はwildcardをescapeしたbind parameterによる単純`LIKE`とし、PGroonga、FTS5、bigram派生列を初期構成へ含めない。
- ADR 005: 定期処理はsupercronicからCLIを起動し、前回正常結果、失敗出力、成功heartbeatを守る。
- ADR 006: likesは`(quote_id, client_uuid)`を一意とし、IP/IP hashを保存しない。
- ADR 008・009: ID/qid/slugのURL互換性と、`display_language_preference`の物理名・値域・fallbackを守る。
- ADR 011: 時点は固定長UTC表現へ統一し、歴史日付とは分離する。
- ADR 012: 管理認証はCloudflare Access + 外部IdPとし、初期DBへidentity/role表を作らない。
- ADR 014: 更新後のcache反映動作を守るが、DB objectとして機械移植しない。

守る対象は、公開・非公開・下書き・編集中を含むコンテンツ、公開・管理機能、URL互換性、正しい関連、likes・ランキング・検索・集計の振る舞い、保持すべき履歴・集計元データである。本書の提案にADR 001〜016との衝突はない。既存計画の「19テーブル」は確定件数ではなく、dumpの20表（19表 + `admin_users`）を個別評価する。

### 1.3 確度ラベル

- **本番dumpで確認**: 2026-07-16取得のschema-only dumpで構造を確認済み。実データ・運用状態は含まない。
- **リポジトリ内で一致**: 複数のコード・migration・文書が一致する。
- **リポジトリから推定**: 根拠はあるが、本番データ・性能・repository外利用を未確認。
- **本番確認待ち**: 実データ、外部consumer、job、実効権限等の確認が必要。

### 1.4 分類の凡例と母集団

構造は「維持 / 再編 / 処理へ置換 / 廃止 / 本番確認待ち」、データは「そのまま移行 / 変換して移行 / 再計算 / 移行しない / 本番確認待ち」で分類する。view、function、trigger、ENUM、EXCLUDE、index、policy、job等のデータを持たないobjectにはデータ分類を付けない。MV 4件は保持行を持つがすべて派生データなので再計算とする。

原子objectの母集団は、table 20 + view 3 + MV 4 + function 26 signature + trigger 14 + ENUM 2 + EXCLUDE 1 + PGroonga index 5 + RLS policy 57 + cron想定job 2 = **134件**である。RLS有効20表、明示GRANT 758文、default privilege 12文はobjectとは単位が異なるため、設定監査件数として別集計する。

## 2. 全objectの2軸分類

### 2.1 table（20件）

表のデータ分類は主要データを1件として集計する。複合データのうち移行しない列等は理由欄に明記する。時点値を持つ表はADR 011形式へ変換するため、原則「変換して移行」とした。

| 現行table | 構造 | データ | 判断・守る対象 | 根拠・確度・条件 |
|---|---|---|---|---|
| `admin_users` | 廃止 | 移行しない | ADR 012の認証へ置換する。管理機能と認可は失わない | 第1部§3.1、第2部§4.1・§6、ADR 012。**リポジトリ内で一致** |
| `author_country` | 再編 | 変換して移行 | 複数の関連国と生誕国の意味を守り、PostgreSQL固有制約と重複indexを整理 | 第1部§3.2・§4.3・§12.8、第2部§3・§4.1。**リポジトリから推定**。0件・flag分布・孤立を確認し、意味変更はユーザー判断待ち |
| `author_professions` | 維持 | 変換して移行 | 順序付き著者–職業関連を維持 | 第1部§3.3、第2部§3・§4.1。**リポジトリ内で一致** |
| `author_rankings` | 維持 | 再計算 | 著者ランキング最新snapshotの責務を維持し、名言scoreから再生成 | 第1部§3.4・§8、第2部§3・§4.1・§4.3、ADR 005。構造は**リポジトリから推定**、派生性は**リポジトリ内で一致** |
| `authors` | 維持 | 変換して移行 | ID、slug、本文、関連、歴史日付を保持。時点とENUM相当値を変換し、歴史日付はUTC変換しない | 第1部§3.5・§3.21、第2部§3・§4.1、ADR 008・011。**リポジトリ内で一致** |
| `categories` | 維持 | 変換して移行 | 2階層master、slug、filter、管理CRUDの責務を維持 | 第1部§3.6、第2部§3・§4.1。**リポジトリ内で一致** |
| `quote_categories` | 維持 | そのまま移行 | 名言–category関連IDを同等値で保持 | 第1部§3.7、第2部§3・§4.1。**リポジトリ内で一致**。孤立の修正・削除はユーザー判断待ち |
| `quotes` | 維持 | 変換して移行 | 全行のID、slug、公開状態、日英本文、表示言語、関連を保持。qidはIDから生成 | 第1部§3.8・§3.21・§12.3–5、第2部§3・§4.1・§7、ADR 008・009・011。**リポジトリ内で一致**。NULL・空値の修正はユーザー判断待ち |
| `category_rankings` | 維持 | 再計算 | categoryランキング最新snapshotの責務を維持し、名言scoreと関連から再生成 | 第1部§3.9・§8、第2部§3・§4.1・§4.3、ADR 005。構造は**リポジトリから推定**、派生性は**リポジトリ内で一致** |
| `characters` | 維持 | 変換して移行 | 登場人物の内容、slug、出典関連と公開・管理機能を維持 | 第1部§3.10、第2部§3・§4.1。**リポジトリ内で一致** |
| `source_type_assignments` | 本番確認待ち | 変換して移行 | 出典–種別の意味は必ず移行。多対多構造の維持可否だけcardinality確認まで保留 | 第1部§3.11・§12.1、第2部§3・§4.1。構造は**本番確認待ち**。意味の縮退はユーザー判断待ち |
| `source_types` | 維持 | 変換して移行 | 出典filter・表示・管理補助に必要なmasterを維持 | 第1部§3.12、第2部§3・§4.1。**リポジトリ内で一致** |
| `sources` | 再編 | 変換して移行 | 出典本体、slug、著者関連は保持。PGroonga用`search_document`は移行しない | 第1部§3.13・§9、第2部§3・§4.1・§4.6・§7、ADR 002・011。判断は**リポジトリから推定** |
| `countries` | 維持 | 変換して移行 | 国master、slug、著者filter・管理機能を維持 | 第1部§3.14、第2部§3・§4.1。**リポジトリ内で一致** |
| `legacy_votes` | 再編 | 変換して移行 | 再構築不能な名言別旧票集計の意味・値を保持するが、独立表維持は前提にしない | 第1部§3.15・§8・§12.7、第2部§4.1・§10。値保護は**リポジトリ内で一致**、構造判断は**リポジトリから推定**。廃棄はユーザー判断待ち |
| `professions` | 維持 | 変換して移行 | 公開一覧・filter、著者関連、管理CRUDのmaster責務を維持 | 第1部§3.16、第2部§3・§4.1。**リポジトリ内で一致** |
| `quote_likes` | 再編 | 変換して移行 | `quote_id`、`client_uuid`、投票時点、一意性、有効票を保持。IP/IP hashは移行しない | 第1部§3.17・§12.6、第2部§3・§4.1・§6・§7、ADR 006。**リポジトリから推定**。`id/user_agent/is_valid`とinvalid行は確認後にユーザー判断 |
| `quote_ranking_scores` | 維持 | 再計算 | 多数の公開機能が読む名言score最新snapshotを原本から再生成 | 第1部§3.18・§8、第2部§3・§4.1・§4.3。**リポジトリ内で一致** |
| `ranking_parameters` | 処理へ置換 | 変換して移行 | ranking係数を本番値確認後に明示的な処理設定へ変換。`ip_daily_limit`はADR 006により移行しない | 第1部§3.19・§8・§12.9、第2部§3・§4.1・§7・§10。**リポジトリから推定**。係数変更はユーザー判断待ち |
| `ranking_refresh_logs` | 処理へ置換 | 本番確認待ち | stderr・外部heartbeat・前回正常状態へ置換。旧履歴の必要範囲は未決 | 第1部§3.20・§8・§12.9、第2部§3・§4.1・§8・§9、ADR 005。**リポジトリから推定**。件数・status・調査価値を確認後にユーザー判断 |

### 2.2 view / materialized view（7件）

| object | 種別 | 構造 | データ | 判断・代替 | 根拠・確度・条件 |
|---|---|---|---|---|---|
| `characters_with_quote_counts` | view | 処理へ置換 | — | 公開名言件数を単純な集計SQLで算出 | 第1部§5.1、第2部§3・§4.2。**リポジトリから推定**。性能・件数一致を実測 |
| `view_admin_kpi_counts` | view | 本番確認待ち | — | runtime参照なし。外部consumerがなければ廃止し、必要なら直接COUNT | 第2部§3・§4.2・§10。**リポジトリから推定** |
| `view_admin_ranking_refresh_logs` | view | 本番確認待ち | — | runtime参照なしでbase table queryと重複。外部consumerがなければ廃止 | 第2部§4.2・§5・§9。**リポジトリから推定** |
| `categories_with_counts` | MV | 処理へ置換 | 再計算 | direct/hierarchy/effective countを単純集計SQLへ置換 | 第1部§5.2・§9、第2部§3・§4.2・§9。**リポジトリから推定**。populate・鮮度・性能を確認 |
| `country_author_counts` | MV | 処理へ置換 | 再計算 | 国別の公開著者・名言数を直接集計 | 第1部§5.2、第2部§3・§4.2。**リポジトリから推定** |
| `profession_author_counts` | MV | 処理へ置換 | 再計算 | 職業別の公開著者・名言数を直接集計 | 第1部§5.2、第2部§3・§4.2。**リポジトリから推定** |
| `quote_ranking_scores_mv` | MV | 処理へ置換 | 再計算 | score table同期前の中間MVを除き、CLIが原本から必要snapshotを再計算 | 第1部§5.2・§8、第2部§3・§4.2–4.3、ADR 005。**リポジトリ内で一致** |

### 2.3 function / RPC（26 signature）

| # | signature | 構造 | 判断・代替 | 根拠・確度・条件 |
|---:|---|---|---|---|
| 1 | `_refresh_quote_ranking_scores_internal(trigger_source text='unknown')` | 処理へ置換 | 多段更新をPython CLIの単一処理へ整理 | 第1部§6・§8、第2部§4.3。**リポジトリ内で一致** |
| 2 | `build_author_jsonb(p_author_id integer)` | 処理へ置換 | SQL結果をPythonで構造化 | 第2部§4.3。**リポジトリ内で一致** |
| 3 | `build_categories_jsonb(p_quote_id integer)` | 処理へ置換 | 関連をSQLで取得しPythonで構造化 | 同上 |
| 4 | `build_character_jsonb(p_character_id integer)` | 処理へ置換 | SQL結果をPythonで構造化 | 同上 |
| 5 | `build_source_jsonb(p_source_id integer)` | 処理へ置換 | SQL結果をPythonで構造化 | 同上 |
| 6 | `check_display_order_sequence()` | 本番確認待ち | trigger未接続・consumerなし。外部利用がなければ廃止 | 第1部§6・§7.1、第2部§4.3・§5。**リポジトリから推定** |
| 7 | `ensure_category_parent_level()` | 再編 | 2階層・親level整合をSQLite互換の制約等へ再編 | 第1部§3.6・§6、第2部§4.3–4.4。**本番dumpで確認／リポジトリ内で一致** |
| 8 | `ensure_quote_categories_level2()` | 再編 | level 2限定割当をSQLite互換の整合性保証へ再編 | 第1部§6、第2部§4.3–4.4。**本番dumpで確認／リポジトリ内で一致** |
| 9 | `get_category_quotes_light(integer,integer,integer)` | 本番確認待ち | consumerなし。外部RPC利用がなければ廃止 | 第2部§4.3・§5・§10。**リポジトリから推定** |
| 10 | `get_featured_quotes_light(integer)` | 処理へ置換 | 上位名言を単純SQL + Python mappingで取得 | 第2部§3・§4.3。**リポジトリ内で一致** |
| 11 | `get_quote_rankings(...)`（13引数） | 処理へ置換 | filter・pagination・sort・検索をbind付きSQL/Pythonへ置換 | 第1部§6、第2部§3・§4.3。**リポジトリ内で一致** |
| 12 | `get_random_quotes(...)`（6引数） | 処理へ置換 | 公開対象から20件を返すSQL/Pythonへ置換 | 第2部§3・§4.3、ADR 010。**リポジトリ内で一致** |
| 13 | `get_sources_with_quote_counts(...)`（5引数） | 廃止 | 7引数相当経路へ統合し、overloadを持ち込まない | 第1部§6・§9、第2部§4.3・§8・§10。**リポジトリ内で一致**。外部consumerを切替前に確認 |
| 14 | `get_sources_with_quote_counts(...)`（7引数） | 処理へ置換 | source一覧・filter・検索・件数をSQL/Pythonへ置換 | 第2部§3・§4.3。**リポジトリ内で一致** |
| 15 | `is_admin()` | 廃止 | Cloudflare Access + FastAPI管理境界へ置換するため不要 | 第2部§4.3・§4.5、ADR 012。**リポジトリ内で一致** |
| 16 | `list_authors(...)`（7引数） | 処理へ置換 | 一覧・filter・歴史日付・件数をSQL/Pythonへ置換 | 第2部§3・§4.3。**リポジトリ内で一致** |
| 17 | `list_popular_authors(integer)` | 処理へ置換 | 公開名言数等による取得を単純SQLへ置換 | 同上 |
| 18 | `list_professions_overview(...)`（5引数） | 処理へ置換 | 件数・featured quoteをSQL/Pythonへ置換 | 同上 |
| 19 | `refresh_quote_ranking_scores()` | 本番確認待ち | MVのみ更新するconsumerなしoverload。外部利用がなければ廃止 | 第1部§8、第2部§4.3・§5・§9–10。**リポジトリから推定** |
| 20 | `refresh_quote_ranking_scores(trigger_source text='unknown')` | 処理へ置換 | supercronicから起動するPython CLIへ置換 | 第2部§3・§4.3、ADR 005。**リポジトリ内で一致** |
| 21 | `refresh_sources_search_document_after_author_delete()` | 廃止 | 派生列を廃止し、title + author nameを直接JOINしてescaped LIKE検索 | 第1部§6・§9、第2部§4.3–4.4、ADR 002。**リポジトリ内で一致** |
| 22 | `refresh_sources_search_document_for_author()` | 廃止 | 同上 | 同上 |
| 23 | `search_authors(text,integer,integer,boolean)` | 処理へ置換 | escaped LIKE検索へ置換 | 第2部§3・§4.3、ADR 002。**リポジトリ内で一致** |
| 24 | `search_quotes(text,integer,integer,boolean,boolean)` | 処理へ置換 | 名言・著者等へのescaped LIKE検索へ置換 | 同上 |
| 25 | `set_source_search_document()` | 廃止 | 派生列保守をやめ、title + author nameを直接検索 | 第2部§4.3–4.4、ADR 002。**リポジトリ内で一致** |
| 26 | `update_updated_at_column()` | 処理へ置換 | ADR 011 serializerを通す明示更新処理へ置換 | 第1部§3.21・§6、第2部§4.3–4.4、ADR 011。**リポジトリ内で一致** |

### 2.4 trigger（14件）

| trigger | 構造 | 判断・代替 | 根拠・確度・条件 |
|---|---|---|---|
| `categories_validate_hierarchy` | 再編 | 2階層と親level整合をSQLite互換方式へ再編 | 第1部§7.1、第2部§4.4・§6。**本番dumpで確認／リポジトリ内で一致** |
| `quote_categories_validate_level` | 再編 | level 2限定割当をSQLite互換方式へ再編 | 同上 |
| `refresh_sources_search_document_after_author_delete` | 廃止 | 検索派生列を持たないため不要 | 第2部§4.4、ADR 002。**リポジトリ内で一致** |
| `refresh_sources_search_document_for_author` | 廃止 | 同上 | 同上 |
| `set_source_search_document` | 廃止 | 同上 | 同上 |
| `update_admin_users_updated_at` | 廃止 | `admin_users`を移植しないため不要 | 第2部§4.4、ADR 012。**リポジトリ内で一致** |
| `update_authors_updated_at` | 処理へ置換 | PythonでADR 011形式を設定 | 第2部§4.4・§6。**リポジトリ内で一致** |
| `update_characters_updated_at` | 処理へ置換 | 同上 | 同上 |
| `update_countries_updated_at` | 処理へ置換 | 同上 | 同上 |
| `update_quotes_updated_at` | 処理へ置換 | 同上 | 同上 |
| `update_ranking_parameters_updated_at` | 本番確認待ち | repository内はSELECTのみ。外部UPDATEと表のmutable判断を確認 | 第2部§4.4。**リポジトリから推定** |
| `update_source_type_assignments_updated_at` | 本番確認待ち | 現行管理はDELETE/INSERT。外部UPDATEがなければ廃止 | 第2部§4.4・§6。**リポジトリから推定** |
| `update_source_types_updated_at` | 本番確認待ち | 現行はread-only補助。外部UPDATEと移行後のmutable判断を確認 | 第2部§3・§4.4。**リポジトリから推定** |
| `update_sources_updated_at` | 処理へ置換 | PythonでADR 011形式を設定 | 第2部§4.4・§6。**リポジトリ内で一致** |

### 2.5 ENUM / EXCLUDE / PGroonga index / cron想定job（10件）

| object | 種別 | 構造 | 判断・守る対象 | 根拠・確度・条件 |
|---|---|---|---|---|
| `date_precision` | ENUM | 再編 | `day/month/year/unknown`の値域と歴史日付の意味をSQLite互換制約で保持 | 第1部§4.1、ADR 011。**本番dumpで確認／リポジトリ内で一致** |
| `life_era` | ENUM | 再編 | `bc/ad`の値域をSQLite互換制約で保持 | 同上 |
| `author_birth_country_unique` | EXCLUDE | 再編 | 著者ごとの生誕国最大1件をSQLite互換方式で保証 | 第1部§3.2。**本番dumpで確認**。0件・複数候補を確認 |
| `idx_quotes_pgroonga` | PGroonga index | 廃止 | 名言検索はescaped LIKEへ置換 | 第2部§4.6、ADR 002。**リポジトリ内で一致** |
| `idx_quotes_text_en_pgroonga` | PGroonga index | 廃止 | 英語本文を含む必要な検索対象はSQL側で保持 | 同上 |
| `idx_sources_search_document_pgroonga` | PGroonga index | 廃止 | title + author nameの意味を直接JOIN + escaped LIKEで保持 | 第2部§4.6、source検索migration、ADR 002。**リポジトリ内で一致** |
| `idx_categories_pgroonga` | PGroonga index | 廃止 | consumerなしで初期検索方式にも不要 | 第2部§4.6、ADR 002。**リポジトリ内で一致**。外部queryを確認 |
| `pgroonga_professions_name_index` | PGroonga index | 廃止 | 現行RPCも`ILIKE`でindex利用経路なし | 同上 |
| `refresh_quote_ranking_scores_scheduler` | cron想定job | 処理へ置換 | supercronic + CLIへ置換 | 第1部§7.5、第2部§4.7、ADR 005。経路は**リポジトリ内で一致**、job実在は**本番確認待ち** |
| `refresh_categories_with_counts_scheduler` | cron想定job | 廃止 | 件数を単純SQLで算出する初期案では不要 | 第1部§7.5、第2部§4.7。**リポジトリから推定**、job実在は**本番確認待ち** |

### 2.6 RLS policy（57件）

policyはデータを持たないため構造だけを分類する。policy名は第1部§7.3、第2部§4.5の全57件を、重複のないgroupとして列挙した。必要な公開read、管理write、likes保護、内部jobの認可動作はFastAPI/Cloudflare Access/内部CLIへ移す。

| policy群 | policy名 | 件数 | 構造 | 判断・代替 |
|---|---|---:|---|---|
| 管理者本人確認 | `admin_users_read_own` | 1 | 処理へ置換 | Supabase own-row照合をADR 012の認証・CSRF境界へ置換 |
| 公開・参照 | `author_country_read_all`, `Author professions are viewable by everyone`, `author_rankings_select_public`, `authors_read_all`, `categories_select_all`, `category_rankings_select_public`, `characters_read_all`, `countries_read_all`, `Professions are viewable by everyone`, `quote_categories_select_all`, `quote_ranking_scores_select_public`, `quotes_select_all`, `source_type_assignments_select_all`, `source_types_select_all`, `sources_read_all` | 15 | 処理へ置換 | 公開route/serviceのSELECTへ置換。15件中12件は`USING (true)`、ranking系3件(`author_rankings_select_public`、`category_rankings_select_public`、`quote_ranking_scores_select_public`)は`auth.role()`による全role許可で実質無条件(レビューでdump確認)。いずれも内容による絞込みを行わないため、公開状態絞込みはquery側で維持 |
| 重複公開SELECT | `Allow public read` on `categories`, `quote_categories`, `quotes` | 3 | 廃止 | 同表の`*_select_all`と重複。必要read動作は前行に集約 |
| repository内write経路ありの管理認可 | `author_country_admin_write`, `author_professions_admin_write`, `authors_admin_write`, `countries_admin_write`; `categories_admin_delete/insert/update`; `characters_admin_delete/insert/update`; `quote_categories_admin_delete/insert/update`; `quotes_admin_delete/insert/update`; `source_type_assignments_admin_delete/insert`; `sources_admin_delete/insert/update` | 21 | 処理へ置換 | 現行writeはservice role bypassするためpolicy自体は適用されないが、対応する管理write経路はある。必要な管理認可をAccess・FastAPI管理route・CSRFへ置換して守る |
| repository内write経路なしの管理認可 | `source_type_assignments_admin_update`; `source_types_admin_delete`, `source_types_admin_insert`, `source_types_admin_update` | 4 | 処理へ置換 | assignment管理はDELETE/INSERTだけでUPDATEせず、source typeはruntime read-onlyである。repository外writeがあればその認可をAccess・FastAPIへ条件付き置換し、なければpolicyを代替なしで廃止する。外部consumer確認までは本番未使用と断定しない |
| 旧authenticated包括write | `Allow authenticated write` on `categories`, `quote_categories`, `quotes` | 3 | 廃止 | 操作別policyと重複し、現行writeにも適用されず、ADR 001/012の境界と不整合 |
| ranking内部write | `author_rankings_service_rw`, `category_rankings_service_rw`, `legacy_votes_service_rw`, `quote_ranking_scores_service_rw` | 4 | 処理へ置換 | 内部CLI/job・管理処理だけがranking更新を実行 |
| 匿名likes保護 | `Allow service role select`, `quote_likes_insert_for_service`, `quote_likes_no_delete_for_clients`, `quote_likes_no_update_for_clients` | 4 | 処理へ置換 | 公開は冪等POSTだけとし、公開UPDATE/DELETE endpointを設けない |
| legacy公開read | `legacy_votes_select_public` | 1 | 廃止 | 直接consumerなし。repository外consumer確認後、policyを廃止。データ判断とは分離 |
| ranking parameter公開read | `ranking_parameters_select_policy` | 1 | 廃止 | 公開read consumerなし。repository外consumerを確認 |
| **合計** |  | **57** | **処理へ置換49 / 廃止8** |  |

根拠は第1部§2・§7.3–7.4、第2部§1.2・§4.5。件数・構造は**本番dumpで確認**、repository内適用経路は**リポジトリ内で一致**。policy適用経路なしを本番未使用とは断定しない。

### 2.7 RLS・GRANT設定監査（原子object集計外）

| 設定群 | 監査件数 | 構造 | 判断 |
|---|---:|---|---|
| 全20表の`ENABLE ROW LEVEL SECURITY` | 20 | 廃止 | SQLiteを匿名clientへ直接公開せず、API/管理/CLI境界へ置換 |
| app function ACL | 78 | 廃止 | 26 signature × 3 Supabase roleを持ち込まない |
| PGroonga function ACL | 572 | 廃止 | 143 signature × 4 role。PGroongaとともに除外 |
| `public` schema USAGE | 4 | 廃止 | SQLiteにschema role ACLはない |
| sequence ACL | 27 | 廃止 | 9 sequence × 3 role。SQLiteへ持ち込まない |
| table/view/MV ACL | 77 | 廃止 | DB object直接公開をやめ、route単位で制御 |
| **明示GRANT合計** | **758** | **廃止** |  |
| default privilege | 12 | 廃止 | sequence/function/table × 4 roleの自動ACLを持ち込まない |

全26 app functionは3 roleへの明示ALLを持ち、8件は`SECURITY DEFINER`である。DDL上の広い権限は**本番dumpで確認**したが、PostgREST等からの到達性、実行実績、実効権限は**本番確認待ち**であり、現行環境の危険性を未確認のまま断定しない。

### 2.8 分類集計

#### 構造の扱い

| 母集団 | 維持 | 再編 | 処理へ置換 | 廃止 | 本番確認待ち | 合計 |
|---|---:|---:|---:|---:|---:|---:|
| table | 12 | 4 | 2 | 1 | 1 | 20 |
| 派生・補助（view/MV/function/trigger/ENUM/EXCLUDE/PGroonga/job） | 0 | 7 | 27 | 15 | 8 | 57 |
| RLS policy | 0 | 0 | 49 | 8 | 0 | 57 |
| **全原子object** | **12** | **11** | **78** | **24** | **9** | **134** |

#### データの扱い

| 対象 | そのまま移行 | 変換して移行 | 再計算 | 移行しない | 本番確認待ち | 合計 |
|---|---:|---:|---:|---:|---:|---:|
| table | 1 | 14 | 3 | 1 | 1 | 20 |
| MV | 0 | 0 | 4 | 0 | 0 | 4 |

データを持たない110 objectにはデータ分類を付けていない。設定監査のRLS有効20、GRANT 758、default privilege 12もこの集計へ含めない。

## 3. 歪み・重複・過剰が疑われる箇所

| 歪みパターン | 第1部・第2部の事実 | 本フェーズの見解 |
|---|---|---|
| 現在は不要なtable/column | `admin_users`はADR 012で移植不要。`quote_likes.ip_hash/user_agent/is_valid`、`sources.search_document`、ranking snapshot/logには移行先で不要な候補がある（第1部§3・§8、第2部§4.1） | 原本と区別して廃止・再編する。likesのinvalid履歴や旧logは確認・ユーザー判断前に廃棄しない |
| 役割が重複するtable/view/RPC | ranking MV→score table→author/category snapshot→log、未使用のlog view、KPI view、source 5/7引数RPC、refresh 2 overload、重複policyがある（第1部§5–8、第2部§3・§4.2–4.5・§10） | 必要な振る舞い単位へ集約。経路なしobjectは条件付き廃止候補 |
| PostgreSQL/Supabase固有構造 | RLS、ACL、Auth role、`SECURITY DEFINER`、PGroonga、`pg_cron`、MV concurrent refresh、ENUM、EXCLUDE、extension（第1部§4–7） | 実装方式は持ち込まず、認可・検索・定期処理・整合性だけをSQLite/FastAPIへ置換 |
| 過去仕様由来の名前・制約 | `legacy_votes`、`authors_new_id_seq`、level 3 commentと1/2 CHECKの差、nullable `quotes.slug/enable`、日時default混在（第1部§3.5–3.8・§3.15・§3.21・§10） | URL・歴史情報を守りつつ再評価し、過去名やcommentを機械移植しない |
| 不要になった集計table/MV | 4 MV、ranking snapshot 3表、count view/MV、logがあり、現行ranking chainは多層（第1部§5・§8、第2部§3） | 件数はまずリアルタイムSQL、rankingは必要snapshotとCLIに絞る。原本・履歴を先に確認 |
| アプリとDBに分散した処理 | ranking、source検索、likes、category件数/cache、KPIがDB function/MV/triggerとアプリへ分散（第2部§3・§6–7・§10） | DB制約・単純SQL・Pythonのいずれかへ責務を寄せ、失敗時の原本と責任を明確化 |
| DB制約で保証可能だがアプリだけで検証 | `quotes.enable`はNULL可、本文fallbackはresolverのみ、log statusにCHECKなし、qidはアプリ生成、bulkは疑似rollback。公開APIだけenable挙動が異なる（第1部§3.8・§3.20、第2部§3・§7・§10） | 基本整合性はDB制約候補とし、公開状態・URL・fallbackはアプリと一貫させる |
| 現在規模に対して過剰な制約・集計 | `author_country`にEXCLUDEと類似index 5本、category CHECK重複、明示index 54本、PGroonga 5本、多数のranking派生object（第1部§2・§3.2・§3.6・§5・§8） | queryと規模に比例して削減。ただしFK・UNIQUE等の基本整合性は弱めない |
| migration上存在するが現行アプリ経路なし | view 2、function 4 signature、trigger 4、policy 38、PGroonga 2、cron 2。`getQuotes`のPGroonga分岐も呼出し元がなく、`author.name` indexもない（第2部§2・§4.2–4.7・§5・§10） | 本番未使用とは断定せず、外部consumer確認後の廃止候補。dead分岐は新実装へ持ち込まない |
| 移行・過去修正用の一時構造 | `legacy_votes`は旧票統合用。import/cleanup/sample scriptには過去修正経路や現行column不一致がある（第1部§3.15・§9–11、第2部§8） | script・一時構造は持ち込まない候補だが、旧票値は再構築不能なので保持判断を分ける |

`QuotesService.getQuotes`のPGroonga直接分岐（第2部§4.6補足）は、定義以外の9呼出しがすべて`search`未指定で、公開検索は`search_quotes` RPCを使う。さらに`author.name`用PGroonga indexは5本の中にない。したがって検索機能は維持しつつ、到達していない重複分岐を移植せず、ADR 002のescaped `LIKE`へ統一する **[リポジトリ内で一致 / planner・外部queryは本番確認待ち]**。

## 4. 重点設計論点への見解

### 4.1 現行19（+ `admin_users`）テーブルを本当にすべて残す必要があるか

**事実:** dumpの20表は既存計画の19表 + `admin_users`で、全表にrepository内経路がある。ただし原本、派生、運用ログ、旧集計、認証の責務が混在する（第1部§2・§3・§8、第2部§3・§4.1）。

**見解・結論:** 全20構造の一律維持はしない。コンテンツ、関連、公開状態、URL、likes、rankingの意味を守り、表単位の分類に従って再編・置換・廃止する。構造削減とデータ削除を混同しない。**本番dumpで確認／リポジトリ内で一致**。

### 4.2 `legacy_votes`を原本データとして残す必要があるか

**事実:** 旧サイト由来の名言別累計で個票ではないが、現行ranking入力である（第1部§3.15・§8・§9、第2部§3・§4.1・§10）。

**見解・結論:** 個票原本ではないが、旧票寄与の唯一の移行元として値を変換移行する。独立表の維持は必須でない。件数・分布・対応を確認し、寄与をリセットするなら**ユーザー判断待ち**。構造・chainは**本番dumpで確認／リポジトリ内で一致**、実値は**本番確認待ち**。

### 4.3 ranking snapshot 3表をすべて保持すべきか

**事実:** `quote_ranking_scores`、`author_rankings`、`category_rankings`は参照中の最新snapshotで再計算可能。周辺にMV、function、parameters、logsが連鎖する（第1部§3.4・§3.9・§3.18・§8、第2部§3・§4.1・§4.3）。

**見解・結論:** 3表それぞれを「SQLiteでも概ね同じ責務と構造を使う」という意味で**維持**し、行は原本から再計算する。この維持判断はフェーズ3で確定し、query時集計へ置き換える案をフェーズ4の未決事項には残さない。一方、現行MV・RPC多段chainは維持せず処理へ置換する。順位・同点順序・score・前回正常結果を失わない。consumerは**本番dumpで確認／リポジトリ内で一致**。

### 4.4 `ranking_refresh_logs`をどこまで保持すべきか

**事実:** CLIがbase tableの直近結果を確認し、保持期限はない（第1部§3.20・§7.5・§8、第2部§3・§4.1・§8）。

**見解・結論:** ADR 005のheartbeat・失敗診断・前回正常状態へ処理置換し、無期限DB履歴は前提にしない。旧履歴の移行範囲・保持期間は件数・status・障害調査実績を示して**ユーザー判断待ち**。構造・参照は**本番dumpで確認／リポジトリ内で一致**、実履歴は**本番確認待ち**。

### 4.5 集計view/MVをリアルタイムSQLへ置換できるか

**事実:** character/count viewと3 count MVはruntime利用中。管理view 2件はconsumerがなく、category MVはmigration外refresh経路がない（第1部§5、第2部§3・§4.2・§4.7・§10）。

**見解・結論:** 規模上、公開限定・階層・重複除外・空要素を再現するリアルタイムSQLを第一候補とする。ranking MVは別扱い。管理view 2件は外部consumer確認後の廃止候補。性能判断は**リポジトリから推定**で、本番相当行数で実測する。

### 4.6 国と著者の関連が過剰に複雑でないか

**事実:** `author_country`は複数関連国と最大1件の生誕国を表し、アプリも両方を扱う。EXCLUDEと類似index 5本がある（第1部§3.2、第2部§3・§4.1）。

**見解・結論:** 2つの意味は維持するが、PostgreSQL固有制約・重複indexは再編する。単一国へ縮退すると意味を失い得るため、0/1/複数・未設定を確認後に狭める場合は**ユーザー判断待ち**。構造・validationは**本番dumpで確認／リポジトリ内で一致**、分布は**本番確認待ち**。

### 4.7 出典と出典種別の関連構造は適切か

**事実:** 出典は任意の著者を持ち、名言・登場人物から参照され、複数種別が一覧・filter・管理で使われる（第1部§3.10–3.13、第2部§3・§4.1・§7）。

**見解・結論:** 関連の意味は妥当で維持する。複雑さの主因である検索派生列・trigger・RPC・JSON builderを再編／処理置換する。構造とconsumerは**本番dumpで確認／リポジトリ内で一致**。

### 4.8 `source_type_assignments`が必要か

**事実:** 管理APIは種別配列を扱い、公開側も複数種別を表示・filterする（第1部§3.11–3.13、第2部§3・§4.1）。

**見解・結論:** 関連概念とデータは必要。現行多対多構造は0/1/複数分布を確認するまで**本番確認待ち**。全件最大1件でも自動的に意味を狭めず、縮退は**ユーザー判断待ち**。アプリ契約は**リポジトリ内で一致**。

### 4.9 `display_language_preference`の制約とfallback

**事実:** 現行は`NOT NULL DEFAULT 'ja'`、`ja|en`で、resolverは指定側がNULL/空文字なら他方へfallbackする（第1部§3.8、第2部§7、ADR 009）。

**見解・結論:** 物理名、値域、default、共通resolverをADRどおり維持する。本文・metadata等の表示を統一する。構造・resolverは**本番dumpで確認／リポジトリ内で一致**、値分布・空文字は**本番確認待ち**。

### 4.10 quote ID、qid、slugの役割と互換性

**事実:** integer PKからアプリが`q{id}`を作り、qidはDB列でない。nullable slugがあればcanonicalに使い、qid fallbackを持つ（第1部§3.8、第2部§7、ADR 008）。

**見解・結論:** ID値・slugを保持し、qidは派生URL識別子のままにする。独立qid列を増やさず、解決順序、旧redirect、sitemap、canonicalをURL契約として維持する。構造は**本番dumpで確認**、規則は**リポジトリ内で一致**、NULL slug・予約形式・実URLは**本番確認待ち**。

### 4.11 `quote_likes`の一意制約と識別情報

**事実:** `(quote_id, client_uuid)`はADR 006と一致し、`created_at`は期間rankingに使う。row UUID consumerやinvalid化writeはrepository内で見つからない（第1部§3.17、第2部§4.1・§7）。

**見解・結論:** quote、client UUID、投票時点、一意性、有効票を保持する。IP/IP hashは保存せず、`user_agent`も根拠がない。`is_valid`とinvalid行は外部運用確認後に整理し、invalid票を有効化しない。構造・consumerは**本番dumpで確認／リポジトリ内で一致**、実値・外部運用は**本番確認待ち**。歴史的寄与を捨てるなら**ユーザー判断待ち**。

### 4.12 管理認証用tableを移行対象から外せるか

**事実:** 現行は`admin_users`、`is_admin()`、RLSを使うが、ADR 012は外部IdPとAccessを確定している（第1部§3.1・§6–7、第2部§1.2・§4.1・§6）。

**見解・結論:** `admin_users`、`is_admin()`、管理RLSを移行しない。管理画面、サーバー側認証、CSRF対策はAccess/FastAPIで維持し、profession actionも親境界だけに依存させない。**リポジトリ内で一致**。ADR衝突なし。

### 4.13 PostgreSQL RPCを単純SQLまたはPythonへ置換できるか

**事実:** 26 signatureはranking、JSON builder、検証、listing/search、認証、検索文書、時点更新に分かれる（第1部§6・§8、第2部§4.3・§5・§7・§10）。

**見解・結論:** 初期構成へPostgreSQL function/RPCを持ち込まず、通常SQL、Python mapping/CLI、基本制約へ置換する。未接続check、未使用category RPC、引数なしrefreshは外部consumer確認後に廃止し、5引数source overloadは7引数相当へ統合する。filter、pagination、公開限定、random 20件、transaction・失敗動作は守る。signature・consumerは**本番dumpで確認／リポジトリ内で一致**、外部consumerは**本番確認待ち**。

### 4.14 検索index・派生列を初期構成から除外できるか

**事実:** PGroonga index 5本と`sources.search_document`を3 function/triggerが保守する。category/profession indexと`getQuotes`直接分岐にはconsumerがなく、同分岐の`author.name` indexもない（第1部§3.6・§3.8・§3.13・§3.16・§5–7、第2部§4.6補足）。

**見解・結論:** ADR 002どおりPGroonga、FTS、bigram、検索派生列を除外し、escaped bind `LIKE`へ統一する。名言・著者・出典等の検索対象、pagination、公開限定は維持し、通常のURL/FK indexまで一律削除しない。構造・経路は**本番dumpで確認／リポジトリ内で一致**、planner・外部queryは**本番確認待ち**。

### 4.15 日時と歴史日付を明確に分離できるか

**事実:** 時点列は`timestamptz`だがdefault・NULL・RPC型が混在し、著者生没日はdate + era/precision、刊行年はintegerである（第1部§3.21、第2部§7・§10）。

**見解・結論:** ADR 011どおり時点を固定長UTC表現と明示serializer/parserへ統一し、歴史日付・紀元・精度・刊行年はUTC変換しない。期間ranking・sitemap時刻とBC/不完全日付を双方守る。現行型は**本番dumpで確認**、方針は**リポジトリ内で一致**、実値は**本番確認待ち**。

### 4.16 第2部§10・§4.6補足との対応

| 第2部からの引継ぎ事実 | 本書の見解 |
|---|---|
| 未使用の管理KPI view、固定KPI | §2.2、§3、論点1・5・13 |
| source RPC 5/7引数overload | §2.3、論点7・8・13 |
| ranking refresh 2 signature | §2.3、論点3・4・13 |
| 未使用`get_category_quotes_light`、`is_admin`、`check_display_order_sequence` | §2.3、論点5・12・13 |
| SELECT policy重複、service role bypass | §2.6–2.7、論点12・13 |
| 複雑なranking chainと`legacy_votes` | §2.1–2.3、論点2・3・4・13 |
| `categories_with_counts`のrefresh代替なし | §2.2・§2.5、論点5 |
| category/profession PGroonga index未使用 | §2.5、論点14 |
| `getQuotes`のdead PGroonga分岐、author indexなし | §3、論点14 |
| source検索文書trigger、assignment UPDATE trigger非発火 | §2.3–2.4、論点7・8・13・14 |
| 公開`/api/quotes`のenable差異 | §3、論点1・10。意図確認前に互換性変更を確定しない |
| profession actionの認証境界 | 論点12。Access・サーバー側認証・CSRFへ引継ぎ |
| validation、bulk、qid、fallback、tree、likes、revalidateがDB外 | 論点5・9–11・13。ADR 014のcache動作もアプリへ引継ぎ |
| timestamp処理の分散 | 論点15 |

## 5. ユーザー判断が必要な事項

| 判断事項 | 推奨案 | 判断材料・判断時期 |
|---|---|---|
| `legacy_votes`の旧票寄与 | 値を保持して変換移行 | 件数、値分布、対象quote、現行表示・scoreへの寄与。廃棄は本番確認後のみ |
| `ranking_refresh_logs`旧履歴 | 新環境の状態確認に必要な最小範囲だけ移し、無期限保持しない | 行数、期間、status、障害調査実績 |
| likesの`id/user_agent/is_valid`とinvalid行 | 有効票・取消可能性を守り、invalid票を有効化しない。IP情報は移さない | valid/invalid件数、外部invalid化、期間rankingへの影響 |
| 公開`/api/quotes`のenable未指定時 | 通常公開機能と同じ公開限定を推奨 | 現行consumer、非公開露出、ADR 008互換範囲 |
| `source_type_assignments`の構造 | 複数関連の意味を維持 | 0/1/複数分布、UI/filter、孤立・重複。本番確認後 |
| `author_country`の意味・制約 | 複数関連国と生誕国を維持 | 0/1/複数、生誕国未設定・孤立。縮退する場合のみ判断 |
| nullable slug、`enable IS NULL`、本文空値 | 行・意味を無断変更せず、URL/表示影響を確認して補正 | 件数、対象URL、fallback結果 |
| ranking係数 | 現行値を同等の処理設定へ移す | `ranking_parameters`のkey/value。挙動を変える場合のみ判断 |
| 管理KPI | 必要なら直接COUNT、不要なら固定cardも廃止 | 実運用での利用者、必要な値、外部consumer |
| 現行Supabase権限の是正 | 外部到達可能な広いACLが確認された場合に別作業として判断 | RLS・GRANT・`SECURITY DEFINER`を組み合わせた実効権限と呼出し履歴 |

原本コンテンツを「移行しない」とする確定提案はない。`admin_users`は認証データでありADR 012により移行対象外、MV 4件は派生データなので再計算する。

## 6. 本番確認待ち（フェーズ5への引き継ぎ）

1. 全tableの行数、NULL、重複、孤立、常時同値。特にslug、公開状態、本文、関連表。
2. `legacy_votes`の件数・値分布・対象quote・ranking寄与。
3. `quote_likes`のclient UUID形式、valid/invalid分布、外部invalid化、補助識別情報。値そのものではなく必要最小限の安全な集計を使う。
4. ranking 3 snapshot、parameters、logs、4 MVの件数・鮮度・整合と、原本からの再計算時間。
5. `ranking_refresh_logs`の期間、status集合、参照・障害調査用途。
6. cron想定job 2件の実在、active、schedule、履歴、実際に呼ぶrefresh signature。
7. category/country/profession/character集計の関連行数、現行件数の意味、SQLite相当データでの単純SQL性能。
8. `author_country`の0/1/複数、生誕国未設定、孤立と意味。
9. `source_type_assignments`の0/1/複数、孤立・重複、repository外consumer。
10. quote ID最大値、slug NULL・予約形式、`enable IS NULL`、既存URL・redirect実例。
11. `display_language_preference`値分布と`text/text_en`のNULL・空文字組合せ。
12. 時点列のoffset・精度・NULL、歴史日付のera/precision分布。
13. repository内経路なしのview 2、function 4、trigger 4、policy 38、PGroonga index 2、cron 2、および5引数source RPCのrepository外consumer。
14. RLS、GRANT/default privilege、`SECURITY DEFINER`、view `security_invoker`の本番実効権限と外部API到達性。
15. repository内writeのない`source_types`のDELETE/INSERT/UPDATEと`source_type_assignments`のUPDATEについて、外部管理writeの有無、broad default privilege・MV再作成後ACLの運用意図。
16. 現行source検索の代表query結果（title、author name、複数token）と、直接JOIN + `LIKE`での結果・性能。
17. PGroonga query planは参考として確認する。ただしADR 002により初期採用判断は変えない。
18. 公開`/api/quotes`の実consumerとenable未指定時の運用意図。

本番DBへの接続・追加取得は本フェーズでは行っていない。具体的な安全な取得手順はフェーズ5で整理する。

## 7. フェーズ4への引き継ぎ

### 7.1 設計に反映する決定

- 現行20表や134 objectを機械移植せず、原本・関連・派生・運用・認証を分離する。
- `legacy_votes`と有効likesの歴史的寄与を保持し、ranking snapshotは再計算する。
- `quote_ranking_scores`、`author_rankings`、`category_rankings`の最新snapshot責務と構造は維持し、行は再計算する。現行MV・function・logの多段chainはPython CLIへ単純化し、ADR 005のsupercronicで実行する。
- character/category/country/profession件数は、公開限定・階層・重複除外を再現するリアルタイムSQLを第一候補とする。
- 国関連と出典種別は、実データ確認までは複数関連の意味を維持する。
- category階層、level 2限定割当、歴史日付の値域、生誕国最大1件等の整合性は廃止せず、SQLite互換方式へ再編する。
- PostgreSQL RPC、RLS、GRANT、PGroonga、検索派生列、Supabase管理認証を初期SQLite構成へ持ち込まない。
- source検索はtitle + author nameの意味を守り、直接JOIN + wildcard escape済み`LIKE`へ置換する。
- qidはIDから生成し、ID・slug・公開状態・redirectのURL契約を維持する。
- ADR 006、008、009、011、012、014を設計制約として反映する。

### 7.2 未決事項

- `source_type_assignments`の現行多対多構造、国関連を単純化できるか。
- 旧ranking logとinvalid likesの移行範囲。
- 公開`/api/quotes`のenable互換性。
- repository外consumerがある条件付き廃止objectの切替・廃止時期。
- KPIの要否、現行Supabase権限を移行前に是正するか。

これらを解決しても、新DBの具体的なテーブル一覧・カラム・DDLはフェーズ4で初めて定義する。
