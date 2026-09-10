# 名言集.com リニューアル計画書（meigen-fly）

> 本ドキュメントはプロジェクトの**土台となる計画書**。全体像・確定事項・検討事項（未決論点）・想定作業を俯瞰する。
> 詳細な技術判断は `docs/decisions/` 配下の決定記録に切り出す。
>
> - 作成日: 2026-07-01
> - 更新日: 2026-08-25（フェーズ3-A完了を反映）
> - 対象リポジトリ: `/Users/sonoda/prj/meigen-fly`（新規）
> - 移管元: `/Users/sonoda/prj/meigensyu`（Next.js 14 + Supabase、稼働中）

---

## 0. 参照ドキュメント

| ドキュメント | 内容 |
|---|---|
| [`docs/decisions/001-architecture-cloudflare-fly-sqlite.md`](decisions/001-architecture-cloudflare-fly-sqlite.md) | 全体構成・キャッシュ戦略・Cloudflare/Fly.io/SQLite 構成の詳細（確定寄り） |
| [`docs/decisions/002-sqlite-japanese-search.md`](decisions/002-sqlite-japanese-search.md) | 初期の日本語検索は単純な`LIKE`、実測後にFTS5を再検討 |
| [`docs/decisions/003-sqlite-daily-backup.md`](decisions/003-sqlite-daily-backup.md) | 単一Machine・日次SQLiteオンラインバックアップ・復旧方針 |
| [`docs/decisions/004-alembic-migrations.md`](decisions/004-alembic-migrations.md) | SQLAlchemy Core + Alembicによるマイグレーション方針 |
| [`docs/decisions/005-uvicorn-supercronic-jobs.md`](decisions/005-uvicorn-supercronic-jobs.md) | Uvicorn worker数とsupercronicによる定期ジョブ実行方針 |
| [`docs/decisions/006-like-count-cache-strategy.md`](decisions/006-like-count-cache-strategy.md) | 匿名いいね数のHTML埋め込み・キャッシュ方針 |
| [`docs/decisions/007-python-sqlite-runtime.md`](decisions/007-python-sqlite-runtime.md) | Python標準sqlite3の採用と最小スモークテスト |
| [`docs/decisions/008-url-compatibility.md`](decisions/008-url-compatibility.md) | 現行URL・リダイレクト・canonicalの互換方針 |
| [`docs/decisions/009-quote-display-language.md`](decisions/009-quote-display-language.md) | 名言レコードごとの主表示言語とfallback仕様 |
| [`docs/decisions/010-random-page-cache.md`](decisions/010-random-page-cache.md) | `/random`の現行機能維持とno-store方針 |
| [`docs/decisions/011-sqlite-datetime-format.md`](decisions/011-sqlite-datetime-format.md) | SQLiteに保存する時点データの固定長UTC形式 |
| [`docs/decisions/012-admin-auth-cloudflare-access.md`](decisions/012-admin-auth-cloudflare-access.md) | Cloudflare Access・外部IdP・MFAによる管理者認証 |
| [`docs/decisions/013-cloudflare-tunnel-origin-protection.md`](decisions/013-cloudflare-tunnel-origin-protection.md) | Cloudflare Tunnel・Fly公開入口削除によるオリジン保護 |
| [`docs/decisions/014-cache-purge-boundaries.md`](decisions/014-cache-purge-boundaries.md) | 更新後の同期パージとTTL fallback |
| [`docs/decisions/015-search-rate-limits.md`](decisions/015-search-rate-limits.md) | 検索UIの1文字検索・500ms debounce・アプリ側レート制限 |
| [`docs/decisions/016-csp-htmx-rules.md`](decisions/016-csp-htmx-rules.md) | CSP許可先、インラインコード禁止、HTMX実装規約 |
| [`docs/decisions/017-design-system-d8.md`](decisions/017-design-system-d8.md) | 提案B「墨（藍）× 宵」とデザインシステムの採用 |
| [`docs/decisions/018-og-image-generation.md`](decisions/018-og-image-generation.md) | Pillowによる名言・著者OG画像のオンデマンド生成方針 |

