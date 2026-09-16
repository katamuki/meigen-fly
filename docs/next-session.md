# 次回以降セッション作業指示: フェーズ4（管理画面）

> 本ファイルはセッション間の引き継ぎメモ。各回の完了時に「進め方」の表を更新する。フェーズ4完了時は、残す価値のある申し送りを計画書・ADRへ移してから削除する。
> 作成日: 2026-09-13（フェーズ3完了と、フェーズ4着手時の決定を受けて作成）

## 目的

[`docs/project-plan.md`](project-plan.md) §8 フェーズ4（管理画面）を完了する。**5回のセッション（4-A〜4-E）に分割**し、1回1セッションで完結させる。

## 設計の正本（この順で優先）

1. 各ADR（特に 012 管理認証・CSRF / 014 パージ / 005 定期ジョブ / 011 日時 / 016 CSP / 008 URL互換）と [URL契約表](url-contract.md)
2. [`docs/design/design-guide.md`](design/design-guide.md) §7（管理画面）
3. [`docs/database/inventory-4-new-db-design.md`](database/inventory-4-new-db-design.md) — §4〜6 表定義・制約（§6.4 ランキング計算式）、§8.2 DB更新とcacheの境界。実際の列と制約は `app/schema.py` が正
4. 旧実装 `/Users/sonoda/prj/meigensyu` — 画面 `src/app/(admin)/admin/`、API `src/app/api/admin/`、フォーム部品 `src/components/admin/`。**機能範囲と入力規則の事実確認に使い、UI・構造は移植しない**

## フェーズ4の決定事項（2026-09-13）

1. **依存**: `pyjwt[crypto]` だけを追加する（Python 3.14で pyjwt 2.14.0 / cryptography 50.0.1 が解決することを確認済み）。`python-multipart` は入れず、管理画面の入力は `application/x-www-form-urlencoded` に限る（旧一括登録もtextareaでファイルアップロードなし）。CSRF tokenは標準 `hmac`、Cloudflareパージ要求は標準 `urllib.request` で作る。httpxを本番依存に加えない
2. **デザイン**: 新しいデザイン作業はしない。`tokens.css` の変数と管理画面専用の小さなCSSで作る（design-guide §7）
3. **ランキング**: 旧式を同値移植する。計算式の正本は inventory-4 §6.4
4. **認証まわり**: `/login` は `/admin` へ302。`/403` ページは作らない。ローカル開発だけの認証迂回 `ADMIN_DEV_EMAIL` を設ける（ADR 012「実装方針」）

## 進め方（5分割・この順で実施）

| 回 | 内容 | 状態 |
|---|---|---|
| 4-A | 管理基盤（Access JWT検証・CSRF・レイアウト・`/login`・操作ログ） | 完了（2026-09-16） |
| 4-B | ランキング再計算（CLI + ボタン）+ Cloudflareパージの共通処理 | 未着手 |
| 4-C | 名言・著者のCRUD | 未着手 |
| 4-D | その他マスタのCRUD（categories / characters / sources / professions） | 未着手 |
| 4-E | 一括登録（quotes / authors） | 未着手 |

各回の終わりに: `docs/project-plan.md` のフェーズ4チェックボックスへ反映 → 上の表の「状態」と下の「直近の完了状況」を更新 → コミット（実装1コミット、レビュー修正があれば別コミット）。

### 直近の完了状況

- 2026-09-16: 4-A完了。Access JWT検証、ローカル開発用迂回、CSRF、URLエンコードフォーム共通処理、管理ダッシュボード、`/login`、操作ログを実装し、管理routeの認証依存を走査するテストを追加
- 2026-09-13: フェーズ4の決定事項と分割を確定（本ファイル作成、ADR 012・001・design-guide・inventory-4を更新）

## 全回共通の実装規約

