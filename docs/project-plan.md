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

> ⚠️ 上記より下流（LiteFS or Litestream、管理者認証方式、パージ運用 等）は **未決**。第7章「検討事項」で扱う。検索方式は**方式B（FTS5+bigram）で確定済み**（D1）。

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
| `/random` | ランダム名言 | |
| `/search` | 全文検索（**キャッシュ不可**） | HTMXインクリメンタル検索 |
| `/about`, `/privacy`, `/terms` | 静的ページ | Markdown管理 |
| `/login`, `/403` | 管理認証フロー | `/admin/*` 認証・権限エラー時の遷移先 |

### 3.2 移植する主要機能

1. **日本語全文検索**（名言・著者）— PGroonga相当を SQLite **FTS5 + アプリ側bigram（方式B・確定）** で再現（第7章・決定記録002）
2. **匿名いいね**（`quote_likes`：client_uuid + ip_hash、重複抑制）
   - ⚠️ **本サイト唯一の「公開ユーザー書き込み」**。§4・§9の「書き込みはAdminのみ」の**明示的な例外**。専用の書き込みエンドポイントを設け、レート制限・Origin/CSRF対策・多重投票抑制を必須とする（D9）。
   - `client_uuid` は現行同様 localStorage 管理を基本とし、公開ページにユーザー識別Cookieを載せない（エッジキャッシュと両立させるため）。
   - いいね数の表示戦略はD9で要決定。ページ本体をキャッシュしつつ毎PVで非キャッシュ断片を叩くと、オリジン負荷削減効果を相殺するため、**HTMLへ焼き込み+短TTL/パージ**、または**ページ単位バッチ断片+短い `s-maxage`**を優先候補にする。
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

- Supabase Auth（→ 独自の管理者認証に置換。第7章）
- PGroonga（→ SQLite検索に置換）
- Next.js特有の revalidate / ISR（→ Cloudflare パージに置換）
- `pg_cron` / PostgreSQL RPC / RLS（→ アプリ層ロジック + SQLに移植）

## 4. データモデル移行方針

現行スキーマ（`docs/database/schema-design.md` 相当、約20テーブル/ビュー）を SQLite へ写す。**PostgreSQL固有要素の置換**が要点。

| PostgreSQL要素 | SQLiteでの扱い |
|---|---|
| `SERIAL` / `BIGSERIAL` | 原則 `INTEGER PRIMARY KEY`。SQLiteの `AUTOINCREMENT` はID再利用を厳密に禁止したいテーブルだけ使う |
| ENUM（`date_precision`, `life_era`） | `TEXT` + `CHECK`制約 |
| `TIMESTAMPTZ` | **要決定（D4）**: `TEXT`(ISO8601, UTC) または `INTEGER`(epoch)。アプリ・移行スクリプト・比較クエリで統一する |
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

`pg_cron` は少なくとも2ジョブを代替する: `refresh_quote_ranking_scores_scheduler`（ランキング）と `refresh_categories_with_counts_scheduler`（カテゴリ件数）。アプリ内スケジューラを採用する場合、`uvicorn --workers 2` では二重実行になるため、Fly Machines cron/単発ジョブ/外部cronを優先候補にする。

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
  - ⚠️ **HTMLはCloudflareのデフォルトでキャッシュされない**（拡張子ベースでCSS/JS/画像のみ）。`Cache-Control` を返すだけでは不十分で、**公開HTMLパスに Cache Rules で「Eligible for cache（Cache Everything相当）」を明示**する必要がある。Cache Rules は **last matching rule wins（最後にマッチしたルールが勝つ）** のため、`/admin/*`・`/search*`・`/random`（no-store採用時）・いいね断片APIのBypassルールは、公開HTMLのEligibleルールより**後（下）**に配置する。詳細は決定記録001 §8。
