# 第5部: 本番DB確認事項と次の作業

作成日: 2026-07-17

## 1. この文書の範囲と安全境界

本書は、第1〜4部で **[本番確認待ち]** とした事項を、実データの取得項目、DB外の運用確認、取得不要事項へ集約するフェーズ5成果物である。構造は2026-07-16取得のschema-only dumpで確認済みのため、追加のschema dumpは主対象にしない **[本番dumpで確認]**。

本書にあるコマンドはすべて**未実行の案**である。本フェーズでは本番DBへの接続、SQL実行、dump/CSV取得、Supabase操作、保存先directoryの作成を行わない。また、SQLite DDL、SQLAlchemy/Alembic、移行script、アプリコードは実装しない。

安全境界は次のとおりとする。

- 接続先は`$SUPABASE_DB_URL`だけで表し、接続文字列、password、API keyを記載しない。
- 確認SQLは`REPEATABLE READ READ ONLY` transaction内の`SELECT`だけとし、短いtimeoutを設ける。
- `INSERT`、`UPDATE`、`DELETE`、DDL、`ANALYZE`、明示`LOCK`、`REFRESH MATERIALIZED VIEW`、ranking refresh RPCを含めない。
- `quote_likes.client_uuid`、row UUID、IP/IP hash、user agentの値は出力しない。形式、件数、NULL、重複候補だけを集計する。
- cronのraw `command`、実行履歴のraw `return_message`、ranking logの`error_message`を出力しない。
- PostgreSQLの`timestamptz`は入力時の元offsetを保存しない。元offset分布は取得不能であり、UTC表示した時点、NULL、範囲、小数秒有無だけを確認する。
- 実URL、外部consumer、Supabase設定、backup/PITR、運用意図はSQLだけで確定せず、§5のDB外確認として扱う。

確度ラベルは第1〜4部と同じ意味で使用する。現時点のSQL案と確認対象は **[本番確認待ち]**、schemaの列・制約・object名は **[本番dumpで確認]**、repository内consumerは **[リポジトリ内で一致]**、外部consumer不在や性能は確認まで **[リポジトリから推定]** である。

## 2. 取得項目の全体像

小規模サイトに比例させ、DBからの確認を9グループへまとめる。A1〜A9は結果内にも同じ見出しを出し、対応表から追跡できるようにする。

| ID | 取得項目 | 主な設計分岐（第4部§12） | 保存先 |
|---|---|---|---|
| A1 | 全20表の行数と移行対象の受容性profile | 本文/fallback、管理KPI、§12.1 | `verification/verification-results.txt` A1 |
| A2 | ID最大値とsequence高水位 | quote ID高水位 | 同 A2 |
| A3 | quoteのURL・公開・言語profile | quote slug、quote enable、本文/fallback、category `updated_at` | 同 A3 |
| A4 | 時点・歴史日付・刊行年・country code | 歴史日付、`published_year`、country code、category `updated_at` | 同 A4 |
| A5 | 国・出典種別・category関連のcardinality/整合 | 国関連、`source_type_assignments` | 同 A5 |
| A6 | `legacy_votes`とlikesの安全な集計 | `legacy_votes`、invalid likes、likes row UUID/UA | 同 A6 |
| A7 | ranking設定・snapshot・MV・log・cronの静的状態 | ranking旧log、ranking係数、snapshot列/sort | 同 A7 |
| A8 | count/searchの現行基準値と後続ローカル比較 | 条件付き廃止object、snapshot列/sort | 同 A8、`local-comparison-results.txt` |
| A9 | 条件付き廃止object・権限・外部writeのDB側手掛かり | 条件付き廃止object、管理KPI、likes row UUID/UA | 同 A9 |

A9はDBだけでconsumer不在を証明できない。DB側ではobject別の呼出し統計等をraw query textなしで参考取得し、最終判断は§5のO1〜O4で補う。統計が無いことを「未使用」の根拠にはしない。

## 3. 取得項目ごとの内容と手順

### A1. 全table profileと現行データ受容性

目的は、第4部§12の「本文/fallback」「管理KPI」と§12.1の新しいNN/CHECK候補を確定することである。

取得内容は次に限定する。

- 全20表の行数。
- 新16表の原本となる現行表について、NULL、空値、意味上の重複、孤立、CHECK違反候補の件数。
- 特に`quotes.weight`、`categories.level/sort_order`、`characters.character_type`、`professions.display_order`のNULL/範囲外件数。
- 個票の本文、slug、識別子は出力しない。対象行の確認が必要になった場合は、集計結果を見て別途最小限の取得を承認する。

SQL案は§4のA1節へまとめる。結果は`verification/verification-results.txt`へ保存する。

### A2. ID最大値とsequence高水位

目的は、第4部§12「quote ID高水位」に従い、現行IDを保持し、削除済みquote IDを再利用しないことである。

9本のsequenceについて、対応表の最大ID、`last_value`、`is_called`を取得する。特に`quotes_id_seq`は最大IDとsequence値の大きい方を後続設計の高水位候補とする。差異は記録するが、この確認でsequenceを変更しない。結果は同ファイルのA2節へ保存する。

### A3. quote URL・公開・表示言語

目的は、第4部§12「quote slug」「quote enable」「本文/fallback」と、category `updated_at`初期値の判断材料を得ることである。

取得内容は、`quotes.slug`のNULL/空/予約`q[0-9]+`形式/重複候補、`enable`分布、`text/text_en`のNULL・空文字組合せ、`display_language_preference`分布、fallback対象数、および`categories.created_at`のNULL・範囲である。slugや本文そのものは出力しない。

実URL、canonical、redirect、公開`/api/quotes` consumerはDB行profileでは分からないため、O1で確認する。結果は同ファイルのA3節へ保存する。

### A4. 時点・歴史日付・刊行年・country code

目的は、第4部§12「歴史日付」「published year」「country code」とcategory `updated_at`初期値を確定することである。

取得内容は、著者のera/precision/date組合せ、`sources.published_year`のNULL・最小/最大・0以下、`countries.code`のNULL・長さ/形式/重複候補、移行対象の主要時点列のNULL・最小/最大・小数秒あり件数である。歴史日付やcodeの個別値は出力しない。

`timestamptz`は内部でUTC instantとして保存されるため、入力時の`+09:00`等の元offsetや入力文字列の桁数は復元できない。`SET LOCAL TIME ZONE 'UTC'`で表示を固定し、移行時にADR 011形式へserializeする。結果は同ファイルのA4節へ保存する。

### A5. 関連表のcardinalityと意味上の整合

目的は、第4部§12「国関連」「source_type_assignments」の構造分岐を判断することである。

`author_country`は著者別0/1/複数関連、生誕国0/1/複数候補、孤立を集計する。`source_type_assignments`は出典別0/1/複数、孤立、意味上の重複を集計する。併せて`quote_categories`のlevel 2以外への割当とcategory階層違反候補を数える。値や関連先IDは出力しない。結果は同ファイルのA5節へ保存する。

