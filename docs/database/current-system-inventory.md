# 現行DB棚卸し・meigen-fly向けDB概念設計

作成日: 2026-07-17

## 1. 目的と読み方

この文書群は、現行のmeigensyu（Next.js + PostgreSQL/Supabase）から
meigen-fly（FastAPI + SQLite）へDBを移行する前に、現行構造と利用状況を棚卸しし、
小規模サイトに適した新しいDB構成と、設計確定前に必要な確認を整理したものである。

現行スキーマを機械的にSQLiteへ移植するための仕様ではない。
調査、分析、概念設計、本番確認手順の整理までを対象とし、
SQLite DDL、Alembic revision、移行script、アプリ実装は含まない。

構造の正本は、2026-07-16取得の本番schema-only dumpとした。
dumpは本番に存在するDB構造を示すが、行数、値、利用実績、実効権限などの実データ・運用状態は示さない。
利用機能は現行アプリコード、構造の由来は生成型とmigration、設計意図は文書で補足した。

重要な記述には、次の確度ラベルを用いる。

- **本番dumpで確認**: schema-only dumpで実在する構造を確認済み。実データや運用状態は含まない。
- **リポジトリ内で一致**: 複数のコード、migration、生成型、文書などが一致する。
- **リポジトリから推定**: 根拠はあるが、本番データ、性能、repository外利用などを未確認である。
- **本番確認待ち**: 実データ、外部consumer、job、実効権限、運用記録などの確認が必要である。

詳細を確認するときは、構造、利用状況、評価、提案、確認手順の順に読む。
結論だけを把握する場合は、本書の§3と§4を読み、判断の根拠は対応する各部を参照する。

## 2. 各部の一覧

### [第1部: 現行構造の棚卸し](inventory-1-current-structure.md)

2026-07-16取得のschema-only dumpを正本として、table、全column、制約、index、
view、MV、function/RPC、trigger、extension、RLS、GRANT、cron意図を記録した。
生成型・migration・文書との差異を断定せず分離し、実データが必要な17項目を引き継いでいる。

### [第2部: アプリからの利用状況](inventory-2-app-usage.md)

公開ページ、管理画面、API、service、scriptをコード検索し、機能とDB objectの対応を整理した。
利用箇所ありとrepository内で利用箇所なしを、直接・間接経路とファイル位置を根拠に区別した。
本番運用や外部consumerがなければ確定できない10項目を引き継いでいる。

### [第3部: 歪み、重複、廃止候補](inventory-3-issues-and-cleanup.md)

現行134 objectを、構造とデータの2軸で分類した。
原本データと必要な振る舞いを守りながら、重複、PostgreSQL/Supabase固有方式、
過剰な集計、未使用候補を整理し、本番確認待ち18項目とユーザー判断事項を示した。

### [第4部: meigen-fly向けDB概念設計](inventory-4-new-db-design.md)

FastAPI + SQLAlchemy Core + SQLite向けに、原本・関連13表とranking snapshot 3表の16表案を示した。
主要column、型、NULL、PK/FK、UNIQUE、CHECK、index、削除動作、代表query、
現行20表との対応、および本番確認・ユーザー判断で変わる18論点を整理した。

### [第5部: 本番DB確認事項と次の作業](inventory-5-production-checklist.md)

第1〜4部の本番確認待ちをA1〜A9、DB外確認O1〜O4、取得不要N1〜N6へ集約した。
本番では実行していないSELECT-onlyの確認案、安全境界、Git管理外の保存先、
判断18件 + 運用判断U1、および確認後の作業順を示した。

## 3. 全体要約

### 3.1 現行DBの規模と構造

**本番dumpで確認**した現行DBの主な規模は次のとおりである。

- table 20件、table column 138件
- view 3件、materialized view 4件
- function/RPC 26 signature（24名称）
- trigger 14件、明示index 54件
- extension 6件、RLS policy 57件
- primary key 20件、foreign key 19件、UNIQUE 13件、CHECK 10件、EXCLUDE 1件、ENUM 2件

20表は、既存計画の19表案に`admin_users`を加えたものと完全一致した。
未知の追加tableはなく、table単位および説明できないcolumn・constraint単位のschema driftは見つからなかった。
生成型は19表135列で、追加時点が後の`legacy_votes` 1表3列を除く共通部分がdumpと一致する。

一方、構造の確認だけでは、各表の行数、NULL・空値、重複、孤立、sequence高水位、
MVのpopulate状態、cron登録、実効権限、repository外consumer、運用実績は確定できない。

### 3.2 利用状況と主な歪み

現行アプリでは20表すべてに直接またはDB内部の間接利用経路がある。
ただし、tableの利用があることは、その構造をSQLiteへそのまま残す根拠にはならない。

主な歪み・重複・過剰構成は次のとおりである。

