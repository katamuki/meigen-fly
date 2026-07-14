# アーキテクチャ決定記録: 管理画面の認証

## ステータス

**確定: Cloudflare Access + 外部IdPを採用**（2026-07-14簡略化）

## コンテキスト

管理画面は本人または少人数が利用し、機微な個人情報は扱わない。一方で、名言の作成・更新・削除を行うため、公開画面から分離された認証は必要である。アプリ独自のパスワード、リセット、MFAを実装せず、Cloudflare Accessへ委譲する。

## 決定

- `/admin`とその全配下をCloudflare AccessのSelf-hosted applicationで保護する。
- Access policyはdeny by defaultとし、管理者のメールアドレスを完全一致で列挙する。ドメイン全体や`Everyone`は許可しない。
- 一次認証はGoogle等の外部IdPへ委譲し、MFAはIdP側で有効化する。Access independent MFA、認証器種別の強制、8時間ごとの一律再認証は初期要件としない。
- FastAPIはAccessが付与する`Cf-Access-Jwt-Assertion`を公式ライブラリまたは小さな共通middlewareで検証し、少なくとも署名、`iss`、管理画面applicationの`aud`、有効期限、emailを確認する。不正または欠落時は403とする。
- 初期管理者が本人だけの場合、アプリ内の`owner`/`editor`ロール、`iss + sub`対応表、独自ログインCookieを作らない。管理者追加や権限差が必要になった時点で認可モデルを追加する。
- `/login`は`/admin/`へリダイレクトしてAccess認証を開始し、ログアウトはCloudflare Accessのlogout endpointを使う。
- 管理画面レスポンスは`Cache-Control: private, no-store`とする。
- 状態変更はPOST/PUT/PATCH/DELETEに限定し、CSRF tokenまたは同等のフレームワーク対策に加えて、`Origin`の完全一致を確認する。Fetch Metadataは追加の軽量な防御として利用できる。
- 作成・更新・削除は管理者email、操作、対象、時刻が分かるアプリログへ記録する。AccessとIdPの詳細ログ相関基盤は作らない。

## オリジン保護との境界

ADR 013どおりCloudflare Tunnelを唯一の公開HTTP経路とし、Flyのpublic IP/serviceを削除する。JWT検証は設定ミスに対する追加防御として維持するが、独立した認証製品相当の機能はアプリへ再実装しない。

## 復旧

IdPまたはAccessへログインできない場合は、Cloudflare/Fly.ioの管理経路から設定を復旧する。共有Basic認証や恒久的なbreak-glass URLは設けない。複数管理者、専用復旧CLI、定期的な障害演習は必要になった時点で追加する。

## 検証

- 未認証利用者が`/admin`と全配下へ入れない。
- 許可した管理者だけがログインできる。
- JWTなし、偽署名、異なる`aud`、期限切れをアプリが拒否する。
- 管理画面と`/login`がCloudflareとブラウザでキャッシュされない。
- CSRF tokenなし、または異なるOriginからの状態変更を拒否する。

## 再検討条件

- 管理者が複数になり権限差が必要になる
- 承認フロー、操作監査、即時の個別失効が事業要件になる
- 機微情報や金銭を扱う管理機能を追加する

## 参考

- [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/)
- [Cloudflare Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