- ルートは `app/routers/admin.py`（prefix `/admin`。大きくなったらエンティティ単位で分割してよい）、テンプレートは `app/templates/admin/`
- `/admin` 配下の全routeに4-Aの認証依存関数を付ける（routerの `dependencies` で一括）。4-Aで入れる「全管理routeに認証が付いている」テストを壊さない
- 状態変更はPOSTだけ。CSRF tokenを必須とし、成功後は303で一覧・詳細へ戻す（PRG）。検証エラーはフォームを入力値つきで再表示する（422）
- 入力は4-Aの共通フォーム読み取り関数 + Pydanticモデルで検証する。DBのCHECK・UNIQUE違反も利用者向けの文言にしてフォームへ戻す
- 時点列（`created_at` / `updated_at`）はADR 011のcodec（`app/instants.py`）で書く
- 作成・更新・削除は4-Aの操作ログ関数で記録する（管理者email・操作・対象・時刻）
- 削除は確認画面を挟む。影響（例: 著者を消すと名言の著者が外れる件数）を示す。JSの `confirm()`・インラインJS・DOM event属性は使わない（ADR 016）。FKの削除動作は `app/schema.py` に従う
- パージは4-Bの共通関数を**DBコミット完了後に**呼ぶ。`get_connection()` の依存関数は応答処理の終わりにコミットするため、書き込みrouteではハンドラ内でトランザクションを閉じてからパージするなど、順序をテストで確かめる。結果（成功 / TTL待ち / 未設定でスキップ）を画面の通知に出す
- 管理画面ではHTMXを使わない。必要になったら理由を記録してから使う
- `/admin`・`/login` の `private, no-store` はフェーズ1のmiddlewareで設定済み（`app/middleware.py`）。確認するだけで変更しない
- テストは `tests/test_admin_*.py`。既存テストと同じ流儀で一時DBを使う

### 4-A. 管理基盤

フェーズ4全体の土台。ここで決めた依存関数・テンプレート・通知の形を以降の回が引き継ぐ。

**1. 依存と設定**

- `uv add "pyjwt[crypto]"`
- `app/config.py` に既存の `get_*` 関数の流儀で追加: `CF_ACCESS_TEAM_DOMAIN`（`https://<team>.cloudflareaccess.com`、末尾slashなし）、`CF_ACCESS_AUD`、`SECRET_KEY`、`ADMIN_DEV_EMAIL`

**2. 認証（依存関数。管理者emailを返す）**

- `Cf-Access-Jwt-Assertion` ヘッダーをPyJWTで検証する。`PyJWKClient(f"{CF_ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs")` をプロセス内で1つ保持し、`algorithms=["RS256"]`・`audience=CF_ACCESS_AUD`・`issuer=CF_ACCESS_TEAM_DOMAIN`・`exp` 必須で `jwt.decode` する。`email` クレームが空でない文字列であることも確かめる
- 失敗は403（短い本文）。理由（欠落 / 署名 / aud / iss / 期限 / email / 鍵取得失敗）はログへ出し、トークン本体は出さない
- `CF_ACCESS_TEAM_DOMAIN`・`CF_ACCESS_AUD`・`SECRET_KEY` のいずれかが無ければ、下記の迂回を除き管理画面全体を403にする
- **開発用迂回**: `ADMIN_DEV_EMAIL` があり、かつ `CF_ACCESS_AUD` が未設定で、`PUBLIC_ORIGIN` のホストが `localhost` か `127.0.0.1` のときだけ、JWT検証を省略してそのemailを管理者とする。CSRF検証は迂回しない（ローカルでも `SECRET_KEY` を設定する）

**3. CSRF**

- token = `{発行unix秒}.{HMAC-SHA256(SECRET_KEY, "{email}|{発行unix秒}") のhex}`。有効期限12時間、未来の発行時刻は拒否、比較は `hmac.compare_digest`
- 画面の全POSTフォームへ `<input type="hidden" name="csrf_token">` を入れる。検証はフォーム読み取りと同じ共通処理で行う
- 独自のセッションCookieは発行しない（ADR 012・001）

**4. フォーム読み取り**

- `app/routers/public.py` の `_like_client_uuid` の本文読み取りを参考に、上限つき（既定1 MiB）で本文を読んで `parse_qs` する共通関数を作る。Content-Typeが `application/x-www-form-urlencoded` 以外は415
- 複数値（例: カテゴリの複数選択）はリストで返す。検証はPydanticモデルで行う
- いいね側の既存関数は、挙動が変わらない範囲でだけ置き換える（無理に統合しない）

