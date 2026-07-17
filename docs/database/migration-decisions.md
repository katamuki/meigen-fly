# 移行判断シート

確認結果と推奨案は本番確認の実行後に記入し、判断はユーザーが記入する。この判断が完了するまで、SQLiteスキーマ、Alembic、移行スクリプト、アプリコードの実装へ進まない。

論点・既定案・分岐の詳細は[第4部§12](inventory-4-new-db-design.md)、確認項目A1〜A9・O1〜O4の内容は[第5部](inventory-5-production-checklist.md)を参照。

## 確認の実施状況

- [x] A1〜A9(DB内確認): 2026-07-17に `verification.sql` を本番へ実行済み(READ ONLY・SELECT-only、exit 0、エラーなし、全セクション出力)。結果は `/Users/sonoda/prj/meigen-fly-private/source-db/verification/verification-results.txt`(Git管理外)。
  - ただしA8の検索3検査は、検索代表語未設定のためskip。語を決めて再実行すれば取得できる。
- [ ] O1〜O4(DB外確認): 未実施。`verification/` 配下の記入テンプレート3件にユーザーが記入する。
- [ ] 確認結果の解析と「確認結果」「推奨案」欄の記入(タスクB)。
- [ ] ユーザーによる「判断」欄の記入(18件+U1)。
- [ ] 判断結果の反映と `docs/project-plan.md` 修正候補6件の適用(タスクC)。

| # | 論点 | 既定案 | 対応する確認項目 | 確認結果 | 推奨案 | 判断 |
|---:|---|---|---|---|---|---|
| 1 | `source_type_assignments` | 多対多表を維持 | A5 + O2 |  |  |  |
| 2 | 国関連 | 複数関連国 + 生誕国最大1件 | A5 |  |  |  |
| 3 | `legacy_votes` | `legacy_vote_count`へ統合 | A6 |  |  |  |
| 4 | invalid likes | `is_valid`を残しinvalid行も状態保持 | A6 + O2 |  |  |  |
| 5 | likes row UUID/UA | 除外 | A6 + O2 |  |  |  |
| 6 | ranking旧log | 新DBへ移さない | A7 + O4 |  |  |  |
| 7 | ranking係数 | CLI明示設定へ同値移行 | A7 |  |  |  |
| 8 | quote slug | NULLを許容して保持 | A3 + O1 |  |  |  |
| 9 | quote enable | 新DBでNN、通常公開は1のみ | A3 + O1 |  |  |  |
| 10 | 本文/fallback | 少なくとも一方非空CHECK | A1/A3 |  |  |  |
| 11 | 歴史日付 | 第4部§4.1の整合CHECK | A4 |  |  |  |
| 12 | `published_year` | nullable正整数 | A4 |  |  |  |
| 13 | country code | nullable2–3文字、通常索引 | A4 |  |  |  |
| 14 | quote ID高水位 | AUTOINCREMENT、高水位引継ぎ | A2 |  |  |  |
| 15 | category `updated_at` | sitemap/cache判定用に新設 | A3/A4 |  |  |  |
| 16 | snapshot列/sort | 現行3表の指標を維持 | A7/A8 + O2 |  |  |  |
| 17 | 条件付き廃止object | 新構成へ持ち込まない | A9 + O2/O3 |  |  |  |
| 18 | 管理KPI | 必要値だけdirect COUNT | A1/A9 + O2 |  |  |  |
| U1 | Supabase権限是正 | O3結果後の別枠の現行運用判断 | O3 |  |  |  |