### A6. 旧票とlikesの安全な集計

目的は、第4部§12「legacy_votes」「invalid likes」「likes row UUID/UA」の移行範囲を判断することである。

`legacy_votes`は件数、vote数の範囲、負値、対応quote不在、総寄与だけを取得する。`quote_likes`はvalid/invalid件数、UUID形式適合件数、trim/lower後の意味上の重複候補、期間、補助列の存在件数だけを取得する。`client_uuid`、`id`、`ip_hash`、`user_agent`の値は一切出力しない。

この取得はフェーズ5の集計検証であり、likes個票を移行できるCSVではない。個票を保持するには後続で`(quote_id, client_uuid)`を含む保護exportが必要になるため、アクセス制御、保存期間、削除手順を定めて別途承認するか、集約/履歴リセットをユーザーが選ぶ。結果は同ファイルのA6節へ保存する。

### A7. ranking・MV・log・cron

目的は、第4部§12「ranking旧log」「ranking係数」「snapshot列/sort」の判断材料を得ることである。

取得内容は、次の集計・設定だけとする。

- `ranking_parameters`のkey、numeric値、JSONの有無/型。JSON本文は出力しない。
- 3 snapshotの件数、rank/score/refreshed_atの範囲、同点候補、原本との孤立。
- 4 MVの`relispopulated`、統計上の推定行数。未populate MVを確認のためにrefreshしない。
- `ranking_refresh_logs`の件数、期間、status別件数、duration集計。`error_message`は出力しない。
- cron jobの名称、schedule、activeと、raw commandを出さない既知signature分類、履歴のstatus/時間集計。`command`、`return_message`は出力しない。

本番でrefreshを実行して計測しない。将来のPython CLIは未実装なので、本フェーズで再計算時間を取得できない。現行履歴のdurationを参考にし、CLI実装後に安全にexportした本番相当データをローカルSQLiteへ入れて測る。結果は同ファイルのA7節へ保存する。

### A8. count/searchの基準値とローカル比較

目的は、第4部§12「snapshot列/sort」「条件付き廃止object」と第4部§14の項目8・10について、現行の意味をSQLite候補SQLで再現できることを確かめることである。

本番から取得するのは、公開名言数、category親の重複除外件数、category子/character/country/profession件数、および事前に選んだ公開済み代表検索語に対する件数・先頭の公開数値IDだけである。検索語は公開コンテンツから選び、結果ファイルには検索語自体を残さなくてもよい。PGroongaのquery planは取得不要（§6 N4）とする。

後続で、選択列CSVを使ったローカルSQLiteに第4部§9の候補SQLを実行し、結果一致と実行時間を`verification/local-comparison-results.txt`へ記録する。本番PostgreSQLの時間だけでSQLite性能を判断しない。未populate MVへのSELECTが失敗してもrefreshせず、その状態をA7の結果として記録する。

### A9. 条件付き廃止object・権限・外部writeのDB側手掛かり

目的は、第4部§12「条件付き廃止object」「管理KPI」とlikes補助列の外部consumer有無を確認することである。

object定義とACL定義はN1のschema dumpで確認済みである。A9では、関連tableの累積read/write統計、既知object名を含む正規化statementの累積call数、Realtime publication設定だけをraw query textなしで参考取得する。`pg_stat_statements`とtable統計はresetされ得て、extension利用権限にも依存するため、0 callを未使用の証明にしない。

実際のconsumer、外部管理write、API到達性、ACL運用意図はO2/O3で確認する。consumerが不明のままobjectを廃止しない。結果は同ファイルのA9節へ保存する。

## 4. まとめて実行するSQL・コマンド案（実行しない）

### 4.1 実行方式

取得時には、次の内容をGit管理外の`verification.sql`として保存し、1つの読み取りtransactionで実行する案を推奨する。以下は案であり、本フェーズではファイル作成も実行もしない。

```bash
psql "$SUPABASE_DB_URL" \
  -X \
  --set=ON_ERROR_STOP=1 \
  --file=/Users/sonoda/prj/meigen-fly-private/source-db/verification/verification.sql \
  > /Users/sonoda/prj/meigen-fly-private/source-db/verification/verification-results.txt
```

`verification.sql`の共通枠:

```sql
\set ON_ERROR_STOP on
\pset pager off
\timing off

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '120s';
SET LOCAL TIME ZONE 'UTC';

-- A1〜A9のSELECTを配置する。

COMMIT;
```

読み取り専用transactionでも通常のSELECTは短い`ACCESS SHARE` lockを取る。これは書込みlockではないが、長時間化を避けるためtimeoutを設け、混雑時は再試行せず中止する。権限不足や未populate MVで失敗した項目は、権限拡大やrefreshで回避せず「未取得」と記録する。

### 4.2 A1〜A6の確認SQL案

