# 名言集.com リニューアル計画書（meigen-fly）

> 本ドキュメントはプロジェクトの**土台となる計画書**。全体像・確定事項・検討事項（未決論点）・想定作業を俯瞰する。
> 詳細な技術判断は `docs/decisions/` 配下の決定記録に切り出す。
>
> - 作成日: 2026-07-01
> - 対象リポジトリ: `/Users/sonoda/prj/meigen-fly`（新規）
> - 移管元: `/Users/sonoda/prj/meigensyu`（Next.js 14 + Supabase、稼働中）

---

## 0. 参照ドキュメント

| ドキュメント | 内容 |
|---|---|
| [`docs/decisions/001-architecture-cloudflare-fly-sqlite.md`](decisions/001-architecture-cloudflare-fly-sqlite.md) | 全体構成・キャッシュ戦略・Cloudflare/Fly.io/SQLite 構成の詳細（確定寄り） |
| [`docs/decisions/002-sqlite-japanese-search.md`](decisions/002-sqlite-japanese-search.md) | 日本語全文検索の方式検討（PGroonga → SQLite FTS5 bigram / LIKE） |

本計画書はこの2つを束ねる上位文書。矛盾が生じた場合は本計画書の「確定事項」を優先し、決定記録を更新する。

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
| CDN/WAF | **Cloudflare**（無料プラン想定、エッジキャッシュ・Bot対策） |
| 開発言語 | Python（3.12系想定） |
| ドメイン | 既存ドメインを最終的に切替（段階リリース） |

> ⚠️ 上記より下流（LiteFS or Litestream、検索方式 B or D、認証方式 等）は **未決**。第7章「検討事項」で扱う。

## 3. スコープ（何を作り変えるか）

### 3.1 移植する公開ページ（現行 `src/app/(site)` より棚卸し）

| パス | 内容 | 備考 |
|---|---|---|
| `/` | トップ（注目名言・ランキング抜粋） | `get_featured_quotes_light` 相当 |
| `/quotes`, `/quotes/page/[n]` | 名言一覧（ページング） | |
| `/quotes/latest`, `/quotes/latest/page/[n]` | 新着名言 | |
| `/quotes/[slugOrQid]` | 名言個別ページ | slug と `qXXXX` 両対応（決定記録: URL構造） |
| `/authors`, `/authors/[slug]/page/[n]` | 著者一覧・詳細 | 職業/国籍/生没年表示 |
| `/authors/places`, `/authors/places/[countrySlug]` | 国別著者 | |
| `/categories`, `/categories/[slug]/page/[n]` | カテゴリ（2階層） | |
| `/characters`, `/characters/[slug]/page/[n]` | 登場人物 | |
| `/professions`, `/professions/[slug]`, `/professions/[slug]/quotes` | 職業 | |
| `/sources`, `/sources/[slug]/page/[n]` | 出典（作品） | 種別フィルタ |
| `/ranking` | ランキング | 名言/著者/カテゴリ |
| `/random` | ランダム名言 | |
| `/search` | 全文検索（**キャッシュ不可**） | HTMXインクリメンタル検索 |
| `/about`, `/privacy`, `/terms` | 静的ページ | Markdown管理 |

### 3.2 移植する主要機能

1. **日本語全文検索**（名言・著者）— PGroonga相当を SQLite **FTS5 + アプリ側bigram（方式B・確定）** で再現（第7章・決定記録002）
2. **匿名いいね**（`quote_likes`：client_uuid + ip_hash、重複抑制）
   - ⚠️ **本サイト唯一の「公開ユーザー書き込み」**。§4・§9の「書き込みはAdminのみ」の**明示的な例外**。専用の書き込みエンドポイントを設け、レート制限・Origin/CSRF対策・多重投票抑制を必須とする（D9）。キャッシュ済みページ上のいいね数は**HTMXで別途取得して差し替える**（ページ本体はキャッシュ、カウントは非キャッシュ経路）
