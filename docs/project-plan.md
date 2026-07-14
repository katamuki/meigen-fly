# 名言集.com リニューアル計画書（meigen-fly）

> 本ドキュメントはプロジェクトの**土台となる計画書**。全体像・確定事項・検討事項（未決論点）・想定作業を俯瞰する。
> 詳細な技術判断は `docs/decisions/` 配下の決定記録に切り出す。
>
> - 作成日: 2026-07-01
> - 更新日: 2026-07-14（D3・D14を確定、公開ドメインを明記）
> - 対象リポジトリ: `/Users/sonoda/prj/meigen-fly`（新規）
> - 移管元: `/Users/sonoda/prj/meigensyu`（Next.js 14 + Supabase、稼働中）

---

## 0. 参照ドキュメント

| ドキュメント | 内容 |
|---|---|
| [`docs/decisions/001-architecture-cloudflare-fly-sqlite.md`](decisions/001-architecture-cloudflare-fly-sqlite.md) | 全体構成・キャッシュ戦略・Cloudflare/Fly.io/SQLite 構成の詳細（確定寄り） |
| [`docs/decisions/002-sqlite-japanese-search.md`](decisions/002-sqlite-japanese-search.md) | 日本語全文検索の方式検討（PGroonga → SQLite FTS5 bigram / LIKE） |
| [`docs/decisions/003-sqlite-daily-backup.md`](decisions/003-sqlite-daily-backup.md) | 単一Machine・日次SQLiteオンラインバックアップ・復旧方針 |
| [`docs/decisions/004-alembic-migrations.md`](decisions/004-alembic-migrations.md) | SQLAlchemy Core + Alembicによるマイグレーション方針 |
| [`docs/decisions/005-uvicorn-supercronic-jobs.md`](decisions/005-uvicorn-supercronic-jobs.md) | Uvicorn worker数とsupercronicによる定期ジョブ実行方針 |
| [`docs/decisions/006-like-count-cache-strategy.md`](decisions/006-like-count-cache-strategy.md) | 匿名いいね数のHTML埋め込み・キャッシュ方針 |
| [`docs/decisions/007-python-sqlite-runtime.md`](decisions/007-python-sqlite-runtime.md) | Python標準sqlite3・FTS5の採用とCI検証方針 |
| [`docs/decisions/008-url-compatibility.md`](decisions/008-url-compatibility.md) | 現行URL・リダイレクト・canonicalの互換方針 |
| [`docs/decisions/009-quote-display-language.md`](decisions/009-quote-display-language.md) | 名言レコードごとの主表示言語とfallback仕様 |
| [`docs/decisions/010-random-page-cache.md`](decisions/010-random-page-cache.md) | `/random`の現行機能維持とno-store方針 |
| [`docs/decisions/011-sqlite-datetime-format.md`](decisions/011-sqlite-datetime-format.md) | SQLiteに保存する時点データの固定長UTC形式 |
| [`docs/decisions/012-admin-auth-cloudflare-access.md`](decisions/012-admin-auth-cloudflare-access.md) | Cloudflare Access・外部IdP・MFAによる管理者認証 |
| [`docs/decisions/013-cloudflare-tunnel-origin-protection.md`](decisions/013-cloudflare-tunnel-origin-protection.md) | Cloudflare Tunnel・Fly公開入口削除によるオリジン保護 |

本計画書はこれらを束ねる上位文書。高レベルの確定事項は本計画書、各方式の実装・運用詳細は対応するADRを正本とし、矛盾を見つけた場合は双方を更新する。

---

## 1. 目的・背景