```sql
\echo 'A1 table counts and acceptance profile'
SELECT * FROM (
  SELECT 'admin_users' object_name, count(*) row_count FROM public.admin_users
  UNION ALL SELECT 'author_country', count(*) FROM public.author_country
  UNION ALL SELECT 'author_professions', count(*) FROM public.author_professions
  UNION ALL SELECT 'author_rankings', count(*) FROM public.author_rankings
  UNION ALL SELECT 'authors', count(*) FROM public.authors
  UNION ALL SELECT 'categories', count(*) FROM public.categories
  UNION ALL SELECT 'quote_categories', count(*) FROM public.quote_categories
  UNION ALL SELECT 'quotes', count(*) FROM public.quotes
  UNION ALL SELECT 'category_rankings', count(*) FROM public.category_rankings
  UNION ALL SELECT 'characters', count(*) FROM public.characters
  UNION ALL SELECT 'source_type_assignments', count(*) FROM public.source_type_assignments
  UNION ALL SELECT 'source_types', count(*) FROM public.source_types
  UNION ALL SELECT 'sources', count(*) FROM public.sources
  UNION ALL SELECT 'countries', count(*) FROM public.countries
  UNION ALL SELECT 'legacy_votes', count(*) FROM public.legacy_votes
  UNION ALL SELECT 'professions', count(*) FROM public.professions
  UNION ALL SELECT 'quote_likes', count(*) FROM public.quote_likes
  UNION ALL SELECT 'quote_ranking_scores', count(*) FROM public.quote_ranking_scores
  UNION ALL SELECT 'ranking_parameters', count(*) FROM public.ranking_parameters
  UNION ALL SELECT 'ranking_refresh_logs', count(*) FROM public.ranking_refresh_logs
) counts ORDER BY object_name;

-- 全20表・全列について、値自体を出さずNULL/空文字/異なる値の数を取得する。
-- information_schemaの識別子をformat(%I)でquoteし、生成される文はSELECTだけである。
SELECT format(
  'SELECT %L table_name, count(*) row_count, %s FROM %I.%I;',
  table_name,
  string_agg(
    format(
      'count(*) FILTER (WHERE %1$I IS NULL) AS %2$I, '
      'count(*) FILTER (WHERE %1$I::text = '''') AS %3$I, '
      'count(DISTINCT %1$I::text) AS %4$I',
      column_name,
      column_name || '_null',
      column_name || '_empty',
      column_name || '_distinct'
    ),
    ', ' ORDER BY ordinal_position
  ),
  table_schema,
  table_name
)
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name IN (
    'admin_users','author_country','author_professions','author_rankings','authors',
    'categories','quote_categories','quotes','category_rankings','characters',
    'source_type_assignments','source_types','sources','countries','legacy_votes',
    'professions','quote_likes','quote_ranking_scores','ranking_parameters',
    'ranking_refresh_logs'
  )
GROUP BY table_schema, table_name
ORDER BY table_name
\gexec

-- validated FKなら任意の孤立行は制約上存在できない。未validatedだけを異常として列挙する。
SELECT count(*) fk_count,
       count(*) FILTER (WHERE NOT convalidated) unvalidated_fk_count
FROM pg_catalog.pg_constraint
WHERE contype='f' AND connamespace='public'::regnamespace;

SELECT count(*) FILTER (WHERE weight IS NULL) weight_null,
       count(*) FILTER (WHERE weight NOT BETWEEN 1 AND 10) weight_out_of_range,
       count(*) FILTER (WHERE enable IS NULL) enable_null,
       count(*) FILTER (WHERE btrim(text) = '' AND COALESCE(btrim(text_en), '') = '') both_text_empty
FROM public.quotes;

SELECT count(*) FILTER (WHERE level IS NULL) level_null,
       count(*) FILTER (WHERE level NOT IN (1,2)) level_out_of_range,
       count(*) FILTER (WHERE sort_order IS NULL) sort_order_null,
       count(*) FILTER (WHERE sort_order < 0) sort_order_negative
FROM public.categories;

SELECT count(*) FILTER (WHERE character_type IS NULL) character_type_null,
       count(*) FILTER (WHERE character_type NOT IN ('character','narrator','author_voice')) character_type_out_of_range
FROM public.characters;

SELECT count(*) FILTER (WHERE display_order IS NULL) display_order_null,
       count(*) FILTER (WHERE display_order < 0) display_order_negative
FROM public.professions;

\echo 'A2 ids and sequences'
SELECT 'authors' object_name, (SELECT max(id) FROM public.authors) max_id,
       last_value, is_called FROM public.authors_new_id_seq
UNION ALL SELECT 'categories', (SELECT max(id) FROM public.categories),
       last_value, is_called FROM public.categories_id_seq
UNION ALL SELECT 'characters', (SELECT max(id) FROM public.characters),
       last_value, is_called FROM public.characters_id_seq
UNION ALL SELECT 'countries', (SELECT max(id) FROM public.countries),
       last_value, is_called FROM public.countries_id_seq
UNION ALL SELECT 'professions', (SELECT max(id) FROM public.professions),
       last_value, is_called FROM public.professions_id_seq
UNION ALL SELECT 'quotes', (SELECT max(id) FROM public.quotes),
       last_value, is_called FROM public.quotes_id_seq
UNION ALL SELECT 'source_types', (SELECT max(id) FROM public.source_types),
       last_value, is_called FROM public.source_types_id_seq
UNION ALL SELECT 'sources', (SELECT max(id) FROM public.sources),
       last_value, is_called FROM public.sources_id_seq
UNION ALL SELECT 'ranking_refresh_logs', (SELECT max(id) FROM public.ranking_refresh_logs),
       last_value, is_called FROM public.ranking_refresh_logs_id_seq;

\echo 'A3 quote URL, publication and language profile'
SELECT count(*) FILTER (WHERE slug IS NULL) slug_null,
       count(*) FILTER (WHERE slug = '') slug_empty,
       count(*) FILTER (WHERE slug ~ '^q[0-9]+$') reserved_qid_shape,
       count(NULLIF(lower(btrim(slug)), ''))
         - count(DISTINCT NULLIF(lower(btrim(slug)), '')) slug_semantic_duplicate_rows,
       count(*) FILTER (WHERE enable IS TRUE) enabled_true,
       count(*) FILTER (WHERE enable IS FALSE) enabled_false,
       count(*) FILTER (WHERE enable IS NULL) enabled_null,
       count(*) FILTER (WHERE text IS NULL) text_null,
       count(*) FILTER (WHERE btrim(text) = '') text_empty,
       count(*) FILTER (WHERE text_en IS NULL) text_en_null,
       count(*) FILTER (WHERE btrim(text_en) = '') text_en_empty,
       count(*) FILTER (
         WHERE (display_language_preference = 'ja' AND btrim(text) = '' AND COALESCE(btrim(text_en), '') <> '')
            OR (display_language_preference = 'en' AND COALESCE(btrim(text_en), '') = '' AND btrim(text) <> '')
       ) fallback_candidates
FROM public.quotes;

SELECT display_language_preference, count(*)
FROM public.quotes GROUP BY display_language_preference ORDER BY display_language_preference;

SELECT count(*) row_count, count(*) FILTER (WHERE created_at IS NULL) created_at_null,
       min(created_at) min_created_at, max(created_at) max_created_at
FROM public.categories;

\echo 'A4 historical values and instants (UTC display)'
SELECT birth_era, birth_precision, (birth_date IS NULL) date_is_null, count(*)
FROM public.authors GROUP BY birth_era, birth_precision, (birth_date IS NULL)
UNION ALL
SELECT death_era, death_precision, (death_date IS NULL), count(*)
FROM public.authors GROUP BY death_era, death_precision, (death_date IS NULL);

SELECT count(*) row_count,
       count(*) FILTER (WHERE published_year IS NULL) year_null,
       count(*) FILTER (WHERE published_year <= 0) year_nonpositive,
       min(published_year) min_year, max(published_year) max_year
FROM public.sources;

SELECT count(*) row_count,
       count(*) FILTER (WHERE code IS NULL) code_null,
       count(*) FILTER (WHERE code IS NOT NULL AND length(code) NOT BETWEEN 2 AND 3) bad_length,
       count(*) FILTER (WHERE code IS NOT NULL AND code !~ '^[A-Za-z]{2,3}$') non_alpha,
       count(NULLIF(upper(btrim(code)), ''))
         - count(DISTINCT NULLIF(upper(btrim(code)), '')) semantic_duplicate_rows
FROM public.countries;

-- schemaで確認済みの全30 timestamptz列を漏れなくprofileする。
SELECT format(
  'SELECT %L object_column, count(*) FILTER (WHERE %I IS NULL) null_count, '
  'min(%I) min_value, max(%I) max_value, '
  'count(*) FILTER (WHERE extract(microseconds FROM %I)::integer %% 1000000 <> 0) fractional_second_count '
  'FROM %I.%I;',
  table_name || '.' || column_name,
  column_name, column_name, column_name, column_name,
  table_schema, table_name
)
FROM information_schema.columns
WHERE table_schema='public' AND data_type='timestamp with time zone'
  AND table_name IN (
    'admin_users','author_country','author_professions','author_rankings','authors',
    'categories','quote_categories','quotes','category_rankings','characters',
    'source_type_assignments','source_types','sources','countries','legacy_votes',
    'professions','quote_likes','quote_ranking_scores','ranking_parameters',
    'ranking_refresh_logs'
  )
ORDER BY table_name, ordinal_position
\gexec

\echo 'A5 relationship cardinality and integrity'
SELECT count(*) author_count,
       count(*) FILTER (WHERE relation_count = 0) no_country,
       count(*) FILTER (WHERE relation_count = 1) one_country,
       count(*) FILTER (WHERE relation_count > 1) multiple_countries,
       count(*) FILTER (WHERE birth_count = 0) no_birth_country,
       count(*) FILTER (WHERE birth_count = 1) one_birth_country,
       count(*) FILTER (WHERE birth_count > 1) multiple_birth_countries
FROM (
  SELECT a.id, count(ac.country_id) relation_count,
         count(ac.country_id) FILTER (WHERE ac.is_birth_country) birth_count
  FROM public.authors a LEFT JOIN public.author_country ac ON ac.author_id = a.id
  GROUP BY a.id
) x;

SELECT count(*) source_count,
       count(*) FILTER (WHERE type_count = 0) no_type,
       count(*) FILTER (WHERE type_count = 1) one_type,
       count(*) FILTER (WHERE type_count > 1) multiple_types
FROM (
  SELECT s.id, count(sta.type_id) type_count
  FROM public.sources s LEFT JOIN public.source_type_assignments sta ON sta.source_id = s.id
  GROUP BY s.id
) x;

SELECT
  (SELECT count(*) FROM public.author_country ac
   LEFT JOIN public.authors a ON a.id=ac.author_id LEFT JOIN public.countries c ON c.id=ac.country_id
   WHERE a.id IS NULL OR c.id IS NULL) author_country_orphans,
  (SELECT count(*) FROM public.source_type_assignments sta
   LEFT JOIN public.sources s ON s.id=sta.source_id LEFT JOIN public.source_types st ON st.id=sta.type_id
   WHERE s.id IS NULL OR st.id IS NULL) source_type_orphans,
  (SELECT count(*) FROM public.quote_categories qc
   LEFT JOIN public.quotes q ON q.id=qc.quote_id LEFT JOIN public.categories c ON c.id=qc.category_id
   WHERE q.id IS NULL OR c.id IS NULL) quote_category_orphans,
  (SELECT count(*) FROM public.quote_categories qc JOIN public.categories c ON c.id=qc.category_id
   WHERE c.level <> 2) quote_category_non_level2,
  (SELECT count(*) FROM public.categories child LEFT JOIN public.categories parent ON parent.id=child.parent_id
   WHERE (child.level=1 AND child.parent_id IS NOT NULL)
      OR (child.level=2 AND (parent.id IS NULL OR parent.level<>1))) category_hierarchy_violations;

\echo 'A6 legacy votes and privacy-minimized likes profile'
SELECT count(*) row_count, coalesce(sum(vote_count),0) total_votes,
       min(vote_count) min_votes, max(vote_count) max_votes,
       count(*) FILTER (WHERE vote_count < 0) negative_rows,
       count(*) FILTER (WHERE q.id IS NULL) orphan_rows
FROM public.legacy_votes lv LEFT JOIN public.quotes q ON q.id=lv.quote_id;

SELECT count(*) row_count,
       count(*) FILTER (WHERE is_valid) valid_rows,
       count(*) FILTER (WHERE NOT is_valid) invalid_rows,
       count(*) FILTER (WHERE client_uuid ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') uuid_shape_rows,
       count(*) FILTER (WHERE client_uuid !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') non_uuid_shape_rows,
       count(*) - count(DISTINCT (quote_id, lower(btrim(client_uuid)))) semantic_duplicate_rows,
       count(*) FILTER (WHERE user_agent IS NOT NULL) user_agent_present_rows,
       count(*) FILTER (WHERE ip_hash IS NOT NULL) ip_hash_present_rows,
       min(created_at) min_created_at, max(created_at) max_created_at
FROM public.quote_likes;
```

