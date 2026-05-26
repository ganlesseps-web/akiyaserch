# 進捗 — trade (0円・格安物件 監視＆通知システム)

## Now
MVP一通り完成 (2026-05-26)。`みんなの0円物件` から RSS+詳細ページで10件取得 → SQLite 保存 → フィルタ → Discord通知 → Webダッシュボード までend-to-end稼働確認済み。Discord Webhook URL設定 + launchd登録 で運用開始できる状態。

## Next (Mac)
- [ ] `.env` を作成: `cp config/.env.example .env` → `DISCORD_WEBHOOK_URL` を貼る
  - Discord サーバー設定 > 連携サービス > ウェブフック で発行
- [ ] launchd 登録: `.venv/bin/trade launchd install`
  - scrape: 15分間隔 / notify: 毎時00分
  - 状態確認: `trade launchd status` / 解除: `trade launchd uninstall`
- [ ] 1日回して通知量を観察、必要なら `config/filters.yaml` の府県allowlist / NGワードを調整
- [ ] (任意) Google Maps Distance Matrix API キー取得 → `.env` に設定 → `trade notify --use-distance-matrix` で境界府県を詰める
- [ ] (任意) `git init` してリモートリポジトリへ push（現状ローカルディレクトリ）

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
- 2026-05-26: 直接 git init せずローカルディレクトリのまま開発（必要になったらユーザー判断で）。