**5. 画面・ルート**

- `app/routers/admin.py` を作り `app/main.py` へ登録
- `GET /admin`: ダッシュボード。名言数（公開/非公開）・著者数程度の件数と、実装済みの管理画面へのメニュー（未実装のメニューは出さない）
- `GET /login`: `/admin` へ302。`/login` はAccessの保護対象外なので認証依存関数を付けない
- `app/templates/admin/base.html` と管理用CSS `app/static/admin.<hash>.css`（design-guide §7）。ヘッダーに管理者emailとログアウトリンク `/cdn-cgi/access/logout`。成功・失敗の通知の出し方もここで決める（PRG後に通知を出す方法は、Cookieを増やさずに済むquery等の単純な形を選ぶ）
- 操作ログ: `logging.getLogger("app.admin")` へ、管理者email・操作（create / update / delete / refresh 等）・対象（表名とID）・UTC時刻を1行で出す小さな関数

**6. テスト**

- テスト内でRSA鍵を生成し、JWKSの取得を差し替えて署名済みトークンを作る（ネットワークへ出ない）
- ADR 012の検証: JWTなし・偽署名・異なるaud・異なるiss・期限切れ・email欠落が403、正しいトークンが200
- 設定不足で403。開発用迂回が「`CF_ACCESS_AUD` あり」「`PUBLIC_ORIGIN` が本番ホスト」「`ADMIN_DEV_EMAIL` なし」のいずれでも無効
- CSRF: なし・改ざん・別email・期限切れが拒否、正しいtokenが成功（POST routeが無ければ関数単位のテストでよい）
- `/admin`・`/login` が `private, no-store`、`/login` が302で `Location: /admin`
- appのroute一覧を走査し、`/admin` 配下の全routeに認証依存関数が付いていることを確かめる（以降の回での付け忘れを防ぐ）

**完了条件**: `uv run pytest -q`・`uv run ruff check .`・`uv run ruff format --check .` が成功。ローカルで `ADMIN_DEV_EMAIL` と `SECRET_KEY` を設定してダッシュボードを表示できる。README にローカルで管理画面を開く手順を追記。

### 4-B. ランキング再計算 + パージ共通処理

**1. 再計算（`app/services/ranking_refresh.py`）**

- inventory-4 §6.4 を正本に実装する。基準時刻 `now` を引数で受ける（テストと突き合わせで固定するため）
- 係数は型付き定数（frozen dataclass等）。コマンド引数や設定表にしない
- 書き込みロックを先に取り、3表を1トランザクションで全行入れ替える。失敗時はrollbackして前回世代を残す
- 戻り値は件数・所要時間・`refreshed_at`

**2. CLI（`scripts/refresh_rankings.py`）**

- `uv run python scripts/refresh_rankings.py`。成功で0、失敗で非ゼロ終了し、stderrへログ。成功後にパージする（未設定ならスキップ）
- `flock`・timeout・supercronic登録・成功Heartbeatはフェーズ5。Heartbeatを足す位置は「transaction成功後・パージ前」（inventory-4 §8.2）

**3. 管理画面**

- ダッシュボードに最終再計算時刻（`MAX(refreshed_at)`、JST表示）と「再計算」ボタン（`POST /admin/rankings/refresh`）
- 同期実行し、所要時間・件数・パージ結果を通知に出す。失敗時は前回世代のままエラーを表示してログへ残す。操作ログにも記録する

**4. パージ共通処理（`app/services/cache_purge.py`）**

- パスのリストを受け、`PUBLIC_ORIGIN` から絶対URLにして重複を除き、成功 / 失敗 / 未設定でスキップ のいずれかを返す。例外を呼び出し元へ投げない
- 標準 `urllib.request` で `POST https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/purge_cache`、body `{"files": [...]}`、`Authorization: Bearer {CF_API_TOKEN}`、timeout 5秒。自動retryなし（ADR 014）
- timeout・429・5xx・応答の `success: false` は失敗としてログへ残す。DB更新は取り消さない
- 1要求あたりのURL数上限は実装時にCloudflareの現行ドキュメントで確かめ、超える場合だけ分割する
- `CF_ZONE_ID`・`CF_API_TOKEN` を `app/config.py` へ追加
- 再計算成功後のパージ対象: `/`・`/ranking`・`/ranking/authors`・`/ranking/categories`。snapshotを並び順に使う他のページ（`/authors` の順位順、`app/services/quotes.py` の人気順）はADR 014どおりTTLへ委ねる

