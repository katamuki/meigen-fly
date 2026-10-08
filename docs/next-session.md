# 次回セッション作業指示: 切替前の残作業

> 本ファイルはセッション間の引き継ぎメモ。切替前準備が完了したら、次の切替セッションの指示へ更新する。秘密の値は記録しない。
> 更新日: 2026-10-08

## 現在地

- Git: 2026-10-08の開始時点で`main`は`origin/main`より`50687b8`の1コミット先、作業ツリーはクリーンだった。このセッションの文書変更は1コミットにまとめる。pushは管理者の指示まで行わない。
- Fly: app `meigensyu`（owner `katamuki-org`）、Machine `185173db303928`が`nrt`で1台起動。暗号化Volume `data`（`vol_v3gkk0wjyy2137o4`、1GB）を接続。public IPとMachine serviceはない。2026-10-08に残り6件のsecretを一括登録・反映し、必要な8件はすべてDeployed。`cloudflared`・`uvicorn`・`supercronic`はRUNNING。
- Cloudflare: Tunnel `meigensyu`は一覧で「正常」、レプリカ1、routeなし。Google IdPの接続テストは成功し、Googleアカウントの2段階認証は有効。`meigensyu.com`のzoneは未追加。切替日が未定のため追加を保留し、Zone IDとCache Purge tokenも未取得。公開DNSの権威NSは`name-services.com`、`www`はVercel向けCNAMEのまま。
- FlyのDB: 手元の`data/app.db`を配置済み。Alembic revision `0002`、authors 774件、quotes 1,831件。`/healthz`と`/quotes`は内部で200。localhostと一時的な`trycloudflare.com`の画面確認は完了し、一時プレビューは停止済み。2026-10-08の手動再計算で`quote_ranking_scores`は1,831件、`refreshed_at`は`2026-10-08T03:46:19.321958Z`。
- 画面確認: 2026-10-08にFlyへの非公開ローカルプレビューで名言・著者・カテゴリのRankingをブラウザ確認。復元後のランキングが画面に表示された。Mac上では手元DBの作業用コピーで`/admin`を確認（公開名言1,785件・非公開名言46件・著者774件）。Fly側の`/admin`は切替前の設定どおり403。確認用サーバーとプロキシはセッション終了時に停止し、作業用コピーは削除した。DNSと公開routeは変更していない。
- R2: 管理者がサブスクリプションを有効化。非公開バケット`meigensyu-backups`をAPAC・Standardで作成し、`daily/`を30日後に削除するEnabledのLifecycleを確認。バケット限定Object Read & WriteのAccount APIトークンを作成し、S3資格情報を手元に保管済み。2026-10-08の手動バックアップは`daily/app-20261008T034608Z.db`・3,059,712バイト。R2 dashboardから取得し、Flyへの復旧演習を完了した。復元後にランキングを再計算済み。
- 定期ジョブ: 管理者の2026-10-08の判断により、有料UptimeRobot Heartbeatと自動通知は使わない。バックアップはR2の最新オブジェクト、ランキングはsnapshot表の`refreshed_at`、両方の成功/失敗はFlyログで手動確認する。Heartbeat URLはFlyへ登録しない。UptimeRobotの`/healthz`外形監視は切替時に別途扱う。

## 次の開始地点

1. 次の定期実行後にバックアップの最新オブジェクトとランキングの`refreshed_at`、Flyログを確認する。予定時刻はランキングが03:00・15:00 UTC、バックアップが18:00 UTC。
2. ローカル管理画面で管理機能リンクの間隔が詰まって表示された。`app/static/admin.b242e875.css`の`--sp-5`はtokens CSSで未定義。切替前に表示を修正・確認する。
3. 定期実行と画面確認の結果を文書へ追記する。pushは管理者の指示までしない。
4. 切替日が決まったらCloudflare zone追加時期を決め、既存DNSレコードの種類・値・TTLを再照合する。旧サイトの最新データ移行は、切替直前の書き込み凍結後に行う。

## 守る範囲

- 稼働中の`www.meigensyu.com`、本番DNS、Flyのpublic IP・serviceを変更しない。Tunnelの公開route、Access、Cache Rules、WAF、apex redirect、外形監視は切替セッションで設定する。
- Cloudflare Free zoneはPendingのまま28日で削除される。追加前に切替時期と既存DNSレコードの照合手順を整理する。ネームサーバー委任は切替時まで変更しない。
- 旧環境の書き込み凍結と最終データ移行、GitHub ActionsのDeploy workflow、`FLY_API_TOKEN`登録は切替セッションで行う。
- 秘密の値をチャット・文書・コマンド引数・ログへ出さない。Flyへの値の入力は管理者が別ターミナルで行い、伴走者は名前だけを確認する。
- アプリコードは演習で不具合が見つかった場合だけ最小限修正する。

## 完了の記録

runbookの§3・§4.1・§5.1・§7に手動実行の検証日と実機差分を記録済み。次の定期実行の結果を追記する。account ID・Zone ID・AUD・資格情報は書かない。次の切替セッションに持ち越すDNSレコードの種類とTTLも整理する。
