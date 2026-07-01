# アーキテクチャ決定記録: SQLite移管時の日本語検索方式

## ステータス

検討中（2026-06-30 調査）

## コンテキスト

現在の名言集.comは **Vercel + Supabase(PostgreSQL)** 構成で稼働している。
これを **AWS Lightsail + FastAPI + HTMX + SQLite** 構成へ作り変えることを検討している。

- **移管の主目的**: Lightsail上で **コストを抑えて運用** すること（DBサーバープロセス不要・ファイル1個で完結するSQLiteを採用したい）。
- **論点**: 現在の検索は PostgreSQL拡張 **PGroonga** による高精度な日本語全文検索に依存している。SQLiteへ移管した場合に **日本語検索（特に2文字語）をどう実現するか** を決める必要がある。

### 現状（移管元）の検索実装

| 項目 | 内容 |
|---|---|
| DB | Supabase (PostgreSQL) |
| 全文検索 | **PGroonga** 拡張の `&@~` 演算子（クエリ構文対応） |
| トークナイザ | PGroonga既定の **TokenBigram（2-gram）** + Unicode正規化 |
| 呼び出し | Next.js API Route → Supabase RPC（`search_quotes` / `search_authors`） |
| 対象（名言） | `quotes(text, text_en, context_note)` |
| 対象（著者） | `authors(name, description)` |
| 順位付け | マッチ箇所による重み付け（本文一致を優先）→ 作成日時降順 |
| インデックス | `quotes` にPGroongaインデックスあり。**`authors` には無し（シーケンシャルスキャン）** |

### データ規模（2025-10時点のseedより概算）

- 名言 `quotes`: 約 **2,100件**
- 著者 `authors`: 約 **890件**
- 合計でも約3,000行と **小規模**

### 前提の確認（重要）

- **Lightsailは永続VPS** のため、Vercel(サーバーレス)で問題になる制約（読み取り専用FS、エフェメラル、拡張ロード不可、ネイティブ依存）は **すべて解消される**。SQLiteの書き込み・FTS5カスタム拡張のロード・形態素解析ライブラリの導入すべて可能。
- したがって技術的制約より **「コストと運用簡素化」「日本語検索精度（2文字問題）」のバランス** が判断軸になる。

---

## 検討した選択肢

### 選択肢A: FTS5 標準 `trigram` トークナイザ

SQLite 3.34.0以降の標準トークナイザ。3文字単位の部分一致。

- **長所**: 追加依存・ビルド不要。SQLite内部で完結しメモリ消費ほぼ0。最小Lightsailインスタンスで動く。
- **致命的短所**: **2文字以下の語が単独でヒットしない**。
  日本語の検索語は「人生」「努力」「自由」「友情」「成功」「希望」など **2文字が主役** であり、これは **クレーム直結の不採用要因**。
- **判定**: ❌ 不採用（2文字問題のため単体では使えない）

### 選択肢B: FTS5 + アプリ側 bigram(2-gram) 分割 ★本命

Python側でテキストを2文字ずつに区切ってFTS5（`unicode61`）へ格納する。
**現在のPGroonga(TokenBigram)と同じ挙動**を再現できる。

```
本文 "人生は美しい" → bigram: 人生 生は は美 美し しい  （空白区切りで格納）
検索 "人生"         → bigram: 人生                      → MATCH '人生'    ✅
検索 "美しい"       → bigram: 美し しい                 → MATCH '美し しい'(AND) ✅
```

```python
def bigrams(s: str) -> str:
    s = s.replace(" ", "")
    return " ".join(s[i:i+2] for i in range(len(s) - 1)) if len(s) >= 2 else s
```

- **長所**:
  - **2文字検索が完全にヒット**（trigramの弱点を根本解決）
  - 形態素解析の辞書を常駐させないため **メモリほぼ0** → 安価なLightsailで運用可
  - FTS5の **bm25ランキング** が使え、現状の重み付け順位を再現可能
  - C拡張ビルド不要・SQLiteファイル1個で完結
- **短所**:
  - インデックス投入時にbigram生成処理が必要（移行スクリプト側で対応）
  - **1文字検索**はbigramでも拾えない → 1文字時のみ `LIKE '%x%'` で補助（1文字検索は元々ノイズが多く、件数も小さいので全件スキャンで一瞬）。必要ならunigramも併せて格納すれば1文字も対応可。
- **判定**: ⭐ 第一候補

### 選択肢C: FTS5 + C製 bigram カスタムトークナイザ拡張

bigramトークナイザをCで実装し `load_extension` で読み込む（Lightsailなら可能）。
`streetwriters/sqlite-better-trigram`（3文字未満も扱える改良trigram）等の既存実装を使う手もある。

- **長所**: N-gram分割をSQLite内部で完結でき、アプリ側のINSERT処理が不要。2文字対応。
- **短所**: ビルド・配布・保守の手間が増える。
- **判定**: ○ 内部完結したい場合の代替。まずはBの方が手軽。

### 選択肢D: FTSをやめて `LIKE '%語%'` 全文

全文検索インデックスを使わず単純部分一致。

- **長所**: 約3,000行という規模なら **全件スキャンでも1ミリ秒未満**。1・2・3文字すべて正しくヒットし、**文字数問題が原理的に存在しない**。依存ゼロ・メモリゼロ・実装最小。
- **短所**: 関連度ランキングやAND/OR構文は自前SQL（CASEでの重み付け）が必要。
  ※ ただし現状のPGroonga版RPCも既にCASEで重み付けしているため、その移植で済む。データが数万件規模に増えたらFTS5へ移行が必要。
