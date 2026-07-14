# アーキテクチャ決定記録: Uvicorn workerと定期ジョブ

## ステータス

**確定: Uvicorn 1 worker + supercronicからのCLI実行**（2026-07-14簡略化）

## コンテキスト

公開HTMLの多くはCloudflareでキャッシュし、DBは単一Machine上のSQLiteである。初期から複数workerや分散ジョブ基盤を必要とする規模ではない。

## 決定

- 初期は`uvicorn --workers 1`とする。
- バックアップ、ランキング再計算、カテゴリ件数再計算などの定期処理はsupercronicからCLIとして実行し、FastAPIのstartup/lifespanからスケジューラを起動しない。
- 各ジョブは単純な`flock`で多重起動を防ぎ、最大実行時間と非ゼロ終了を設定する。
- 失敗は標準エラーログへ出し、既存の通知経路があれば通知する。独自のstatus JSON、ジョブ鮮度API、共有・排他maintenance lockは初期実装しない。
- 集計更新は短いtransactionで行い、失敗時は前回の正常結果を残す。
- SQLite接続には`busy_timeout`を設定する。

Uvicorn、cloudflared、supercronicを同一Machineで動かすための最小限のプロセス監督は許容するが、アプリ固有の再起動・状態機械は作らない。

## 検証

- 定期ジョブが予定時刻に1回だけ実行される。
- 同じジョブの重複実行が`flock`で拒否またはスキップされる。
- 失敗時に非ゼロ終了し、ログまたは通知で確認できる。

## workerを増やす条件

キャッシュヒット率、応答時間、CPU、メモリ、SQLite lockを観測し、1 workerが実測上のボトルネックになった場合だけ2 workerを検討する。複数Machineへ増やす場合は定期ジョブの配置を別途再設計する。