3. **ランキング**（名言/著者/カテゴリ、いいね数・weight による定期再計算）
4. **OG画像生成**（`/api/og`：名言・著者向け動的画像）
5. **SEO**（sitemap.xml / robots.txt / 構造化データ / メタタグ / canonical）
6. **広告**（AdSense 配置）
7. **管理画面**（`/admin/*`）— CRUD + 一括登録 + ランキング再計算

### 3.3 管理画面の対象エンティティ（現行 `src/app/(admin)` より）

quotes / authors / categories / characters / sources / source_types / professions / countries
＋ 一括登録（quotes・authors bulk）＋ ランキング手動再計算 ＋ キャッシュパージ

### 3.4 スコープ外（今回持ち込まない／再検討）

- Supabase Auth（→ 独自の管理者認証に置換。第7章）
- PGroonga（→ SQLite検索に置換）
- Next.js特有の revalidate / ISR（→ Cloudflare パージに置換）
- `pg_cron` / PostgreSQL RPC / RLS（→ アプリ層ロジック + SQLに移植）

## 4. データモデル移行方針

現行スキーマ（`docs/database/schema-design.md` 相当、約20テーブル/ビュー）を SQLite へ写す。**PostgreSQL固有要素の置換**が要点。

| PostgreSQL要素 | SQLiteでの扱い |
|---|---|
| `SERIAL` / `BIGSERIAL` | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| ENUM（`date_precision`, `life_era`） | `TEXT` + `CHECK`制約 |
| `TIMESTAMPTZ` | `TEXT`(ISO8601, UTC) または `INTEGER`(epoch) |
| `JSONB` | アプリ層でJOIN構築（RPCのJSONB返却は廃止しPython側で組む） |
| `EXCLUDE`制約（生誕国排他） | アプリ層 or 部分UNIQUEインデックスで代替 |
| RLS / `is_admin()` | 書き込みは原則Admin経路のみ（アプリ層で担保）。**例外は匿名いいねの専用書き込み経路のみ**（§3.2-2 / D9） |
| PGroongaインデックス | FTS5仮想テーブル + アプリ側bigram（方式B・第7章） |
| マテビュー（ランキング） | 通常テーブル + 定期再計算バッチ |
| RPC（`get_quote_rankings` 等） | FastAPIサービス層のSQL関数に移植 |

### 対象テーブル一覧（移行必須）
`authors` / `sources` / `source_types` / `source_type_assignments` / `characters` / `quotes` / `categories` / `professions` / `author_professions` / `countries` / `author_country` / `quote_categories` / `quote_likes` / `ranking_parameters` / `quote_ranking_scores` / `author_rankings` / `category_rankings` / `ranking_refresh_logs` / `admin_users`

> データ規模（決定記録002）: 名言 約2,100件・著者 約890件・全体 約3,000行と**小規模**。移行・検索性能上の懸念は小さい。

### 移行スクリプト
- Supabase(PostgreSQL) から `pg_dump` / CSVエクスポート → 変換 → SQLite投入するビルドスクリプトを用意。
- 投入時に**検索用bigram列/FTS5テーブルを派生生成**（方式B確定・決定記録002）。
- 元テキスト（`text` / `text_en` / `context_note`）は原本保持。

## 5. アーキテクチャ（決定記録001の要約）

```
[User/Bot] → [Cloudflare CDN+WAF] → [Fly.io FastAPI+Uvicorn] → [SQLite (/data)]
```