**5. 旧snapshotとの突き合わせ（一度だけ・コミットしない）**

- 旧環境の定期再計算（pg_cron `0 3,15 * * *`、UTC）の直後に、`scripts/export_source_db.sh` で原本ダンプを取り直し、続けて旧3表（`quote_ranking_scores`・`author_rankings`・`category_rankings`）を読み取り専用でエクスポートする。保存先は `meigen-fly-private/source-db/` 配下（Git管理外）。接続文字列はキーチェーン `meigen-fly-supabase-db`
- `scripts/rebuild_sqlite.sh` で再構築し、旧 `refreshed_at` を `now` にして再計算した結果と比べる（score・likes件数・rankの一致。浮動小数は相対誤差で比較）
- 差分が出た行は、取得までの間のいいね等で説明できるかを確かめる。結果を「直近の完了状況」に1〜2行で残す

**6. テスト**

- 手計算の小データ: 名言score（`weight` NULL、旧票、1日/7日境界ちょうど、`is_valid=0` の除外、非公開名言も名言表に入る）、著者・カテゴリのz値（標準偏差0を含む）、同点時のID順、親カテゴリへ合算しない、非公開名言を除く
- 計算途中の例外で前回世代が残る。`likes_1d <= likes_7d <= likes_total` のCHECKを満たす
- パージ: 送るURLとヘッダー、timeout・429・5xx・`success: false` で失敗扱いかつ例外なし、未設定でスキップ（HTTPは差し替え）
- ボタン: CSRFなしで拒否、成功で3表が埋まり通知が出る

**完了条件**: テスト・lint成功。ローカルで `uv run python scripts/refresh_rankings.py` 後、公開の `/ranking`（3タブ）とトップにランキングが出る。突き合わせ結果を記録。

### 4-C. 名言・著者のCRUD

- 旧実装の対応箇所: `src/app/(admin)/admin/quotes/`・`authors/`、`src/app/api/admin/quotes/`・`authors/`（`authors/[id]/professions` を含む）、`src/components/admin/quotes/`・`authors/`
- **名言**: 一覧（ページング、IDまたは本文の部分一致での絞り込み程度）・新規・編集・削除。著者 / 出典 / 登場人物の選択、カテゴリの複数選択（level 2だけ。trigger制約あり）、`enable`・`weight`・`slug`・`display_language_preference` 等は `app/schema.py` の列に従う
  - slugの書式は [URL契約表](url-contract.md)§2 の解決規則と矛盾しないように決める（`q{id}` の厳密形や4桁数字をslugにすると解決が変わる）
  - 旧 `PUT /api/admin/quotes`（一覧側の更新）と `quotes/context-note-preview` は、旧画面での用途を確かめてから移植要否を決める
- **著者**: 一覧（名前の部分一致）・新規・編集・削除。職業（順序つき関連）、国（生誕国は最大1件の部分UNIQUE）、生没年のera・precision（inventory-4 §7.2 とCHECK制約）
- 選択肢に使う出典・登場人物・カテゴリ・職業・国・source_typesは既存データから出す（追加・編集は4-D）
- **パージ**（ADR 014の対応表）:
  - 名言: 旧新の詳細URL、URL契約表§8のOG URL（旧新）、`/`・`/quotes`・`/quotes/latest`・`/sitemap.xml`、旧新の著者・出典・登場人物・カテゴリの詳細（1ページ目）。**slugを追加・変更したら `/quotes/q{id}` も含める**（URL契約表§6）
  - 著者: 旧新の `/authors/{slug}` と `og.png`、`/authors`、`/sitemap.xml`、旧新の国・職業の詳細
  - 2ページ目以降のページング、`/quotes/{4桁}`・`/quotations/view/{id}.html` の301はTTL待ちを許容する