本計画書はこれらを束ねる上位文書。**確定事項の正本は各ADR**とし、本計画書は概要と参照だけを持つ。矛盾があればADRを優先し、計画書側を修正する。

---

## 1. 目的・背景

- 現行 **Vercel（サーバーレス）+ Supabase(PostgreSQL/PGroonga)** 構成を、**Fly.io + FastAPI + HTMX + SQLite** の**永続VPS型・SSR**構成へ作り変える。
- **狙い**
  - **運用コスト削減**: DBサーバープロセス不要・SQLiteファイル1個で完結。Supabase 従量課金からの脱却。
  - **表示の高速化・オリジン負荷削減**: Cloudflare エッジキャッシュ + SSR で TTFB 短縮（決定記録001の期待効果）。
  - **デザイン一新**: HTMX ベースの軽量 SSR で UI を刷新。
  - **アーキテクチャの単純化**: サーバーレス制約から解放され、SQLite書き込みと移行スクリプトが素直に動く。

## 2. 確定事項（前提）

| 項目 | 決定 |
|---|---|
| ホスティング | **Fly.io**（東京 `nrt`） |
| アプリ | **FastAPI + Uvicorn**（SSR、Jinja2 テンプレート） |
| フロント | **HTMX**（+ 最小限のCSS/JS。SPAフレームワークは使わない） |
| DB | **SQLite**（`/data` ボリューム、WALモード） |
| 永続化・バックアップ | **単一Machine + Fly Volume**。Online Backup APIで日次バックアップを作りR2へ保存し30日保持 |
| マイグレーション | **SQLAlchemy Core + Alembic**（手書きrevision中心） |
| アプリプロセス | 初期は **Uvicorn 1 worker**。全定期ジョブは **supercronic** で分離実行 |
| CDN/WAF | **Cloudflare**（無料プラン想定、エッジキャッシュ・Bot対策） |
| 開発言語 | **Python 3.14**（通常版） |
| Python依存管理 | **uv**（`pyproject.toml` + `uv.lock`） |
| 環境 | **ローカル開発環境 + 本番環境**。専用の検証環境は設けない |
| 公開オリジン | **`https://www.meigensyu.com/`**（既存ドメインから切替） |

> キャッシュパージ、検索レート制限、CSP/HTMX、OG画像を含む確定事項の詳細は対応するADRを正本とする。第7章の設計判断はすべて確定済みである。

## 3. スコープ（何を作り変えるか）

### 3.1 移植する公開ページ（現行 `src/app/(site)` より棚卸し）

| パス | 内容 | 備考 |
|---|---|---|
| `/` | トップ（注目名言・ランキング抜粋） | `get_featured_quotes_light` 相当 |
| `/quotes`, `/quotes/page/[n]` | 名言一覧（ページング） | |
| `/quotes/latest`, `/quotes/latest/page/[n]` | 新着名言 | |
| `/quotes/[slugOrQid]` | 名言個別ページ | slug と `qXXXX` 両対応（決定記録: URL構造） |
| `/authors`, `/authors/[slug]`, `/authors/[slug]/page/[n]` | 著者一覧・詳細 | 職業/国籍/生没年表示。`page/1` は基底URLへ301 |
| `/authors/places/[countrySlug]` | 国別著者 | `/authors/places` の基底一覧は現行に存在しない |
| `/categories`, `/categories/[slug]`, `/categories/[slug]/page/[n]` | カテゴリ（2階層） | `page/1` は基底URLへ301 |
| `/characters`, `/characters/[slug]`, `/characters/[slug]/page/[n]` | 登場人物 | `page/1` は基底URLへ301 |
| `/professions`, `/professions/[slug]`, `/professions/[slug]/quotes` | 職業 | |
| `/sources`, `/sources/[slug]`, `/sources/[slug]/page/[n]` | 出典（作品） | 種別フィルタ |
| `/ranking` | ランキング | 名言/著者/カテゴリ |
| `/random` | ランダム名言20件＋シャッフル | 現行機能を維持し、`private, no-store`＋Cloudflare Bypass |
| `/search` | 全文検索（**キャッシュ不可**） | HTMXインクリメンタル検索 |
| `/about`, `/privacy`, `/terms` | 静的ページ | Markdown管理 |
| `/login`, `/403` | 管理認証フロー | `/login`は`/admin/`へ一時リダイレクトしてCloudflare Access認証を開始。`/403`は権限エラー時の遷移先 |

