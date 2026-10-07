# 次回セッション作業指示: 切替前の残作業

> 本ファイルはセッション間の引き継ぎメモ。このセッションは管理者が手を動かし、Claude CodeまたはCodexが伴走する。完了時は、残す価値のある申し送りをrunbook・計画書・ADRへ移し、本ファイルを次の切替セッション用に更新する。
> 作成日: 2026-10-06（フェーズ5完了・push済みを受けて作成）

## 進捗（2026-10-07）と直近の希望

- runbook §1は実機検証済み。既存のFly app `meigensyu`（owner `katamuki-org`）と`nrt`の`data` Volume 1つ（ID `vol_v3gkk0wjyy2137o4`）を使用。初回デプロイ後のMachineは`185173db303928`の1台で、public IP/serviceはない。初回ビルドは成功したがMachine作成時に支払い情報不足で失敗し、管理者が登録後の再実行で成功した。
- §2.1は一部完了。Cloudflare Tunnel `meigensyu`を作成し、`TUNNEL_TOKEN`をFlyに登録。公開アプリケーションrouteは空。`fly logs`でconnectorの接続登録を確認した。team domainを控え、Google IdPの接続テストで`Your connection works!`を確認した。Zero Trust画面のHEALTHYとGoogleアカウントのMFA確認は未報告。
- `meigensyu.com`はCloudflareのDomainsに未登録。2026-10-07の公開DNS確認では権威NSは`dns1`〜`dns5.name-services.com`、`www`はVercel向けCNAME。Zone ID・`CF_API_TOKEN`は未取得。zoneを追加しても切替まではネームサーバーを変更しない。Free zoneのPending状態は28日で削除されるため、追加時期に注意する。
- `TUNNEL_TOKEN`と`SECRET_KEY`は登録済み。手元の`data/app.db`をVolumeへ配置し、revision `0002`、authors 774件・quotes 1,831件、`/healthz`と`/quotes`の200を確認した。ランキング3テーブルは0件で、Rankingは集計前のため空。R2・Heartbeatを設定するまで`supercronic`は停止中。Machine再起動時にはsupervisordが再び起動するため、残りの設定前に再起動した場合は再度停止する。
- `localhost:8000`の非公開プレビューと一時的な`trycloudflare.com`の外部プレビューを管理者がブラウザで確認した。CSS/JS/画像も200、外部から`/admin`は403。一時Uvicorn・`fly proxy`・Quick Tunnelはすべて停止済み。外部URLは停止後530。既存`www.meigensyu.com`、DNS、Fly public service/IPは変更していない。手順と実機差分はrunbook §5.1・§6へ反映済み。
- runbook・計画書・本ファイルに今回の結果を反映した。R2・Heartbeat・復旧演習は残っているため、切替前準備全体は未完了。

## 次回の開始地点

管理者が再開を依頼したら、以下を順に進める。既存`www.meigensyu.com`と本番DNSは切替セッションまで変更しない。

1. `git status`とFlyのMachine・Volume・secret名・public IPを確認する。`supercronic`は停止中であることを確かめる。
2. §2.1の残り（Zero TrustでTunnelのHEALTHY、Google MFA、zone追加時期・Zone ID・Cache Purge token）を管理者と確認する。Free zoneを追加する場合はPending 28日の期限を踏まえ、ネームサーバー委任は切替セッションまで変更しない。
3. §3のR2バケット・Lifecycle・バケット限定資格情報、§4.1のHeartbeat 2つと通知先を管理者が設定する。
4. 管理者が別ターミナルで残りのsecretを非表示入力で登録する。値はチャットへ貼らない。伴走者は`fly secrets list`で名前だけ確認し、定期ジョブを再開する。
5. バックアップとランキング再計算を手で実行し、R2オブジェクトとHeartbeatの受信を確認する。Rankingは現時点では集計前で空。
6. §7のR2からの復旧演習後、runbook・計画書・本ファイルを更新する。public service/IPと本番DNSは追加・変更しない。

