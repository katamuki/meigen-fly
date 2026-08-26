# 次回以降セッション作業指示: フェーズ3（公開ページ実装）

> 本ファイルはセッション間の引き継ぎメモ。各回の完了時に「進め方」の表を更新し、フェーズ3完了時に削除する。
> 作成日: 2026-08-25（フェーズ2完了を受けて作成）

## 目的

[`docs/project-plan.md`](project-plan.md) §8 フェーズ3（公開ページ実装）を完了する。規模が大きいため**5回のセッション（3-A〜3-E）に分割**し、1回1セッションで完結させる。

## 設計の正本（この順で優先）

1. 各ADR（特に 002 検索LIKE / 006 いいね / 008 URL互換 / 009 表示言語 / 010 random / 011 日時 / 015 検索UI・レート制限 / 016 CSP・HTMX / 017 デザイン / 018 OG画像）
2. [`docs/design/design-guide.md`](design/design-guide.md) — デザイン実装仕様の正本。`docs/design/proposal-b/` のtokens.css・components.css・Jinja2テンプレートを実装素材として流用する（矛盾時はガイドとADRを優先）
3. [`docs/database/inventory-4-new-db-design.md`](database/inventory-4-new-db-design.md) §9 — 主要機能の代表クエリ（EXISTS filter、カテゴリ件数、検索、いいね等）
4. [`docs/database/inventory-2-app-usage.md`](database/inventory-2-app-usage.md) — 現行の画面・機能・URL契約の事実

## 進め方（5分割・この順で実施）

| 回 | 内容 | 状態 |
|---|---|---|
| 3-A | 共通基盤 + トップ + 名言一覧/詳細 | 完了（2026-08-25） |
| 3-B | 著者・カテゴリ・出典・登場人物・職業・国の一覧/詳細 | 完了（2026-08-26） |
| 3-C | ランダム + いいね + ランキング表示 | 未着手 |
| 3-D | 検索（HTMXインクリメンタル） | 未着手 |
| 3-E | SEO + URL互換リダイレクト + OG画像 | 未着手 |

各回の終わりに: `docs/project-plan.md` のフェーズ3チェックボックスへ反映 → 上の表の「状態」を更新 → コミット。

### 3-A. 共通基盤 + トップ + 名言一覧/詳細

フェーズ3全体の土台になる回。ここでの構造の決定（テンプレート構成、ルーティング、共通ヘルパー）は以降の回が引き継ぐ。

- proposal-bの`tokens.css`/`components.css`/`base.html`/partialsをアプリへ組み込み（静的ファイルはフェーズ1のハッシュ付きファイル名方式に合わせる）。`theme.js`はADR 017の仕様で外部ファイルとして実装（CSPインライン禁止・ADR 016）
- 表示言語resolver（ADR 009: `display_language_preference`優先、空なら他方へfallback）を共通ヘルパーとして実装。カード・詳細・metadataで共用
- 名言一覧 `/quotes`（ページネーション、著者/カテゴリ/職業filterは第4部§9.1のEXISTS形。`enable=1`のみ）
- 名言詳細のURL解決（ADR 008: slugがあればcanonical、なければ`q{id}`。`q123`は厳密parse。非公開・存在しないIDは404）
- トップページ（注目名言はsnapshot依存のため3-Cまでプレースホルダー可）
- ADR 011のcodec（`app/instants.py`）で読み出し・表示日時を扱う
- テスト: URL解決（slug/qid/404）、fallback resolver、一覧filter、キャッシュヘッダ（フェーズ1のmiddlewareとの整合）

### 3-B. その他エンティティの一覧/詳細

- authors（ランキングJOINはLEFTで、空snapshotでも動く順序: 第4部§9.2）、categories（2階層+件数: §9.3）、sources/source_types filter、characters、professions、countries（§9.4）
- 件数はすべてリアルタイムSQL（COUNT DISTINCT、公開限定、0件も表示。判断#17・#18）
- 一覧の並び: `display_order`/`sort_order`/`name_reading`等、現行契約（第2部）に合わせる
- テスト: 各詳細のslug解決と404、件数SQLの意味（親カテゴリは子を横断してDISTINCT）