全138列は値を出さないNULL/空/異なる値の数までに留める。これにより常時NULL/同値候補を漏れなくscreeningし、意味上の重複・新制約候補は後続の固定queryで確認する。異常件数が0でない場合だけ、該当列の値分類を別途承認する。

### 4.3 A7〜A9の確認SQL案

```sql
\echo 'A7 ranking parameters, snapshots, MVs, logs and cron'
SELECT key, value_numeric, (value_json IS NOT NULL) has_json,
       CASE WHEN value_json IS NULL THEN NULL ELSE jsonb_typeof(value_json) END json_type
FROM public.ranking_parameters ORDER BY key;

SELECT count(*) row_count,
       min(score_total) min_score_total, max(score_total) max_score_total,
       min(likes_total) min_likes_total, max(likes_total) max_likes_total,
       min(likes_7d) min_likes_7d, max(likes_7d) max_likes_7d,
       min(likes_1d) min_likes_1d, max(likes_1d) max_likes_1d,
       min(refreshed_at) min_refreshed_at, max(refreshed_at) max_refreshed_at,
       count(*) FILTER (WHERE q.id IS NULL) orphan_rows
FROM public.quote_ranking_scores r LEFT JOIN public.quotes q ON q.id=r.quote_id;

SELECT count(*) row_count, min(rank) min_rank, max(rank) max_rank,
       count(*)-count(DISTINCT rank) duplicate_rank_rows,
       min(score) min_score, max(score) max_score,
       min(total_score) min_total_score, max(total_score) max_total_score,
       min(avg_score) min_avg_score, max(avg_score) max_avg_score,
       min(quote_count) min_quote_count, max(quote_count) max_quote_count,
       min(refreshed_at) min_refreshed_at, max(refreshed_at) max_refreshed_at,
       count(*) FILTER (WHERE a.id IS NULL) orphan_rows
FROM public.author_rankings r LEFT JOIN public.authors a ON a.id=r.author_id;

SELECT count(*) row_count, min(rank) min_rank, max(rank) max_rank,
       count(*)-count(DISTINCT rank) duplicate_rank_rows,
       min(score) min_score, max(score) max_score,
       min(total_score) min_total_score, max(total_score) max_total_score,
       min(avg_score) min_avg_score, max(avg_score) max_avg_score,
       min(adjusted_score) min_adjusted_score, max(adjusted_score) max_adjusted_score,
       min(quote_count) min_quote_count, max(quote_count) max_quote_count,
       min(refreshed_at) min_refreshed_at, max(refreshed_at) max_refreshed_at,
       count(*) FILTER (WHERE c.id IS NULL) orphan_rows
FROM public.category_rankings r LEFT JOIN public.categories c ON c.id=r.category_id;

SELECT object_name, count(*) tie_group_count, coalesce(sum(group_size),0) rows_in_ties
FROM (
  SELECT 'quote_ranking_scores.score_total' object_name, score_total metric, count(*) group_size
  FROM public.quote_ranking_scores GROUP BY score_total HAVING count(*) > 1
  UNION ALL
  SELECT 'author_rankings.score', score::numeric, count(*)
  FROM public.author_rankings GROUP BY score HAVING count(*) > 1
  UNION ALL
  SELECT 'category_rankings.score', score::numeric, count(*)
  FROM public.category_rankings GROUP BY score HAVING count(*) > 1
) ties GROUP BY object_name ORDER BY object_name;

SELECT c.relname, c.relispopulated, coalesce(s.n_live_tup,0) estimated_rows,
       s.last_analyze, s.last_autoanalyze
FROM pg_catalog.pg_class c
LEFT JOIN pg_catalog.pg_stat_all_tables s ON s.relid=c.oid
WHERE c.oid IN ('public.categories_with_counts'::regclass,
                'public.country_author_counts'::regclass,
                'public.profession_author_counts'::regclass,
                'public.quote_ranking_scores_mv'::regclass)
ORDER BY c.relname;

SELECT status, count(*) run_count,
       min(started_at) min_started_at, max(started_at) max_started_at,
       min(duration_ms) min_duration_ms, max(duration_ms) max_duration_ms,
       avg(duration_ms)::numeric(12,2) avg_duration_ms
FROM public.ranking_refresh_logs GROUP BY status ORDER BY status;

-- 想定2 job名で絞ると別名のjobを見落とすため、全jobをraw commandなしで列挙する（レビューで修正）。
SELECT jobname, schedule, active,
       CASE
         WHEN command ~ 'refresh_quote_ranking_scores' AND command ~ 'scheduler' THEN 'ranking_text_signature'
         WHEN command ~ 'categories_with_counts' AND command ~ 'REFRESH' THEN 'category_mv_refresh'
         WHEN command ~ 'refresh_quote_ranking_scores' THEN 'ranking_signature_other'
         ELSE 'other'
       END command_class
FROM cron.job
ORDER BY jobname;

SELECT j.jobname, d.status, count(*) run_count,
       min(d.start_time) min_start_time, max(d.start_time) max_start_time,
       min(d.end_time - d.start_time) min_duration, max(d.end_time - d.start_time) max_duration
FROM cron.job_run_details d
JOIN cron.job j ON j.jobid = d.jobid
GROUP BY j.jobname, d.status ORDER BY j.jobname, d.status;

\echo 'A8 current count/search baselines'
\timing on
SELECT count(*) FILTER (WHERE enable IS TRUE) public_quotes,
       count(*) FILTER (WHERE enable IS NOT TRUE) nonpublic_or_null_quotes
FROM public.quotes;

SELECT relispopulated AS categories_mv_populated
FROM pg_catalog.pg_class
WHERE oid='public.categories_with_counts'::regclass
\gset

\if :categories_mv_populated
SELECT id, level, direct_count, hierarchy_count, effective_count
FROM public.categories_with_counts ORDER BY level, id;
\else
\echo 'categories_with_counts is not populated; do not refresh it for this check'
\endif

SELECT 'direct_parent' calculation, parent.id,
       (SELECT count(DISTINCT qc.quote_id)
        FROM public.quote_categories qc JOIN public.quotes q ON q.id=qc.quote_id
        WHERE q.enable IS TRUE
          AND (qc.category_id=parent.id OR qc.category_id IN (
            SELECT child.id FROM public.categories child WHERE child.parent_id=parent.id
          ))) quote_count
FROM public.categories parent WHERE parent.level=1 ORDER BY parent.id;

SELECT 'direct_child' calculation, child.id,
       count(DISTINCT q.id) FILTER (WHERE q.enable IS TRUE) quote_count
FROM public.categories child
LEFT JOIN public.quote_categories qc ON qc.category_id=child.id
LEFT JOIN public.quotes q ON q.id=qc.quote_id
WHERE child.level=2 GROUP BY child.id ORDER BY child.id;

SELECT id, quotes_count FROM public.characters_with_quote_counts ORDER BY id;

SELECT 'direct_character' calculation, c.id,
       count(DISTINCT q.id) FILTER (WHERE q.enable IS TRUE) quote_count
FROM public.characters c LEFT JOIN public.quotes q ON q.character_id=c.id
GROUP BY c.id ORDER BY c.id;

SELECT relispopulated AS country_mv_populated
FROM pg_catalog.pg_class WHERE oid='public.country_author_counts'::regclass
\gset
\if :country_mv_populated
SELECT id, author_count, quote_count FROM public.country_author_counts ORDER BY id;
\else
\echo 'country_author_counts is not populated; do not refresh it for this check'
\endif

SELECT 'direct_country' calculation, c.id,
       count(DISTINCT ac.author_id) FILTER (WHERE q.enable IS TRUE) author_count,
       count(q.id) FILTER (WHERE q.enable IS TRUE) quote_count
FROM public.countries c
LEFT JOIN public.author_country ac ON ac.country_id=c.id
LEFT JOIN public.quotes q ON q.author_id=ac.author_id
GROUP BY c.id ORDER BY c.id;

SELECT relispopulated AS profession_mv_populated
FROM pg_catalog.pg_class WHERE oid='public.profession_author_counts'::regclass
\gset
\if :profession_mv_populated
SELECT id, author_count, quote_count FROM public.profession_author_counts ORDER BY id;
\else
\echo 'profession_author_counts is not populated; do not refresh it for this check'
\endif

SELECT 'direct_profession' calculation, p.id,
       count(DISTINCT ap.author_id) FILTER (WHERE q.enable IS TRUE) author_count,
       count(q.id) FILTER (WHERE q.enable IS TRUE) quote_count
FROM public.professions p
LEFT JOIN public.author_professions ap ON ap.profession_id=p.id
LEFT JOIN public.quotes q ON q.author_id=ap.author_id
GROUP BY p.id ORDER BY p.id;

-- 実行前に公開コンテンツから、title一致、author一致、複数token用の代表語を選ぶ。
-- 変数値はrepositoryや結果へechoしない。
-- \set source_title_term '...'
-- \set source_author_term '...'
-- \set source_token_1 '...'
-- \set source_token_2 '...'
\if :{?source_title_term}
SELECT 'current_rpc_title' case_name, max(total_count) total_count,
       array_agg(id ORDER BY ordinality) first_public_ids
FROM public.get_sources_with_quote_counts(
  20, 0, NULL, NULL, NULL, false, :'source_title_term'
) WITH ORDINALITY;
WITH matched AS (
  SELECT s.id, s.title, s.published_year, count(q.id) quotes_count
  FROM public.sources s LEFT JOIN public.authors a ON a.id=s.author_id
  JOIN public.quotes q ON q.source_id=s.id AND q.enable IS TRUE
  WHERE (s.title ILIKE '%' || replace(replace(replace(:'source_title_term', '\', '\\'), '%', '\%'), '_', '\_') || '%' ESCAPE '\'
     OR a.name ILIKE '%' || replace(replace(replace(:'source_title_term', '\', '\\'), '%', '\%'), '_', '\_') || '%' ESCAPE '\')
  GROUP BY s.id
), first_rows AS (
  SELECT * FROM matched
  ORDER BY quotes_count DESC, published_year DESC NULLS LAST, title, id LIMIT 20
)
SELECT 'direct_like_title' case_name, (SELECT count(*) FROM matched) total_count,
       (SELECT array_agg(id ORDER BY quotes_count DESC, published_year DESC NULLS LAST, title, id)
        FROM first_rows) first_public_ids;
\else
\echo 'source_title_term is not set; title search check skipped'
\endif

\if :{?source_author_term}
SELECT 'current_rpc_author' case_name, max(total_count) total_count,
       array_agg(id ORDER BY ordinality) first_public_ids
FROM public.get_sources_with_quote_counts(
  20, 0, NULL, NULL, NULL, false, :'source_author_term'
) WITH ORDINALITY;
WITH matched AS (
  SELECT s.id, s.title, s.published_year, count(q.id) quotes_count
  FROM public.sources s LEFT JOIN public.authors a ON a.id=s.author_id
  JOIN public.quotes q ON q.source_id=s.id AND q.enable IS TRUE
  WHERE (s.title ILIKE '%' || replace(replace(replace(:'source_author_term', '\', '\\'), '%', '\%'), '_', '\_') || '%' ESCAPE '\'
     OR a.name ILIKE '%' || replace(replace(replace(:'source_author_term', '\', '\\'), '%', '\%'), '_', '\_') || '%' ESCAPE '\')
  GROUP BY s.id
), first_rows AS (
  SELECT * FROM matched
  ORDER BY quotes_count DESC, published_year DESC NULLS LAST, title, id LIMIT 20
)
SELECT 'direct_like_author' case_name, (SELECT count(*) FROM matched) total_count,
       (SELECT array_agg(id ORDER BY quotes_count DESC, published_year DESC NULLS LAST, title, id)
        FROM first_rows) first_public_ids;
\else
\echo 'source_author_term is not set; author search check skipped'
\endif

\if :{?source_token_1}
\if :{?source_token_2}
SELECT 'current_rpc_multiple_tokens' case_name, max(total_count) total_count,
       array_agg(id ORDER BY ordinality) first_public_ids
FROM public.get_sources_with_quote_counts(
  20, 0, NULL, NULL, NULL, false, :'source_token_1' || ' ' || :'source_token_2'
) WITH ORDINALITY;
WITH matched AS (
  SELECT s.id, s.title, s.published_year, count(q.id) quotes_count
  FROM public.sources s LEFT JOIN public.authors a ON a.id=s.author_id
  JOIN public.quotes q ON q.source_id=s.id AND q.enable IS TRUE
  WHERE concat_ws(' ', s.title, a.name) ILIKE '%' || replace(replace(replace(:'source_token_1', '\', '\\'), '%', '\%'), '_', '\_') || '%' ESCAPE '\'
    AND concat_ws(' ', s.title, a.name) ILIKE '%' || replace(replace(replace(:'source_token_2', '\', '\\'), '%', '\%'), '_', '\_') || '%' ESCAPE '\'
  GROUP BY s.id
), first_rows AS (
  SELECT * FROM matched
  ORDER BY quotes_count DESC, published_year DESC NULLS LAST, title, id LIMIT 20
)
SELECT 'direct_like_multiple_tokens' case_name, (SELECT count(*) FROM matched) total_count,
       (SELECT array_agg(id ORDER BY quotes_count DESC, published_year DESC NULLS LAST, title, id)
        FROM first_rows) first_public_ids;
\else
\echo 'source_token_2 is not set; multiple-token search check skipped'
\endif
\else
\echo 'source_token_1 is not set; multiple-token search check skipped'
\endif
\timing off

\echo 'A9 DB-side operational clues (not proof of no consumer)'
SELECT schemaname, relname, seq_scan, idx_scan,
       n_tup_ins, n_tup_upd, n_tup_del
FROM pg_catalog.pg_stat_user_tables
WHERE relname IN ('source_types','source_type_assignments','quote_likes',
                  'ranking_refresh_logs')
ORDER BY schemaname, relname;

SELECT coalesce(sum(calls) FILTER (WHERE query ILIKE '%get_category_quotes_light%'),0) get_category_calls,
       coalesce(sum(calls) FILTER (WHERE query ILIKE '%get_sources_with_quote_counts%'),0) source_rpc_calls,
       coalesce(sum(calls) FILTER (WHERE query ILIKE '%view_admin_kpi_counts%'),0) admin_kpi_calls,
       coalesce(sum(calls) FILTER (WHERE query ILIKE '%view_admin_ranking_refresh_logs%'),0) admin_log_view_calls
FROM extensions.pg_stat_statements;

SELECT pubname, puballtables, pubinsert, pubupdate, pubdelete, pubtruncate
FROM pg_catalog.pg_publication
WHERE pubname='supabase_realtime';

SELECT count(*) publication_member_count
FROM pg_catalog.pg_publication_tables
WHERE pubname='supabase_realtime';

SELECT schemaname, tablename
FROM pg_catalog.pg_publication_tables
WHERE pubname='supabase_realtime'
ORDER BY schemaname, tablename;
```

