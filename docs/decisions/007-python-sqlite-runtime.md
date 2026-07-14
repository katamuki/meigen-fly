# アーキテクチャ決定記録: Python SQLiteランタイム

## ステータス

**確定: Python標準`sqlite3`を採用**（2026-07-14改訂）

## コンテキスト

初期検索は`LIKE`、バックアップは`sqlite3.Connection.backup()`を使用する。カスタムSQLiteビルドや代替DBAPIを必要とする機能はない。

## 決定

- Python標準`sqlite3`を使用する。
- 最終DockerイメージでSQLite接続、WAL、Online Backup API、foreign key、Alembic migrationをスモークテストする。
- FTS5は初期リリースの必須条件にしない。
- 必要な機能が不足した場合だけ`pysqlite3-binary`やAPSW等を比較し、自動fallbackは実装しない。

## 再検討条件

検索をFTS5へ移行する、標準`sqlite3`にないSQLite機能が必要になる、または性能上の問題が実測された場合に再評価する。