## 目的

[`docs/operations-runbook.md`](operations-runbook.md)のうち**切替前に行ってよい範囲**を実機で完了し、runbookの「未検証」を「検証済み」に置き換える。成果物は次の3つ。

1. 本番Machineが`nrt`で動き、Tunnel connectorがCloudflareへ接続し、public IPもpublic serviceも無い状態
2. バックアップがR2へ実際に保存され、Heartbeatが2つともUptimeRobotへ届いた記録
3. R2のバックアップから復旧する手順を一度通した記録と、実機で分かった差分を反映したrunbook

対象はrunbookの **§1 → §2.1 → §3 → §4.1 → §5.1 → §6（本番相当データの配置）→ §7** である。

## このセッションでやらないこと

- **DNS切替とそれに伴う設定**（runbook §2.2〜2.6・§4.2・§5.2）。`www`のTunnel route、apexの301、Cache Rules、WAF、Access、`/healthz`外形監視は、旧サイトと同じzoneに効くため、最終移行と同じ日に行う。別セッションにする
- 旧環境の書き込み凍結と最終データ移行（`migration-runbook.md` §5の再実行）
- GitHub Actionsの`Deploy` workflowの実行と`FLY_API_TOKEN`の登録（切替後から使う）
- アプリコードの変更。runbookの演習で不具合が見つかった場合だけ直し、理由を報告する

## 役割分担

| 作業 | 誰が | 備考 |
|---|---|---|
| ダッシュボード操作（Cloudflare・R2・UptimeRobot） | 管理者 | 伴走者はrunbookの該当節を示し、控えるべき値の名前を言う |
| 秘密の値の入力（`fly secrets import`） | 管理者 | **別のターミナルで**runbook §5.1の非表示入力を使う。チャットへ貼らない |
| `fly`コマンド（app・Volume作成、deploy、`ips list`、`logs`、`ssh console`、`sftp`） | 伴走者が実行してよい | 管理者が事前に`fly auth login`しておく。秘密を引数に取るコマンドは伴走者が実行しない |
| 実行結果の確認・判断 | 両者 | 期待値はrunbookに書いてある。食い違ったら先に進まず原因を見る |
| runbook・計画書・ADRの更新 | 伴走者 | 検証した節に「検証済み（日付）」を付け、実機との差分を直す |

伴走者への指示: 秘密の値（`TUNNEL_TOKEN`・R2の鍵・Heartbeat URL・`SECRET_KEY`・`CF_API_TOKEN`）を管理者に貼らせない。`fly secrets list`は名前とdigestしか出さないので、登録の確認にはこれを使う。ログや出力に秘密が混ざっていると気づいたら、その場で言う。

## 事前準備（セッション開始前に管理者が済ませる）

- `flyctl`の導入と`fly auth login`（支払い方法の登録を含む）。`fly auth whoami`が通ること
- CloudflareのZero Trustは利用可能で、`meigensyu.com`のzoneは未登録。zone追加と既存DNSレコードの照合は残作業。ドメインのネームサーバー委任変更は切替セッションまで行わない。R2は初回に支払い方法の登録を求められることがある
- UptimeRobotのアカウントと、公式アプリの導入
- `data/app.db`（authors 774・quotes 1,831）はFly Volumeへ初回配置済み。最終移行時には旧環境の最新データから作り直す

## 進め方

runbookの節番号で進め、各節の終わりに結果を確認してから次へ進む。当初計画の1・5の初回デプロイ部分・6は完了済み。以下は全体の作業順であり、完了済みの操作を繰り返さない。