`pg_stat_statements`のquery本文は出力せず、既知object名に該当したstatementの`calls`合計だけを返す。統計viewや`cron` schemaへの権限がなければ、A7/A9の該当SELECTだけを別のread-only実行へ分け、未取得を記録する。権限を変更してまで取得しない。通常viewの利用や外部consumerは統計だけで確定せずO2で確認する。

## 5. DB外の運用確認

次は「取得不要」ではなく、DB SQLだけでは完結しない確認である。秘密値やraw request/queryを成果物へ残さず、集計または有無だけを記録する。

| ID | 確認内容 | 確認方法案 | 保存先 |
|---|---|---|---|
| O1 | 実URL、canonical/redirect、公開`/api/quotes` consumer、enable省略意図 | 公開URL契約表、route、匿名化access log集計、運用者確認 | `verification/url-api-consumer-notes.md` |
| O2 | 未使用候補object、likes invalid化/row UUID/UA、5引数RPC、PGroonga索引、Realtimeの外部consumer、snapshot列consumerと同点sort | Supabase設定、API gateway/logのobject別件数、外部script一覧、公開UI/APIのsort契約、運用者確認 | `verification/external-consumer-notes.md` |
| O3 | 実効権限、外部管理write、MV ACL、cron/refresh運用 | role別の承認済みread-only疎通試験と設定review。write試験はしない | 同上 |
| O4 | migration/import/修正/backup/syncの適用実績、backup成功、復元試験、PITR | 運用記録・job履歴・backup管理画面の確認。秘密値は表示しない | `verification/operations-notes.md` |

