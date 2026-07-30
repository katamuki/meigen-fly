# 現行DB棚卸し・概念設計 フェーズ0作業メモ

作成日: 2026-07-16

対象フェーズ: フェーズ0（準備・前提確認）

このメモは、フェーズ1以降が前提確認をやり直さずに着手できるよう、確定済み方針、見直し可能な事項、開始時のリポジトリ状態、安全上の制約をまとめたものです。フェーズ0ではDB構造の調査・分析・設計・実装を行っていません。

## 1. 調査範囲と確認結果

### 読了した一次資料

- `docs/database/current-system-inventory-task.md`（全文）
- `docs/database/current-system-inventory-roadmap.md`（全文）
- `docs/project-plan.md`（全文）
- `docs/decisions/001-architecture-cloudflare-fly-sqlite.md` 〜 `016-csp-htmx-rules.md`（全16件・全文）
- `/Users/sonoda/prj/meigen-fly/AGENTS.md`
- `/Users/sonoda/prj/meigensyu/AGENTS.md`
- `/Users/sonoda/prj/meigensyu/node_modules/png-to-ico/AGENTS.md`
- `/Users/sonoda/prj/meigensyu/CLAUDE.md`（`AGENTS.md`を参照する旨のみ）

`AGENTS.md`は両リポジトリ内を探索し、上記3件を確認した。`meigen-fly`では、小規模な個人運営サイトに比例した単純で局所的な設計を優先する。`meigensyu`は読み取り専用とし、本番環境を直接操作しない。

### schema dump

- 配置先: `/Users/sonoda/prj/meigen-fly-private/source-db/schema/schema.sql`
- 通常ファイルとして存在することを確認した。
- 2026-07-16取得済み、schema-only確認済みという前提はロードマップおよび今回のユーザー指示による。
- フェーズ0では存在確認のみを行い、**本文は読んでいない**。
- ロードマップ記載のヘッダー集計ではテーブル20件である。既存の「19テーブルを移行する」は仮説であり、20件の実名・内訳や19件一覧との差はフェーズ1でdump本文を正本として確認する。

### 情報源の優先順位

構造について食い違いがある場合は、原則として次の順で扱う。

1. 本番schema dump（実在する構造の正本）
2. 現行アプリコード（現在の利用機能・クエリ）
3. 生成済みDB型
4. migration（由来・変更履歴）
5. 文書（設計意図・運用経緯）

重要な結論にはロードマップの確度ラベル（「本番dumpで確認」「リポジトリ内で一致」「リポジトリから推定」「本番確認待ち」）を付ける。構造をdumpで確認できても、実データの件数・値・利用状態は別途確認が必要である。

## 2. 変更しない確定事項

以下は本棚卸し・概念設計が従う制約であり、調査結果だけを理由に本作業内で変更しない。変更が必要なら、既存ADRとの矛盾として提示し、ユーザー判断とADRの正式な見直しを待つ。

### project-planで確定している前提

- 全体はFly.io（東京`nrt`）+ FastAPI/Uvicorn + Jinja2/HTMX + SQLite + Cloudflareの構成とし、Python 3.14通常版、依存管理は`uv`を使う。環境はローカルと本番の2つで、専用の検証環境は設けない。詳細が重複する箇所はADRを正本とする。
- 公開ページ・機能として、名言、著者、カテゴリ、登場人物、職業、出典の一覧・詳細、トップ、ランキング、検索、匿名いいね、ランダム、SEO、管理画面を移植対象とする。管理画面の主要entityはquotes / authors / categories / characters / sources / professions、補助APIはsource_types / countriesである。
- Supabase Auth、PGroonga、Next.js固有のrevalidate/ISR、PostgreSQLのRLS・RPC・`pg_cron`という**実装方式**はそのまま持ち込まない。必要な振る舞いは、各ADRに従うSQLite・FastAPI・Cloudflare・supercronic側の単純な仕組みへ置き換える。
- データ規模は名言約2,100件、著者約890件という小規模サイトを設計前提とする。ただし、中間テーブル・いいね・ランキング履歴等を含むDB全体の行数は未確認であり、過小評価しない。