- **キャッシュ**: パスごとに `Cache-Control` をMiddlewareで一元管理。`/search` と `/admin/*` は `private, no-store`。公開ページは `s-maxage` を長め・`max-age` を短めに。
- **パージ**: Admin更新時に Cloudflare API で該当URLのみパージ。
  - ⚠️ **Cloudflare Free の制約**: パージは**URL単位（単一ファイル）** と **全パージ（purge_everything）のみ**。**タグパージ／プレフィックスパージは Enterprise 限定で使えない**。したがって「1更新で影響する全URL」を**アプリ側で列挙**する必要がある（決定記録001 §5 のパージ対象表を実URLに展開）。
  - **列挙が必要な派生URL**: 一覧の**全ページングURL**（`/quotes/page/N`, 著者/カテゴリ/出典の各ページ）、`/quotes/latest*`、`/ranking`、`/`、該当**OG画像** `/api/og?...`、`/sitemap.xml`。
  - **割り切り方針（D12）**: 全ページ列挙は非現実的なため、**個別詳細ページ・OGはURL列挙で即時パージ**、**一覧/ランキング/新着は短めTTL（`s-maxage`）で自然失効に委ねる**方針を基本とする。列挙対象とTTL委任対象の境界を実装前に確定する。
  - **いいね数**: ページ本体はキャッシュしたまま、カウントのみ非キャッシュのHTML断片/軽量エンドポイントで取得し差し替える（パージ対象にしない）。
- **ETag/304**: 個別名言・著者は `updated_at` からETag生成。
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
├── migrations/                # スキーマ管理（alembic or 素のSQL）
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
| D2 | **SQLiteレプリカ/永続化** | LiteFS / Litestream / 単一ボリューム | まず**単一マシン+Litestream(R2/S3日次)**で開始、スケール時LiteFS |
| D3 | **管理者認証** | Basic認証 / セッション認証（Cookie） | Admin限定Cookie+IP制限。Supabase Auth廃止に伴う要設計 |
| D4 | **マイグレーション管理** | alembic / 素のSQL + バージョン表 | SQLite規模なら軽量でよい。要決定 |
| D5 | **OG画像生成** | Pillow / Playwright / satori相当 | 常駐メモリと相談。事前生成（ビルド時）＋キャッシュも検討 |
| D6 | **ランキング再計算の起動** | Fly Machines cron / アプリ内スケジューラ / 手動 | `pg_cron`廃止の代替。頻度と起動方式を決める |
| D7 | **SQLiteバージョン/FTS5** | 同梱sqlite / `pysqlite3-binary` / `apsw` | FTS5有効性・trigram要3.34+を確認（決定記録002） |
| D8 | **デザイン刷新の範囲** | 全面刷新 / 現行トーン踏襲 | 「デザイン一新」の具体要件を別途デザインガイドで定義 |
| D9 | **いいね（公開書き込み）の設計・多重対策** | 専用エンドポイント＋ip_hash+client_uuid（＋任意でTurnstile） | **公開ユーザー書き込みの唯一の経路**。レート制限・Origin/CSRF対策・重複抑制・カウント差し替え方針をまとめて設計（§3.2-2） |
| D10 | **URL互換性** | 現行URLを完全維持するか | SEO維持のため**維持推奨**。差分は301で吸収（決定記録: URL構造） |
| D11 | **多言語/表示言語** | `display_language_preference` の扱い | 現行仕様を踏襲 |
| D12 | **キャッシュパージの境界** | URL列挙で即時パージ / 短TTLで自然失効 | Cloudflare Freeはタグ/prefixパージ不可。詳細＝即時列挙、一覧/ランキング＝短TTL委任の境界を確定（§5） |

> これらは各々を `docs/decisions/003-...` 以降のADRとして起票し、決定次第この表を更新する。

## 8. 作業フェーズ（WBS / マイルストーン）

### フェーズ0: 準備・意思決定（本計画書の次）
- [ ] 未決論点 D2〜D12 の決定（ADR起票。D1=検索方式Bは確定済み）
- [ ] リポジトリ初期化（git init, Python環境, 依存管理: uv/poetry/pip-tools 選定）
- [ ] デザイン要件定義（D8）

### フェーズ1: 基盤構築
- [ ] FastAPIスケルトン + Jinja2 + 静的配信
- [ ] SQLiteスキーマ定義（PG→SQLite変換）＋ マイグレーション基盤（D4）
- [ ] キャッシュ/セキュリティ Middleware（決定記録001 §4, §11）
- [ ] `/healthz`