### 3-C. ランダム + いいね + ランキング表示

- `/random`: 20件・200・no-store（ADR 010。`ORDER BY random()`の単純形）
- いいね（ADR 006）: クライアント側UUID + `POST`専用route。`(quote_id, client_uuid)`の存在確認→INSERT、競合は冪等成功。現在値 = `legacy_vote_count` + 有効likes。公開HTMLは総数を埋め込みキャッシュ、押した本人の応答だけ最新化。アプリ側レート制限（判断#7の`ip_daily_limit`相当はrankingと分離した設定）
- ランキングページ: snapshot 3表からの表示（`score_total DESC, id`）。**snapshotは空のままで正**（再計算CLIはフェーズ4）。ページ自体は空データで壊れないこと。動作確認用に一時データをテスト内で投入するのは可、`data/app.db`へ手動投入した場合は`rebuild_sqlite.sh`で戻す
- トップの注目名言をランキング連動に差し替え（空なら代替表示）
- テスト: いいねの冪等性・UUID検証・レート制限、randomのno-store

### 3-D. 検索

- ADR 002: bind parameter + `%`/`_`/escape文字のリテラル化によるLIKE。対象は本文/text_en/context_note/著者名/出典タイトル（第4部§9.6）。FTS5・派生列は作らない
- ADR 015: 1文字から検索可、500ms debounce（proposal-bの`search_results.html`部品を流用）、アプリ側レート制限、結果は`private, no-store`（フェーズ1のmiddlewareが`/search`をno-store化済みであること確認）
- HTMXはADR 016の規約（インラインコード禁止、許可属性）に従う
- テスト: escape（`%`・`_`を含む語）、空クエリ、レート制限、HTMX部分応答と通常GETの両方

### 3-E. SEO + URL互換リダイレクト + OG画像

- sitemap.xml（第4部§9.8: 公開quotesはslug/qid契約、authors/sources/categoriesは`updated_at`をlastmodに）・robots.txt
- 構造化データ・canonical・OGP metadata（表示言語resolverを共用）
- URL互換（ADR 008）: 静的301 23本 + `/quotations/view/[id].html`動的301。**URL契約表**（slug/qid解決優先順位・`page/1`正規化・主要リダイレクト一覧）を`docs/`に作成し、リリース前チェックの正本にする。1 hopで最終canonicalへ到達すること
- OG画像（ADR 018）: Pillowオンデマンド生成（名言・著者、1200×630、表示幅20/40/80で文字サイズ切替、80超は`…`）。視覚仕様は`docs/design/proposal-b/og/og.html`。エッジ30日キャッシュはフェーズ1のmiddlewareで設定済み。フォント（Noto CJK）はローカルで動く形にし、コンテナ導入はフェーズ5
- テスト: リダイレクトのステータス・Location・hop数、sitemapの内容、OG画像の生成（3段階の文字量）

## スコープ境界（フェーズ3全体で重要）

- 管理画面・Cloudflare Access検証・CSRFはフェーズ4
- ランキング再計算CLI・ranking係数設定・Cloudflareパージ連携はフェーズ4以降（snapshot 3表は空のまま）
- FTS5・検索派生インデックスは作らない（D1/ADR 002）
- GA4・AdSenseはサイト完成後の別フェーズ
- Dockerfile・デプロイ・バックアップはフェーズ5
- DBスキーマ変更は原則なし。必要が生じたら理由を説明してユーザー判断を仰ぐ

## データ準備

- ローカルDB: `data/app.db`（フェーズ2で構築済み・本番相当データ入り）。壊れたら `scripts/rebuild_sqlite.sh` で再構築（ダンプは`~/prj/meigen-fly-private/source-db/data/`に保存済み。再取得する場合はキーチェーンの`meigen-fly-supabase-db`から接続文字列を取得、本番へは読み取り専用）
- ranking snapshot 3表は空が正常

## 運用ルール

- 完了したタスクは `docs/project-plan.md` のチェックボックスと本ファイルの表へ反映する
- 秘密情報をリポジトリ・シェル設定ファイルへ書かない
- CSP・キャッシュヘッダ等フェーズ1の決定はテストで担保されている。変更が必要な場合は理由を明記する
