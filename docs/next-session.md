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
| 3-B | 著者・カテゴリ・出典・登場人物・職業・国の一覧/詳細 | 完了（2026-08-26、レビュー済み） |
| 3-C | ランダム + いいね + ランキング表示 | 完了（2026-08-26） |
| 3-D | 検索（HTMXインクリメンタル） | 完了（2026-09-10） |
| 3-E | SEO + URL互換リダイレクト + OG画像 | 完了（2026-09-10） |

各回の終わりに: `docs/project-plan.md` のフェーズ3チェックボックスへ反映 → 上の表の「状態」を更新 → コミット。

### 直近の完了状況

- 3-B実装: `ff78e67`（著者・カテゴリ・出典・登場人物・職業・国の一覧/詳細）
- レビュー修正: `fe2be76`（著者詳細の生没年表示。`day`/`month`/`year`、紀元前、部分不明に対応）
- 3-C実装: `/random`、クライアントUUIDによる匿名いいね、3種のsnapshotランキング、トップのランキング連動注目名言と空snapshot fallback
- 3-D実装: `/search` + `/search/partial`、`app/services/search.py`、HTMX 2.0.10の自前配信、`RateLimiter`の共通化
- 3-E実装: `/sitemap.xml`・`/robots.txt`（`app/services/seo.py`）、canonical/OGP/JSON-LD、
  旧URLリダイレクト（`app/services/redirects.py` + `legacy_redirect_middleware`）、
  Pillow製OG画像（`app/services/og_image.py`、`/quotes/{識別子}/og.png`・`/authors/{slug}/og.png`）、
  [`docs/url-contract.md`](url-contract.md)
- 最終検証: `uv run pytest -q` 118件成功、`uv run ruff check .` / `ruff format --check .` 成功
- DBスキーマ変更なし。`data/app.db`のranking snapshotは空のままで正常

**フェーズ3は完了した。次はフェーズ4（管理画面）。本ファイルは冒頭の方針どおり削除してよい。**

#### 3-Eで決めた既定値と申し送り

- canonicalは「現在のパス＋内容を決めるquery（filterと`page`）」。例外は`/ranking/quotes`→`/ranking`と、
  `/professions/{slug}/quotes`の1ページ目→`/professions/{slug}`。詳細はURL契約表§3
- `/page/1`の正規化は「末尾が`/page/1`のパスは接頭辞へ301」という1つの規則にまとめた。旧サイトの5本を包含し、
  旧サイトに無かった`/sources/{slug}/page/1`も同じ扱いになる
- 行き先が固定ページの接頭辞リダイレクトはqueryを引き継がない（旧Next.jsは引き継いだ）。
  `/page/1`と`/search/quotations`はqueryを維持する
- `/quotes/{4桁}`と`/quotations/view/{id}.html`はDBを引いて最終canonicalへ1 hopで送り、
  該当する公開名言が無ければ301せず404にする（旧実装は301の先で404だった）
- `/`以外の末尾スラッシュ付きパスは、除去した形に旧URL規則を当てたうえで301（相対Location）で送る。
  旧Next.jsの308除去の移植。DBを引く形（`/quotes/{4桁}/`など）は2 hopを許容し、GET/HEAD以外はStarletteの307のまま
- 3xx応答は`public, s-maxage=86400, max-age=3600`。ただし`/search/`配下は先に`no-store`になる
- sitemapの対象は§9.8どおり4表。characters/professionsの詳細ページは旧サイトと同様に含めない。
  静的一覧にはlastmodを付けない（毎日変わる値に意味がないため）
- OG画像のフォントは`app/services/og_image.py:FONT_CANDIDATES`の順に探す。開発機（macOS）は
  ヒラギノ明朝 ProN W6、本番はDebianの`fonts-noto-cjk`。**フェーズ5でDockerfileへ導入し、
  `fc-match`での検査を入れる**こと
- OG画像のフッター著者名は、落款ブランドとの間に32px空くよう実測幅で切り詰める（`…`）。
  実データに表示幅28の著者名があり、切り詰めないとブランドへ重なる。全1,785件の公開名言と
  774人の著者で描画例外ゼロ・重なりゼロを確認済み（1件あたり約47ms）
- 共通OG画像`app/static/og-default.{hash}.png`はコミット済み。デザインを変えたときだけ
  `uv run python scripts/build_default_og.py`で再生成し、`og_image.py`の`DEFAULT_OG_FILENAME`を更新する
- JSON-LDは`<script type="application/ld+json">`のインライン。データブロックであり実行可能JSではないため
  ADR 016の`script-src 'self'`に抵触しない
- **既知の未対応（3-E以前からの挙動、フェーズ4以降で判断）**: 全routeが`@router.get`のみのため
  HEADリクエストは405を返す（リダイレクトmiddlewareだけはHEADにも301を返す）。
  外形監視やクローラがHEADを使う場合は`methods=["GET", "HEAD"]`相当の対応が要る
- **フェーズ5への申し送り**: Cloudflare Cache Rulesで`*/og.png`・`/sitemap.xml`・`/robots.txt`を
  キャッシュ対象にする。`meigensyu.com`→`www.meigensyu.com`のhost正規化もCloudflare側