### フェーズ2: データ移行
- [ ] Supabase→SQLite 移行スクリプト（bigram/FTS5生成込み・D1）
- [ ] 移行データの整合性検証（件数・関連・文字化け）

### フェーズ3: 公開ページ実装
- [ ] 一覧/詳細（quotes, authors, categories, characters, sources, professions）
- [ ] トップ・ランキング・ランダム
- [ ] 検索（HTMXインクリメンタル・D1）
- [ ] いいね（D9）
- [ ] SEO（sitemap/robots/構造化データ/canonical）
- [ ] OG画像（D5）
- [ ] 広告配置

### フェーズ4: 管理画面
- [ ] 認証（D3）+ CSRF
- [ ] 各エンティティCRUD
- [ ] 一括登録（quotes/authors bulk）
- [ ] ランキング再計算（D6）
- [ ] Cloudflareパージ連携

### フェーズ5: デプロイ・インフラ
- [ ] Dockerfile / fly.toml / ボリューム
- [ ] Litestream or LiteFS（D2）
- [ ] Cloudflare（DNS/SSL/Cache Rules/WAF）
- [ ] CI/CD（GitHub Actions → flyctl deploy）
- [ ] 監視（Flyメトリクス/UptimeRobot）・バックアップ

### フェーズ6: 段階リリース（決定記録001 §12）
- [ ] `new.` サブドメインで並行稼働・検証
- [ ] キャッシュヘッダ検証（`curl -I`、`cf-cache-status: HIT`）
- [ ] DNS切替（TTL事前短縮）
- [ ] 旧環境1〜2週間維持後に廃止

## 9. リスクと対策

| リスク | 対策 |
|---|---|
| 日本語検索精度の劣化（特に2文字語） | **方式B（FTS5+bigram）を確定採用**しPGroonga相当を再現（D1）。trigram単体は不採用（決定記録002） |
| SQLite書き込み競合 | 書き込みは原則Admin・WAL・`busy_timeout`。**匿名いいねのみ公開書き込み**だが低頻度・単純INSERTで競合影響は限定的（§3.2-2/D9） |
| 単一マシン障害 | Litestreamバックアップ＋将来LiteFSでレプリカ |
| URL変更によるSEO低下 | URL互換維持＋301リダイレクト（D10） |
| OG画像/ランキングのメモリ負荷 | 事前生成・キャッシュ・軽量ライブラリ選定（D5/D6） |
| 移行時のデータ欠損/文字化け | 件数・関連・サンプル比較の検証スクリプト |
| 管理画面のセキュリティ | IP制限＋認証＋CSRF＋no-store（D3） |

## 10. 環境変数（初期案・決定記録001 §10）

| 変数 | 用途 |
|---|---|
| `DATABASE_URL` | SQLiteパス（例 `/data/app.db`） |
| `CF_ZONE_ID` / `CF_API_TOKEN` | Cloudflareキャッシュパージ |
| `ADMIN_USER` / `ADMIN_PASS` | 管理者認証 |
| `SECRET_KEY` | セッション署名 |
| `LITESTREAM_*` / `R2_*` | バックアップ先（採用時） |

## 11. 検収チェックリスト（抜粋・決定記録001 §14）

- [ ] 公開ページ2回目アクセスで `cf-cache-status: HIT`
- [ ] `/search`・`/admin/` が `private, no-store`
- [ ] 2文字検索（例「人生」）が正しくヒット
- [ ] Admin更新後に該当URLがパージされ最新反映
- [ ] SQLiteがWALで稼働・`/healthz` 200
- [ ] 主要現行URLが200 or 301で到達（SEO互換）

## 12. 次のアクション

1. 本計画書レビュー・合意
2. 未決論点 **D2（永続化）・D3（認証）・D9（いいね公開書き込み）・D12（パージ境界）** を優先決定しADR化（D1=検索方式Bは確定済み）
3. リポジトリ初期化 → フェーズ1着手
