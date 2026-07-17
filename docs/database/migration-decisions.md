# 移行判断シート

確認結果と推奨案は本番確認の実行後に記入し、判断はユーザーが記入する。この判断が完了するまで、SQLiteスキーマ、Alembic、移行スクリプト、アプリコードの実装へ進まない。

論点・既定案・分岐の詳細は[第4部§12](inventory-4-new-db-design.md)、確認項目A1〜A9・O1〜O4の内容は[第5部](inventory-5-production-checklist.md)を参照。

## 確認の実施状況

- [x] A1〜A9(DB内確認): 2026-07-17に `verification.sql` を本番へ実行済み(READ ONLY・SELECT-only、exit 0、エラーなし、全セクション出力)。結果は `/Users/sonoda/prj/meigen-fly-private/source-db/verification/verification-results.txt`(Git管理外)。A8の検索3検査も代表語を指定してread-onlyで再実行し、現行RPCとdirect `LIKE`の件数・先頭IDが3件とも一致した。
- [x] O1〜O4(DB外確認): 2026-07-17に `verification/` 配下の記入テンプレート3件へ確認結果を記録済み。
- [x] 確認結果の解析と「確認結果」「推奨案」欄の記入(タスクB): 2026-07-17完了。
- [ ] ユーザーによる「判断」欄の記入(18件+U1)。
- [ ] 判断結果の反映と `docs/project-plan.md` 修正候補6件の適用(タスクC)。