#### 3-Dで決めた既定値と申し送り

- カテゴリチップは実装しない（ADR 002・§9.6の検索対象外）。チップは「すべて / 名言 / 著者」の3つ
- 上限は名言50件・著者20件、並びは`ORDER BY id`（§9.6）。チップの件数は`scope`に関わらず全体のヒット数
- ハイライトは`markupsafe.escape()`→`Markup`で組み立てる`app/services/search.py`の`highlight()`で実装済み。
  SQLiteの`LIKE`に合わせASCIIのみ大小同一視する（長さが変わる`casefold()`は使わない）
- 100文字超は切り詰め、不正な`scope`は「すべて」に丸める。HTMX断片でエラーページを出さないため
- レート制限超過時、断片側は外部JSが待ち時間を案内する。**通常GETの429はFastAPI既定のJSON**のまま。
  HTMLエラーページは本プロジェクトにまだ無いため、必要なら3-E以降でまとめて用意する
- HTMXは検索ページだけで読み込む（`base.html`の`{% block extra_head %}`）。バージョン更新時は
  `app/static/htmx.<sha256先頭8桁>.min.js`を差し替え、`search.html`の参照も更新する
- **IME中のkeyupは`search.js`がcaptureで`stopPropagation()`し、htmxへ渡さない。**
  htmxの`changed`修飾子はトリガー評価の時点で入力値を記録するため、`htmx:beforeRequest`で
  中断するだけでは変換中の値が「送信済み」として残り、同じ値で確定したときに二度と送られない
  （「かな入力→変換→候補を1秒見て確定」で再現）。`beforeRequest`の中断は、変換開始前に
  予約済みだったリクエスト向けの保険として残している
- インクリメンタル検索は`hx-push-url`を使わず、アドレスバーを更新しない（`no-store`・`noindex`の
  ページであり、チップのhrefがサーバー生成の`q`を持つため導線は成立する）
- **3-Eのrobots.txtで`/search`を`Disallow`する**こと。`/search/partial`には`noindex`が付かない
  （metaを持たない断片のため）ので、パスごと除外して揃える

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

#### 目的

`/search` を実装し、`docs/project-plan.md` フェーズ3の「検索（HTMXインクリメンタル・D1）」を完了する。1セッションで完結させる。DBスキーマ変更なし。

#### 設計の正本

ADR 002（LIKE検索）/ ADR 015（検索UI・レート制限）/ ADR 016（CSP・HTMX規約）/ [design-guide](design/design-guide.md) §5・§6 / [inventory-4](database/inventory-4-new-db-design.md) §9.6 / 実装素材として `docs/design/proposal-b/templates/search.html`・`partials/search_results.html`

#### 実装内容

**1. 検索サービス（`app/services/search.py` 新設）**