O1〜O4でconsumer不在を確認できないobjectは、条件付き廃止のまま据え置く。現行権限の是正や秘密情報対応が必要と判明した場合は、SQLite移行データ取得とは別の運用・security作業として承認を得る。

## 6. 取得不要または後続へ回す事項

| ID | 事項 | 分類と理由 |
|---|---|---|
| N1 | schema定義、object数、extensionの存在・配置schema | 2026-07-16のschema dumpで確認済み **[本番dumpで確認]**。追加schema dumpは不要。extension versionや差異の由来はSQLite設計分岐を変えないため、必要なら別の運用調査で扱う |
| N2 | `admin_users`の行、Supabase認証情報 | ADR 012により新DBへ移行しない **[リポジトリ内で一致]**。認証行を取得しない |
| N3 | snapshot 3表・MV 4件のraw行、IP/IP hash、検索派生列 | snapshot/MVは原本から再計算し、基準集計だけA7/A8で取る。IP/hashはADR 006により移行しない。`sources.search_document`も再生成不要 **[リポジトリ内で一致]** |
| N4 | PGroonga query plan | ADR 002のescaped `LIKE`採用を変更しないため取得不要。必要な検索結果とSQLite性能はA8で比較する **[リポジトリ内で一致]** |
| N5 | 生成型の生成環境/時点、資格情報様literalの有効性 | 新DBのデータ分岐には不要。資格情報は値を表示せず別security作業で扱う。seed/data migration適用状態だけはO4で確認する |
| N6 | 将来のPython CLI再計算時間 | CLIは未実装で本フェーズでは測定不能。本番refreshを実行せず、実装後にローカル本番相当データで測る |

