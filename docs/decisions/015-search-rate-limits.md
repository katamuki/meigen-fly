# アーキテクチャ決定記録: 検索UIとレート制限

## ステータス

**確定: 1文字から500ms debounceで検索し、アプリ側の単純なIP制限を設ける**（2026-07-14決定、2026-07-15簡略化）

## コンテキスト

`/search`はキャッシュしないHTMXインクリメンタル検索である。データは約3,000行で、ADR 002どおり単純な`LIKE`検索は十分軽く、守る対象のリスクは小さい。防御と実装は最小限にし、詳細な制御はコードとテストに委ねる。

## 決定

- 検索開始は正規化後**1文字**から。日本語には「愛」「夢」など1文字の有効な検索語があるため、最小2文字にしない。
- 入力は前後空白の除去と連続空白の畳み込みで正規化し、0文字は検索せず初期表示を返す。上限は100文字。正規化と検証はサーバーを正とし、クライアントは同じ規則を先行適用するだけとする。
- インクリメンタル検索は**500ms**のtrailing debounceとし、IME変換（composition）中は送信しない。実装はADR 016に従い外部の静的JSで行う。Enter・検索ボタンの通常GET submitはdebounceなしで動き、JavaScript無効時も検索できる。
- 通常GETとHTMX fragment（`HX-Request`）は同じ検証・検索ロジックを共有し、`Vary: HX-Request`を返す。全応答は`private, no-store`（ADR 001）。
- アプリ側にIP単位の単純なレート制限を1つ設ける（初期値の目安: 30回/10秒）。超過は`Retry-After`付き429とし、クライアントは待ち時間を案内して自動再試行しない。
- カウンターはプロセスメモリのbest-effortとし、再起動で消えることを受容する。Redis・SQLiteへの永続化はしない。IPとqueryをDB・通常ログへ永続化しない。
- 送信元IPはADR 013どおりTunnel経由の`CF-Connecting-IP`から得る。
- Cloudflare FreeのRate Limiting 1枠はいいねPOST（ADR 006）へ優先配分し、検索用Cloudflareルールは初期配置しない。Turnstile・Challenge・Bot Managementも初期導入しない。

## リリース前確認

- IME変換中に送信されず、確定後500msで1回だけ送信される。
- 0文字・1文字日本語・上限超過で、通常GETとfragmentの挙動が一致する。
- レート超過で429と`Retry-After`が返り、通常利用では429が出ない。

## 再検討条件

- 通常利用の429が継続する、または検索負荷による可用性影響が実測された場合（閾値調整 → Cloudflareルール → Challengeの順で検討）
- Uvicornの複数worker化・Machineの複数台化でプロセス内カウンターの実効性が下がる場合
- データ量増加で`LIKE`検索自体が重くなった場合（ADR 002の再検討条件）

## 採用しなかった選択肢

- **2文字以上のみ検索**: 日本語の1文字語を失うため不採用。
- **Cloudflareだけで制限**: Freeの1ルール枠がいいねPOSTと競合するため不採用。
- **Redis等の永続カウンター・Turnstile常時表示**: 初期規模のリスクに見合わないため不採用。

## 参考

- [Cloudflare Rate limiting rules](https://developers.cloudflare.com/waf/rate-limiting-rules/)
- [htmx `hx-trigger`](https://htmx.org/attributes/hx-trigger/)

## 追記（2026-10-06、フェーズ5-C）

Uvicornは`--no-access-log`で起動する。Uvicornは既定で`127.0.0.1`からの`X-Forwarded-For`を信頼するため、Tunnel経由のアクセスログには送信元IPとqueryが出る。書式加工よりログ自体を出さない方が単純で確実である。通信量はCloudflare Analyticsで見る。アプリ通常ログにもIP・検索語を出さない。

Cloudflare FreeはRate limitingのMethod条件を提供しないため、いいね用の1枠は`/api/likes/`のpath条件とし、全methodをカウントする（APIはPOSTのみ）。検索用ルールは追加しない。[公式プラン別仕様](https://developers.cloudflare.com/waf/rate-limiting-rules/)