| 順 | runbook | 内容 | 主に動く人 | 完了の確認 |
|---|---|---|---|---|
| 1 | §1 | `fly apps create` / `fly volumes create` | 伴走者 | `fly volumes list`に`data`が`nrt`で1つ |
| 2 | §2.1 | Tunnel作成・team domain・Zone ID・Cache Purge token | 管理者 | 4つの値を管理者が手元に控えた（public hostnameは空のまま） |
| 3 | §3 | R2バケット・30日Lifecycle・バケット限定資格情報 | 管理者 | Lifecycleが`daily/`・30日・Enabled |
| 4 | §4.1 | Heartbeat監視2つ・通知先 | 管理者 | 2つのURLを控え、monitorはpause |
| 5 | §5.1 | secrets登録（別ターミナル）→ 初回デプロイ → 内部確認 | 管理者 → 伴走者 | 下の「§5.1で必ず確かめること」 |
| 6 | §6 | 手元の`data/app.db`をVolumeへ配置 | 伴走者 | `/quotes`に名言が出る。件数が774・1,831 |
| 7 | §3・§4.1 | バックアップとランキングを手で実行 | 伴走者 | R2に`daily/app-*.db`、UptimeRobotに受信時刻、両monitorをpause解除 |
| 8 | §7 | R2から取得 → 手元で検査 → §6の共通手順で入れ替え | 管理者（取得）→ 伴走者 | 入れ替え後も件数が同じ、`/healthz`が200 |
| 9 | — | runbook・計画書・ADRの更新、コミット | 伴走者 | 下の「完了時に行うこと」 |

6を先に行うのは、空のDBをバックアップしても§7の演習にならないためである。ここで置いたデータは最終移行（別セッション）で置き換える。

### §5.1で必ず確かめること

- `fly secrets list`に必要な変数がすべてあり、`CF_ACCESS_AUD`と`ADMIN_DEV_EMAIL`が**無い**
- `fly deploy --remote-only --ha=false --no-public-ips`が成功し、Machineが1台だけ
- `fly ips list`が空。空でなければ`fly ips release`して、理由を報告に書く
- `fly logs`で、`alembic upgrade head`→supervisord→3プロセスの順に起動し、`cloudflared`が`Registered tunnel connection`を出す。Zero TrustのTunnel一覧でHEALTHY
- `fly ssh console`から: `supervisorctl status`で3つがRUNNING、`Host: www.meigensyu.com`付きの`/healthz`が200、Hostなしが400、`PRAGMA journal_mode`が`wal`
- ランキング再計算を手で実行して0で終わる（`UPTIMEROBOT_RANKING_HEARTBEAT_URL`が登録済みなら、この時点でHeartbeatが届く）

### 実機との差分が出たとき

- コマンドの名前・オプション・ダッシュボードの画面がrunbookと違う: runbookを現行に直し、確かめたことを「検証済み」と書く
- ADRの前提が成り立たない（例: Freeプランで使えない設定）: ADRへ日付付きで追記し、報告に書く。黙って別案へ切り替えない
- アプリの不具合: 直すのは最小限にし、テストを足して、別コミットにする

## 完了時に行うこと

- runbookの各節の先頭に「検証済み（2026-10-nn）」または「未検証」を明記する。冒頭の「外部サービスの操作は全章未検証」を実態に合わせて書き換える
- `docs/project-plan.md`: フェーズ5の`[ ]`項目のうち済んだものを`[x]`にし、更新日と§12「次のアクション」を直す（次は最終移行と切替）
- 実機で得た秘密でない値（app名、Machine ID、Volume ID、イメージサイズ、初回デプロイの所要時間、R2バケット名、Tunnel名）はrunbookに書いてよい。account ID・Zone ID・AUDは書かない
- ドキュメントの変更を1コミットにし、管理者の指示でpushする（pushで`Test` workflowが走る）
- 本ファイルは、次の切替セッションの指示へ書き換える（削除ではなく更新）

## 完了時の報告

- runbookの節ごとに: 検証済み／未検証／実機との差分
- 管理者が控えた値の**名前の一覧**（値は書かない）と、登録済みのsecretsの名前
- UptimeRobotの受信時刻、R2のオブジェクト名、復旧演習の結果（件数・revision）
- 切替セッションに持ち越す作業と、その前提（DNS TTL短縮の要否、旧サイトのレコードの種類）