`ranking_refresh_logs`のraw error、cronのraw command/return message、likesの補助識別値は「後で念のため取る」対象にも含めない。必要性が判明した場合に限り、目的・閲覧者・保存期間を定めて別途承認する。

## 7. 保存先構成とdata取得方式

次の構成をGit管理外で使う。schemaだけ取得済みであり、本フェーズではdirectory/fileを作成しない。

```text
source-db/
├── schema/        # 取得済み: schema.sql (2026-07-16)
├── data/          # 後続の選択列CSV
└── verification/  # verification.sqlと確認結果
```

想定ファイルの詳細:

```text
source-db/
├── schema/
│   └── schema.sql
├── data/
│   ├── authors.csv
│   ├── professions.csv
│   ├── author-professions.csv
│   ├── countries.csv
│   ├── author-country.csv
│   ├── source-types.csv
│   ├── sources.csv
│   ├── source-type-assignments.csv
│   ├── characters.csv
│   ├── categories.csv
│   ├── quotes.csv
│   ├── quote-categories.csv
│   └── legacy-votes.csv
└── verification/
    ├── verification.sql
    ├── verification-results.txt
    ├── url-api-consumer-notes.md
    ├── external-consumer-notes.md
    ├── operations-notes.md
    └── local-comparison-results.txt
```

全tableのdata-only dumpではなく、移行に必要な列を明示したtable別CSVを推奨する。理由は、約2,100名言・約890著者の規模では分割CSVで十分扱え、変換・件数照合が容易で、`admin_users`、ranking派生行/log、`sources.search_document`、likesのIP hash/UA/row UUID等を不用意に含めずに済むためである。

後続のCSV取得は、たとえば次のread-only client-side copy形式とする。列一覧は16表案とユーザー判断の確定後に固定するため、ここでは実行しない。

```bash
psql "$SUPABASE_DB_URL" -X --set=ON_ERROR_STOP=1 \
  --command="\copy (SELECT id, name, slug /* approved columns only */ FROM public.authors ORDER BY id) TO STDOUT WITH (FORMAT csv, HEADER true)" \
  > /Users/sonoda/prj/meigen-fly-private/source-db/data/authors.csv
```

`quote_likes`は上の通常CSV一覧に含めない。フェーズ5のA6は集計だけである。個票移行を選ぶ場合だけ、`quote_id/client_uuid/created_at/is_valid`の保護exportを別承認し、IP/hash、UA、row UUIDを除外する。

## 8. 全「本番確認待ち」の対応表

### 8.1 第1部§12（17項目）

| # | 要約 | 対応 |
|---:|---|---|
| 1 | 全table profile | A1 |
| 2 | PK/sequence | A2 |
| 3 | quote URL/公開 | A3 + O1 |
| 4 | 本文/表示言語 | A3 |
| 5 | 時点/歴史日付 | A4（元offsetは取得不能） |
| 6 | likes | A6 + O2 |
| 7 | legacy votes | A6 |
| 8 | author-country | A5 |
| 9 | ranking設定/log/snapshot | A7 |
| 10 | MV populate/refresh | A7（populate/静的状態）+ O3（更新運用） |
| 11 | cron 2件 | A7 + O3 |
| 12 | extension version/schema差異 | N1 |
| 13 | 実効権限 | A9 + O3 |
| 14 | Realtime | A9 + O2 |
| 15 | 生成型/seed/data migration | N5（生成型）+ O4（適用状態） |
| 16 | backup/restore/PITR/script | O4 |
| 17 | 資格情報様literal | N5（別security作業） |

第1部の各節にあるURL、表示言語、likes、日時、sequence、MV、Realtime、権限、cron、ranking、生成型、script実績の個別 **[本番確認待ち]** はすべて§12へ再掲されている。節外だけに存在する未対応ラベルはない。

### 8.2 第2部§9（10項目）

| # | 要約 | 対応 |
|---:|---|---|
| 1 | cron/signature | A7 + O3 |
| 2 | MV populate/refresh運用 | A7/A8 + O3 |
| 3 | CLI/import/backup/sync実績 | O4 |
| 4 | 実効権限 | A9 + O3 |
| 5 | PGroonga plan/外部query | N4（plan）+ O2（consumer） |
| 6 | `/api/quotes` consumer | O1 |
| 7 | likes外部運用 | A6 + O2 |
| 8 | ranking鮮度/外部refresh | A7 + O2/O3 |
| 9 | 未使用候補consumer | A9 + O2 |
| 10 | Realtime等consumer | A9 + O2 |

第2部の節外ラベル（権限、planner、cron、日時実値、script実績）も§9、第1部§12、または第3部§6へ再掲されており、未対応はない。

### 8.3 第3部§6（正本18項目）

