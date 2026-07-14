# アーキテクチャ決定記録: 管理者認証

## ステータス

**確定: Cloudflare Access + 外部IdP + MFAを採用する**（2026-07-14決定）

## コンテキスト

本番の公開オリジンは `https://www.meigensyu.com/` とする。管理者の接続元IPアドレスは固定できないため、IP allowlistを管理者認証の前提にできない。また、Basic認証はMFA、利用者別の失効、セッション管理、監査を扱いにくいため採用しない。

管理画面は少人数で利用するが、コンテンツの一括更新、削除、Cloudflareキャッシュパージなど影響の大きい操作を持つ。アプリが管理者パスワードやTOTP秘密鍵を独自管理せず、フィッシング耐性のある認証器を利用できる構成を優先する。

## 決定

- `https://www.meigensyu.com/admin` とその全配下をCloudflare AccessのSelf-hosted applicationとして保護する。Access policyはdeny by defaultとし、許可する管理者のメールアドレスを完全一致で列挙する。`Everyone`、メールドメイン全体、One-time PIN利用者全体を許可するルールは作らない。
- 一次認証はGoogle、Microsoft Entra IDなどの外部IdPへ委譲する。IdPの種類やAMR claim実装にかかわらず、管理画面applicationではCloudflare Access independent MFAを必須にする。認証器はpasskey、biometrics、FIDO2 security keyを優先し、TOTPを許可する場合もメールOne-time PINだけによる管理者認証は採用しない。IdP側のMFAは追加防御として利用できるが、初期構成ではAccess independent MFAの代替としない。
- Access policyの再評価とindependent MFAの再要求を8時間以内に行うため、Accessのpolicy/application session、global session、independent MFA session durationをすべて8時間以下に設定する。管理画面ではCloudflare One Clientによる認証を有効にせず、IdP MFAのAMR matchingによるindependent MFA省略も有効にしない。管理者の無効化や侵害疑いがある場合は、即時のアプリ側拒否手段として最初に`admin_users`を無効化し、続いてIdPとAccess policyを無効化し、Cloudflare Accessで対象ユーザーを`Revoke`する。全管理者を止める必要がある場合はapplicationの`Revoke existing tokens`を使う。AccessやIdPだけを失効しても、発行済みJWTが期限までオリジンへ直接再送される可能性があるため、`admin_users`無効化とD14を省略しない。
- FastAPIは`/admin`とその全配下への全リクエストで`Cf-Access-Jwt-Assertion`を検証する。Cloudflare Accessの公開鍵による署名と許可アルゴリズムに加え、`iss`、管理画面application固有の`aud`、`exp`、`nbf`、妥当な`iat`、`type == "app"`、非空の`sub`と確認済みemailを確認し、欠落・不正・期限切れはfail closedで403にする。公開鍵は適切にキャッシュし、鍵ローテーション時に再取得する。
- JWT検証後、`iss`と`sub`の組を不変の認証identity keyとして`admin_users`に対応付け、`is_active`とroleをアプリ側で認可する。確認済みemailはAccess policyの完全一致許可と表示・監査に使い、JWTとDBで不一致ならfail closedにする。email変更やIdP変更時は自動で再紐付けせず、`owner`または復旧CLIが新identityを明示登録する。初回`owner`もFly.ioの管理経路からCLIで登録する。`admin_users`には認証用パスワード、TOTP秘密鍵、リカバリーコードを保存しない。roleは少なくとも`owner`と`editor`を表現できる構造にする。
- Cloudflare Access JWTを管理者セッションとして扱い、アプリ独自のログインCookieは発行しない。既存の`/login`はアプリ独自のログインフォームを表示せず、`/admin/`へ一時リダイレクトしてAccess認証を開始する。管理画面のログアウト操作は`https://www.meigensyu.com/cdn-cgi/access/logout`へ遷移し、Access sessionを終了する。
- 全管理画面レスポンスを`Cache-Control: private, no-store`とし、状態変更はPOST/PUT/PATCH/DELETEに限定する。状態変更ではAccess identityと短い有効期限にbindした署名付きCSRF token、環境ごとの`PUBLIC_ORIGIN`との完全一致`Origin`、Fetch Metadataを検証する。本番の`PUBLIC_ORIGIN`は`https://www.meigensyu.com`に固定し、SameSite属性だけをCSRF対策とはみなさない。
- 認証試行、MFA、Access policy拒否、session失効はCloudflare AccessとIdPの監査ログを正本とする。FastAPIはJWT・`admin_users`の認可拒否、作成・更新・削除、一括処理、権限変更、パージ操作を構造化監査ログへ記録する。両者を時刻、`iss`、`sub`、emailで相関できるようにし、保持・export期間は監視運用の決定時に定める。秘密情報とAccess JWTそのものはログへ出さない。
- Web経由のBasic認証や共有パスワードをbreak-glass経路として残さない。管理者を原則2アカウント以上登録し、認証器とIdPのrecovery codeを安全に分散保管する。全管理者が利用不能になった場合はFly.ioの管理経路からCLIで`admin_users`を復旧するrunbookを使用する。