- 現行 **Vercel（サーバーレス）+ Supabase(PostgreSQL/PGroonga)** 構成を、**Fly.io + FastAPI + HTMX + SQLite** の**永続VPS型・SSR**構成へ作り変える。
- **狙い**
  - **運用コスト削減**: DBサーバープロセス不要・SQLiteファイル1個で完結。Supabase 従量課金からの脱却。
  - **表示の高速化・オリジン負荷削減**: Cloudflare エッジキャッシュ + SSR で TTFB 短縮（決定記録001の期待効果）。
  - **デザイン一新**: HTMX ベースの軽量 SSR で UI を刷新。
  - **アーキテクチャの単純化**: サーバーレス制約（読み取り専用FS・拡張ロード不可）から解放され、SQLite書き込み/FTS5/移行スクリプトが素直に動く。

## 2. 確定事項（前提）

| 項目 | 決定 |
|---|---|
| ホスティング | **Fly.io**（東京 `nrt`） |
| アプリ | **FastAPI + Uvicorn**（SSR、Jinja2 テンプレート） |
| フロント | **HTMX**（+ 最小限のCSS/JS。SPAフレームワークは使わない） |
| DB | **SQLite**（`/data` ボリューム、WALモード） |
| 永続化・バックアップ | **単一Machine + Fly Volume**。Online Backup APIで日次バックアップを作りR2へ保存。Fly snapshotは二次復旧手段 |
| マイグレーション | **SQLAlchemy Core + Alembic**（手書きrevision中心） |
| アプリプロセス | 初期は **Uvicorn 1 worker**。全定期ジョブは **supercronic** で分離実行 |
| CDN/WAF | **Cloudflare**（無料プラン想定、エッジキャッシュ・Bot対策） |
| 開発言語 | Python（3.12系想定） |
| 公開オリジン | **`https://www.meigensyu.com/`**（既存ドメインを段階リリース後に切替） |

> ⚠️ パージ運用等は **未決**。第7章「検討事項」で扱う。管理者認証を含む確定事項の詳細は対応するADRを正本とする。

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

1. **日本語全文検索**（名言・著者）— PGroonga相当を SQLite **FTS5 + アプリ側bigram（方式B・確定）** で再現（第7章・決定記録002）
2. **匿名いいね**（`quote_likes`：client_uuid + ip_hash、重複抑制）
   - ⚠️ **本サイト唯一の「公開ユーザー書き込み」**。§4・§9の「書き込みはAdminのみ」の**明示的な例外**。専用の書き込みエンドポイントを設け、レート制限・Origin/CSRF対策・多重投票抑制を必須とする（D9）。
   - `client_uuid` は現行同様 localStorage 管理を基本とし、公開ページにユーザー識別Cookieを載せない（エッジキャッシュと両立させるため）。
   - ✅ いいね数は名言詳細・一覧のSSR HTMLへ焼き込み、10分TTLで自然更新する。毎PVのGET/断片APIと、いいねごとのキャッシュパージは行わない。POSTした本人のDOMだけ応答で即時更新する（D9/ADR 006）。
3. **ランキング**（名言/著者/カテゴリ、いいね数・weight による定期再計算）
4. **OG画像生成**（`/api/og`：名言・著者向け動的画像）
5. **SEO**（sitemap.xml / robots.txt / 構造化データ / メタタグ / canonical）
6. **広告**（AdSense 配置）
7. **管理画面**（`/admin/*`）— CRUD + 一括登録 + ランキング再計算

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
| `SERIAL` / `BIGSERIAL` | 原則 `INTEGER PRIMARY KEY`。SQLiteの `AUTOINCREMENT` はID再利用を厳密に禁止したいテーブルだけ使う |
| ENUM（`date_precision`, `life_era`） | `TEXT` + `CHECK`制約 |
| `TIMESTAMPTZ` | **固定長UTC `TEXT`**（`YYYY-MM-DDTHH:MM:SS.ffffffZ`）。明示codecで入出力し、別形式を混在させない（D17/ADR 011） |
| `JSONB` | アプリ層でJOIN構築（RPCのJSONB返却は廃止しPython側で組む） |
| `EXCLUDE`制約（生誕国排他） | アプリ層 or 部分UNIQUEインデックスで代替 |
| RLS / `is_admin()` | 書き込みは原則Admin経路のみ（アプリ層で担保）。**例外は匿名いいねの専用書き込み経路のみ**（§3.2-2 / D9） |
| PGroongaインデックス | FTS5仮想テーブル + アプリ側bigram（方式B・第7章） |
| マテビュー/集計ビュー | SQLiteでは通常テーブル + 定期再計算バッチ、またはリアルタイムSQLへ置換。小規模データのためフェーズ1で削除可能性を判定 |
| RPC（`get_quote_rankings` 等） | FastAPIサービス層のSQL関数に移植 |