### 3.2 移植する主要機能

1. **日本語検索**（名言・著者）— 初期はSQLiteの単純な`LIKE`部分一致を使用し、実測後にFTS5を再検討（第7章・決定記録002）
2. **匿名いいね**（`quote_likes`）— ⚠️ **本サイト唯一の「公開ユーザー書き込み」**で、§4・§9の「書き込みはAdminのみ」の明示的な例外。専用POSTエンドポイント + best-effort重複抑止 + いいね数のHTML焼き込み（10分TTL）。詳細はADR 006を正本とする
3. **ランキング**（名言/著者/カテゴリ、いいね数・weight による定期再計算）
4. **OG画像生成**（名言 `/quotes/{slugまたはq{id}}/og.png`、著者 `/authors/{slug}/og.png`。Pillowによるオンデマンド生成、ADR 018）
5. **SEO**（sitemap.xml / robots.txt / 構造化データ / メタタグ / canonical）
6. **広告**（サイト本体完成後に必要性を判断）
7. **アクセス解析**（サイト本体完成後に任意導入。初期は通常のpage viewに限定）
8. **管理画面**（`/admin/*`）— CRUD + 一括登録 + ランキング再計算

### 3.3 管理画面の対象エンティティ（現行 `src/app/(admin)` より）

画面として移植する対象:

quotes / authors / categories / characters / sources / professions
＋ 一括登録（quotes・authors bulk）＋ ランキング手動再計算

補助APIとして移植する対象:

source_types / countries（著者・出典フォーム内から利用。専用管理画面は現行に存在しない）

キャッシュパージは現行では名言単位の再検証ボタンのみ。Cloudflare移行後の一括パージUIを作る場合は新規機能として扱う。

### 3.4 スコープ外（今回持ち込まない／再検討）

- Supabase Auth（→ Cloudflare Access + 外部IdP + MFAに置換。ADR 012）
- PGroonga（→ SQLite検索に置換）
- Next.js特有の revalidate / ISR（→ Cloudflare パージに置換）
- `pg_cron` / PostgreSQL RPC / RLS（→ アプリ層ロジック + SQLに移植）

## 4. データモデル移行方針

現行スキーマ（`docs/database/schema-design.md` 相当、約20テーブル/ビュー）を SQLite へ写す。**PostgreSQL固有要素の置換**が要点。

| PostgreSQL要素 | SQLiteでの扱い |
|---|---|
| `SERIAL` / `BIGSERIAL` | 原則 `INTEGER PRIMARY KEY`。`AUTOINCREMENT`は公開qidのID再利用を防ぐ`quotes`だけに使う |
| ENUM（`date_precision`, `life_era`） | `TEXT` + `CHECK`制約 |
| `TIMESTAMPTZ` | **固定長UTC `TEXT`**（`YYYY-MM-DDTHH:MM:SS.ffffffZ`）。明示codecで入出力し、別形式を混在させない（D17/ADR 011） |
| `JSONB` | アプリ層でJOIN構築（RPCのJSONB返却は廃止しPython側で組む） |
| `EXCLUDE`制約（生誕国排他） | アプリ層 or 部分UNIQUEインデックスで代替 |
| RLS / `is_admin()` | 書き込みは原則Admin経路のみ（アプリ層で担保）。**例外は匿名いいねの専用書き込み経路のみ**（§3.2-2 / D9） |
| PGroongaインデックス | 初期は`LIKE`部分一致。検索インデックスは性能上必要になった場合だけ追加（第7章） |
| マテビュー/集計ビュー | count系は原本に対するリアルタイムSQLへ置換し、rankingだけは3つのsnapshot表を定期再計算する |
| RPC（`get_quote_rankings` 等） | FastAPIサービス層のSQL関数に移植 |

### 対象テーブル一覧
SQLiteで扱うテーブルは、原本・関連13表 + ranking snapshot 3表の計16表:

`authors` / `sources` / `source_types` / `source_type_assignments` / `characters` / `quotes` / `categories` / `professions` / `author_professions` / `countries` / `author_country` / `quote_categories` / `quote_likes` / `quote_ranking_scores` / `author_rankings` / `category_rankings`

現行の`legacy_votes`はquote別の値を`quotes.legacy_vote_count`へ統合し、独立表を作らない。`ranking_parameters`の4係数は型付きCLI設定へ同値移行し、`ip_daily_limit`はアプリ側rate limit設定へ分離する。`ranking_refresh_logs`は移行せず、新DBに履歴表を作らない。定期処理の成否はstderr・外部監視・heartbeatで扱う。

既存の`admin_users`は初期認証に利用せず、移行必須対象から除外する。将来、複数管理者の権限差が必要になった場合に、ADR 012に従って新しい認可モデルとして再設計する。

### 集計ビュー・マテビュー・RPCの置換対象

現行の集計ビュー/MVはそのまま移植しない。count系と管理KPIは必要な値だけ原本へのリアルタイムSQLで算出し、rankingは原本から3つのsnapshot表だけを再計算する。rankingの中間MVと更新履歴viewは作らない。

- `categories_with_counts`（現行は最終的にMV）
- `quote_ranking_scores_mv`（ランキング計算。`legacy_votes` を加算）
- `characters_with_quote_counts`
- `country_author_counts`
- `profession_author_counts`
- `view_admin_kpi_counts`
- `view_admin_ranking_refresh_logs`

現行`pg_cron`ジョブから移す定期処理はranking CLIだけとし、supercronicから実行する。カテゴリ件数はリアルタイムSQLで算出するためrefresh jobを作らない。初期はUvicorn 1 workerとし、FastAPI startup/lifespanではスケジューラを起動しない。ranking CLIには多重起動ロック・timeout・失敗通知を設ける（D6/ADR 005）。

> データ規模（2026-07-17本番確認）: 名言1,831件、著者774件、likes 7,591件。中間表・snapshot・履歴等を含む現行20表の合計は20,833行（`admin_users`を除くアプリデータは20,831行）で、引き続き小規模である。

### URL互換性

- 現行IDを保持し、`quotes`だけに`AUTOINCREMENT`を使って、確認済みの高水位3,197を引き継ぐ。他テーブルには`AUTOINCREMENT`を付けない。
- qid専用列は保存せず、`quotes.id`から`q{id}`を決定的に生成する。
- `quotes.slug`はnullable UNIQUEのまま保持する。現行1,831件中未設定の1,825件は`q{id}`をcanonicalとし、slugの補完・NOT NULL化・redirect表追加は行わない。
- `quotes.enable`は0/1 NNへ同値移行し、通常公開経路は1だけに限定する。`/api/quotes`のパラメータ省略時に非公開も返す互換は引き継がない。

### 移行スクリプト
- Supabase(PostgreSQL) から `pg_dump` / CSVエクスポート → 変換 → SQLite投入するビルドスクリプトを用意。
- 検索用の派生bigram列やFTS5テーブルは初期生成しない（決定記録002）。
- 元テキスト（`text` / `text_en` / `context_note`）は原本保持。

## 5. アーキテクチャ（決定記録001の要約）

```
[User/Bot] → [Cloudflare CDN+WAF] → [Cloudflare Tunnel] → [Fly.io FastAPI+Uvicorn] → [SQLite (/data)]
```

- **キャッシュ**: パスごとの`Cache-Control`をMiddlewareで一元管理し、公開HTMLはCloudflare Cache Rulesでエッジキャッシュする（HTMLはデフォルト非キャッシュのためEligible指定が必須）。`/search`・`/admin`配下・`/login`・`/random`等はno-store + Bypass。Cache-Control表とCache Rules設定の詳細は決定記録001 §3・§8を正本とする。
- **パージ**: Admin更新後に少数のURL/集合タグを同期パージし、失敗時はTTLに委任する（D12/ADR 014）。いいね数はHTML焼き込み + 10分TTLで、いいねごとのパージはしない（D9/ADR 006）。
- **オリジン保護**: Cloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除する（D14/ADR 013）。管理画面はAccess + JWT検証（D3/ADR 012）。
- **セキュリティヘッダ**: 共通CSPと基本ヘッダー（D16/ADR 016、決定記録001 §11）。
- fly.toml・Dockerfile要点・ETag方針など実装詳細は決定記録001を参照。

