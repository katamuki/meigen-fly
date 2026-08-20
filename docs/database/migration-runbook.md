# Supabase→SQLite データ移行 runbook

作成日: 2026-08-20（フェーズ2で整備。フェーズ6の最終移行で同じ手順を再実行する）

設計の正本は [`migration-decisions.md`](migration-decisions.md) の「判断」列と [`inventory-4-new-db-design.md`](inventory-4-new-db-design.md)（第4部）。本書はそれを実装に落としたときの規約・手順・変換ルールの記録である。

## 1. 制約・索引の命名規約（ADR 004）

SQLAlchemy Coreの`MetaData(naming_convention=...)`（[`app/db.py`](../../app/db.py)）で自動命名する。`app/schema.py`の表定義とAlembic revisionは同じ名前を使う。

| 種別 | 形式 | 例 |
|---|---|---|
| 主キー | `pk_<table>` | `pk_quotes` |
| 外部キー | `fk_<table>_<column>_<referred_table>` | `fk_quotes_author_id_authors` |
| UNIQUE制約 | `uq_<table>_<col1>_<col2>…` | `uq_author_professions_author_id_display_order` |
| CHECK制約 | `ck_<table>_<短い意味名>` | `ck_quotes_weight`, `ck_authors_day_order` |
| 索引 | `ix_<table>_<col1>_<col2>…` | `ix_quotes_author_id_enable_id` |
| 部分UNIQUE索引 | `uq_<table>_<意味名>`（明示命名） | `uq_author_country_birth_country` |
| トリガー | `trg_<table>_<event>_<意味名>` | `trg_quote_categories_insert_level2` |

CHECK制約と部分UNIQUE索引・トリガーは自動命名できないため、上の形式で明示的に名前を付ける。

## 2. スキーマ（Alembic revision 0002）

- [`app/schema.py`](../../app/schema.py): 16表のSQLAlchemy Core定義（原本・関連13表 + ranking snapshot 3表）。
- [`migrations/versions/0002_create_application_tables.py`](../../migrations/versions/0002_create_application_tables.py): `create_table`部分はautogenerateの下書きをレビューして採用。手書き部分は次のとおり。
  - 生誕国最大1件: `author_country`に`is_birth_country = 1`の部分UNIQUE索引
  - category階層: `trg_categories_insert_parent_level` / `trg_categories_update_parent_level`（level 2の親はlevel 1・自己参照禁止）、`trg_categories_update_level_in_use`（子や名言割当が存在する間はlevelを変更できない）
  - level 2割当: `trg_quote_categories_insert_level2` / `trg_quote_categories_update_level2`
  - 各CHECK（第4部§4〜6）。歴史日付はAD出生→BC死亡の拒否と、両端day精度の明白な逆転だけをDBで拒否する（BCは年だけ逆順比較）
  - `quotes`のみ`AUTOINCREMENT`
- 検証: `tests/test_migrations.py`で空DBへの`alembic upgrade head`、単一head、`app/schema.py`とmigration結果の一致（`compare_metadata`が空）、トリガー・部分UNIQUE・CHECKの挙動を確認する。

## 3. 移行元データの取得（[`scripts/export_source_db.sh`](../../scripts/export_source_db.sh)）

**方式: `psql`の単一トランザクション（REPEATABLE READ, READ ONLY）で`row_to_json`を使い、表ごとにJSON Linesへ書き出す。** `pg_dump`のデータダンプやCSVではなく、JSON Linesを選んだ理由:

- NULLと空文字、真偽値、数値がそのまま区別される（CSVはNULLマーカーの約束が別途必要）
- 全表が1スナップショットなので、取得中に増える`quote_likes`が孤立しない
- 必要な列だけを`SELECT`で選べるため、`quote_likes`のrow UUID・`ip_hash`・`user_agent`は移行元の外に出さない（判断#5）
- Python側は`json.loads`だけで読めて、`pg_dump`形式の解析が不要

出力先は`~/prj/meigen-fly-private/source-db/data/`（Git管理外）。`quotes_id_seq`の`last_value`と取得時刻（`export_meta.jsonl`）も書き出す。

```bash
export SUPABASE_DB_URL="$(security find-generic-password -s meigen-fly-supabase-db -w)"
scripts/export_source_db.sh            # 既定の出力先へ。引数で出力先を変更できる
```

接続はサーバー側で`default_transaction_read_only=on`・`TimeZone=UTC`を設定する。接続文字列はファイルへ書かない。

## 4. 変換ルール（[`scripts/load_source_data.py`](../../scripts/load_source_data.py)）

