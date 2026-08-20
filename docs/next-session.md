# 次回セッション作業指示: フェーズ2（Supabase→SQLiteデータ移行）

> 本ファイルはセッション間の引き継ぎメモ。フェーズ2完了時に削除する。
> 作成日: 2026-08-20

## 目的

[`docs/project-plan.md`](project-plan.md) 第8章のフェーズ2（2-1〜2-4）を完了する。

## 設計の正本（この順で優先）

1. [`docs/database/migration-decisions.md`](database/migration-decisions.md) — 判断シート19件の「判断」列と「実装フェーズへの引き継ぎ」節
2. [`docs/database/inventory-4-new-db-design.md`](database/inventory-4-new-db-design.md) — 16表DDL・制約・索引の設計（第4部）
3. [`docs/project-plan.md`](project-plan.md) §8 フェーズ2 — タスク一覧（チェックボックスを進捗管理に使う）

## 作業順序

1. **2-1. スキーマ作成**: 制約・索引の命名規約（D4/ADR 004）→ 16表DDLのAlembic revision → 空DBへの `alembic upgrade head` を自動テストへ追加
2. **2-2. 移行元データ取得**: エクスポート方式（`pg_dump` データダンプ or CSV）を決定し、「取得→変換→投入→検証」を再実行可能なコマンド列として整備
3. **2-3. 変換・投入スクリプト**: `scripts/` 新設。13表 + `legacy_vote_count` 統合
4. **2-4. 整合性検証**: 検証スクリプト。期待値は同一ダンプから動的算出（件数のハードコード禁止）

## スコープ境界（重要）

- ranking snapshot 3表は**スキーマのみ作成し、データは投入しない**（再計算CLIはフェーズ4）
- 検索用の派生インデックス・FTS5は作らない（D1/ADR 002）
- 現行Supabase側の権限是正は行わない（判断U1）

## 準備済みの環境（2026-08-20確認済み）

- **本番DB接続文字列**: macOSキーチェーンに保存済み。取り出しは
  `export SUPABASE_DB_URL="$(security find-generic-password -s meigen-fly-supabase-db -w)"`
  接続テスト（`SELECT 1`）済み。IPv6環境のためDirect connectionを直接使用（pooler不要）
- **ツール**: `psql` / `pg_dump` 17.10 インストール済み
- **ダンプ保存先**: `~/prj/meigen-fly-private/source-db/data/`（Git管理外・空）
- **スキーマ情報**: `~/prj/meigen-fly-private/source-db/schema/schema.sql` 取得済み
- **本番の件数・分布**: `~/prj/meigen-fly-private/source-db/verification/verification-results.txt`（2026-07-17時点）

## 運用ルール

- 接続文字列・パスワード等の秘密情報をリポジトリ・`meigen-fly-private/` のファイル・シェル設定ファイルへ書かない
- 本番DBへの操作は読み取り専用（エクスポート）に限定する
- 完了したタスクは `docs/project-plan.md` のチェックボックスへ反映する
