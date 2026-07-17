# アーキテクチャ決定記録: SQLite のマイグレーション管理

## ステータス

**確定: SQLAlchemy Core + Alembicを採用**（2026-07-13決定）

> 追記（2026-07-17）: 移行対象は本番確認と移行判断により**16表**（原本・関連13表 + ranking snapshot 3表。`legacy_votes`は`quotes.legacy_vote_count`へ統合）へ確定した。下記コンテキストの「19テーブル」は決定時点の想定。詳細は`docs/database/migration-decisions.md`を参照。決定内容は変わらない。

## コンテキスト

PostgreSQLから管理者認証用の旧`admin_users`を除く19テーブルをSQLiteへ移植する。スキーマ変更履歴、適用済みrevision、データ変換を再現可能にする必要がある。

## 決定

- アプリのDBアクセスは **SQLAlchemy Core** を基本とし、スキーマmigrationは **Alembic** で管理する。全面的なORM採用は必須としない。
- Alembicのautogenerateは通常テーブル変更の**下書き**に限定し、生成結果を必ずレビューする。
- トリガー、ビュー、`CHECK`制約、データ変換は必要な場合だけ手書きrevisionとして明示する。
- SQLiteでテーブル再作成が必要な変更には `batch_alter_table()` を使い、`render_as_batch=True` を設定する。
- 主キー、外部キー、UNIQUE、CHECK、インデックスには一貫した命名規約を設定する。
- downgradeは安全に戻せる変更に限って実装する。破壊的変更の本番復旧は、事前バックアップと対応するアプリ版への切り戻しを基本とする。
- migration前のバックアップと本番実行順序はADR 003に従う。

## 検証

- 空DBに対する `alembic upgrade head` をCIで実行する。
- 本番相当データのコピーに全revisionを適用し、`PRAGMA integrity_check`、主要件数、外部キー、FTS検索を確認する。
- autogenerate後に空migrationや意図しないDROPがないことをレビューする。
- CIで複数headがないことを確認し、デプロイ後のDB revisionが単一の期待script headと一致することを確認する。

## 採用しなかった選択肢

- **yoyo-migrations**: 生SQL中心なら有力だが、通常テーブルをSQLAlchemy Coreと共有できるAlembicを優先した。
- **素のSQL + 独自バージョン表**: 依存は少ないが、適用履歴、ロック、失敗処理、検証の独自保守が増える。
- **Atlas**: schema diffやlintは強力だが、この規模では別CLIと運用フローの追加が過剰。

## 参考

- [Alembic: Running Batch Migrations for SQLite](https://alembic.sqlalchemy.org/en/latest/batch.html)
- [Alembic: Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