- **パージ**: Admin更新時に Cloudflare API で該当URL/タグ/プレフィックスをパージ。
  - ✅ **Cloudflare Free でも利用可能な方式**（公式ドキュメント「Purge cache」Availability and limits, 2026-04-16更新で確認）: **URL / Hostname / Tag / Prefix / Purge Everything すべて Free で使える**（旧記述「タグ/prefixはEnterprise限定」は誤りのため訂正）。
  - ⚠️ **Free のレート制限**: Tag/Prefix/Hostname/Purge Everything は **5リクエスト/分・1リクエスト最大100オペレーション**（バケット25）。URL単位パージは別枠で上限が高く **800 URLs/秒・1リクエスト最大100URL**（Free）。→ **一括登録など短時間の大量更新でタグ/prefixを多用すると 5/分 に当たる**点が実運用上の論点。
  - **列挙が必要な派生URL（URLパージ採用時）**: 一覧の**全ページングURL**（`/quotes/page/N`, 著者/カテゴリ/出典の各ページ）、`/quotes/latest*`、`/ranking`、`/`、該当**OG画像** `/api/og?...`、`/sitemap.xml`。
  - **方針（D12）**: **個別詳細ページ・OGは高上限のURLパージで即時反映**。一覧/著者/カテゴリ/ランキング等の広範な無効化は、`Cache-Tag` を付与して**タグパージ**（例 `quotes-list`, `author-123`）でまとめて落とす選択肢が Free でも取れる。ただし **5リクエスト/分**の制約に収まるようバッチ集約する。制約に収まらない範囲は**短めTTL（`s-maxage`）で自然失効に委任**。URLパージ／タグパージ／TTL委任の**使い分け境界**を実装前に確定する。
  - **いいね数**: D9で要決定。毎PV非キャッシュ取得は避け、焼き込み+短TTL/パージまたは短TTLのバッチ断片APIを優先候補にする。
- **オリジン保護**: Cloudflare WAF/IP制限だけでは `*.fly.dev` やオリジンIP直撃を防げない。Authenticated Origin Pulls（Free可）を第一候補に、Hostヘッダ検証・Cloudflare IPレンジ検証も含めてD3で確定する。
- **IP取得**: Cloudflare経由の公開書き込みでは `CF-Connecting-IP` を信頼する。オリジン直撃対策とセットで、信頼できない経路からの同ヘッダー偽装を拒否する。
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
| D6 | **集計再計算の起動** | Fly Machines cron / アプリ内スケジューラ / 手動 / リアルタイムSQL化 | `pg_cron`廃止の代替。ランキングに加え `categories_with_counts` も対象。`uvicorn --workers 2` でのアプリ内スケジューラは二重実行対策が必要 |
| D7 | **SQLiteバージョン/FTS5** | 同梱sqlite / `pysqlite3-binary` / `apsw` | 主条件は**FTS5有効性**と**`unicode61`でbigram済みテキストを扱えること**（方式B）。古い場合は `pysqlite3-binary`/`apsw` で同梱（決定記録002） |
| D8 | **デザイン刷新の範囲** | 全面刷新 / 現行トーン踏襲 | 「デザイン一新」の具体要件を別途デザインガイドで定義 |
| D9 | **いいね（公開書き込み）の設計・多重対策** | 専用エンドポイント＋ip_hash+client_uuid（＋任意でTurnstile） | **公開ユーザー書き込みの唯一の経路**。レート制限・Origin/CSRF対策・重複抑制・いいね数表示戦略をまとめて設計（§3.2-2）。IPはCloudflare前提で `CF-Connecting-IP` を利用 |
| D10 | **URL互換性** | 現行URLを完全維持するか | SEO維持のため**維持推奨**。現行 `next.config.js` の静的301 20本 + middlewareの `/quotations/view/[id].html` 動的301を移植。`page/1` 正規化も含む |
| D11 | **多言語/表示言語** | `display_language_preference` の扱い | 現行仕様を踏襲 |
| D12 | **キャッシュパージの使い分け** | URLパージ / タグ・prefixパージ / 短TTL委任 | **Freeでも URL/Tag/Prefix/全パージ可**（2025-04開放）。URLは800/秒・100/req、Tag/Prefixは**5req/分・100ops/req**。詳細＝URL即時、広範＝タグ（バッチ集約）、収まらない分＝短TTL。**タグ名は短い小文字ASCII**（スペース不可・合計16KB上限）で統一（§5） |
| D13 | **`/random` のキャッシュ方針** | `private, no-store` / ランダムな個別ページへ302 | 公開HTML一括キャッシュに巻き込むとTTL中同じ結果になる。推奨は302方式（オリジン負荷を抑え、個別ページは通常キャッシュ） |
| D14 | **オリジン保護** | Authenticated Origin Pulls / Hostヘッダ検証 / CF IPレンジ検証 | Cloudflare迂回を防ぐ。AOPを第一候補にD3と一体で設計 |
| D15 | **検索レート制限** | Cloudflare Rate Limiting + debounce/最小文字数 | 60req/min固定では300ms debounceのインクリメンタル検索と衝突し得る。閾値・debounce・最小文字数をセットで確定 |
| D16 | **CSPとHTMX規約** | `hx-on` 禁止 / hx-csp導入 / `unsafe-eval` 許容 | 原則 `hx-on`、イベントフィルタ、`js:`/`javascript:` 値を使わず、インラインJS禁止CSPと整合させる |

