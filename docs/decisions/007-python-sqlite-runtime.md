# アーキテクチャ決定記録: Python SQLiteランタイムとFTS5検証

## ステータス

**確定: Python標準`sqlite3`を採用し、最終Dockerイメージで必要機能を検証する**（2026-07-13決定）

## コンテキスト

日本語検索はFTS5 + アプリ側bigramを使い、バックアップは`sqlite3.Connection.backup()`を使う。PythonやSQLiteのバージョン番号だけでなく、本番配布物に必要な機能が実際に含まれることを保証する必要がある。

## 決定

- 本番のSQLite DBAPIはPython標準ライブラリ`sqlite3`を採用する。
- ベースイメージはPython patch・Debian世代を固定し、リリース時にイメージdigestを記録する。
- CIはホスト環境ではなく、Fly.ioへ配布する最終Dockerイメージと同じCPUアーキテクチャで実行する。
- CIで`sqlite3.sqlite_version`とcompile optionsを記録し、次をスモークテストする。
  - FTS5仮想テーブルを`tokenize='unicode61'`で作成できる
  - bigram済みテキストをINSERTし、2文字語を`MATCH`できる
  - WALモード、`foreign_keys`、`busy_timeout`が有効になる
  - `sqlite3.Connection.backup()`で整合したコピーを作れる
  - 空DBへの`alembic upgrade head`が成功する
- 必要機能が不足した場合は、SQLAlchemy Core、Alembic、Online Backup APIとの互換性を検証したうえで代替DBAPIを別途決定する。`pysqlite3-binary`や`apsw`へ自動的に切り替えない。

## 検証

- CIの機能検査が失敗したイメージはデプロイしない。
- ベースイメージ更新時にも同じ検査を実行する。
- 開発環境と本番イメージのSQLiteバージョン・compile optionsの差を診断情報として確認できるようにする。