### ADR 001〜016

- **ADR 001 — 全体構成:** Fly.io（東京`nrt`）上のFastAPI + Uvicorn + Jinja2/HTMXによるSSR、単一Fly Volume上のSQLite（WAL）を採用する。公開HTTP経路はCloudflare経由とし、DB書き込みは原則Admin、匿名いいねだけを公開書き込みの例外とする。SQLiteでは外部キーを有効化し、`busy_timeout`を設定する。公開HTMLのキャッシュ、動的・管理系の`no-store`という境界も維持する。
- **ADR 002 — 日本語検索:** 初期検索は名言・著者等へのbind parameterを使った単純な`LIKE`部分一致とする。入力中の`%`・`_`等はリテラル扱いとし、FTS5、bigram派生列、形態素解析は初期構成へ含めない。実測上の問題が出た場合だけ再検討する。
- **ADR 003 — 永続化・バックアップ:** 単一Fly Machine + Fly Volumeで運用し、PythonのOnline Backup APIで日次バックアップを作成してR2へ保存・30日保持する。稼働中DBの単純な`cp`は禁止する。大規模データ移行・破壊的migration前はオンデマンドバックアップを取得する。
- **ADR 004 — DBアクセス・migration（重点）:** アプリのDBアクセスは**SQLAlchemy Core**を基本とし、migrationは**Alembic**で管理する。全面ORM化は必須ではない。autogenerateは下書きに限定してレビューし、trigger・view・`CHECK`・データ変換は必要な場合だけ手書きrevisionにする。SQLiteの再作成型変更では`batch_alter_table()`と`render_as_batch=True`を使い、主キー・外部キー・UNIQUE・CHECK・indexへ一貫した命名規約を設ける。安全に戻せない破壊的変更はdowngradeへ無理に詰め込まず、バックアップと対応アプリ版への切り戻しを基本とする。**確定事項は技術選択とmigration方針であり、19テーブルという件数ではない。**
- **ADR 005 — worker・定期ジョブ:** 初期はUvicorn 1 workerとする。バックアップ、ランキング・カテゴリ件数再計算等はFastAPI lifecycleで起動せず、supercronicからCLI実行する。ジョブは`flock`、timeout、非ゼロ終了、短いtransaction、成功時のみのheartbeatを使い、前回正常結果を保つ。
- **ADR 006 — いいね件数・キャッシュ（重点）:** `like_count`は名言詳細・一覧のSSR HTMLへ埋め込み、edge TTL 10分とする。毎PVの件数GET APIと、いいねごとのキャッシュパージは作らない。`POST /api/likes/{quote_id}`は`private, no-store`かつCloudflare Bypassで、成功時は押した本人のDOMだけ最新化する。`client_uuid`はlocalStorageで管理し、DBでは`(quote_id, client_uuid)`をUNIQUEにして再送を冪等成功とする。厳密な一人一票・リアルタイム表示は要件ではなく、IP・IP hashはDBへ保存しない。
- **ADR 007 — SQLiteランタイム:** Python標準`sqlite3`を使う。自動fallbackは実装せず、最終イメージで接続、WAL、Online Backup API、foreign key、Alembic migrationをスモークテストする。
- **ADR 008 — URL互換性（重点）:** canonical hostは`https://www.meigensyu.com/`とし、現行で200を返す公開URLは同じpath/queryで同等コンテンツを返す。現行canonical、ページング、filter、sort、末尾slash、範囲外ページの404を維持する。既存redirectは最終canonicalへの1 hop 301/308とし、静的redirect 23本と`/quotations/view/[id].html`の動的301を移植する。slug、`qXXXX`、`page/1`等をURL契約表にする。したがって、qid・slug・公開状態・旧IDや関連付けなどURL解決に必要なデータを、根拠なく変更・削除しない。
- **ADR 009 — 主表示言語（重点）:** `display_language_preference`は閲覧者設定ではなく名言ごとのコンテンツ属性である。物理カラム名を維持し、`ja | en`、`NOT NULL`、default `ja`とする。`text`と`text_en`の指定側が空なら他方へfallbackし、カード・詳細・metadata・OG・構造化データは同じresolverを使う。
- **ADR 010 — `/random`:** 公開対象からランダムな20件を一覧として200で返す現行機能を維持し、`private, no-store`かつCloudflare Bypassとする。個別名言への302へ変更しない。
- **ADR 011 — 日時形式（重点）:** `created_at`、`updated_at`、いいね・ジョブ実行日時等の「時点」はSQLiteで固定長UTC `TEXT`（`YYYY-MM-DDTHH:MM:SS.ffffffZ`）に統一する。timezone-aware datetimeだけを受理し、明示serializer/parserを通す。SQLiteの`CURRENT_TIMESTAMP`、標準adapter/converter、桁数やoffsetの異なる表現を混在させず、比較・期間境界のbind値にも同じserializerを使う。`birth_date`・`death_date`等の暦日・歴史日付は時点と分離し、UTC変換しない。
- **ADR 012 — 管理者認証:** Cloudflare Access + 外部IdPを採用し、初期はアプリ内role/identity表や独自ログインCookieを作らない。現行`admin_users`は初期認証の移植必須対象ではないが、現行DBオブジェクトとしては棚卸しから除外しない。Adminの状態変更にはCSRF対策を設ける。
- **ADR 013 — オリジン保護:** Cloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを持たない。`CF-Connecting-IP`はTunnel経由のbest-effortな補助信号に限り、認証identityには使わず、`X-Forwarded-For`へfallbackしない。IPを永続化しない。
- **ADR 014 — キャッシュ更新反映:** DB transaction成功後に関連URLまたは集合タグを同期パージし、失敗時は更新を取り消さずTTLによる自然失効へ委ねる。初期はoutbox、自動retry、非同期flusher、専用queueを作らず、いいねではパージしない。
- **ADR 015 — 検索UI・制限:** 正規化後1文字から500ms trailing debounceで検索し、通常GETも利用可能にする。アプリ内IP単位カウンターはbest-effortかつプロセスメモリ上とし、IP・queryをDBや通常ログへ永続化しない。
- **ADR 016 — CSP・HTMX:** 共通CSPと基本セキュリティヘッダーを適用し、Jinja2のescapeを主防御とする。HTMXは`allowEval=false`、`allowScriptTags=false`、`selfRequestsOnly=true`とし、危険な属性・断片内scriptを使わない。GA4/AdSenseは初期必須ではなく、導入時も検索語、raw query、`client_uuid`、管理者情報、いいね情報を送信しない。

