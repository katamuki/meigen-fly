# アーキテクチャ決定記録: SQLite の永続化・日次バックアップ・復旧

## ステータス

**確定: 単一 Fly Machine + Fly Volume + 日次オンラインバックアップを採用**（2026-07-13決定）

## コンテキスト

初期リリースは東京リージョンの単一 Machine で運用し、公開ページの読み取り負荷は Cloudflare のエッジキャッシュで吸収する。データ規模は約3,000行で、書き込みは Admin 操作と匿名いいねに限られる。

継続レプリケーションや自動フェイルオーバーは初期要件ではない。正常に日次バックアップが完了している場合に、最大約24時間分の更新を失う可能性と手動復旧を許容し、構成を単純に保つ。

## 決定

- SQLite は東京 `nrt` の **単一 Fly Machine** に接続した **Fly Volume `/data`** で運用する。
- **LiteFS と Litestream は初期構成では採用しない**。継続レプリケーションと複数 Machine 間の自動フェイルオーバーは行わない。
- 稼働中の `/data/app.db` を単純に `cp` しない。WAL モードでも一貫したスナップショットを作れる **Python `sqlite3.Connection.backup()`（SQLite Online Backup API）** を使う。
- 毎日 **03:00 JST** に同一Machine内の専用 `supercronic` プロセスから単一ジョブを実行し、Uvicorn worker 内のスケジューラでは動かさない。
- バックアップは一時DBへ出力し、`PRAGMA integrity_check`後に圧縮する。圧縮済み成果物のSHA-256を作り、成果物と `.sha256` sidecarを Cloudflare R2 へアップロードする。R2オブジェクト名にはUTCタイムスタンプを含め、上書きしない。
- R2へのアップロード成功後に一時ファイルを削除する。失敗時はリトライし、失敗通知を送る。
- R2上の最新成功バックアップ時刻を監視し、**03:30 JSTまでに当日分がない場合**、または最新成功から25時間を超えた場合にアラートにする。ジョブ失敗時にはRPOが24時間を超え得ることを運用上の制約として受け入れる。
- バックアップは専用R2バケットの `daily/` prefixへ保存する。`daily/` に30日のBucket Lockを設定して上書き・削除を防ぎ、同prefixのLifecycleで30日経過後に失効させる。これらはR2側で管理し、アプリから削除しない。
- 長期R2資格情報はバックアップ専用バケットだけに読み書きを許可する。prefix単位に制限する必要が生じた場合は、短命なR2 temporary credentialsを使用する。
- Fly Volume の日次snapshotは**14日保持**し、R2とは独立した**二次復旧手段**として使う。snapshotだけを主要バックアップにはしない。
- Admin一括更新、データ移行、Alembic migrationの直前には、定時処理とは別にオンデマンドバックアップを取得する。

## migration時の手順

SQLiteファイルをマウントしないFlyの `release_command` ではmigrationを実行しない。VolumeをマウントしたMachineで、Uvicorn worker起動前に一度だけ実行する。

1. 公開いいねとAdmin書き込みを停止し、メンテナンス状態にする。
2. Online Backup APIでmigration直前バックアップを作成する。
3. `PRAGMA integrity_check`後に圧縮し、圧縮済み成果物のSHA-256を作成する。
4. R2へのアップロード成功を確認する。
5. `alembic upgrade head` を実行する。
6. Uvicorn workerを起動し、`/healthz` と主要ページを確認する。
7. 書き込みを再開する。

migration失敗時は、旧DBに対応するアプリ版へ戻してバックアップを復元するか、復元DBへ必要なrevisionを適用してから起動する。バックアップ取得からmigration完了まで書き込みを止め、復元時の更新欠損を防ぐ。

## 復旧手順

1. アプリと全書き込みを停止する。
2. R2から復元対象と `.sha256` sidecarを別パスへダウンロードし、圧縮済み成果物のSHA-256を検証して展開する。
3. `PRAGMA integrity_check`、Alembic revision、主要テーブル件数を確認する。
4. 必要に応じて `alembic upgrade head` を適用する。
5. 既存DBを直接上書きせず、検証済みDBへ切り替える。
6. アプリを起動し、`/healthz`、検索、Admin、いいねを確認する。

Fly Volume snapshotを使う場合も、新しいVolumeへ復元して検証後にMachineへ付け替える。

## 運用・検収

- 毎日03:30 JSTまでに当日分がR2に存在し、最新成功から25時間以内であることを監視する。
- バックアップ失敗通知をテストする。
- 月1回、R2バックアップを別DBへ実際に復元し、整合性・Alembic revision・主要件数を検証する。
- 暫定目標は、正常時 **RPO 約24時間、RTO 30分〜数時間**とする。実復元演習の結果で見直す。

## 将来の再検討条件

数分の停止も許容できない、自動フェイルオーバーが必要、または複数リージョンでローカルDB読み取りが必要になった場合は、LiteFSだけに限定せずマネージドPostgreSQLやlibSQL系も含めて再評価する。

## 参考

- [SQLite Online Backup API](https://sqlite.org/backup.html)
- [Fly Volume snapshots](https://fly.io/docs/volumes/snapshots/)
- [Fly Volumes overview](https://fly.io/docs/volumes/overview/)
- [Cloudflare R2 Bucket Locks](https://developers.cloudflare.com/r2/buckets/bucket-locks/)
- [Cloudflare R2 Object Lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)