> これらは各々を `docs/decisions/003-...` 以降のADRとして起票し、決定次第この表を更新する。

## 8. 作業フェーズ（WBS / マイルストーン）

### フェーズ0: 準備・意思決定（本計画書の次）
- [ ] 未決論点 D2〜D16 の決定（ADR起票。D1=検索方式Bは確定済み）
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
- [ ] URL互換リダイレクト（静的301 20本 + `/quotations/view/[id].html` 動的301 + `page/1` 正規化）
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
- [ ] Authenticated Origin Pulls等のオリジン直撃対策（D14）
- [ ] CI/CD（GitHub Actions → flyctl deploy）
- [ ] 監視（Flyメトリクス/UptimeRobot）・バックアップ

### フェーズ6: 段階リリース（決定記録001 §12）
- [ ] `new.` サブドメインで並行稼働・検証
- [ ] `new.` サブドメインは `noindex` / robots deny を有効化
- [ ] DNS切替直前の差分再移行、または旧環境の書き込み凍結を実施
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
| Cloudflare迂回によるWAF/IP制限バイパス | Authenticated Origin Pulls等でオリジン直撃を拒否（D14） |
| `/random` がエッジキャッシュされ固定化 | `no-store` またはランダム個別ページへの302方式をD13で確定 |
| 段階リリース中のデータ差分 | 切替直前の差分再移行または書き込み凍結をフェーズ6に組み込む |

## 10. 環境変数（初期案・決定記録001 §10）

| 変数 | 用途 |
|---|---|
| `DATABASE_URL` | SQLiteパス（例 `/data/app.db`） |
| `CF_ZONE_ID` / `CF_API_TOKEN` | Cloudflareキャッシュパージ |
| `ADMIN_USER` / `ADMIN_PASS` | 管理者認証 |
| `SECRET_KEY` | セッション署名 |
| `RANKING_IP_HASH_SALT` | 匿名いいねの `ip_hash` 生成 |
| `NEXT_PUBLIC_GA_ID` | GA4（採用時） |
| `NEXT_PUBLIC_ADSENSE_PUBLISHER_ID` | AdSense（採用時。`ads.txt` 相当も移植） |
| `ORIGIN_PROTECTION_*` | AOP/Host/CF IP検証など、D14で方式確定後に定義 |
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
2. 未決論点 **D2（永続化）・D3/D14（認証・オリジン保護）・D9（いいね公開書き込み）・D12（パージ境界）・D13（`/random`）** を優先決定しADR化（D1=検索方式Bは確定済み）
3. リポジトリ初期化 → フェーズ1着手