## 6. アプリ構成案（FastAPI + HTMX）

```
meigen-fly/
├── app/
│   ├── main.py                # FastAPI起動・Middleware（cache/security）
│   ├── config.py              # 環境変数
│   ├── db.py                  # SQLite接続・PRAGMA・コネクション管理
│   ├── routers/               # 公開ルート（quotes, authors, categories, search, ranking...）
│   ├── admin/                 # 管理画面ルート（認証必須）
│   ├── services/              # データアクセス・検索・ランキング（旧RPC相当）
│   ├── templates/             # Jinja2（base, partials, HTMX断片）
│   └── static/                # CSS/JS/画像（ファイル名ハッシュ）
├── data/                      # SQLite（本番はFlyボリューム）
├── scripts/                   # 移行・ランキング再計算・sitemap生成
├── migrations/                # Alembic revision
├── tests/
├── Dockerfile
├── fly.toml
└── docs/
```

- **テンプレート**: `base.html` + 部分テンプレート。HTMX は検索・いいね・一覧の追加読込など**部分更新**に限定利用。
- **サービス層**: 旧 Supabase RPC のロジック（ランキング取得・ランダム・出典集計・著者一覧）をSQLへ移植。JSONBはPython辞書で構築。

## 7. 設計判断（すべて確定済み）

各決定の内容・理由・再検討条件は対応するADRを正本とする。ここでは状態だけを一覧する。

| # | 論点 | 状態 |
|---|---|---|
| D1 | 検索方式 | ✅ 単純な`LIKE`部分一致（[ADR 002](decisions/002-sqlite-japanese-search.md)） |
| D2 | SQLite永続化・バックアップ | ✅ 単一Machine + 日次R2バックアップ（[ADR 003](decisions/003-sqlite-daily-backup.md)） |
| D3 | 管理者認証 | ✅ Cloudflare Access + 外部IdP（[ADR 012](decisions/012-admin-auth-cloudflare-access.md)） |
| D4 | マイグレーション管理 | ✅ SQLAlchemy Core + Alembic（[ADR 004](decisions/004-alembic-migrations.md)） |
| D5 | OG画像生成 | ✅ Pillowによるオンデマンド生成 + Cloudflareキャッシュ。表示幅20/40/80の3段階、80超は省略（[ADR 018](decisions/018-og-image-generation.md)） |
| D6 | worker数・定期ジョブ | ✅ Uvicorn 1 worker + supercronic（[ADR 005](decisions/005-uvicorn-supercronic-jobs.md)） |
| D7 | SQLiteランタイム | ✅ Python標準`sqlite3`（[ADR 007](decisions/007-python-sqlite-runtime.md)） |
| D8 | デザイン刷新の範囲 | ✅ 確定。提案B「墨（藍）× 宵」採用。デザインガイドを正本（[ADR 017](decisions/017-design-system-d8.md)、[design-guide](design/design-guide.md)） |
| D9 | いいね（公開書き込み） | ✅ HTML焼き込み + 専用POST + best-effort重複抑止（[ADR 006](decisions/006-like-count-cache-strategy.md)） |
| D10 | URL互換性 | ✅ 現行URL・意味・canonicalを維持（[ADR 008](decisions/008-url-compatibility.md)） |
| D11 | 名言の主表示言語 | ✅ 現行`display_language_preference`仕様を維持（[ADR 009](decisions/009-quote-display-language.md)） |
| D12 | キャッシュ更新反映 | ✅ 同期パージ + TTL委任（[ADR 014](decisions/014-cache-purge-boundaries.md)） |
| D13 | `/random` | ✅ 現行20件一覧を維持し`no-store`（[ADR 010](decisions/010-random-page-cache.md)） |
| D14 | オリジン保護 | ✅ Cloudflare Tunnel + Fly公開入口削除（[ADR 013](decisions/013-cloudflare-tunnel-origin-protection.md)） |
| D15 | 検索レート制限 | ✅ 1文字検索 + 500ms debounce + アプリ側の単純なIP制限（[ADR 015](decisions/015-search-rate-limits.md)） |
| D16 | CSPとHTMX規約 | ✅ 共通CSP + HTMX危険機能の無効化（[ADR 016](decisions/016-csp-htmx-rules.md)） |
| D17 | 日時のSQLite保存形式 | ✅ 固定長UTC `TEXT`（[ADR 011](decisions/011-sqlite-datetime-format.md)） |