| # | 要約 | 対応 |
|---:|---|---|
| 1 | 全table profile | A1 |
| 2 | legacy votes | A6 |
| 3 | likes安全集計 | A6 + O2 |
| 4 | ranking一式/MV/再計算時間 | A7/A8 + N6 |
| 5 | ranking log | A7 + O4 |
| 6 | cron | A7 + O3 |
| 7 | count意味/性能 | A8 |
| 8 | author-country | A5 |
| 9 | source-type | A5 + O2 |
| 10 | quote ID/slug/enable/URL | A2/A3 + O1 |
| 11 | 表示言語/本文 | A3 |
| 12 | 時点/歴史日付 | A4 |
| 13 | 外部consumer | A9 + O2 |
| 14 | 実効権限/API到達性 | A9 + O3 |
| 15 | 外部管理write/ACL意図 | A9 + O3 |
| 16 | source検索結果/LIKE性能 | A8 |
| 17 | PGroonga plan | N4 |
| 18 | 公開API consumer/意図 | O1 |

18/18項目がA1〜A9、O1〜O4、または理由付きNへ対応し、未対応はない。

### 8.4 第4部§12（正本18行）と§12.1

| # | 論点 | 対応 |
|---:|---|---|
| 1 | source type | A5 + O2 |
| 2 | 国関連 | A5 |
| 3 | legacy votes | A6 |
| 4 | invalid likes | A6 + O2 |
| 5 | likes row UUID/UA | A6 + O2 |
| 6 | ranking旧log | A7 + O4 |
| 7 | ranking係数 | A7 |
| 8 | quote slug | A3 + O1 |
| 9 | quote enable | A3 + O1 |
| 10 | 本文/fallback | A1/A3 |
| 11 | 歴史日付 | A4 |
| 12 | published year | A4 |
| 13 | country code | A4 |
| 14 | quote ID高水位 | A2 |
| 15 | category `updated_at` | A3/A4 |
| 16 | snapshot列/sort | A7/A8 + O2 |
| 17 | 条件付き廃止object | A9 + O2/O3 |
| 18 | 管理KPI | A1/A9 + O2 |

§12.1の`quotes.enable/weight`、`categories.level/sort_order`、`characters.character_type`、`professions.display_order`、本文空値候補はA1/A3、歴史日付・時点はA4、`legacy_votes`/likesはA6、孤立/category階層/生誕国候補はA5へ対応する。snapshot 3表のraw行はN3とし、A7/A8の基準だけ取得する。

### 8.5 第4部§14（正本10項目）

| # | 要約 | 対応 |
|---:|---|---|
| 1 | 16表原本profile | A1 |
| 2 | ID/sequence | A2 |
| 3 | quote/実URL/API | A3 + O1 |
| 4 | 歴史日付/年/code | A4 |
| 5 | 国/source type | A5 |
| 6 | legacy/likes/consumer | A6 + O2 |
| 7 | ranking一式/CLI時間 | A7/A8 + N6 |
| 8 | count一致/SQLite時間 | A8 |
| 9 | 条件付き廃止consumer | A9 + O2/O3 |
| 10 | 検索結果/性能 | A8 |

10/10項目が対応済みで、未対応はない。

## 9. ユーザー判断事項

DB設計・移行範囲の正本は第4部§12の18件とし、取得結果を見て次を判断する。

1. `source_type_assignments`を多対多のまま保つか。
2. 国関連を複数関連国 + 生誕国として保つか。
3. `legacy_votes`を`legacy_vote_count`へ統合するか、リセット/不正値処置をどうするか。
4. invalid likesと`is_valid`列を保持するか。
5. likes row UUID/UAの互換列が必要か（IP/hashは移さない）。
6. ranking旧logをDB外archiveするか。
7. ranking係数をどの型付きCLI設定へ同値移行するか。
8. nullable quote slugを保持/補完/NN化するか。
9. NULL quote enableの変換値と公開API互換をどうするか。
10. 本文空値をどう補正してfallback CHECKを適用するか。
11. 歴史日付の受容形式を調整するか。
12. `published_year`へera/precisionを追加するか。
13. country codeを正規化/UNIQUE化するか。
14. quote IDの高水位をどう引き継ぐか。
15. category `updated_at`の初期値を`created_at`/移行時点のどちらにするか。
16. snapshotの未使用列・同点sortを維持するか。
17. 外部consumerがある条件付き廃止objectの切替計画をどうするか。
18. 管理KPIの必要指標とUIを残すか。

第3部§5の10件は重複した別の判断一覧ではなく、次のようにこの18件へ包含される。

| 第3部§5 | 第4部§12の正本 |
|---|---|
| legacy votes | 3 |
| ranking旧log | 6 |
| likes id/UA/valid | 4, 5 |
| 公開API enable | 9 |
| source type | 1 |
| author-country | 2 |
| slug/enable/本文 | 8, 9, 10 |
| ranking係数 | 7 |
| 管理KPI | 18 |
| Supabase権限是正 | 17の切替条件とは分離し、O3結果後の運用判断 U1 |

U1. O3で外部到達可能な過大権限が確認された場合、現行Supabase権限を移行前に是正するかをユーザーが別途判断する。

したがって、DB設計・移行範囲のユーザー判断は正本18件、現行運用の判断は別枠1件（U1）である。第3部§5の10/10件は「18 + U1」で欠けなく包含する。U1は緊急度をO3結果で判定し、移行設計の判断件数へ重ねない。

## 10. 確認後の次の作業

本番確認とユーザー判断が完了した後、次の順で進める。本フェーズでは着手しない。

1. 第4部の16表案、条件付き列、CHECK/NULL、likes個票の扱いを確定する。
2. 既存文書の19表案を更新し、命名規約とSQLite DDLを設計する。
3. SQLAlchemy Core定義、Alembic revision、変換規則、件数・checksum・URL/検索/ranking検証、backup/切戻しを含む移行手順を設計する。
4. 承認済みの選択列CSVを取得し、保護・retentionを適用する。
5. 設計と取得手順のreview後に、migration・移行script・アプリ実装へ進む。

## 11. フェーズ6への引き継ぎ

フェーズ6では次を確認し、`current-system-inventory.md`の目次・全体要約へ反映する。

- 第1部§12の17/17、第2部§9の10/10、第3部§6の18/18、第4部§12の18/18 + §12.1、第4部§14の10/10が追跡可能であること。
- schema-only事実と実データ未確認事項、DB外運用確認、取得不要事項が混同されていないこと。
- A1〜A9のSQLがSELECT-only、read-only transaction、timeout付きで、秘密値・識別値・raw error/commandを出力しないこと。
- フェーズ5の集計likes確認と、別承認が必要な移行用個票exportが分離されていること。
- 16表案と18件のユーザー判断が未確定のまま、DDL/Alembic/移行/アプリ実装へ先行していないこと。
- `docs/project-plan.md`の19表記載など、第4部§13の修正候補を最終報告へ引き継ぐこと。

本書作成時点では、本番DBへの接続、SQL実行、Supabase操作、private保存先の作成、実装、既存文書の修正を行っていない。