## D14（オリジン保護）との境界

FastAPIによるAccess JWT検証により、`*.fly.dev`などから`/admin`またはその配下へ直接到達しても、正しく署名された管理画面用JWTがなければ拒否できる。ただし、これはサイト全体のCloudflare迂回を防ぐものではない。

匿名いいね、検索、公開ページを含むオリジン全体の保護はD14として別途決定する。D14確定後も、管理画面のAccess JWT検証は多層防御として維持する。

## 実装・検証

- Access applicationが`/admin`自体とその全配下のルート、HTMX endpoint、管理用APIを漏れなく含むことを自動検査する。
- 正常JWTのほか、JWTなし、偽署名、異なる`iss`、異なる`aud`、期限切れ、未来の`nbf`/`iat`、`type != "app"`、`sub`/email欠落、無効管理者、role不足をテストする。
- IdPの種類やAMR claimの有無にかかわらずAccess independent MFAが要求され、未登録・未実施の利用者を拒否することをデプロイ前に確認する。各session durationが8時間以下で、8時間経過後の次回アクセス時にAccess policyの再評価とindependent MFAが行われることを確認する。
- JWTと`admin_users`のemail不一致、未登録`iss`/`sub`、IdP切替、管理者追加・無効化のcontrol-plane不整合をfail closedにできることを確認する。
- 設定した`PUBLIC_ORIGIN`以外のOrigin、CSRF tokenなし、cross-site Fetch Metadataによる状態変更を拒否する。本番では`https://www.meigensyu.com`だけを許可する。
- `*.fly.dev/admin/*`への直接アクセスと、偽造した`Cf-Access-Jwt-Assertion`が403になることをE2Eで確認する。
- `/admin`とその全配下、および`/login`がCloudflareとブラウザでキャッシュされないことを確認する。
- 通常ログアウト、ユーザー単位`Revoke`、application単位`Revoke existing tokens`、管理者無効化、IdP障害、Cloudflare Access障害、公開鍵ローテーション、CLI復旧を演習する。

## 採用しなかった選択肢

- **Basic認証**: MFA、個人別の失効、セッション制御、監査が弱く、共有資格情報になりやすいため不採用。
- **アプリ独自のパスワード + TOTP**: 強化は可能だが、password hash、TOTP秘密鍵、recovery、brute-force対策をアプリで保守する必要があるため不採用。
- **メールOne-time PIN単独**: メールアカウント侵害が管理画面侵害へ直結し、passkey/FIDO2ほどのフィッシング耐性がないため不採用。
- **アプリ独自WebAuthn**: 強い認証を実現できるが、登録・復旧・認証器管理の実装負担が初期規模に対して大きいため不採用。

## 参考

- [Cloudflare Access: Publish a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
- [Cloudflare Access: Validate JWTs](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [Cloudflare Access: Enforce MFA](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/mfa-requirements/)
- [Cloudflare Access: Session management](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/)
- [Cloudflare Access: Application token claims](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [NIST SP 800-63B: Phishing Resistance](https://pages.nist.gov/800-63-4/sp800-63b.html#phishres)
