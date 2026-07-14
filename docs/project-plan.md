# 名言集.com リニューアル計画書（meigen-fly）

> 本ドキュメントはプロジェクトの**土台となる計画書**。全体像・確定事項・検討事項（未決論点）・想定作業を俯瞰する。
> 詳細な技術判断は `docs/decisions/` 配下の決定記録に切り出す。
>
> - 作成日: 2026-07-01
> - 更新日: 2026-07-14（個人開発・閲覧主体の前提でD1・D2・D3・D6・D9・D12・D16を簡略化）
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

本計画書はこれらを束ねる上位文書。高レベルの確定事項は本計画書、各方式の実装・運用詳細は対応するADRを正本とし、矛盾を見つけた場合は双方を更新する。

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
| 開発言語 | Python（3.12系想定） |
| 公開オリジン | **`https://www.meigensyu.com/`**（既存ドメインを段階リリース後に切替） |

> キャッシュパージ、検索レート制限、CSP/HTMXを含む確定事項の詳細は対応するADRを正本とする。残る未決論点は第7章のD5・D8である。

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
2. **匿名いいね**（`quote_likes`：client_uuid + ip_hash、重複抑制）
   - ⚠️ **本サイト唯一の「公開ユーザー書き込み」**。§4・§9の「書き込みはAdminのみ」の**明示的な例外**。専用の書き込みエンドポイントを設け、レート制限・Origin/CSRF対策・多重投票抑制を必須とする（D9）。
   - `client_uuid`は現行同様localStorage管理とし、アプリ独自の識別Cookieを公開HTMLへ使わない。GA4 cookieはADR 016の同意後だけ許可するが、HTML生成・cache key・cache可否には使わない。
   - ✅ いいね数は名言詳細・一覧のSSR HTMLへ焼き込み、10分TTLで自然更新する。毎PVのGET/断片APIと、いいねごとのキャッシュパージは行わない。POSTした本人のDOMだけ応答で即時更新する（D9/ADR 006）。
3. **ランキング**（名言/著者/カテゴリ、いいね数・weight による定期再計算）
4. **OG画像生成**（`/api/og`：名言・著者向け動的画像）
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
| `SERIAL` / `BIGSERIAL` | 原則 `INTEGER PRIMARY KEY`。SQLiteの `AUTOINCREMENT` はID再利用を厳密に禁止したいテーブルだけ使う |
| ENUM（`date_precision`, `life_era`） | `TEXT` + `CHECK`制約 |
| `TIMESTAMPTZ` | **固定長UTC `TEXT`**（`YYYY-MM-DDTHH:MM:SS.ffffffZ`）。明示codecで入出力し、別形式を混在させない（D17/ADR 011） |
| `JSONB` | アプリ層でJOIN構築（RPCのJSONB返却は廃止しPython側で組む） |
| `EXCLUDE`制約（生誕国排他） | アプリ層 or 部分UNIQUEインデックスで代替 |
| RLS / `is_admin()` | 書き込みは原則Admin経路のみ（アプリ層で担保）。**例外は匿名いいねの専用書き込み経路のみ**（§3.2-2 / D9） |
| PGroongaインデックス | 初期は`LIKE`部分一致。検索インデックスは性能上必要になった場合だけ追加（第7章） |
| マテビュー/集計ビュー | SQLiteでは通常テーブル + 定期再計算バッチ、またはリアルタイムSQLへ置換。小規模データのためフェーズ1で削除可能性を判定 |
| RPC（`get_quote_rankings` 等） | FastAPIサービス層のSQL関数に移植 |

### 対象テーブル一覧
アプリデータとして移行する19テーブル:

`authors` / `sources` / `source_types` / `source_type_assignments` / `characters` / `quotes` / `categories` / `professions` / `author_professions` / `countries` / `author_country` / `quote_categories` / `quote_likes` / `legacy_votes` / `ranking_parameters` / `quote_ranking_scores` / `author_rankings` / `category_rankings` / `ranking_refresh_logs`

既存の`admin_users`は初期認証に利用せず、移行必須対象から除外する。将来、複数管理者の権限差が必要になった場合に、ADR 012に従って新しい認可モデルとして再設計する。

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
- 検索用の派生bigram列やFTS5テーブルは初期生成しない（決定記録002）。
- 元テキスト（`text` / `text_en` / `context_note`）は原本保持。

## 5. アーキテクチャ（決定記録001の要約）

```
[User/Bot] → [Cloudflare CDN+WAF] → [Cloudflare Tunnel] → [Fly.io FastAPI+Uvicorn] → [SQLite (/data)]
```

