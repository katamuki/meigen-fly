# アーキテクチャ決定記録: Cloudflareオリジン保護

## ステータス

**確定: Cloudflare TunnelでFly.ioの公開入口をなくす**（2026-07-14決定）

## コンテキスト

`*.fly.dev`やFly.ioの公開IPからオリジンへ直接到達できると、CloudflareのWAF、レート制限、Accessを迂回できる。匿名いいねで利用する`CF-Connecting-IP`も、信頼できない経路から同名ヘッダーを送信できる状態では信用できない。

本番はSQLite Volumeを持つ単一Machineで、日次ジョブのため常時起動する。初期構成では単一Machine・短時間のデプロイ停止を受容し、オリジン保護のためだけに複数Machineやロードバランサーを追加しない。

## 決定

- 本番への唯一の公開HTTP経路として、同一Fly Machine上で動かす**remotely-managed Cloudflare Tunnel**を採用する。`cloudflared`はCloudflareへoutbound-onlyで接続し、`www.meigensyu.com`を`http://127.0.0.1:8000`へ転送する。
- Fly Appから公開IPv4・IPv6を解放し、`fly.toml`に公開`http_service`または公開`services`を定義しない。Uvicornは`127.0.0.1:8000`だけにbindし、インターネット、Fly Proxy、6PNから直接受けない。
- 本番TunnelのPublished application routeは`www.meigensyu.com`だけに限定し、wildcardを使わない。未一致routeは404にする。apex `meigensyu.com`にはoriginless redirect用のproxied Aレコード`192.0.2.0`を設定し、Cloudflare Redirect Ruleでpathとqueryを維持した301または308を`www.meigensyu.com`へ返す。
- Tunnelで`Host`を一律上書きせず、FastAPIでも環境ごとの許可Hostを完全一致で限定する。本番は`www.meigensyu.com`だけを許可する。`*.fly.dev`や未知のHostをcanonical hostへリダイレクトせず、400または421で拒否する。
- 専用の検証環境は設けず、ローカルと本番の2環境で運用する。本番公開前のアプリ確認はローカルとFlyの管理経路から行い、Cloudflare経由の確認はDNS/Tunnel切替直後に本番URLで行う。
- Tunnelは管理者認証の代替にしない。`/admin`とその全配下ではADR 012のCloudflare Accessとアプリ側の最小限のJWT検証を維持する。
- `CF-Connecting-IP`はTunnel経由のHTTPリクエストでのみ信頼し、レート制限などbest-effortな補助信号に限定して使う。認証identityには使わず、`X-Forwarded-For`へのfallbackもしない。Tunnel以外の公開経路が存在しないため、アプリ側での網羅的なヘッダー形式検証は行わない。
- Authenticated Origin Pulls、Cloudflare IPレンジallowlist、独自secret headerは併用しない。Tunnelでは公開TLSオリジンが存在せず、これらを重ねても初期構成の防御効果に対して運用負担が大きいためである。

## プロセス・秘密情報

- `supervisord`がUvicorn、`cloudflared`、supercronicを監督し、子プロセス異常終了時に再起動する。公開serviceを持たない常時起動Machineにはrestart policy `always`を明示する。
- `cloudflared`はコンテナ内でバージョンを固定し、自動更新を使わない。通常の依存更新時またはセキュリティ修正版公開時にイメージを更新する。
- remotely-managed Tunnel tokenは`cloudflared`標準の`TUNNEL_TOKEN`環境変数としてFly secretに保存し、リポジトリ、イメージ、ログへ出さない。漏洩疑い時はtokenを更新し、旧tokenの確立済みconnectionをCloudflareダッシュボードから切断して`cloudflared`を再起動する。定期rotationや事前演習は必須にしない。

## ヘルスチェック・デプロイ

- Fly ProxyのHTTP service health checkを正本にしない。`GET /healthz`を`private, no-store`かつCloudflare Cache RuleのBypass対象とし、外形監視から1〜5分間隔で確認する。キャッシュ可能なトップページはorigin停止時にもHITし得るため、外形監視に使わない。
- `/healthz`はUvicornの応答とSQLiteへの軽いreadiness確認だけを行い、秘密情報や詳細な内部状態を返さない。
- デプロイ直後に`https://www.meigensyu.com/healthz`をsmoke testする。失敗時はログを確認し、DB schemaとの後方互換性を確認できる場合だけ直前イメージへrollbackする。非互換migration適用後はforward fixを優先し、DB自体の復旧が必要な場合はADR 003・004の手順に従う。
- 単一Machine・単一Volumeではzero-downtime deployを保証しない。デプロイ中の短い5xxを受容し、blue-green構成やTunnelだけの冗長化は行わない。
- 初回切替は、公開Fly service/IPを維持したままTunnel経由を検証し、その後に公開serviceを削除してpublic IPv4/IPv6を解放する二段階で行う。緊急時にFlyの管理経路から直前イメージへ戻せる手順を残す。