> D1〜D17の設計判断はすべて確定済み。詳細は各ADRを正本とする。

## 8. 作業フェーズ（WBS / マイルストーン）

### フェーズ0: 準備・意思決定（本計画書の次）
- [x] D9・D12・D15・D16の決定とADR化（2026-07-14、ADR 006・014・015・016）
- [x] D8（デザイン刷新）の決定とADR化（2026-07-17、ADR 017。提案B採用・デザインガイド正本化）
- [x] D5（OG画像生成）の決定とADR化（2026-07-19、ADR 018。Pillowオンデマンド生成）
- [x] Python 3.14 + uvによる開発環境初期化（`pyproject.toml`・`uv.lock`、2026-07-30）
- [x] デザイン要件定義（D8。[design-guide](design/design-guide.md)）

### フェーズ1: 基盤構築
- [x] FastAPIスケルトン + Jinja2 + 静的配信（2026-07-30。標準APIドキュメントの無効化を2026-08-05に確認）
- [x] SQLite接続 + Alembicマイグレーション基盤（D4、2026-07-30）
- [x] キャッシュ/セキュリティ Middleware（決定記録001 §4, §11、2026-07-30）
- [x] `/healthz` + 最低限の自動テスト（2026-07-30）

### フェーズ2: データ移行

設計の正は`docs/database/migration-decisions.md`の「判断」列と`inventory-4-new-db-design.md`（第4部）。実装した命名規約・手順・変換ルールは[`docs/database/migration-runbook.md`](database/migration-runbook.md)。検索用派生インデックスは初期不要（D1）。

**フェーズ2完了（2026-08-25）**: 実装2026-08-20、レビュー指摘4件の対応完了2026-08-25。本番ダンプで再構築・全検証PASS（86項目）。フェーズ6の最終移行は同runbookの手順を再実行する。

**スコープ境界**: ranking snapshot 3表はスキーマのみ作成し、データは投入しない（再計算CLIとranking係数のCLI設定移行はフェーズ4）。フェーズ2のデータ移行・検証対象は原本・関連13表 + `quotes.legacy_vote_count`統合。

#### 2-1. スキーマ作成
- [x] 制約・索引の命名規約を設定（D4/ADR 004、2026-08-20。[migration-runbook §1](database/migration-runbook.md)）
- [x] 16表DDLのAlembic revision作成（第4部を正とする。手書き部分: category階層・level 2割当のSQLite互換trigger、生誕国最大1件の部分UNIQUE索引、各CHECK制約）（2026-08-20、revision 0002 + `app/schema.py`）
- [x] 空DBへの`alembic upgrade head`を自動テストに追加（ADR 004の検証要件）（2026-08-20、`tests/test_migrations.py`）

#### 2-2. 移行元データ取得
- [x] エクスポート方法と変換スクリプトの読み込み方式を決定（2026-08-20。`psql`単一トランザクションの`row_to_json`によるJSON Lines。理由は[migration-runbook §3](database/migration-runbook.md)）。ダンプは`meigen-fly-private/source-db/data/`（Git管理外）へ保存
- [x] 「取得→変換→投入→検証」を毎回まっさらなSQLiteファイルを作る再実行可能な一連のコマンドとして整備（フェーズ6の最終移行で同じ手順を再実行する）（2026-08-20、`scripts/export_source_db.sh` + `scripts/rebuild_sqlite.sh`）