- **キャッシュ**: パスごとに `Cache-Control` をMiddlewareで一元管理。`/search`、`/admin`とその全配下、`/login`は `private, no-store`。公開ページは `s-maxage` を長め・`max-age` を短めに。
  - ⚠️ **HTMLはCloudflareのデフォルトでキャッシュされない**（拡張子ベースでCSS/JS/画像のみ）。`Cache-Control` を返すだけでは不十分で、**公開HTMLパスに Cache Rules で「Eligible for cache（Cache Everything相当）」を明示**する必要がある。Cache Rules は **last matching rule wins（最後にマッチしたルールが勝つ）** のため、`/admin`・`/admin/*`・`/login`・`/search*`・`/random`・`/api/likes/*`・`/healthz` のBypassルールは、公開HTMLのEligibleルールより**後（下）**に配置する。詳細は決定記録001 §8。
- **パージ**: Admin更新時に Cloudflare API で該当URL/タグをパージする。通常処理ではPrefix/Purge Everythingを使わない（D12/ADR 014）。
  - ✅ **Cloudflare Free でも利用可能な方式**（公式ドキュメント「Purge cache」Availability and limits, 2026-04-16更新で確認）: **URL / Hostname / Tag / Prefix / Purge Everything すべて Free で使える**（旧記述「タグ/prefixはEnterprise限定」は誤りのため訂正）。
  - ⚠️ **Free のレート制限**: Tag/Prefix/Hostname/Purge Everything は **5リクエスト/分・1リクエスト最大100オペレーション**（バケット25）。URL単位パージは別枠で上限が高く **800 URLs/秒・1リクエスト最大100URL**（Free）。→ **一括登録など短時間の大量更新でタグ/prefixを多用すると 5/分 に当たる**点が実運用上の論点。
  - **方針（D12/ADR 014）**: 管理更新後に少数の関連URLまたは集合タグを同期パージする。失敗時は管理者へ表示してログへ残し、TTLによる自然失効へ委任する。outbox、自動retry、非同期flusherは作らない。
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
├── scripts/                   # 移行・ランキング再計算・sitemap生成
├── migrations/                # Alembic revision
├── tests/
├── Dockerfile
├── fly.toml
└── docs/
```

- **テンプレート**: `base.html` + 部分テンプレート。HTMX は検索・いいね・一覧の追加読込など**部分更新**に限定利用。
- **サービス層**: 旧 Supabase RPC のロジック（ランキング取得・ランダム・出典集計・著者一覧）をSQLへ移植。JSONBはPython辞書で構築。

## 7. 設計判断（確定事項と残る未決論点）

| # | 論点 | 選択肢 | 推奨/メモ |
|---|---|---|---|
| D1 | **検索方式** | `LIKE '%語%'` | ✅**確定（2026-07-14改訂）**: 約3,000行では単純な部分一致で十分。FTS5/bigramは実測上の問題が出た場合だけ再検討（ADR 002） |
| D2 | **SQLite永続化・バックアップ・復旧** | 単一Machine + 日次オンラインバックアップ | ✅**確定（2026-07-14簡略化）**: Online Backup APIで日次バックアップをR2へ保存し、30日Lifecycleと失敗通知を設定。追加snapshot、Bucket Lock、月次演習は必須としない（ADR 003） |
| D3 | **管理者認証** | Cloudflare Access + 外部IdP | ✅**確定（2026-07-14簡略化）**: 管理者emailを完全一致で許可し、IdP側MFAを利用。FastAPIでもAccess JWTを最小限検証する。単一管理者の初期段階ではアプリ内role・identity表・独自復旧CLIを作らない（ADR 012） |
| D4 | **マイグレーション管理** | SQLAlchemy Core + Alembic | ✅**確定（2026-07-13）**: autogenerateは下書きとし、必要なトリガー・ビュー・データ変換は手書きrevision。SQLite変更はbatch migration（ADR 004） |
| D5 | **OG画像生成** | Pillow / Playwright / satori相当 | 常駐メモリと相談。事前生成（ビルド時）＋キャッシュも検討 |
| D6 | **worker数・定期ジョブ実行** | Uvicorn + supercronic | ✅**確定（2026-07-14簡略化）**: 初期は1 worker。定期処理はsupercronicからCLI実行し、ジョブ別`flock`とtimeoutを使う。独自status APIや共有maintenance lockは作らない（ADR 005） |
| D7 | **SQLiteランタイム** | Python標準`sqlite3` | ✅**確定（2026-07-14改訂）**: WAL・Online Backup API・foreign key・Alembicをスモークテスト。FTS5は初期必須条件にしない（ADR 007） |
| D8 | **デザイン刷新の範囲** | 全面刷新 / 現行トーン踏襲 | 「デザイン一新」の具体要件を別途デザインガイドで定義 |
| D9 | **いいね（公開書き込み）の設計・多重対策** | HTML焼き込み + 専用POST + best-effort重複抑制 | ✅**確定（2026-07-14簡略化）**: `(quote_id, client_uuid)`一意制約と単純な短時間IP制限だけを初期導入。IP hash、鍵ローテーション、複合bucket、日次不正集計は作らない（ADR 006） |
| D10 | **URL互換性** | 現行URL・意味・canonicalを完全維持 | ✅**確定（2026-07-13）**: 静的301 **23本** + middlewareの `/quotations/view/[id].html` 動的301を含め、path/query/末尾slash/page/1/404をURL契約として移植・比較検証する（ADR 008） |
| D11 | **多言語/表示言語** | 名言レコードごとの主表示言語 | ✅**確定（2026-07-13）**: `display_language_preference`は閲覧者設定ではなく名言の主表示言語。`ja|en`、既定`ja`、指定側欠損時は他方へfallback。物理列名は維持する（ADR 009） |
| D12 | **キャッシュ更新反映** | 同期パージ + TTL委任 | ✅**確定（2026-07-14簡略化）**: 更新後に少数のURL/集合タグを同期パージし、失敗時はログと管理者表示を残してTTLを待つ。outboxと自動retryは作らない（ADR 014） |
| D13 | **`/random` のキャッシュ方針** | 現行20件一覧 + `private, no-store` | ✅**確定（2026-07-13）**: 現行のランダム20件一覧・シャッフル・canonicalを維持し、Cloudflareでも明示Bypassする。個別名言への302は機能・SEO変更になるため採用しない（ADR 010） |
| D14 | **オリジン保護** | Cloudflare Tunnel + Fly公開入口削除 + exact Host | ✅**確定（2026-07-14）**: Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除。Uvicornはloopbackだけにbindする。AOP・CF IP allowlist・独自secret headerは不採用。管理画面のAccess JWT検証は維持する（ADR 013） |
| D15 | **検索レート制限** | 1文字検索 + 500ms debounce + アプリ側IP制限 | ✅**確定（2026-07-14）**: 1文字検索を許可し、IME対応の外部静的JSで500ms trailing debounce。アプリを正本に30回/10秒・120回/60秒とする。Cloudflare Freeの1ルールはD9へ優先し、検索ruleは初期配置しない。429では結果を残して待ち時間を案内し、自動再試行しない（ADR 015） |
| D16 | **CSPとHTMX規約** | 共通CSP + HTMX危険機能の無効化 | ✅**確定（2026-07-14簡略化）**: 共通の現実的なCSPを使い、HTMXのeval/script実行を無効化。CSP report endpoint、検索event、GA4/AdSenseの初期必須化は行わない（ADR 016） |
| D17 | **日時のSQLite保存形式** | 固定長UTC `TEXT` | ✅**確定（2026-07-13）**: `YYYY-MM-DDTHH:MM:SS.ffffffZ`へ正規化し、明示serializer/parserを使う。暦日・歴史日付は別規則（ADR 011） |

> 残る未決事項はD5（OG画像生成）とD8（デザイン刷新範囲）。D9・D12・D15・D16は対応ADRを正本として確定済みである。

## 8. 作業フェーズ（WBS / マイルストーン）

### フェーズ0: 準備・意思決定（本計画書の次）
- [x] D9・D12・D15・D16の決定とADR化（2026-07-14、ADR 006・014・015・016）
- [ ] 残る未決論点 D5・D8 の決定
- [ ] リポジトリ初期化（git init, Python環境, 依存管理: uv/poetry/pip-tools 選定）
- [ ] デザイン要件定義（D8）

### フェーズ1: 基盤構築
- [ ] FastAPIスケルトン + Jinja2 + 静的配信
- [ ] SQLiteスキーマ定義（PG→SQLite変換）＋ マイグレーション基盤（D4）
- [ ] キャッシュ/セキュリティ Middleware（決定記録001 §4, §11）
- [ ] `/healthz`

### フェーズ2: データ移行
- [ ] Supabase→SQLite 移行スクリプト（検索用派生インデックスは初期不要・D1）
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
- [ ] 日次SQLiteオンラインバックアップ、R2 Lifecycle、失敗通知（D2/ADR 003）
- [ ] R2からの復旧runbookと、リリース前または大きな変更後の復元確認（D2/ADR 003）
- [ ] Cloudflare（DNS/SSL/Cache Rules/WAF）
- [ ] Cloudflare Tunnel同居、Uvicorn loopback bind、Fly public IP/service削除、exact Host検証（D14/ADR 013）
- [ ] no-store/Bypassの`/healthz`外形監視、デプロイ後smoke test、Tunnel/token漏洩時runbook（D14/ADR 013）
- [ ] CI/CD（GitHub Actions → flyctl deploy）
- [ ] 監視（Flyメトリクス/UptimeRobot）・バックアップ

### フェーズ6: 段階リリース（決定記録001 §12・ADR 013）
- [ ] `new.` サブドメインで並行稼働・検証
- [ ] `new.` サブドメインは `noindex` / robots deny を有効化
- [ ] 検証環境を設ける場合は環境全体をAccessで本人だけに制限し、許可Host/`PUBLIC_ORIGIN`を`new.meigensyu.com`に限定する
- [ ] DNS切替直前の差分再移行、または旧環境の書き込み凍結を実施
- [ ] キャッシュヘッダ検証（`curl -I`、`cf-cache-status: HIT`）
- [ ] 許可Host/`PUBLIC_ORIGIN`を`www.meigensyu.com`へ、`CF_ACCESS_AUD`を本番Access applicationのaudienceへ変更してデプロイする
- [ ] DNS切替（TTL事前短縮）
- [ ] `www`切替後に公開ページと管理画面の正常性を確認し、`new.`のTunnel routeと一時Access applicationを削除する
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
| OG画像/ランキングのメモリ負荷 | 事前生成・キャッシュ・軽量ライブラリ選定（D5/D6） |
| 移行時のデータ欠損/文字化け | 件数・関連・サンプル比較の検証スクリプト |
| 管理画面のセキュリティ | Cloudflare Access + 外部IdP側MFA、FastAPIでのJWT検証、CSRF、no-store（D3/ADR 012）。初期は単一管理者を想定 |
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
| `GA_MEASUREMENT_ID` | 本体完成後、GA4を導入する場合だけ設定。未設定時はAnalyticsを無効化 |
| `ADSENSE_PUBLISHER_ID` | 本体完成後、AdSenseを導入する場合だけ設定。未設定時は広告を無効化 |
| `BACKUP_R2_ENDPOINT` / `BACKUP_R2_BUCKET` / `BACKUP_R2_PREFIX` | 日次SQLiteバックアップの保存先（prefix初期値: `daily/`） |
| `BACKUP_R2_ACCESS_KEY_ID` / `BACKUP_R2_SECRET_ACCESS_KEY` | バックアップ専用バケットだけに限定した資格情報 |

## 11. 検収チェックリスト（抜粋・決定記録001 §14）

- [ ] 公開ページ2回目アクセスで `cf-cache-status: HIT`
- [ ] `/search`・`/admin`とその全配下・`/login` が `private, no-store`
- [ ] 共通CSPと基本セキュリティヘッダーが付き、主要な閲覧・検索・管理・HTMX導線が動作する
- [ ] `/admin/*`でAccess JWTの署名・issuer・audience・期限・emailを検証し、直アクセス・偽造JWTを403にできる
- [ ] 2文字検索（例「人生」）が正しくヒット
- [ ] Admin更新後に該当URLがパージされ最新反映
- [ ] SQLiteがWALで稼働し、`/healthz`がno-store/Bypassで200を返し、外形監視とデプロイ後smoke testがorigin停止を検知する
- [ ] 初期構成のUvicorn 1 workerで各定期ジョブが1回だけ動き、supercronic停止・timeout・失敗を検知できる。2 workerへ変更する場合は同じ回帰確認を行う
- [ ] 名言詳細・一覧が10分TTLでHITし、いいねPOSTがno-store/Bypass、GETが405になる
- [ ] 日次バックアップがR2に保存され、失敗を通知できる
- [ ] リリース前または大きな変更後にR2バックアップを復元し、`integrity_check`・Alembic revision・主要件数が一致する
- [ ] 空DBと本番相当DBの両方で `alembic upgrade head` が成功する
- [ ] 主要現行URLが200 or 301で到達（SEO互換）
- [ ] Flyにpublic IP/serviceがなく`*.fly.dev`から到達不能で、Tunnel routeとFastAPIが`www.meigensyu.com`だけを許可する
- [ ] 匿名いいねPOSTが不正な`CF-Connecting-IP`を拒否し、`cloudflared`停止時に迂回経路がない

## 12. 次のアクション

1. 本計画書レビュー・合意
2. 残る未決論点 **D5（OG画像生成）・D8（デザイン刷新範囲）** を決定（D9・D12・D15・D16はADR 006・014・015・016で確定済み）
3. リポジトリ初期化 → フェーズ1着手