- rankingがMV、通常table 3件、parameter、log、複数RPC、cron、CLIへ多段化している。
- count用途にview/MVが重なり、管理KPI view 2件にはrepository内consumerが見つからない。
- source一覧RPCの5/7引数overload、ranking refreshの2 signature、重複RLS policyが併存する。
- RLS、広いACL、Supabase Auth role、`SECURITY DEFINER`、PGroonga、`pg_cron`など固有方式への依存がある。
- `sources.search_document`と3 trigger、PGroonga 5 indexなど、検索処理と派生列保守が分散している。
- `author_country`にはEXCLUDEと類似index 5本、categoryには重複CHECKがある。
- `quotes.slug`と`enable`のNULL許容、日時default・RPC日時型の混在など、現行契約と整合性に差がある。
- `legacy_votes`は旧票集計用の過去構造だが、再構築不能な値として現行rankingへ寄与している。
- repository内経路がないview、function、trigger、policy、index、cron意図があるが、本番未使用とは断定していない。

第3部ではtable、view/MV、function、trigger、ENUM/EXCLUDE/index/job、RLS policyを
計134 objectとして漏れなく分類した。分類集計は、構造の扱いが
維持12、再編11、処理へ置換78、廃止24、本番確認待ち9である。

### 3.3 meigen-fly向け構成案

既定案は、**原本・関連13表 + ranking snapshot 3表 = 16表**である。
これは本番確認とユーザー判断前の概念設計であり、実装確定ではない。

- コンテンツmaster、関連表、`quote_likes`を原本として保持する。
- `legacy_votes`の値は`quotes.legacy_vote_count`へ統合し、独立表を作らない。
- `admin_users`はCloudflare Access + 外部IdPへ置換し、新DBへ移行しない。
- `ranking_parameters`は型付きCLI設定、`ranking_refresh_logs`はstderr・監視・heartbeatへ置換する。
- `quote_ranking_scores`、`author_rankings`、`category_rankings`の3 snapshotは責務を維持し、原本から再計算する。
- view、MV、PostgreSQL function/RPC、RLS、GRANT、PGroonga、`pg_cron`は新DBへ持ち込まない。
- character/category/country/profession等の件数は、まずリアルタイムSQLで算出する。
- rankingだけをsupercronicから起動するPython CLIで定期再計算し、前回正常snapshotを保つ。
- 検索はwildcardをescapeしたbind parameterによる`LIKE`とし、検索派生列を持たない。
- ID、slug、公開状態、qid=`q{id}`、表示言語fallback、歴史日付、likes一意性を維持する。

この案は名言約2,100件・著者約890件の規模に合わせ、原本と派生を分け、
通常のJOIN、EXISTS、GROUP BYと最小限の制約・indexで公開・管理機能を成立させる。
DB全体の実行時行数とSQLite上の性能は、本番相当データによる後続検証事項である。

### 3.4 未完了の本番確認とユーザー判断

本番DB・運用で必要な確認は、第5部の次の区分へ集約されている。

- A1: 全20表の行数と、新16表が受け入れるNULL・空値・重複・孤立・制約違反候補
- A2: 9 sequenceと最大ID、特にquote IDの高水位
- A3: quote slug、公開状態、本文、表示言語fallback、category時点候補
- A4: 時点、歴史日付、刊行年、country code
- A5: 国、出典種別、category関連のcardinalityと整合
- A6: `legacy_votes`とlikesの、識別値を出さない安全な集計
- A7: ranking設定、3 snapshot、4 MV、log、cronの静的状態
- A8: count/searchの基準値と、後続のローカルSQLite比較
- A9: 条件付き廃止object、権限、外部writeのDB側手掛かり

SQLだけでは確定しない事項は、次のDB外確認に分離されている。

- O1: 実URL、canonical/redirect、公開API consumerと公開状態の意図
- O2: 条件付き廃止object、likes補助列、外部consumer、snapshot sort
- O3: 実効権限、外部管理write、MV ACL、cron/refresh運用
- O4: migration/import/修正script、backup、復元試験、PITRの運用実績

第1部17件、第2部10件、第3部18件、第4部§12の18行と§12.1、
第4部§14の10件は、A1〜A9、O1〜O4、または理由付き取得不要項目へすべて対応済みである。

設計・移行範囲については、第4部§12を正本とする18件が未判断である。
主題は関連構造、旧票・likes、ranking、URL・公開・本文、歴史日付、country code、
ID高水位、snapshot、条件付き廃止object、管理KPIである。
加えて、過大な本番Supabase権限が確認された場合の是正判断U1が別枠で残る。

## 4. 次の作業

本番確認と18件 + U1のユーザー判断を終えるまで、16表案を実装へ進めない。
次の作業順は第5部§10を正本とする。

1. A1〜A9とO1〜O4を、承認済みの安全な手順で確認する。
2. 結果に基づき、16表案、条件付きcolumn、NULL/CHECK、likes個票の扱いを確定する。
3. 既存の19表案を更新し、命名規約とSQLite DDLを設計する。
4. SQLAlchemy Core定義、Alembic、変換規則、照合・検証、backup・切戻しを含む移行手順を設計する。
5. 承認済みの選択列だけをGit管理外へ取得し、保護・retentionを適用する。
6. 設計と取得手順のreview後に、migration、移行script、アプリ実装へ進む。

`docs/project-plan.md`の19表案などに対する修正候補は、第4部§13に提示済みである。
本棚卸しでは候補の提示だけを行い、同ファイルへの修正はまだ適用していない。
