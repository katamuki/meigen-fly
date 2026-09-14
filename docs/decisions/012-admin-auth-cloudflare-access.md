# アーキテクチャ決定記録: 管理画面の認証

## ステータス

**確定: Cloudflare Access + 外部IdPを採用**（2026-07-14簡略化。2026-09-13にフェーズ4着手時の実装方針を追記）

## コンテキスト

管理画面は本人または少人数が利用し、機微な個人情報は扱わない。一方で、名言の作成・更新・削除を行うため、公開画面から分離された認証は必要である。アプリ独自のパスワード、リセット、MFAを実装せず、Cloudflare Accessへ委譲する。

## 決定

- `/admin`とその全配下をCloudflare AccessのSelf-hosted applicationで保護する。
- Access policyはdeny by defaultとし、管理者のメールアドレスを完全一致で列挙する。ドメイン全体や`Everyone`は許可しない。
- 一次認証はGoogle等の外部IdPへ委譲し、MFAはIdP側で有効化する。Access independent MFA、認証器種別の強制、8時間ごとの一律再認証は初期要件としない。
- FastAPIはAccessが付与する`Cf-Access-Jwt-Assertion`を公式ライブラリまたは小さな共通middlewareで検証し、少なくとも署名、`iss`、管理画面applicationの`aud`、有効期限、emailを確認する。不正または欠落時は403とする。
- 初期管理者が本人だけの場合、アプリ内の`owner`/`editor`ロール、`iss + sub`対応表、独自ログインCookieを作らない。管理者追加や権限差が必要になった時点で認可モデルを追加する。
- `/login`は`/admin`へ302でリダイレクトしてAccess認証を開始し、ログアウトはCloudflare Accessのlogout endpoint（`/cdn-cgi/access/logout`）を使う。行き先を末尾スラッシュ付きの`/admin/`にしないのは、既存の末尾スラッシュ除去で`/admin`へ301され二重リダイレクトになるため（2026-09-13修正）。
- 旧サイトの`/403`ページは移植しない。許可されていない利用者はAccessが自身の拒否画面で止め、アプリでのJWT検証失敗は403応答とする（2026-09-13追記）。
- 管理画面レスポンスは`Cache-Control: private, no-store`とする。
- 状態変更はPOST/PUT/PATCH/DELETEに限定し、CSRF token（または同等のフレームワーク対策）を必須とする。`Origin`完全一致やFetch Metadataの検証は任意の追加防御とし、初期必須にしない。管理画面は既にAccessの内側にある。
- 作成・更新・削除は管理者email、操作、対象、時刻が分かるアプリログへ記録する。AccessとIdPの詳細ログ相関基盤は作らない。

## 実装方針（2026-09-13、フェーズ4着手時に追記）

- **JWT検証**: PyJWT（`pyjwt[crypto]`）を使う。`{CF_ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs`の公開鍵を`PyJWKClient`で取得・キャッシュし、`Cf-Access-Jwt-Assertion`ヘッダーをRS256で検証する。`iss`は`CF_ACCESS_TEAM_DOMAIN`（`https://<team>.cloudflareaccess.com`）、`aud`は`CF_ACCESS_AUD`と一致し、`exp`があり、`email`が空でないことを確認する。Pythonの標準ライブラリだけではRS256を検証できないため、この依存は追加する。
- **設定不足**: `CF_ACCESS_TEAM_DOMAIN`・`CF_ACCESS_AUD`・`SECRET_KEY`のいずれかが無ければ、下記の開発用迂回を除き管理画面全体を403にし、ログへ残す。
- **CSRF**: 標準`hmac`と`SECRET_KEY`で「発行時刻 + HMAC-SHA256(管理者email | 発行時刻)」のtokenを作り、フォームの隠しフィールドで送る。有効期限は12時間、比較は`hmac.compare_digest`。独自のセッションCookieは発行しない。
- **フォーム**: 管理画面の入力は`application/x-www-form-urlencoded`に限り、`python-multipart`は導入しない。ファイルアップロードは作らない（旧サイトの一括登録もtextarea入力）。本文は上限つきで読み、Pydanticモデルで検証する。
- **ローカル開発用の迂回**: `ADMIN_DEV_EMAIL`があり、かつ`CF_ACCESS_AUD`が未設定で、`PUBLIC_ORIGIN`のホストが`localhost`または`127.0.0.1`のときだけ、JWT検証を省略してそのemailを管理者とする。本番は`PUBLIC_ORIGIN`が`https://www.meigensyu.com`のため有効にならない。CSRF検証は迂回しない。ローカルにAccessが無く、迂回が無いと管理画面をブラウザで確認できないために設ける。

## オリジン保護との境界

ADR 013どおりCloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除する。JWT検証は設定ミスに対する追加防御として維持するが、独立した認証製品相当の機能はアプリへ再実装しない。

## 復旧

IdPまたはAccessへログインできない場合は、Cloudflare/Fly.ioの管理経路から設定を復旧する。共有Basic認証や恒久的なbreak-glass URLは設けない。複数管理者、専用復旧CLI、定期的な障害演習は必要になった時点で追加する。

## 検証

- 未認証利用者が`/admin`と全配下へ入れない。
- 許可した管理者だけがログインできる。
- JWTなし、偽署名、異なる`aud`、異なる`iss`、期限切れ、email欠落をアプリが拒否する。
- 管理画面と`/login`がCloudflareとブラウザでキャッシュされない。
- CSRF tokenなし・改ざん・期限切れの状態変更を拒否する。
- 開発用迂回が、`CF_ACCESS_AUD`の設定時や`PUBLIC_ORIGIN`がlocalhost以外のときに有効にならない。
- `/admin`配下の全routeに認証の依存関数が付いている。

## 再検討条件

- 管理者が複数になり権限差が必要になる
- 承認フロー、操作監査、即時の個別失効が事業要件になる
- 機微情報や金銭を扱う管理機能を追加する

## 参考

- [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/)
- [Cloudflare Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
