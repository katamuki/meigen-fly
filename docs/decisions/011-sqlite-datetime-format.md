# アーキテクチャ決定記録: SQLiteの日時保存形式

## ステータス

**確定: 時点データは固定長UTCの`TEXT`で保存する**（2026-07-13決定）

## コンテキスト

SQLiteには専用のtimestamp型がなく、`TEXT`、epoch整数など複数の表現が可能である。表現が混在すると、文字列によるORDER BY、カーソルページング、期間集計、移行データの比較が不正確になる。

## 決定

- `created_at`、`updated_at`、いいね日時、ジョブ実行日時など「時点」を表す列は`TEXT`で保存する。
- 保存形式はUTCの固定長`YYYY-MM-DDTHH:MM:SS.ffffffZ`に統一する。
- アプリはtimezone-awareなdatetimeだけを受理し、UTC変換後に明示serializerで保存する。
- 読み出しは明示parserでtimezone-awareなUTC datetimeへ変換する。
- Python標準`sqlite3`の既定datetime adapter/converter、SQLiteの`CURRENT_TIMESTAMP`、異なる桁数・offset表現を混在させない。
- 比較、ORDER BY、期間境界のbind値も同じserializerで生成する。
- `birth_date`、`death_date`など暦日・歴史日付は時点データと分離し、UTC変換しない。精度や紀元を表す既存列と合わせて別規則で保存する。

## 移行・検証

- Supabaseの全日時列についてtimezone、NULL、精度を棚卸しし、移行時に正規化する。
- round-trip、UTC日付境界、並び順、`created_at DESC, id DESC`、直近1日・7日集計をテストする。
- SQLAlchemy Coreのbind/result処理が常に明示codecを通ることを確認する。