#### 2-3. 変換・投入スクリプト（`scripts/`新設）
- [x] 13表 + `legacy_vote_count`統合の変換・投入（判断シート19件の判断列に従う）（2026-08-20、`scripts/load_source_data.py`）
- [x] 変換ルールをスクリプト仕様として明文化（[migration-runbook §4](database/migration-runbook.md)）:
  - 全時点列: TIMESTAMPTZ → 27文字固定長UTC `TEXT`（マイクロ秒6桁パディング、D17/ADR 011）
  - `categories.updated_at`: 新設、初期値は現行`created_at`流用（判断#15）
  - `quote_likes`: `quote_id`/`client_uuid`/`created_at`/`is_valid`のみ移行。row UUID・UA・IP/IP hashは除外（判断#4・#5）
  - `countries.code`: 無変換移行を既定とする（意味上の重複1行があるためUNIQUE化しない。正規化する場合のみ該当コードの対応を記録。判断#13）
- [x] quotes高水位: 投入後の`sqlite_sequence`を`max(id)`と旧sequence値3,197の大きい方に設定（判断#14）（2026-08-20。旧sequence値はダンプから動的に読み、3,197を下限とする）

#### 2-4. 整合性検証
- [x] 検証スクリプト作成。期待値は同一ダンプから動的算出する（本番は更新が続くため、2026-07-17時点の件数をハードコードしない）（2026-08-20、`scripts/verify_migration.py`。本番ダンプで全件PASS、[migration-runbook §7](database/migration-runbook.md)）
  - 表ごとの件数一致、`PRAGMA integrity_check` / `PRAGMA foreign_key_check`、孤立関連ゼロ
  - 全時点列の27文字固定長UTC形式とround-trip一致（ADR 011）
  - `quotes.legacy_vote_count`合計 = 旧`legacy_votes`合計票数
  - quotes高水位（`sqlite_sequence` ≥ 3,197）
  - 本文サンプルのバイト一致（文字化け検査）、`enable`・`slug`・`is_valid`の分布一致

### フェーズ3: 公開ページ実装
- [x] 名言一覧/詳細（quotes。3-A、2026-08-25）
- [x] その他の一覧/詳細（authors, categories, characters, sources, professions, countries。3-B、2026-08-26、レビュー完了）
- [x] トップ（3-Aで基盤、3-Cでランキング連動の注目名言と空snapshot fallbackを実装。2026-08-26）
- [x] ランキング・ランダム（3-C、2026-08-26）
- [x] 検索（HTMXインクリメンタル・D1。3-D、2026-09-10）
- [x] いいね（D9。3-C、2026-08-26）
- [ ] SEO（sitemap/robots/構造化データ/canonical）
- [ ] URL互換リダイレクト（静的301 23本 + `/quotations/view/[id].html` 動的301 + URL契約表に基づく正規化）
- [ ] OG画像（D5/ADR 018）
- [ ] サイト本体完成後、必要な場合だけGA4を別フェーズで導入（通常のpage view、Privacy Policy、同意要件を確認）
- [ ] サイト本体完成後、必要な場合だけAdSenseを別フェーズで導入（対象route、Privacy Policy、同意要件を確認）

### フェーズ4: 管理画面
- [ ] Cloudflare Access JWTの最小限の検証（署名・issuer・audience・期限・email）+ CSRF（D3/ADR 012）
- [ ] 各エンティティCRUD
- [ ] 一括登録（quotes/authors bulk）
- [ ] ランキング再計算（D6）
- [ ] Cloudflareパージ連携

### フェーズ5: デプロイ・インフラ
- [ ] Dockerfile / fly.toml / ボリューム
- [ ] 日次SQLiteオンラインバックアップ、R2 Lifecycle、UptimeRobot Heartbeat通知（アプリPushを主、メールを予備。D2/ADR 003）
- [ ] R2からの復旧runbookと、リリース前または大きな変更後の復元確認（D2/ADR 003）
- [ ] Cloudflare（DNS/SSL/Cache Rules/WAF）
- [ ] Cloudflare Tunnel同居、Uvicorn loopback bind、exact Host検証、Fly public IP/service削除手順（D14/ADR 013）
- [ ] no-store/Bypassの`/healthz`外形監視、デプロイ後smoke test、Tunnel/token漏洩時runbook（D14/ADR 013）
- [ ] CI/CD（GitHub Actions → flyctl deploy）
- [ ] UptimeRobotによる`/healthz`外形監視と定期ジョブHeartbeat監視（アプリPushを主通知、メールを予備）

