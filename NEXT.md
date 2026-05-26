# 進捗 — trade (0円・格安物件 監視＆通知システム)

## Now
クラウド本番稼働中 + 家いちば (2本目ソース) 追加完了 (2026-05-26)。Turso に 210件 (zero.estate 10, ieichiba 200)、Discord に関西圏 24件の初回 notify 完了済み。次セッションは追加ソース or 通知強化 (B: 画像/地図/ハザード) のどちらか。

## Next (Mac)
- [x] Turso DB 作成、Vercel デプロイ、GitHub Secrets 登録、Basic 認証セット (2026-05-26 完了)
- [ ] スマホで https://akiyaserch.vercel.app/ → Basic 認証 (admin / Qo-H1qXJO4RlZK-sMFzDr4UnOk0V8j4f) → 「ホーム画面に追加」
- [ ] 1日回して通知量を観察、必要なら `config/filters.yaml` の府県allowlist / NGワードを調整
- [ ] (推奨) Discord Webhook URL を再生成し古いものを revoke (会話履歴に平文で残っているため)
- [ ] (任意) Google Maps Distance Matrix API キー取得 → GitHub secret `GOOGLE_MAPS_API_KEY` に登録
- [ ] (任意) Vercel access token (vcp_...) を https://vercel.com/account/tokens で revoke (セットアップ完了したので不要)

## Next (Mac) — ローカル運用したい場合のみ
- [ ] `cp config/.env.example .env` → `DISCORD_WEBHOOK_URL` だけ設定
- [ ] `.venv/bin/trade launchd install` で 15分scrape + 毎時notify を仕掛ける

## Next (Remote-safe)
- [x] `src/scrapers/ieichiba.py`: 家いちば JSON API 経由 (2026-05-26 完了、200件取得実績)
- [ ] `src/scrapers/akiya_bank.py`: 全国版空き家・空き地バンク (LIFULL or アットホーム) スクレイパ
  - LIFULL は CloudFront bot block あり (実 User-Agent で回避可、ただし利用規約再確認)
  - アットホーム akiya-athome.jp は 403 (要調査)
- [ ] **次フェーズ候補 B (通知強化)**: Discord Embed に物件画像メイン表示 + Google Maps リンク + ストリートビュー + ハザードマップリンク
- [ ] `src/filter.py`: Distance Matrix API 呼び出し本体を実装し、`drive_cache` テーブルに保存
- [ ] DEPLOY.md の `turso db create --location nrt` を `aws-ap-northeast-1` に修正
- [ ] DEPLOY.md の Turso URL 例を `libsql://` から `https://` に書き換え (現状の libsql-client は ws ハンドシェイクが 400 を返すため)
- [ ] db.py: `using_libsql()` の判定を `https://*.turso.io` も認識するよう拡張 (現状 URL prefix の確認なしで動いてはいるが明示的に)
- [ ] ダッシュボードに「お気に入りのみメモ追加」モーダル追加（要 `python-multipart`）
- [ ] ダッシュボードに「ソース別フィルタ」追加
- [ ] GitHub Actions の `actions/checkout@v4`, `actions/setup-python@v5` は Node.js 20 deprecation 警告中。2026-09 までに v5/v6 系へ更新
- [ ] スクレイパが取得した raw HTML を debug のため `data/raw/<source>/<listing_id>.html` に保存するオプション（任意）
- [ ] 通知本文に「物件詳細ページの最初の画像」をプレビュー表示するよう Embed 改善
- [ ] `trade db vacuum` コマンド追加

## Blocked / Questions
- 全国版空き家・空き地バンクの利用規約と robots.txt 確認 (着手前)
- 関東/東北/北海道/九州の0円物件は10件取得済みだが allowlist (大阪圏) 対象外。次の RSS 更新で関西物件が出るまで Discord 通知は0件のまま (正常動作)。