- テスト: 作成・更新・削除の成功とDB内容、検証エラーの再表示、CSRFなしの拒否、slugの一意性と書式、パージ対象のURL（slug変更時の `/quotes/q{id}` を含む）、操作ログ

### 4-D. その他マスタのCRUD

- 対象: categories（2階層。親子とlevelの制約はtrigger）/ characters（出典FK）/ sources（source_typesの多対多、著者FK）/ professions（旧は1画面で一覧・追加・名称変更・削除）
- source_typesは選択肢だけ（旧APIもGETのみ）。countriesは旧に追加・編集・削除APIがあるが専用画面は無い。旧フォームでの使われ方を確かめ、必要なら最小の画面を作る
- パージ: 旧新の詳細URL、対応する一覧（`/categories`・`/characters`・`/sources`・`/professions`）、`/sitemap.xml`（sitemap対象の表だけ。URL契約表§7）、影響が明らかな関連ページ
- テスト: 4-Cと同じ観点。カテゴリ階層の制約違反がフォームのエラーになること

### 4-E. 一括登録

- **名言**（旧 `quote-bulk-import-form.tsx`）: 1行1件のタブ区切り「本文 [TAB 英文 [TAB 重み1〜10]]」、3列まで。著者・出典・登場人物のうち最低1つを全行共通で選ぶ。入力 → 確認画面 → 登録の2段階
- **著者**（旧 `author-bulk-import-form.tsx` と `authors/bulk/validate`）: 1〜10件のJSON配列。職業・生誕国は名称で指定する。旧の検証APIが何を確かめていたか（名称の未登録・slug重複等）を読んで同じ範囲を確かめる
- 成否の単位は旧実装を確かめ、既定は全件1トランザクション（1件でも失敗したら登録しない）
- パージ: 大量更新として個別の詳細URLは送らず、対応する一覧・`/`・`/sitemap.xml` だけ（ADR 014）
- テスト: 各入力規則のエラー（列数・重みの範囲・空行・JSON形式・件数上限）、確認画面を経た登録、全件ロールバック

## スコープ境界（フェーズ4全体）

- supercronic登録・`flock`・timeout・Heartbeat・Dockerfile はフェーズ5
- 本物のCloudflare Access・パージAPIでの確認はフェーズ6（ローカルはテスト用の鍵とHTTPの差し替え）
- 複数管理者・ロール・承認フロー・操作履歴のDB表は作らない（ADR 012の再検討条件）
- 一括パージUI・Cache-Tag・旧の名言単位の再検証ボタンは作らない（保存時の自動パージで置き換える。計画書§3.3）
- 旧APIのうち移行・初期設定用（`create-admin-user`・`setup-migration`・`migrate-professions`・`seed-categories`）は移植しない
- HTMLエラーページはフェーズ6で判断する
- DBスキーマ変更は原則なし。必要が生じたら理由を説明してユーザー判断を仰ぐ

## データ準備

- ローカルDB: `data/app.db`（本番相当データ入り）。壊れたら `scripts/rebuild_sqlite.sh` で再構築する（ダンプは `~/prj/meigen-fly-private/source-db/data/`。再取得はキーチェーン `meigen-fly-supabase-db` の接続文字列で、本番へは読み取り専用）
- ranking snapshot 3表は4-Bまで空が正常。再構築すると空に戻るので、必要なら再計算CLIを実行する
- 管理画面の手動確認で `data/app.db` を書き換えた場合も、再構築で戻せる

## 運用ルール

- 完了したタスクは `docs/project-plan.md` のチェックボックスと本ファイルの表へ反映する
- 秘密情報（`SECRET_KEY`・Cloudflareのtoken等）をリポジトリ・シェル設定ファイルへ書かない。ローカルで使う値はその場の環境変数で渡す
- CSP・キャッシュヘッダ・URL互換はテストで担保されている。変更が必要な場合は理由を明記する
- ADRと矛盾する実装が必要になった場合はADRを正とし、ADR自体を変えるべきと判断したらユーザーへ確認する
