# アーキテクチャ決定記録: SQLiteの永続化・日次バックアップ・復旧

## ステータス

**確定: 単一Fly Machine + Fly Volume + 日次R2バックアップを採用**（2026-07-14簡略化）

> 追記（2026-07-17）: 本番実測では、likes・中間表・snapshot等を含むDB全体は20,833行（下記「約3,000行」は主要コンテンツの規模）。DB全体でも数MB程度の小規模に変わりなく、決定内容は変わらない。

## コンテキスト

データは約3,000行で、書き込みは管理操作と匿名いいねに限られる。自動フェイルオーバーは初期要件とせず、正常時に最大約24時間分の更新を失う可能性と手動復旧を許容する。

## 決定

- SQLiteは東京`nrt`の単一Fly Machineに接続したFly Volume `/data`で運用する。
- LiteFS、Litestream、複数Machineによる自動フェイルオーバーは初期導入しない。
- 毎日1回、`sqlite3.Connection.backup()`で一貫した一時DBを作り、`PRAGMA integrity_check`後にCloudflare R2へ保存する。稼働DBを単純に`cp`しない。
- R2の`daily/`配下へUTC日時を含む一意なオブジェクト名で保存し、同一キーを上書きしない。Lifecycleで各オブジェクトを30日後に自動削除する。Bucket LockとFly Volume snapshotの追加設定は必須としない。
- バックアップ成功時だけ専用のUptimeRobot Heartbeat URLへpingする。予定時刻までにpingがなければ公式アプリPushを主、メールを予備として通知し、最新成功時刻を確認できるログも残す。アプリ内に独自の鮮度監視機能は作らない。
- 大きなデータ移行または破壊的migrationの前にはオンデマンドバックアップを取得する。通常の小さなmigrationでは任意とする。

## migration時の手順

1. 書き込みを停止するか、短いmaintenance windowを設ける。
2. 必要に応じてオンデマンドバックアップを取得する。
3. `alembic upgrade head`を実行する。
4. `/healthz`と主要ページを確認して書き込みを再開する。

失敗時は対応するアプリ版へ戻し、必要なら直前または日次バックアップから手動復元する。

## 復旧手順

1. アプリの書き込みを停止する。
2. R2から対象バックアップを別パスへ取得する。
3. `PRAGMA integrity_check`、Alembic revision、主要テーブル件数を確認する。
4. 必要なrevisionを適用し、検証済みDBへ切り替える。
5. `/healthz`、検索、管理画面、いいねを確認して再開する。

## 運用・検証

- バックアップ成功時のHeartbeat pingと、未着時のアプリPush・メール通知をリリース前に確認する。
- 復元確認は初回リリース前、大きなスキーマ変更後、または四半期を目安に実施する。月次演習は必須としない。
- 暫定目標は正常時RPO約24時間、RTO数時間以内とする。

## 再検討条件

数分の停止も許容できない、自動フェイルオーバーが必要、または更新頻度が大きく増えた場合は、継続レプリケーションやマネージドDBを再評価する。

## 参考

- [SQLite Online Backup API](https://sqlite.org/backup.html)
- [Fly Volumes](https://fly.io/docs/volumes/overview/)
- [Cloudflare R2 Object Lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)
- [UptimeRobot Heartbeat Monitoring](https://uptimerobot.com/help/heartbeat-monitoring/)
- [UptimeRobot Mobile App](https://uptimerobot.com/mobile-app/)

## 追記（2026-10-06、フェーズ5-C）

R2へのアップロードは`boto3`を追加せず、標準ライブラリの`hashlib`・`hmac`・`urllib.request`でSigV4署名した単一PUTとする。数MBのDBにmultipartは不要。キーは`daily/app-<UTC日時（秒まで）>.db`、圧縮なし。R2必須設定が不足したら欠けた変数名を示して非ゼロ終了する。Heartbeat URLと署名・鍵はログに出さない。

復旧の具体的なコマンドは[運用runbook §6・§7](../operations-runbook.md#6-sqliteファイルの配置と入れ替え最終移行)。R2 dashboardから手元へ取得し、検査して別名でVolumeへ置き、Uvicorn・supercronicを止めて旧DB/WAL/SHMをまとめて退避する。cloudflaredは止めない。ローカル演習はR2取得を本番相当の手元DBで代用した。本物のR2取得・通知・復元検収は管理者がリリース前に行う。