### フェーズ6: 本番リリース（決定記録001 §12・ADR 013）
- [ ] ローカルで本番相当データの移行、主要導線、URL互換を確認する
- [ ] 本番Machineへデプロイし、Flyの管理経路からUvicorn・SQLite・migrationを確認する
- [ ] DNS切替直前に旧環境のAdmin・いいね書き込みを短時間凍結し、最終データを移行する
- [ ] 本番の許可Host・`PUBLIC_ORIGIN`・`CF_ACCESS_AUD`を設定する
- [ ] `www`のDNS/Tunnel routeを切り替える（TTL事前短縮）
- [ ] 公開ページ、管理画面、いいね、キャッシュヘッダ、`/healthz`を本番URLで確認する
- [ ] Tunnel経由の正常性確認後、Flyのpublic service/IPを削除する
- [ ] 旧環境1〜2週間維持後に廃止

## 9. リスクと対策

| リスク | 対策 |
|---|---|
| 日本語検索精度・性能の劣化 | 初期は単純な`LIKE`で開始し、本番相当データの実測で問題が出た場合だけFTS5等を再検討（D1） |
| SQLite書き込み競合 | 書き込みは原則Admin・WAL・`busy_timeout`。**匿名いいねのみ公開書き込み**だが低頻度・単純INSERTで競合影響は限定的（§3.2-2/D9） |
| 定期ジョブの二重実行・部分更新 | FastAPI内でスケジュールせずsupercronicへ分離。`flock`、timeout、失敗通知、単一transactionで前回正常結果を保持（D6/ADR 005） |
| いいね取得が全PVでオリジン到達 | 件数を詳細・一覧HTMLへ含め10分キャッシュ。毎PV GET APIを作らず、POSTした本人だけ即時更新（D9/ADR 006） |
| 単一マシン/Volume障害 | R2の日次バックアップから手動復旧。正常時も最大約24時間の更新欠損を許容し、失敗を通知する（D2/ADR 003） |
| 稼働中SQLiteの不整合バックアップ | 単純なファイルコピーを禁止し、Online Backup APIで一貫したバックアップを作成して`integrity_check`する（D2/ADR 003） |
| URL変更によるSEO低下 | URL互換維持＋301リダイレクト（D10） |
| OG画像/ランキングのメモリ負荷 | OG画像はPillowでキャッシュミス時のみ生成しCloudflareで30日キャッシュ。ランキングはD6に従いジョブを分離（ADR 018/005） |
| 移行時のデータ欠損/文字化け | 件数・関連・サンプル比較の検証スクリプト |
| 管理画面のセキュリティ | Cloudflare Access + 外部IdP側MFA、FastAPIでのJWT検証、CSRF、no-store（D3/ADR 012）。初期は単一管理者を想定 |
| Cloudflare迂回によるWAF/IP制限バイパス | Cloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除。exact Hostも検証（D14/ADR 013） |
| `/random` がエッジキャッシュされ固定化 | 現行20件一覧を`private, no-store`とし、Cloudflare Cache Rulesでも明示Bypass（D13/ADR 010） |
| 本番切替時のデータ差分 | 切替直前に旧環境のAdmin・いいね書き込みを短時間凍結して最終移行する |

## 10. 環境変数

決定記録001 §10を正本とする。概要: `DATABASE_URL`・`PUBLIC_ORIGIN`、Cloudflare関連（パージ・Tunnel・Access）、バックアップ用R2資格情報、任意機能のGA4/AdSense ID。

## 11. 検収チェックリスト

決定記録001 §14を正本とする（エッジキャッシュHIT/Bypass、Access JWT検証、検索、いいね、定期ジョブ、バックアップ・復元、URL互換、オリジン保護の確認項目）。

## 12. 次のアクション

1. フェーズ3（公開ページ実装）へ着手。`data/app.db`は`scripts/rebuild_sqlite.sh`で本番相当データから再構築できる
2. フェーズ3でADR 018に従ってOG画像生成を実装