### 対象テーブル一覧（移行必須）
20テーブル:

`authors` / `sources` / `source_types` / `source_type_assignments` / `characters` / `quotes` / `categories` / `professions` / `author_professions` / `countries` / `author_country` / `quote_categories` / `quote_likes` / `legacy_votes` / `ranking_parameters` / `quote_ranking_scores` / `author_rankings` / `category_rankings` / `ranking_refresh_logs` / `admin_users`

### 集計ビュー・マテビュー・RPC移植対象

現行の集計ビュー/MVは次を棚卸し対象に含める。ただし全てをそのまま移植するのではなく、SQLite上でリアルタイムSQLに置換できるかをフェーズ1で判定する。

- `categories_with_counts`（現行は最終的にMV）
- `quote_ranking_scores_mv`（ランキング計算。`legacy_votes` を加算）
- `characters_with_quote_counts`
- `country_author_counts`
- `profession_author_counts`
- `view_admin_kpi_counts`
- `view_admin_ranking_refresh_logs`

`pg_cron` の少なくとも2ジョブ（ランキング、カテゴリ件数）は、バックアップを含む全定期処理とともにsupercronicからCLIとして実行する。初期はUvicorn 1 workerとし、FastAPI startup/lifespanではスケジューラを起動しない。全ジョブに多重起動ロック・timeout・失敗通知を設ける（D6/ADR 005）。

> データ規模（決定記録002）: 名言 約2,100件・著者 約890件・全体 約3,000行と**小規模**。移行・検索性能上の懸念は小さい。

### 移行スクリプト
- Supabase(PostgreSQL) から `pg_dump` / CSVエクスポート → 変換 → SQLite投入するビルドスクリプトを用意。
- 投入時に**検索用bigram列/FTS5テーブルを派生生成**（方式B確定・決定記録002）。
- 元テキスト（`text` / `text_en` / `context_note`）は原本保持。

## 5. アーキテクチャ（決定記録001の要約）

```
[User/Bot] → [Cloudflare CDN+WAF] → [Cloudflare Tunnel] → [Fly.io FastAPI+Uvicorn] → [SQLite (/data)]
```

- **キャッシュ**: パスごとに `Cache-Control` をMiddlewareで一元管理。`/search`、`/admin`とその全配下、`/login`は `private, no-store`。公開ページは `s-maxage` を長め・`max-age` を短めに。
  - ⚠️ **HTMLはCloudflareのデフォルトでキャッシュされない**（拡張子ベースでCSS/JS/画像のみ）。`Cache-Control` を返すだけでは不十分で、**公開HTMLパスに Cache Rules で「Eligible for cache（Cache Everything相当）」を明示**する必要がある。Cache Rules は **last matching rule wins（最後にマッチしたルールが勝つ）** のため、`/admin`・`/admin/*`・`/login`・`/search*`・`/random`・`/api/likes/*`・`/healthz` のBypassルールは、公開HTMLのEligibleルールより**後（下）**に配置する。詳細は決定記録001 §8。