### ADR横断のDB設計制約

- PostgreSQL/Supabaseの現行実装を機械的にSQLiteへ移さず、必要なコンテンツ、公開・管理機能、URL互換性、いいね・ランキング・検索等の振る舞いを守る。
- 公開・非公開・下書き・編集中を含む、本番DB上の管理対象コンテンツを原則棚卸し対象とする。削除候補は件数・利用箇所・意味を確認し、ユーザー判断なしに「移行不要」と確定しない。
- 原本データと派生データを区別し、小規模サイトに不要なキャッシュテーブル、ビュー、RPC、将来向け抽象化を持ち込まない。
- Supabase Auth、PGroonga、RLS、PostgreSQL RPC、`pg_cron`等の現行の実装方式自体は維持対象ではない。ただし、それらが提供している必要なデータ・振る舞いは先に確認する。

## 3. 本作業で見直してよい事項

以下は既存文書の案・仮説または未確定な具体設計であり、フェーズ1〜4の根拠に基づいて見直してよい。

- 「アプリデータとして19テーブルを移行する」という一覧、各テーブルの要否、統合・分割・改名・廃止。ロードマップではdumpに20テーブルあるため、まず実名と差分を確定する。
- 20件目が`admin_users`なのか別オブジェクトなのか、19件一覧に何が含まれ／漏れているか。
- 各テーブル・カラム・主キー・外部キー・UNIQUE・CHECK・EXCLUDE・default・NULL可否・indexの実在状態と、SQLiteでの具体形。
- IDに`AUTOINCREMENT`を使う範囲、PostgreSQL ENUMを表す`TEXT + CHECK`、生誕国排他制約等のSQLiteでの表現。
- テーブル、view、materialized view、RPC、trigger、extension、RLS policy、grant、`pg_cron` jobの全件と現行利用状況。
- `legacy_votes`、`ranking_parameters`、`quote_ranking_scores`、`author_rankings`、`category_rankings`、`ranking_refresh_logs`の構造・データの扱い。
- `categories_with_counts`等の集計view/MVをリアルタイムSQLへ置換するか、通常テーブル + 定期再計算にするか、廃止するか。
- PostgreSQL RPCを単純SQLまたはPythonサービス処理へ置換する具体的方法。
- 国と著者、出典と出典種別、`source_type_assignments`等の関連構造。
- 初期検索にFTSを採用しない制約の範囲内での、必要な検索列・indexの具体設計。
- 実データの件数、NULL、重複、孤立参照、不正値、常に同値の列、最大ID・sequence、実際の日時精度・timezone等。schema-only dumpでは確定できない。
- 当時未決だったD5（OG画像生成方式）とD8（デザイン刷新範囲）。いずれもDB棚卸しの主対象外とした。その後、D8はADR 017、D5はADR 018で確定済み。

