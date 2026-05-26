# 進捗 — trade (0円・格安物件 監視＆通知システム)

## Now
クラウドデプロイ準備完了 (2026-05-26)。Vercel + Turso + GitHub Actions の完全無料構成 (案A) で動かせる状態。コード側はすべて完了、ユーザー側で Turso/Vercel/Secrets のセットアップ作業をすれば本番稼働。手順書: [DEPLOY.md](DEPLOY.md)

## Next (Mac) — クラウド運用のセットアップ作業
詳細は [DEPLOY.md](DEPLOY.md)。サマリ:
- [ ] **Turso** アカウント作成 + CLI install (`brew install tursodatabase/tap/turso`) + DB 作成 + URL/Token 取得
- [ ] **GitHub Secrets** 登録: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `DISCORD_WEBHOOK_URL`
- [ ] **Vercel** アカウント作成 + akiyaserch リポを Import + 環境変数 4個 (`TURSO_*`, `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`) を設定 + Deploy
- [ ] GitHub `Actions` タブで `scrape` を手動 Run → Turso にデータ入る確認
- [ ] スマホで Vercel URL → Basic 認証 → ホーム画面に追加
- [ ] 1日回して通知量を観察、必要なら `config/filters.yaml` の府県allowlist / NGワードを調整
- [ ] (任意) Google Maps Distance Matrix API キー取得 → GitHub secret `GOOGLE_MAPS_API_KEY` に登録

## Next (Mac) — ローカル運用したい場合のみ
- [ ] `cp config/.env.example .env` → `DISCORD_WEBHOOK_URL` だけ設定
- [ ] `.venv/bin/trade launchd install` で 15分scrape + 毎時notify を仕掛ける

## Next (Remote-safe)
- [ ] `src/scrapers/akiya_bank.py`: 全国版空き家・空き地バンク (LIFULL運営) スクレイパ
  - サイト構造: 都道府県別ページ → ID 抽出 → 詳細
  - 価格上限フィルタが活きてくる (¥0〜¥300万)
- [ ] `src/scrapers/iechiba.py`: 家いちば（激安寄り、任意）
- [ ] `src/filter.py`: Distance Matrix API 呼び出し本体を実装し、`drive_cache` テーブルに保存
- [ ] ダッシュボードに「お気に入りのみメモ追加」モーダル追加（要 `python-multipart`）
- [ ] ダッシュボードに「ソース別フィルタ」追加
- [ ] スクレイパが取得した raw HTML を debug のため `data/raw/<source>/<listing_id>.html` に保存するオプション（任意）
- [ ] 通知本文に「物件詳細ページの最初の画像」をプレビュー表示するよう Embed 改善
- [ ] `trade db vacuum` コマンド追加

## Blocked / Questions
- 「現在の `data/properties.db` を user 環境でそのまま使うか、それとも launchd 設定後にクリアして再scrapeするか」→ どちらでも可。継続でOK。
- 全国版空き家・空き地バンクの利用規約と robots.txt 確認 (着手前)

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