- **パージ**: Admin更新時に Cloudflare API で該当URL/タグ/プレフィックスをパージ。
  - ✅ **Cloudflare Free でも利用可能な方式**（公式ドキュメント「Purge cache」Availability and limits, 2026-04-16更新で確認）: **URL / Hostname / Tag / Prefix / Purge Everything すべて Free で使える**（旧記述「タグ/prefixはEnterprise限定」は誤りのため訂正）。
  - ⚠️ **Free のレート制限**: Tag/Prefix/Hostname/Purge Everything は **5リクエスト/分・1リクエスト最大100オペレーション**（バケット25）。URL単位パージは別枠で上限が高く **800 URLs/秒・1リクエスト最大100URL**（Free）。→ **一括登録など短時間の大量更新でタグ/prefixを多用すると 5/分 に当たる**点が実運用上の論点。
  - **列挙が必要な派生URL（URLパージ採用時）**: 一覧の**全ページングURL**（`/quotes/page/N`, 著者/カテゴリ/出典の各ページ）、`/quotes/latest*`、`/ranking`、`/`、該当**OG画像** `/api/og?...`、`/sitemap.xml`。
  - **方針（D12）**: **個別詳細ページ・OGは高上限のURLパージで即時反映**。一覧/著者/カテゴリ/ランキング等の広範な無効化は、`Cache-Tag` を付与して**タグパージ**（例 `quotes-list`, `author-123`）でまとめて落とす選択肢が Free でも取れる。ただし **5リクエスト/分**の制約に収まるようバッチ集約する。制約に収まらない範囲は**短めTTL（`s-maxage`）で自然失効に委任**。URLパージ／タグパージ／TTL委任の**使い分け境界**を実装前に確定する。
  - **いいね数**: 名言詳細・一覧HTMLへ焼き込み、10分TTLで自然更新する。毎PVのGET APIといいねごとのパージは行わない（D9/ADR 006）。