## 4. 開始時のgit status

### `/Users/sonoda/prj/meigen-fly`

- branch: `orchestrator/inventory-phase-0`
- HEAD: `b3f7b7cd1bbbafafe7f7b92f60e9fc15e617db70`
- upstream: なし
- フェーズ0成果物作成前はcleanで、merge/rebase/cherry-pick等の進行中状態はなかった。
- 本メモだけを未コミットの成果物としてworking treeへ追加する。ユーザーレビュー前にコミットしない。

### `/Users/sonoda/prj/meigensyu`

- branch: `develop`
- HEAD: `7ea47136de87deef455901b133af0b175a60e9cb`
- upstream: `origin/develop`、ahead 0 / behind 0
- merge/rebase/cherry-pick等の進行中状態はない。
- 作業開始前から次の未追跡ファイル2件が存在した。既存変更として扱い、本文・内容には触れず、変更もしない。
  - `docs/decisions/004-sqlite-migration-japanese-search.md`
  - `docs/decisions/meigensyu_architecture.md`

## 5. 文書間の矛盾・不明点

1. **schema dump取得時点:** 作業指示書は「今回はschema dumpも取得しない」という取得前の前提を含む一方、後発のロードマップと今回のユーザー指示では2026-07-16取得済み・配置済みである。後発情報を現在の状態として採用し、本作業では新規取得や本番接続を行わず、配置済みdumpだけをフェーズ1から読む。
2. **ADR 004のFTS検証記述:** ADR 004は本番相当データへの全revision適用後の確認項目に「FTS検索」を挙げる。一方、ADR 002と007は初期リリースでFTS5を必須とせず、単純な`LIKE`を採用している。現時点ではADR 002/007の具体的な検索決定を優先し、「初期migration検証はLIKE検索」と解釈する。ADR 004の記述は旧方針が残った可能性があり、将来の文書修正候補である。
3. **19テーブルとdumpの20テーブル:** ADR 004のコンテキストとproject-planは旧`admin_users`を除く19テーブルの移植を前提にするが、ロードマップのdumpヘッダー集計は20テーブルである。差分の実名・意味・移行要否は未確認で、フェーズ1で確定する。
4. **project-planの「約20テーブル/ビュー」:** 同じ箇所の19テーブル一覧と比べ、概数なのかテーブルとviewの種別を混同した表現なのかが曖昧である。正確な種別・件数はdumpを正本に分離して記録する。
5. **ランキングobjectの同名類似:** `quote_ranking_scores`テーブルと`quote_ranking_scores_mv`等は別objectとして扱う必要がある。既存一覧だけで同一視せず、dump、migration、生成型、利用コードを突合する。
6. **ADR 006のstatus表記:** ADR 006本文は「採用」、project-planのD9は「確定」と表記する。内容は一致しており、本作業では確定事項として扱う。

