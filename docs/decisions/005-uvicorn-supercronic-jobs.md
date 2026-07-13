# アーキテクチャ決定記録: Uvicorn worker と定期ジョブの実行方式

## ステータス

**確定: 初期はUvicorn 1 worker、全定期ジョブはsupercronicで実行**（2026-07-13決定）

## コンテキスト

直近28日間はアクティブユーザー約1.3万人、イベント約18万件で、公開HTMLの大半はCloudflareでキャッシュする。GAイベント数はHTTPリクエスト数や同時実行数ではないため容量の直接指標にはしないが、初期から複数workerを必要とする規模ではない。

Uvicornの各workerは独立プロセスである。FastAPIのstartup/lifespanからスケジューラを起動するとworker数だけ同じジョブが動き、ランキング・集計・バックアップが二重実行され得る。

## 決定

- 初期は `uvicorn --workers 1` とする。FastAPIのstartup/lifespanから定期ジョブを起動しない。
- バックアップ、ランキング再計算、カテゴリ件数再計算など、**全定期ジョブを同一MachineのsupercronicからCLIとして実行**する。
- entrypointがmaintenance lockを取得してmigrationを完了した後、PID 1として `supervisord` をexecする。supervisordはUvicornとsupercronicを監督し、異常終了時に再起動する。
- cronのタイムゾーンは `Asia/Tokyo` に固定し、バックアップ・集計ジョブの開始時刻をずらす。
- 定期・手動のどちらも同じジョブラッパーを通す。各DBジョブは `/data/locks/db-maintenance.lock` の共有lockを実行中ずっと保持し、migrationは同じファイルの排他lockを取得して既存ジョブの終了を待つ。これにより確認と実行の間のTOCTOU競合を防ぐ。
- ラッパーは上記に加え、ジョブ別 `flock` による多重起動防止、最大実行時間、非ゼロ終了、失敗通知を提供する。migration配下のオンデマンドバックアップは、呼び出し元が排他lockを保持するmaintenance modeで実行し、共有lockをネスト取得しない。
- 共通ラッパーは成功時に `/data/job-status/{job}.json` をatomic renameで更新する。ジョブ名、開始・終了時刻、結果を保存し、ジョブごとの期限を設定ファイルで管理する。監視用エンドポイントと外形監視が期限超過を検知する。supervisordはプロセス監督、statusファイルはジョブ鮮度監視を担当する。
- 集計テーブルの入替えは単一の短いtransactionで行い、失敗時は前回の正常結果を残す。SQLite接続には `busy_timeout` と限定回数のretry/jitterを設定する。
- supervisordはUvicorn/supercronicに `stopasgroup=true` と `killasgroup=true` を設定し、停止時にsupercronicが起動した子ジョブも終了・待機する。その後にentrypointが排他maintenance lockを取得する。
- 同期的なSQLite/SQLAlchemy処理はasync routeのevent loop上で直接実行せず、sync route/threadpoolまたは選定した非同期DB境界から呼ぶ。

## workerを増やす条件

Cloudflareのキャッシュヒット率、オリジンのp95/p99応答時間、CPU、メモリ、5xx/timeout、SQLite busy/locked、検索・いいねPOSTなど非キャッシュ経路を継続観測する。負荷試験でボトルネックを再現し、CPU待ちまたはHTTP並行処理に改善が見込める場合だけ、**Machineは1台のままHTTP workerを2へ増やす**。

SQLiteの書き込み性能はworker追加では向上せず、競合とメモリ使用量が増える可能性がある。workerを増やしても定期ジョブ数は1のままとする。

複数Machineへ拡張する場合、各Machineのsupercronicが実行されるため、本方式をそのまま使わず分散ロックまたは専用ジョブMachineを含めて再設計する。

## 検証

- worker 1/2の両方で各定期ジョブが予定時刻に1回だけ実行される。
- 定期実行中の手動実行が `flock` で拒否またはスキップされる。
- 実行中ジョブが共有lockを保持する間はmigrationの排他lock取得が待機し、排他lock中は全DBジョブが開始されない。migration完了後にのみsupervisordが起動する。
- supercronic停止、ジョブtimeout/失敗、Machine再起動を注入し、再起動・通知・最終成功時刻アラートを確認する。
- いいね、Admin更新、バックアップ、集計を並行実行し、ロックエラーとデータ整合性を確認する。

## 再検討条件

- 観測と負荷試験で1 workerがボトルネックになった場合
- Machineを複数台に増やす場合
- 定期ジョブの処理時間が運用時間枠に収まらなくなった場合