- **オリジン保護**: Cloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除する。Uvicornはloopbackだけにbindし、Tunnel routeとFastAPIの両方で`www.meigensyu.com`を完全一致で許可する。AOP、CF IP allowlist、独自secret headerは併用しない（D14/ADR 013）。管理画面ではD3/ADR 012のAccess JWT検証も維持する。
- **IP取得**: Tunnel経由の公開書き込みでは `CF-Connecting-IP` を信頼する。匿名いいねPOSTでは単一かつ妥当なIPv4/IPv6だけを受け入れ、`X-Forwarded-For`等へfallbackしない。同一zoneのWorkerをoriginへのsubrequestに使う場合は再評価する。
- **ETag/304**: 名言・著者ページは関連データを含む合成HTMLのため、単一行の `updated_at` から独自ETagを生成しない。TTLとAdmin更新時のパージで更新する。
- **セキュリティヘッダ**: CSP / nosniff / Referrer-Policy 等（決定記録001 §11）。
- 詳細な Cache-Control 表・パージ対象表・fly.toml・Dockerfile要点は決定記録001を参照。
  - ⚠️ 決定記録001 §4.1 の `CACHE_RULES` サンプルは、先頭キー `/` が `startswith` で**全パスにマッチ**してしまう。実装時は**最長prefix優先**（キーを長さ降順で評価）または正規表現ルールに直すこと（決定記録001 側に注記済み）。

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
├── scripts/                   # 移行・bigram生成・ランキング再計算・sitemap生成
├── migrations/                # Alembic revision（FTS5等は手書き）
├── tests/
├── Dockerfile
├── fly.toml
└── docs/
```

- **テンプレート**: `base.html` + 部分テンプレート。HTMX は検索・いいね・一覧の追加読込など**部分更新**に限定利用。
- **サービス層**: 旧 Supabase RPC のロジック（ランキング取得・ランダム・出典集計・著者一覧）をSQLへ移植。JSONBはPython辞書で構築。

## 7. 検討事項（未決論点＝プロジェクト開始前に決めること）

| # | 論点 | 選択肢 | 推奨/メモ |
|---|---|---|---|
| D1 | **検索方式** | ~~D: `LIKE '%語%'`~~ / **B: FTS5+アプリ側bigram** | ✅**確定: 初期からB**（2026-07-01決定）。PGroonga相当の精度・bm25ランキングを再現。移行スクリプトにbigram列/FTS5生成を含める。将来Dへ退行しない |
| D2 | **SQLite永続化・バックアップ・復旧** | 単一Machine + 日次オンラインバックアップ | ✅**確定（2026-07-13）**: LiteFS/Litestreamは採用しない。Online Backup APIで日次バックアップをR2へ保存し、Fly snapshotを二次復旧手段とする。正常時RPO約24時間、手動復旧（詳細はADR 003） |
| D3 | **管理者認証** | Cloudflare Access + 外部IdP + independent MFA | ✅**確定（2026-07-14）**: `/admin`と全配下をAccessで保護し、管理者emailを完全一致で許可。IdPの種類にかかわらずAccess independent MFAを必須とし、passkey/biometrics/FIDO2を優先。FastAPIでもAccess JWTを検証し、`admin_users`でrole・有効状態を認可。Basic認証・アプリ独自パスワード・メールOTP単独は不採用（ADR 012） |
| D4 | **マイグレーション管理** | SQLAlchemy Core + Alembic | ✅**確定（2026-07-13）**: autogenerateは下書き、FTS5・トリガー・ビュー・データ変換は手書きrevision。SQLite変更はbatch migration（ADR 004） |
| D5 | **OG画像生成** | Pillow / Playwright / satori相当 | 常駐メモリと相談。事前生成（ビルド時）＋キャッシュも検討 |
| D6 | **worker数・定期ジョブ実行** | Uvicorn + supercronic | ✅**確定（2026-07-13）**: 初期は1 worker。全定期処理はsupercronicから単一実行し、負荷観測後にHTTP workerだけ2へ増やす（ADR 005） |
| D7 | **SQLiteバージョン/FTS5** | Python標準`sqlite3` | ✅**確定（2026-07-13）**: 標準`sqlite3`を採用し、最終Dockerイメージ上でFTS5・`unicode61`・WAL・Online Backup API・AlembicをCI検証する。失敗時の代替DBAPIは別途評価（ADR 007） |
| D8 | **デザイン刷新の範囲** | 全面刷新 / 現行トーン踏襲 | 「デザイン一新」の具体要件を別途デザインガイドで定義 |
| D9 | **いいね（公開書き込み）の設計・多重対策** | HTML焼き込み + 専用POST + best-effort重複抑制 | 🟡**表示方式は確定（2026-07-13）**: 詳細・一覧HTMLへ件数を含め10分TTL。毎PV GETなし。POSTはno-storeで本人だけ即時更新。保持期間・salt rotation・閾値・Turnstile条件は要決定（ADR 006） |
| D10 | **URL互換性** | 現行URL・意味・canonicalを完全維持 | ✅**確定（2026-07-13）**: 静的301 **23本** + middlewareの `/quotations/view/[id].html` 動的301を含め、path/query/末尾slash/page/1/404をURL契約として移植・比較検証する（ADR 008） |
| D11 | **多言語/表示言語** | 名言レコードごとの主表示言語 | ✅**確定（2026-07-13）**: `display_language_preference`は閲覧者設定ではなく名言の主表示言語。`ja|en`、既定`ja`、指定側欠損時は他方へfallback。物理列名は維持する（ADR 009） |
| D12 | **キャッシュパージの使い分け** | URLパージ / タグ・prefixパージ / 短TTL委任 | **Freeでも URL/Tag/Prefix/全パージ可**（2025-04開放）。URLは800/秒・100/req、Tag/Prefixは**5req/分・100ops/req**。詳細＝URL即時、広範＝タグ（バッチ集約）、収まらない分＝短TTL。**タグ名は短い小文字ASCII**（スペース不可・合計16KB上限）で統一（§5） |
| D13 | **`/random` のキャッシュ方針** | 現行20件一覧 + `private, no-store` | ✅**確定（2026-07-13）**: 現行のランダム20件一覧・シャッフル・canonicalを維持し、Cloudflareでも明示Bypassする。個別名言への302は機能・SEO変更になるため採用しない（ADR 010） |
| D14 | **オリジン保護** | Cloudflare Tunnel + Fly公開入口削除 + exact Host | ✅**確定（2026-07-14）**: Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除。Uvicornはloopbackだけにbindする。AOP・CF IP allowlist・独自secret headerは不採用。管理画面のAccess JWT検証は維持する（ADR 013） |
| D15 | **検索レート制限** | Cloudflare Rate Limiting + debounce/最小文字数 | 60req/min固定では300ms debounceのインクリメンタル検索と衝突し得る。閾値・debounce・最小文字数をセットで確定 |
| D16 | **CSPとHTMX規約** | `hx-on` 禁止 / hx-csp導入 / `unsafe-eval` 許容 | 原則 `hx-on`、イベントフィルタ、`js:`/`javascript:` 値を使わず、インラインJS禁止CSPと整合させる |
| D17 | **日時のSQLite保存形式** | 固定長UTC `TEXT` | ✅**確定（2026-07-13）**: `YYYY-MM-DDTHH:MM:SS.ffffffZ`へ正規化し、明示serializer/parserを使う。暦日・歴史日付は別規則（ADR 011） |

> 残る未決事項は `docs/decisions/014-...` 以降のADRとして起票し、決定次第この表を更新する。

## 8. 作業フェーズ（WBS / マイルストーン）

### フェーズ0: 準備・意思決定（本計画書の次）
- [ ] 未決論点 D5・D8・D9（残件）・D12・D15・D16 の決定（D3・D14を含む既決事項と、D9表示方式は確定）
- [ ] リポジトリ初期化（git init, Python環境, 依存管理: uv/poetry/pip-tools 選定）
- [ ] デザイン要件定義（D8）

### フェーズ1: 基盤構築
- [ ] FastAPIスケルトン + Jinja2 + 静的配信
- [ ] SQLiteスキーマ定義（PG→SQLite変換）＋ マイグレーション基盤（D4）
- [ ] キャッシュ/セキュリティ Middleware（決定記録001 §4, §11）
- [ ] `/healthz`

### フェーズ2: データ移行
- [ ] Supabase→SQLite 移行スクリプト（bigram/FTS5生成込み・D1）
- [ ] `legacy_votes`・集計ビュー/MV・RPC群を含む移行対象の完全リスト化
- [ ] 移行データの整合性検証（件数・関連・文字化け）

### フェーズ3: 公開ページ実装
- [ ] 一覧/詳細（quotes, authors, categories, characters, sources, professions）
- [ ] トップ・ランキング・ランダム
- [ ] 検索（HTMXインクリメンタル・D1）
- [ ] いいね（D9）
- [ ] SEO（sitemap/robots/構造化データ/canonical）
- [ ] URL互換リダイレクト（静的301 23本 + `/quotations/view/[id].html` 動的301 + URL契約表に基づく正規化）
- [ ] OG画像（D5）
- [ ] 広告配置

### フェーズ4: 管理画面
- [ ] Cloudflare Access JWT検証・`admin_users`認可（D3/ADR 012）+ CSRF
- [ ] 各エンティティCRUD
- [ ] 一括登録（quotes/authors bulk）
- [ ] ランキング再計算（D6）
- [ ] Cloudflareパージ連携

### フェーズ5: デプロイ・インフラ
- [ ] Dockerfile / fly.toml / ボリューム
- [ ] 日次SQLiteオンラインバックアップ、R2 Lifecycle、失敗通知（D2/ADR 003）
- [ ] Fly Volume snapshot保持設定、復旧runbook、月次復元演習（D2/ADR 003）
- [ ] Cloudflare（DNS/SSL/Cache Rules/WAF）
- [ ] Cloudflare Tunnel同居、Uvicorn loopback bind、Fly public IP/service削除、exact Host検証（D14/ADR 013）
- [ ] no-store/Bypassの`/healthz`外形監視、デプロイ後smoke test、Tunnel/token漏洩時runbook（D14/ADR 013）
- [ ] CI/CD（GitHub Actions → flyctl deploy）
- [ ] 監視（Flyメトリクス/UptimeRobot）・バックアップ

### フェーズ6: 段階リリース（決定記録001 §12・ADR 013）
- [ ] `new.` サブドメインで並行稼働・検証
- [ ] `new.` サブドメインは `noindex` / robots deny を有効化
- [ ] 検証環境の許可Host/`PUBLIC_ORIGIN`を`new.meigensyu.com`に限定し、`/admin*`用の一時Access applicationを本番同等ポリシーで設定して固有のaudienceを`CF_ACCESS_AUD`に設定する
- [ ] DNS切替直前の差分再移行、または旧環境の書き込み凍結を実施
- [ ] キャッシュヘッダ検証（`curl -I`、`cf-cache-status: HIT`）
- [ ] 許可Host/`PUBLIC_ORIGIN`を`www.meigensyu.com`へ、`CF_ACCESS_AUD`を本番Access applicationのaudienceへ変更してデプロイする
- [ ] DNS切替（TTL事前短縮）
- [ ] `www`切替後に公開ページと管理画面の正常性を確認し、`new.`のTunnel routeと一時Access applicationを削除する
- [ ] 旧環境1〜2週間維持後に廃止

## 9. リスクと対策

| リスク | 対策 |
|---|---|
| 日本語検索精度の劣化（特に2文字語） | **方式B（FTS5+bigram）を確定採用**しPGroonga相当を再現（D1）。trigram単体は不採用（決定記録002） |
| SQLite書き込み競合 | 書き込みは原則Admin・WAL・`busy_timeout`。**匿名いいねのみ公開書き込み**だが低頻度・単純INSERTで競合影響は限定的（§3.2-2/D9） |
| 定期ジョブの二重実行・部分更新 | FastAPI内でスケジュールせずsupercronicへ分離。`flock`、timeout、失敗通知、単一transactionで前回正常結果を保持（D6/ADR 005） |
| いいね取得が全PVでオリジン到達 | 件数を詳細・一覧HTMLへ含め10分キャッシュ。毎PV GET APIを作らず、POSTした本人だけ即時更新（D9/ADR 006） |
| 単一マシン/Volume障害 | R2の日次バックアップから手動復旧。Fly snapshotは二次手段。正常時も最大約24時間の更新欠損を許容し、ジョブ失敗・未検知時はRPO超過となるため最新成功時刻を監視（D2/ADR 003） |
| 稼働中SQLiteの不整合バックアップ | 単純なファイルコピーを禁止し、Online Backup APIで一貫したスナップショットを作成。`integrity_check`とSHA-256を検証（D2/ADR 003） |
| URL変更によるSEO低下 | URL互換維持＋301リダイレクト（D10） |
| OG画像/ランキングのメモリ負荷 | 事前生成・キャッシュ・軽量ライブラリ選定（D5/D6） |
| 移行時のデータ欠損/文字化け | 件数・関連・サンプル比較の検証スクリプト |
| 管理画面のセキュリティ | Cloudflare Access + 外部IdP + Access independent MFA、FastAPIでのJWT検証、`admin_users`認可、CSRF、no-store（D3/ADR 012）。接続元IP固定は前提にしない |
| Cloudflare迂回によるWAF/IP制限バイパス | Cloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除。exact Hostも検証（D14/ADR 013） |
| `/random` がエッジキャッシュされ固定化 | 現行20件一覧を`private, no-store`とし、Cloudflare Cache Rulesでも明示Bypass（D13/ADR 010） |
| 段階リリース中のデータ差分 | 切替直前の差分再移行または書き込み凍結をフェーズ6に組み込む |

## 10. 環境変数（初期案・決定記録001 §10）

| 変数 | 用途 |
|---|---|
| `DATABASE_URL` | SQLite絶対パス（例 `sqlite:////data/app.db`） |
| `PUBLIC_ORIGIN` | 環境ごとの公開オリジン。本番は`https://www.meigensyu.com`（末尾slashなし） |
| `CF_ZONE_ID` / `CF_API_TOKEN` | Cloudflareキャッシュパージ |
| `TUNNEL_TOKEN` | remotely-managed Cloudflare Tunnelのconnector token（Fly secret） |
| `CF_ACCESS_TEAM_DOMAIN` / `CF_ACCESS_AUD` | Cloudflare Access JWTのissuer・管理画面application audience検証 |
| `SECRET_KEY` | CSRF token等のアプリ署名（管理者パスワードやAccess JWT署名には使わない） |
| `RANKING_IP_HASH_SALT` | 匿名いいねの `ip_hash` 生成 |
| `NEXT_PUBLIC_GA_ID` | GA4（採用時） |
| `NEXT_PUBLIC_ADSENSE_PUBLISHER_ID` | AdSense（採用時。`ads.txt` 相当も移植） |
| `BACKUP_R2_ENDPOINT` / `BACKUP_R2_BUCKET` / `BACKUP_R2_PREFIX` | 日次SQLiteバックアップの保存先（prefix初期値: `daily/`） |
| `BACKUP_R2_ACCESS_KEY_ID` / `BACKUP_R2_SECRET_ACCESS_KEY` | バックアップ専用バケットだけに限定した資格情報 |