- **判定**: ○ とにかく簡単に始めたい場合は現データ規模で十分実用的。

### 選択肢E: PostgreSQL + PGroonga を Lightsail上で継続

検索ロジックをほぼ無改修で移植でき日本語精度も最高水準。

- **短所**: DBプロセスが常駐しメモリ・運用コストが増える。**「コストを抑える」という移管目的に反する** ため不採用。
- **判定**: ❌ 不採用（コスト目的に反する）

---

## 比較表

| 案 | 2文字検索 | メモリ常駐 | 実装の手間 | ランキング | 評価 |
|---|---|---|---|---|---|
| A: FTS5 trigram | ❌不可 | ほぼ0 | 小 | bm25 | 不採用 |
| **B: FTS5 + アプリ側bigram** | ✅完全 | ほぼ0 | 中 | bm25 | **⭐本命** |
| C: FTS5 + C bigram拡張 | ✅完全 | ほぼ0 | 大 | bm25 | 代替 |
| D: LIKE全文（FTSなし） | ✅完全 | 0 | 小 | 自前CASE | 簡易案として有力 |
| E: PG + PGroonga継続 | ✅完全 | DBプロセス分 | 小 | PGroonga | 不採用（コスト） |

---

## 決定（暫定）

- **本命: 選択肢B（FTS5 + アプリ側bigram分割）。** 2文字問題を根本解決しつつ、辞書を常駐させずメモリ消費ほぼ0で安価なLightsailに収まり、PGroonga相当の精度・ランキングを低コストで再現できる。
- **簡易に始めるなら: 選択肢D（LIKE全文）。** 現データ規模（約3,000行）なら性能上問題なく、文字数問題も起きない。MVP・初期移行に有力。将来データ増でBへ移行。
- いずれも **2文字検索のクレームは発生しない**。trigram単体（A）とPGroonga継続（E）は不採用。

## 留意事項・補足

- **形態素解析（SudachiPy/MeCab/Janome）は初期採用しない**。精度は最高だが辞書ロードで数十〜数百MBのメモリを食い、安価なLightsailインスタンスと相性が悪い。将来精度に不満が出た場合のみ、**インデックス時（オフラインのビルドスクリプト）だけ**形態素解析を使い、本番サーバーには辞書を常駐させない案を検討する。
- **Python同梱SQLiteのバージョン確認**: FTS5有効性と、trigram利用時は **SQLite 3.34.0以降** が必要。古い場合は `pip install pysqlite3-binary` か `apsw` で新しいSQLiteを同梱（追加コストなし）。
- **`authors` もFTS5化する**: 現状authorsには全文検索インデックスが無くシーケンシャルスキャンだったため、移管を機にFTS5化して改善する。
- **HTMXとの相性**: 検索結果のpartial HTMLを返すだけなので、`hx-get="/search"` + `hx-trigger="keyup changed delay:300ms"` でインクリメンタル検索を軽量に実装できる。
- **バックアップ/運用**: SQLiteはファイル1個のためコピーでバックアップ可。継続レプリが必要なら `litestream` でS3へ安価にレプリケーション可能。
- **移行作業**: Supabase(PostgreSQL)からSQLiteへ移す際、元テキスト（`text/text_en/context_note`等）は保持しつつ、検索用のbigramカラム/FTS5テーブルを派生生成するビルドスクリプトを用意する。現状 `search_quotes` の重み付けロジック（本文一致優先）はFTS5 bm25 + 補助ソートへ置き換える。

## 次のアクション（未着手）

- [ ] 採用案（B or D）の最終決定
- [ ] Supabase → SQLite 移行スクリプト（bigramカラム/FTS5テーブル生成込み）
- [ ] FastAPI 検索エンドポイント（現 `search_quotes`/`search_authors` 相当の置き換え）
- [ ] HTMX検索UIの実装
- [ ] Python同梱SQLiteのFTS5/バージョン確認

## 参考リンク

- [SQLite FTS5 公式ドキュメント](https://sqlite.org/fts5.html)
- [SQLite FTS trigram tokenizer 日本語全文検索 (space-i)](https://www.space-i.com/post-blog/sqlite-fts-trigram-tokenizer%E3%81%A7unigram%EF%BC%86bigram%E6%A4%9C%E7%B4%A2%E3%81%BE%E3%81%A7%E3%82%B5%E3%83%9D%E3%83%BC%E3%83%88-%E6%97%A5%E6%9C%AC%E8%AA%9E%E5%85%A8%E6%96%87%E6%A4%9C%E7%B4%A2/)
- [sqlite-better-trigram (GitHub)](https://github.com/streetwriters/sqlite-better-trigram)
- [Janome + SQLite FTS5 で日本語検索精度向上 (lunaplus)](https://www.lunaplus.net/posts/2026/05/japanese-morphological-search/)
- [SQLite3 FTS5のMeCab用トークナイザ実装 (やってみる)](https://ytyaru.hatenablog.com/entry/2021/02/22/000000)
- [Python SQLiteで日本語全文検索 N-Gram/FTS5 (シラベルノート)](https://srbrnote.work/archives/5846)
- [なぜunicode61はCJK非対応か (sqlite-users)](https://sqlite-users.sqlite.narkive.com/N5MOmskp/sqlite-why-sqlite-fts5-unicode61-tokenizer-does-not-support-cjk-chinese-japanese-krean)
- [awesome-japanese-nlp-resources (GitHub)](https://github.com/taishi-i/awesome-japanese-nlp-resources)