## 公開前検証

- `fly ips list`にpublic IPv4/IPv6がなく、デプロイ後のMachine実設定に公開serviceがない。
- `https://<app>.fly.dev/`および解放前の旧Anycast IPへ直接到達できない。
- `www.meigensyu.com`だけがTunnel経由で正常応答し、未知のHostと未一致Tunnel routeが拒否される。
- apexのproxied placeholder DNSとRedirect Ruleにより、`meigensyu.com`のpath・queryが1 hopの301または308で`www.meigensyu.com`へ維持される。
- `/healthz`がCloudflareとブラウザでキャッシュされず、外形監視とデプロイ後smoke testがorigin停止を検知する。
- 匿名いいねPOSTで`CF-Connecting-IP`から送信元IPを取得できる。
- Cloudflare WAFとレート制限が匿名いいね経路に適用され、`cloudflared`停止時に迂回経路がなくfail closedになる。
- public IP削除後も`fly ssh console`、`fly logs`、`fly deploy`による管理・復旧ができる。

## 再検討条件

- Machineを複数台または複数リージョンへ増やす場合
- SQLiteを共有・複製可能なDBへ移行し、zero-downtime deployを目指す場合
- 同一Cloudflare zoneのWorkerから匿名いいね等をoriginへsubrequestする場合
- Cloudflare Tunnelを利用できない契約・障害・技術要件が生じた場合。この場合は、公開Fly Proxy + exact Host + Cloudflareで上書きするsecret headerを代替候補とし、AOPはraw TCPと独自TLS終端の運用負担を含めて再評価する。

## 採用しなかった選択肢

- **Authenticated Origin Pulls**: Fly Proxyの通常のTLS終端ではFastAPIがクライアント証明書を必須検証できない。raw TCP、専用IPv4、Caddy/nginx等のTLS終端と証明書運用が必要になり、初期の個人運用には過剰なため不採用。
- **Cloudflare IPレンジallowlist**: 公開入口を残し、IPリスト更新とアプリ側判定が必要になる。Tunnelで公開入口をなくす方が境界が単純なため不採用。
- **独自secret header**: 公開Fly Proxyを残す代替策としては有効だが、secret漏洩時に再送できる。Tunnel tokenだけを管理する方が単純なため不採用。
- **複数Tunnel replica・複数Machine・Cloudflare Load Balancer**: SQLite Volumeとアプリ自体が単一障害点であり、Tunnelだけを冗長化しても初期構成の可用性は大きく改善しないため不採用。

## 参考

- [Cloudflare Tunnel: Routing](https://developers.cloudflare.com/tunnel/routing/)
- [Cloudflare Tunnel: Tunnel tokens](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens/)
- [Cloudflare DNS: Originless setups](https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/#originless-setups)
- [Cloudflare: Restrict external connections](https://developers.cloudflare.com/learning-paths/prevent-ddos-attacks/advanced/prevent-external-connections/)
- [Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/)
- [Fly.io: Connect to an App Service](https://fly.io/docs/networking/app-services/)
- [Fly.io: App configuration](https://fly.io/docs/reference/configuration/)
- [Fly.io: Health Checks](https://fly.io/docs/reference/health-checks/)

## 追記（2026-10-06、フェーズ5-C）

初回切替について、上の「公開Fly service/IPを維持した二段階」の記述は旧案である。5-Aで公開serviceなし・Uvicorn loopbackだけの設定が完成したため、初回デプロイから公開入口を持たず、管理経路で内部確認する。public IPが割り当てられた場合も初回デプロイ後に解放し、Tunnel routeの公開前にserviceなしを確認する。旧サイトと同じzoneを使うため、Tunnel connectorだけを先に接続し、www route・DNS・Access・Cache Rules・WAFはフェーズ6の切替時に設定する。

Access applicationを切替時に作るため、初回デプロイ時の`CF_ACCESS_AUD`は実JWTと一致しない`pending-cutover`とし、管理画面を閉じる。切替時に実AUDへ更新してからrouteを公開する。秘密情報や認証検証の実装は変更しない。[運用runbook](../operations-runbook.md)を実行手順の正本とする。