## 11. 検収チェックリスト（抜粋・決定記録001 §14）

- [ ] 公開ページ2回目アクセスで `cf-cache-status: HIT`
- [ ] `/search`・`/admin`とその全配下・`/login` が `private, no-store`
- [ ] `/admin/*`でAccess JWTの署名・issuer・audience・期限と`admin_users`のrole・有効状態を検証し、直アクセス・偽造JWTを403にできる
- [ ] 2文字検索（例「人生」）が正しくヒット
- [ ] Admin更新後に該当URLがパージされ最新反映
- [ ] SQLiteがWALで稼働し、`/healthz`がno-store/Bypassで200を返し、外形監視とデプロイ後smoke testがorigin停止を検知する
- [ ] Uvicorn 1/2 workerのどちらでも各定期ジョブが1回だけ動き、supercronic停止・timeout・失敗を検知できる
- [ ] 名言詳細・一覧が10分TTLでHITし、いいねPOSTがno-store/Bypass、GETが405になる
- [ ] 毎日03:30 JSTまでに当日分がR2に存在し、最新成功から25時間を超えた場合または失敗を検知・通知できる
- [ ] R2バックアップからの復元演習が成功し、`integrity_check`・Alembic revision・主要件数が一致する
- [ ] 空DBと本番相当DBの両方で `alembic upgrade head` が成功する
- [ ] 主要現行URLが200 or 301で到達（SEO互換）
- [ ] Flyにpublic IP/serviceがなく`*.fly.dev`から到達不能で、Tunnel routeとFastAPIが`www.meigensyu.com`だけを許可する
- [ ] 匿名いいねPOSTが不正な`CF-Connecting-IP`を拒否し、`cloudflared`停止時に迂回経路がない

## 12. 次のアクション

1. 本計画書レビュー・合意
2. 未決論点 **D9の保持期間/不正対策閾値・D12（パージ境界）** を優先決定しADR化（D3管理者認証はADR 012、D14オリジン保護はADR 013で確定済み）
3. リポジトリ初期化 → フェーズ1着手
