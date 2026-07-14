# アーキテクチャ決定記録: SQLiteの永続化・日次バックアップ・復旧

## ステータス

**確定: 単一Fly Machine + Fly Volume + 日次R2バックアップを採用**（2026-07-14簡略化）

## コンテキスト

データは約3,000行で、書き込みは管理操作と匿名いいねに限られる。自動フェイルオーバーは初期要件とせず、正常時に最大約24時間分の更新を失う可能性と手動復旧を許容する。

## 決定

- SQLiteは東京`nrt`の単一Fly Machineに接続したFly Volume `/data`で運用する。
- LiteFS、Litestream、複数Machineによる自動フェイルオーバーは初期導入しない。
- 毎日1回、`sqlite3.Connection.backup()`で一貫した一時DBを作り、`PRAGMA integrity_check`後にCloudflare R2へ保存する。稼働DBを単純に`cp`しない。
- R2の`daily/`配下へUTC日時を含む一意なオブジェクト名で保存し、同一キーを上書きしない。Lifecycleで各オブジェクトを30日後に自動削除する。Bucket LockとFly Volume snapshotの追加設定は必須としない。
- ジョブ失敗を通知し、最新成功時刻を確認できるログを残す。専用の鮮度監視サービスは作らない。
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

- バックアップ処理と失敗通知をリリース前に確認する。
- 復元確認は初回リリース前、大きなスキーマ変更後、または四半期を目安に実施する。月次演習は必須としない。
- 暫定目標は正常時RPO約24時間、RTO数時間以内とする。

## 再検討条件

数分の停止も許容できない、自動フェイルオーバーが必要、または更新頻度が大きく増えた場合は、継続レプリケーションやマネージドDBを再評価する。

## 参考

- [SQLite Online Backup API](https://sqlite.org/backup.html)
- [Fly Volumes](https://fly.io/docs/volumes/overview/)
- [Cloudflare R2 Object Lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)