| # | 論点 | 既定案 | 対応する確認項目 | 確認結果 | 推奨案 | 判断 |
|---:|---|---|---|---|---|---|
| 1 | `source_type_assignments` | 多対多表を維持 | A5 + O2 | 234出典のうち0種別35、1種別180、複数種別19。218関連に孤立0。現行UI/filterで利用し、外部consumerなし。 | 19出典が複数種別を必要とするため、多対多表と218関連を維持する。 |  |
| 2 | 国関連 | 複数関連国 + 生誕国最大1件 | A5 | 774著者のうち国なし9、1国657、複数国108。生誕国はなし9、1件765、複数0。880関連に孤立0。 | 複数関連国を維持し、生誕国は部分UNIQUE等で最大1件を保証する。 |  |
| 3 | `legacy_votes` | `legacy_vote_count`へ統合 | A6 | 1,650行・合計24,044票、最小1・最大574。負値・孤立・NULLは0。 | quote別の正常値を`quotes.legacy_vote_count`へ全件統合し、独立表は作らない。 |  |
| 4 | invalid likes | `is_valid`を残しinvalid行も状態保持 | A6 + O2 | 7,591件すべてvalid。invalid、UUID形式不正、意味上の重複はいずれも0で、外部invalid化運用/jobもない。 | 現行値をすべて有効票として移し、未使用の`is_valid`列は新DBから除外する。将来無効化要件が生じた時だけ再導入する。 |  |
| 5 | likes row UUID/UA | 除外 | A6 + O2 | row UUID・UA・IP hashは全7,591行に存在するが、外部consumerも監査利用もない。投票識別に必要な`client_uuid`は全件UUID形式。 | `client_uuid`は冪等キーとして維持し、row UUID・UA・IP/IP hashは移行しない。 |  |
| 6 | ranking旧log | 新DBへ移さない | A7 + O4 | 380件は全件success。障害調査に未使用で、DB内保持・archiveとも必須ではない。 | 新DBへ移さず履歴表も作らない。低コストで必要なら旧DB廃止前に任意のDB外archiveだけ行う。 |  |
| 7 | ranking係数 | CLI明示設定へ同値移行 | A7 | 5設定はJSON未使用。ranking係数は`like_weight_1d=10`、`like_weight_7d=5`、`like_weight_default=1`、`weight_factor=10`で、`ip_daily_limit=100`が混在。 | 4係数だけを型付きCLI設定へ同値移行し、`ip_daily_limit`はrankingから分離してアプリ側rate limit設定で扱う。 |  |
| 8 | quote slug | NULLを許容して保持 | A3 + O1 | 1,831件中slugなし1,825、あり6。空・重複・予約`q{id}`形は0。qid/slugの200・canonical・旧URL redirectを確認し、slug変更実績と旧slug consumerはない。 | 現行slugをそのままnullable UNIQUEで保持し、未設定は`q{id}`をcanonicalにする。補完・NN化・redirect表追加は行わない。 |  |
| 9 | quote enable | 新DBでNN、通常公開は1のみ | A3 + O1 | true 1,785、false 46、NULL 0。通常公開経路はtrueのみ。一覧`/api/quotes`は省略時に46非公開件も返すが、実consumerはいない。 | 0/1 NNへ同値移行し、公開経路は1だけに限定する。未使用一覧APIの省略時全件公開互換は引き継がない。 |  |
| 10 | 本文/fallback | 少なくとも一方非空CHECK | A1/A3 | `text`は全1,831件が非空、`text_en`は68件あり・1,763件NULL・空0。表示言語とのfallback不整合候補は0。 | 少なくとも一方非空CHECKと共通fallback resolverを採用し、現行本文を無補正で移行する。 |  |
| 11 | 歴史日付 | 第4部§4.1の整合CHECK | A4 | AD/BC、day/month/year/unknownを実使用。BCは生年37件・没年32件、unknownかつ日付NULLは生年15件・没年116件で、既定の表現範囲に収まる。 | era・precision・日付の組を保持し、第4部§4.1の整合CHECKをそのまま採用する。歴史日付をUTC時点へ変換しない。 |  |
| 12 | `published_year` | nullable正整数 | A4 | 234出典中NULL 228、値あり6。非正数0、範囲1989〜2024で、BC・特殊表現なし。 | nullable正整数の単一列を採用し、era/precision列は追加しない。 |  |
| 13 | country code | nullable2–3文字、通常索引 | A4 | 109国中NULL 72。非NULLは長さ・英字形式違反0だが、大文字化・trim後の意味上の重複が1行ある。 | nullable 2〜3英字CHECKと通常索引を採用する。重複があるためUNIQUE化せず、移行時に大文字へ正規化する場合は該当コードの対応を記録する。 |  |
| 14 | quote ID高水位 | AUTOINCREMENT、高水位引継ぎ | A2 | quote最大IDとsequence `last_value`はいずれも3,197で一致し、sequenceは呼出し済み。 | `quotes`をAUTOINCREMENTとし、高水位3,197を引き継いで削除済みIDを再利用しない。 |  |
| 15 | category `updated_at` | sitemap/cache判定用に新設 | A3/A4 | 62件すべて`created_at`ありで、全件同一の2026-01-12作成時点。現行にcategory `updated_at`はない。 | 新設し、初期値は現行`created_at`を流用する。以後の管理更新時に更新し、移行日を一律lastmodにはしない。 |  |
| 16 | snapshot列/sort | 現行3表の指標を維持 | A7/A8 + O2 | quote 1,831、author 755、category 53の3 snapshotは孤立0・同一refresh時点。公開UIはrank/score等を利用し、外部consumerなし。score同点はquote 1,776行、author 590行に存在する。 | 現行3表の指標を維持して原本から再計算し、同点時はIDを最終キーにして決定的sortとする。snapshot raw行は移さない。 |  |
| 17 | 条件付き廃止object | 新構成へ持ち込まない | A9 + O2/O3 | repository外consumer・管理write・Realtime購読はなし。対象view/RPC/trigger/policy/PGroonga/cronの外部依存もなし。category/character countはdirect集計と一致する一方、長期未refreshのcountry/profession MVにはdirect集計との差がある。 | 条件付き対象は持ち込まず、必要機能だけ単純SQL/Pythonとranking CLIへ置換する。countは新DB原本からdirect算出し、RLS/GRANT/MV/PGroonga/DB cronは再作成しない。 |  |
| 18 | 管理KPI | 必要値だけdirect COUNT | A1/A9 + O2 | 管理KPI/log viewには各7 callsの痕跡があるが、利用者は運用者1名で外部consumerなし。必要値は総数・公開数・ranking更新時点等の小規模集計。 | 必要KPIだけdirect COUNT/MAXで算出し、専用view・集計表・refresh jobは作らない。不要な指標はUIごと除外する。 |  |
| U1 | Supabase権限是正 | O3結果後の別枠の現行運用判断 | O3 | broad default privilegeとMVの広いACLは非意図的。特に`SECURITY DEFINER`のranking refresh内部関数と公開2 overloadをanon/authenticatedが実行可能で、外部利用実績はないが高負荷処理・log増加を誘発できる。 | 現行DBで最低限、ranking refresh 3関数のanon/authenticated `EXECUTE`を早期にREVOKEする。移行まで現行運用が続くなら、default privilegeとMV ACLも別の承認済みsecurity作業で最小権限化する。 |  |