## 6. フェーズ1への引き継ぎ

1. 最初にschema dump本文を読み、テーブル20件の実名と、19件一覧・`admin_users`との差を確認する。これはフェーズ0では未実施である。
   - **フェーズ0レビューで判明(2026-07-16):** dumpの`CREATE TABLE`名を突合した結果、**20テーブル = project-planの19テーブル一覧 + `admin_users`で完全一致**。未知テーブルやテーブル単位のschema driftはない。§5の矛盾3はこれで解消。カラム・制約レベルの差分確認はフェーズ1で行う。
2. dumpを実在構造の正本として、テーブル、型、制約、index、view、MV、関数/RPC、trigger、extension、RLS、grant、定期jobをobject種別ごとに棚卸しする。ロードマップ記載の各集計値は、dump定義との照合前に確定値として転記しない。
3. 事実、文書上の意図、推論を分離し、各重要結論へ確度ラベルと根拠（dump定義、migrationファイル、生成型等）を付ける。
4. qid、slug、公開状態、旧ID・redirect参照等、ADR 008のURL互換性に関係する列・制約・関連を優先して追跡する。
5. `text`、`text_en`、`display_language_preference`の型、default、NULL、不正値の可能性とfallback要件をADR 009に照らして確認する。
6. timestamp系のdefault、timezone、NULL、精度を棚卸しし、暦日・歴史日付と分離する。SQLiteの提案はADR 011の固定長UTC形式に合わせる。
7. `quote_likes`の現行キー、重複可能性、保持している識別情報を確認し、ADR 006の`UNIQUE (quote_id, client_uuid)`とIP非保存方針へどう移すかを後続フェーズの論点にする。
8. rankingのテーブル・MV・RPC・consumer・定期jobを、廃止や統合を決める前に一組として追跡する。dump内にFTS関連objectがあれば現行構造として棚卸しするが、初期SQLite要件にはしない。
9. migration 99本は最終構造の正本ではない。dumpとの差分と構造の由来・変更経緯を確認する用途に絞る。
10. `meigensyu`の既存未追跡2件を含む既存変更に触れず、同リポジトリを読み取り専用で扱う。

## 7. 継続する禁止事項・安全上の注意

- 本番DBへ接続しない。dump取得、SQL実行、Supabase操作、Supabase MCPの本番利用を行わない。
- `.env`、接続文字列、API key、password等の秘密値を画面・ツール出力・成果物へ表示または転記しない。
- `/Users/sonoda/prj/meigensyu/scripts/backup_via_copy.sh`の本文を表示しない。必要ならパス、問題種別、推奨対応だけを記録する。
- `/Users/sonoda/prj/meigensyu`を変更しない。
- `/Users/sonoda/prj/meigen-fly-private/source-db/schema/schema.sql`や他の取得済み実データを変更しない。
- SQLite DDL、SQLAlchemy/Alembic実装、migration、移行script、アプリコードを実装しない。
- 仮想的な将来要件のためのテーブル、抽象化、分散構成を追加しない。
- 本番DBから追加情報が必要になった場合は、対象・目的・取得内容・安全な手順・保存先を提示し、ユーザー確認前に実行しない。

## 8. フェーズ0完了判定

schema dumpの配置、適用されるリポジトリ指示、開始時のgit status、project-planおよびADR 001〜016の確定方針、見直し可能な事項を整理済みである。上記の矛盾・不明点を未確定のまま明示し、安全上の制約を守れば、**フェーズ1を開始できる状態**である。
