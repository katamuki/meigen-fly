# meigen-fly

## 開発方針

本プロジェクトは個人開発の小規模なWebサイトです。

管理画面はありますが、主な機能はデータの参照であり、個人情報・決済情報・その他の機微情報は扱いません。

そのため、開発では次の方針を重視します。

- 現在必要な機能を、理解しやすく保守しやすい形で実装する
- 将来の可能性だけを理由にした抽象化や複雑化は避ける
- 小規模サービスに見合った、シンプルな構成を優先する
- テストやエラーハンドリングは、機能の重要度と障害時の影響に応じて行う
- セキュリティの基本事項は守りつつ、扱うデータや想定リスクに対して過剰な仕組みは導入しない

大規模運用、高可用性、厳格な監査対応、複雑な権限管理などは、実際に必要になった時点で検討します。

## データベースの構築

SQLiteのスキーマはAlembicで管理し（`migrations/`）、アプリ用の表定義は`app/schema.py`にあります。

```bash
uv run alembic upgrade head   # 空のdata/app.dbにスキーマを作る
uv run pytest                 # テスト
```

旧環境（Supabase）からのデータ移行は`scripts/`のエクスポート・投入・検証スクリプトで行います。手順と変換ルールは[docs/database/migration-runbook.md](docs/database/migration-runbook.md)を参照してください。

## ローカル管理画面

ローカルでは、開発用の管理者メールアドレスと一時的なCSRF署名鍵をコマンドの環境変数として渡して起動します。`CF_ACCESS_AUD`は設定しないでください。

```bash
ADMIN_DEV_EMAIL=you@example.com SECRET_KEY="$(openssl rand -hex 32)" uv run uvicorn app.main:app --reload
```

起動後に <http://localhost:8000/admin> を開きます。この迂回は`PUBLIC_ORIGIN`のホストが`localhost`または`127.0.0.1`の場合だけ有効です。生成した鍵の実値はリポジトリやシェル設定へ保存しません。