- 正規化: 前後空白の除去と連続空白の畳み込み（`" ".join(value.split())`。全角空白も畳まれる）。0文字は検索せず初期表示。100文字超は先頭100文字へ切り詰めて検索する（エラー応答にはしない。HTMX断片でエラーを出さないため）
- LIKE: SQLAlchemyの `contains(term, autoescape=True)` を使い、`%`・`_`・escape文字をリテラル化する（SQLAlchemy 2.0のautoescapeはescape文字に `/` を使う。§9.6の例は `\` だが、リテラル化されていればどちらでもよい）。利用者入力をSQL文字列へ連結しない
- 名言検索: `quotes.text` / `text_en` / `context_note` / `authors.name` / `sources.title` を対象、`enable = 1`、`ORDER BY q.id`（§9.6）、上限50件。既存の `_quote_select()` と `_present_quotes()`（`app/services/quotes.py`）を再利用し、カード表示・いいね数・表示言語resolverを一覧と揃える
- 著者検索: `name` / `name_kana` / `name_foreign` / `name_reading` を対象、上限20件。公開名言件数は `app/services/entities.py` の既存の数え方に合わせる
- チップ用に名言・著者それぞれの総ヒット件数（COUNT）を返す
- `scope`: 未指定（すべて）/ `quotes` / `authors`。**カテゴリ検索は対象外**（ADR 002・§9.6の対象に含まれない）。proposal-bのカテゴリチップは落とし、チップは「すべて / 名言 / 著者」の3つにする。design-guideとの差分としてコミットメッセージに残す

**2. ルート（`app/routers/public.py`）**

- `GET /search`（フルページ）と `GET /search/partial`（HTMX断片）。正規化・検証・検索は同一の内部関数を共有し、テンプレートだけ差し替える
- 両応答に `Vary: HX-Request` を付ける（ADR 015）
- `Cache-Control: private, no-store` はフェーズ1のmiddlewareが付与済み（`NO_STORE_PATHS` に `/search`、`NO_STORE_PREFIXES` に `/search/`）。**確認するだけでmiddlewareは変更しない**
- レート制限超過は429 + `Retry-After`（断片側も同じ）。クライアントは自動再試行せず待ち時間を案内する
- 送信元IPは既存 `_like_source_ip` と同じ `CF-Connecting-IP` 優先の取り出し。関数を `_source_ip` に改名して両方から使う

**3. レート制限の共有**

- `app/services/likes.py` の `LikeRateLimiter` を `app/services/rate_limit.py` へ `RateLimiter` として移し、likes と search がそれぞれ別インスタンスを持つ。クラスの実装自体は変えない（移動と改名のみ）。既存importとテストを更新する
- `app/config.py` に `get_search_rate_limit()` を追加（既定30回/10秒、環境変数 `SEARCH_RATE_LIMIT_REQUESTS` / `SEARCH_RATE_LIMIT_WINDOW_SECONDS`）

**4. テンプレート**

- `app/templates/search.html`（proposal-b版を移植。`autofocus`、`{% block meta_robots %}` で `noindex`）と `app/templates/partials/search_results.html`
- `app/templates/base.html` に `{% block meta_robots %}` を追加。HTMXは検索ページだけで読み込む（`{% block extra_head %}` を用意し、`search.html` から差し込む）
- ハイライト（`<mark>`）を実装する場合は、`markupsafe.escape()` した文字列にサーバ側で `Markup` を組み立てる小さなヘルパーを書く。proposal-bの `highlighted|safe` を生の値へそのまま使わない。XSSテストを必ず添える。安全に書けない場合はハイライト無しでよい（デザインより安全側を優先）

**5. HTMX導入（本プロジェクトで初めて使う）**

- htmx 2.x をバージョン固定でvendorし、`app/static/htmx.<hash>.min.js` として自前配信する（CDN不可。CSPは `script-src 'self'`）。ファイル名ハッシュは既存の静的ファイルと同じ方式
- 設定はインラインJS禁止のため `<meta name="htmx-config" content='{"allowEval":false,"allowScriptTags":false,"selfRequestsOnly":true}'>` で与える。ADR 016の「設定値を小さなテストで確認する」はこのmetaの検証で満たす
- `hx-get="/search/partial"` / `hx-trigger`（500ms trailing debounce）/ `hx-target="#search-results"`
- IME変換中は送信しない: 外部静的JS `app/static/search.<hash>.js` で `compositionstart` / `compositionend` を見て、composition中の `htmx:beforeRequest` を中断し、確定後に改めて発火させる。`hx-on` やDOM event属性は使わない（ADR 016）
- JavaScript無効時は `/search` への通常GET submitで同じ結果になること

#### やらないこと

- FTS5・bigram・派生列・派生テーブル（ADR 002）
- Cloudflare側の検索用レート制限ルール、Turnstile、Challenge（ADR 015）
- 検索語・IPのDB保存や通常ログへの記録、GA4検索イベント（ADR 015・016）
- sitemap・canonical・構造化データ・OG画像・URL互換リダイレクト（3-E）
- カテゴリ・出典を独立させた検索画面、AND/OR検索、関連度ランキング
- DBスキーマ変更（必要が生じたら理由を説明してユーザー判断を仰ぐ）

#### テスト

既存 `tests/test_public_quotes.py` と同じ流儀。件数が多いので `tests/test_search.py` を新設してよい。

- 正規化: 前後空白・連続空白・全角空白・100文字超の切り詰め・0文字（初期表示を返し検索しない）
- LIKEエスケープ: `%`・`_`・`\` を含む語がリテラルとして扱われる（例: `100%` が全件ヒットしない）
- 日本語1文字（「愛」等）で検索できる
- 対象列ごとのヒット: 本文 / `text_en` / `context_note` / 著者名 / 出典タイトル。`enable = 0` は出ない
- 通常GETとHTMX断片（`HX-Request: true`）が同じ結果を返し、断片は完全なHTML文書を返さない。両方に `Vary: HX-Request` と `Cache-Control: private, no-store`
- レート制限: 上限超過で429 + `Retry-After`、通常操作では発生しない
- 出力エスケープ: `<script>` を含む検索語・本文がエスケープされる（ハイライト実装時は特に）
- `noindex` metaと `htmx-config` metaが検索ページに出る

#### 完了条件

1. `uv run pytest -q` と `uv run ruff check .` が成功
2. ローカル（`data/app.db`は本番相当データ）で手動確認: IME確定後500msで1回だけ送信、JS無効相当の通常GETでも同じ結果、429時の案内、ヘッダー
3. `docs/project-plan.md` フェーズ3の「検索」チェックボックス、本ファイル冒頭の表と「直近の完了状況」を更新
4. コミットは3-Cまでと同じ粒度（実装1コミット、レビュー修正があれば別コミット）

#### 判断の既定値

上限件数（名言50 / 著者20）、チップ構成（すべて / 名言 / 著者）、ハイライトの有無は上記を既定とする。変更する場合は理由をコミットメッセージへ残す。ADRと矛盾する実装が必要になった場合はADRを正とし、ADR自体を変えるべきと判断したらユーザーへ確認する。

### 3-E. SEO + URL互換リダイレクト + OG画像（次回の作業指示）

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