| 対象 | ルール | 根拠 |
|---|---|---|
| 全時点列（`created_at`/`updated_at`/`quote_likes.created_at`） | timestamptz → `YYYY-MM-DDTHH:MM:SS.ffffffZ` 27文字固定長UTC。`app/instants.py`の`format_instant`で生成。offsetなしは拒否 | ADR 011 |
| 真偽値（`quotes.enable`, `author_country.is_birth_country`, `quote_likes.is_valid`） | `true/false` → `1/0` | 判断#4・#9 |
| 歴史日付（`authors.birth_date`/`death_date`） | `"YYYY-MM-DD BC"` → `"YYYY-MM-DD"`。` BC`接尾辞の有無がera列と食い違えば中断 | 判断#11 |
| `categories.updated_at` | 新設。初期値は現行`created_at` | 判断#15 |
| `quotes.legacy_vote_count` | `legacy_votes.vote_count`をquote別に合算。なければ0。存在しないquoteへの票・負値は中断 | 判断#3 |
| `quote_likes` | `quote_id`/`client_uuid`/`created_at`/`is_valid`のみ。大文字小文字・空白の正規化はしない（本番は全件小文字UUIDと確認済み） | 判断#4・#5 |
| `countries.code` | 無変換 | 判断#13 |
| `quotes`高水位 | 投入後に`sqlite_sequence.quotes = max(投入後max(id), 旧`quotes_id_seq.last_value`, 3197)` | 判断#14 |
| その他の列 | 無変換。NULL→NOT NULL化される列（`weight`, `level`, `sort_order`, `character_type`, `display_order`等）は本番でNULL 0件を確認済みで、NULLが来れば制約違反で中断 | 第4部§12.1 |

投入は1トランザクション。対象DBが`alembic head`かつ全表空であることを先に確認し、どこかで失敗すれば全体をrollbackする（データを勝手に補正しない）。categoriesはlevel 1→2の順、他は親表→子表の順に投入する。

## 5. 再実行可能な手順（取得→変換→投入→検証）

```bash
# 1. 取得（ネットワーク必要・読み取り専用）
export SUPABASE_DB_URL="$(security find-generic-password -s meigen-fly-supabase-db -w)"
scripts/export_source_db.sh

# 2. まっさらなSQLiteを作り直して投入・検証（既定: data/app.db を削除して再作成）
scripts/rebuild_sqlite.sh [SOURCE_DIR] [DB_PATH]
```

`rebuild_sqlite.sh`は「DBファイル削除 → `alembic upgrade head` → `load_source_data.py` → `verify_migration.py`」を順に実行し、検証が1件でも失敗すれば非0で終了する。

## 6. 整合性検証（[`scripts/verify_migration.py`](../../scripts/verify_migration.py)）

期待値はすべて同じダンプから算出する（件数のハードコードなし。例外は高水位の下限3,197）。

- `PRAGMA integrity_check` = ok、`PRAGMA foreign_key_check` = 0件
- 13表について、件数一致・主キー集合一致に加えて、**主キーごとに全列を移行元と比較**する。比較対象の列集合がSQLite側の列集合と一致することも確認し、ダンプから列が落ちてserver defaultで埋まった場合を検出する（loader側も投入前に全列が明示されていることを確認する）
  - 無変換列（FK列・`countries.code`・歴史日付のera/precision・本文等）は値の完全一致（文字列は同一コードポイント=同一バイト列）
  - 変換列は検証スクリプト側で独立に期待値を作る: 真偽値→0/1、歴史日付は` BC`接尾辞を外した値、`quotes.legacy_vote_count`は`legacy_votes`のquote別合算、`categories.updated_at`は移行元`created_at`
  - 全時点列は27文字形式であることと、`parse_instant`した値が移行元timestamptzと等しいこと（loaderの`format_instant`は使わない）
- snapshot 3表が空、関連・FK列15本で孤立0（行比較とは別に残す）
- `quotes.legacy_vote_count`合計 = `legacy_votes`合計
- `sqlite_sequence.quotes ≥ max(max(id), 旧sequence, 3197)`

投入時にDB制約（NOT NULL/CHECK/FK/UNIQUE）で拒否された場合、`load_source_data.py`は行単位に再試行して最初に拒否された行の表名・主キー・制約名を`load aborted: quotes: row {'id': 3000} rejected: CHECK constraint failed: ck_quotes_weight`の形で報告し、全体をrollbackする。

`tests/test_migration_scripts.py`が小さな合成ダンプで投入→検証、非空DBの拒否、不整合データでの中断と拒否行の報告、改ざん（本文・FK列の差し替え・フラグの行間入れ替え・日付）の検知を確認する。

## 7. 実施記録

| 日付 | 内容 | 結果 |
|---|---|---|
| 2026-08-20 | 本番から取得（06:43 UTC）→ `rebuild_sqlite.sh`（レビュー反映後の行単位比較でも再実行） | 全検証PASS（86項目）。authors 774・quotes 1,831・quote_likes 7,942（2026-07-17の7,591から増加）・legacy票合計24,044・高水位3,197。DBファイル約3MB |

フェーズ6の最終移行では、旧環境の書き込み凍結後に同じ2コマンドを実行し、本記録へ追記する。