## Recent decisions
- 2026-05-26: フィルタは「大阪駅から車で2時間以内」OR「指定都道府県内」のOR条件。府県allowlistで粗くフィルタ後、境界ケースのみ Google Maps Distance Matrix API で確認（コスト最小化）。
- 2026-05-26: 通知は Discord Webhook、テンポは1時間ごとのダイジェスト（新着0件ならスキップ）。
- 2026-05-26: 価格上限は¥300万。みんなの0円物件は¥0 のみだが、他ソース併用時に効く。
- 2026-05-26: MVP のデータソースは「みんなの0円物件」「全国版空き家・空き地バンク」の2本。家いちば・アットホーム・ジモティーは拡張で。
- 2026-05-26: スクレイプ15分間隔、通知バッチは毎時00分。両方 launchd で。
- 2026-05-26: ダッシュボードは FastAPI + HTMX、localhost:8000、既読/お気に入り管理。
- 2026-05-26: みんなの0円物件は WordPress の RSS (`/feed/`) を持っており新着検知に最適。詳細ページは `wp-content` 配下に画像、`物件概要` テーブルから属性抽出。価格フィールドは「希望価格」表記もあるため `xxx価格` を suffix 一致で拾う方式に。
- 2026-05-26: 市区町村抽出は3パターン (郡+町村 / 市+任意の政令指定区 / 23区) を non-greedy で実装。greedy だと「桶川市大字加納...」のような字を吸ってしまうため。
- 2026-05-26: GitHub リポジトリ ganlesseps-web/akiyaserch (private) に push。初期コミット 36f9ded。
- 2026-05-26: クラウド構成として「Vercel + Turso + GitHub Actions」(案A) を採用。完全無料・Mac OFF可・PC/スマホ両対応。
- 2026-05-26: db.py を libsql 対応の thin wrapper で SQLite/Turso 両対応に。`TURSO_DATABASE_URL` 環境変数で自動切替。tests は in-memory sqlite3 のまま動くので CI も速い。
- 2026-05-26: FastAPI に Basic 認証追加 (`DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` 未設定時は no-auth)。`/healthz` は認証バイパス。
- 2026-05-26: GitHub Actions scrape は 30分間隔 (private repo 2000分/月の枠を考慮)。notify は毎時。月間 ~1080分使用見込み。public repo にすれば無制限。
- 2026-05-26: スマホ対応として viewport meta + 480px 以下のレスポンシブCSSを追加。PWA 風にホーム画面追加可。
- 2026-05-26: GitHub Actions の scrape/notify ワークフローに secrets early-exit ガード追加。secrets 未設定時は install 前に即 fail して時間を浪費しない。
- 2026-05-26: 本番デプロイ完了。Turso DB (aws-ap-northeast-1) 作成、Vercel akiyaserch project に env vars 4個 + SSO protection 無効化、https://akiyaserch.vercel.app/ で Basic 認証付きダッシュボード公開。
- 2026-05-26: libsql-client (Python 0.3.1) は libsql:// (WebSocket) URL で 400 エラー。Turso の Hrana HTTP API (https://) を使うことで解決。GitHub Secret と Vercel env var どちらも https:// 形式で登録。
- 2026-05-26: vercel.json の legacy `builds` + `rewrites` 構文で routing が破綻 (404)。新構文 (`rewrites` のみ、`api/*.py` 自動検出) に切替えてデプロイ成功。
- 2026-05-26: 認証情報 admin / Qo-H1qXJO4RlZK-sMFzDr4UnOk0V8j4f は会話チャット内に平文残存。ユーザー側でパスワードマネージャに保存済みなら revoke/再生成は任意。
- 2026-05-26: 家いちばスクレイパは公式 JSON API `/api/properties?orderby=price_asc&page=N` を採用。HTML パースより速い・正確・サイト負荷小。1リクエスト10件、500件総数、20ページ MAX_PAGES + SCRAPE_PRICE_CEILING (500万) で早期 break。
- 2026-05-26: 家いちば初回スクレイプで関西圏 24件が price ≤ 300万でヒット → Discord に digest 2分割で送信成功。神戸90万円農地、京都伊根町80万円、兵庫赤穂35万円山林、大阪大東270万円戸建てなど良物件多数。
