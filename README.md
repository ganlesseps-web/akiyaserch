# trade — 0円・格安物件 監視＆通知システム

「みんなの0円物件」をはじめとする無償譲渡・激安物件サイトを巡回し、条件に合う物件を Discord で通知。ローカルダッシュボードで一覧管理できる。

## 何ができる
- 30分間隔（クラウド）or 15分間隔（ローカル）で各サイトをスクレイピング → SQLite/Turso に保存
- 毎時00分に新着のうちフィルタ通過したものを Discord にダイジェスト通知
- ダッシュボード (localhost or Vercel) で全件一覧 / 既読 / お気に入り管理

## 動かし方は2通り
- **ローカル運用** (Mac + launchd): 後述の「セットアップ」セクション参照
- **クラウド運用** (Vercel + Turso + GitHub Actions, 完全無料・Mac OFF可・スマホ可): [DEPLOY.md](DEPLOY.md) 参照

## フィルタ仕様
- 価格: `config/filters.yaml` の `price_max` 以下
- エリア: 都道府県 allowlist に含まれる OR 大阪駅から車で2時間以内（後者は Google Maps Distance Matrix API 利用、後実装）
- NG ワード: タイトル/本文除外

## データソース
- ✅ みんなの0円物件 (https://zero.estate) — RSS 主、HTML補完
- 🚧 全国版空き家・空き地バンク (LIFULL運営)
- 🚧 アットホーム空き家バンク
- 🚧 家いちば
- 🚧 ジモティー (不動産0円)

## セットアップ
```bash
# 1. Python 3.11+ 確認
python3 --version

# 2. uv で仮想環境作成（推奨）
brew install uv  # 未インストールなら
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. 設定
cp config/.env.example .env
# .env を編集し DISCORD_WEBHOOK_URL を設定

# 4. DB 初期化
trade db init

# 5. 試しに1回スクレイピング
trade scrape minna_0en

# 6. 試しに通知（dry-run）
trade notify --dry-run

# 7. ダッシュボード起動
trade web  # → http://localhost:8000
```

## 定期実行（launchd）
```bash
trade launchd install  # ~/Library/LaunchAgents/ に plist 配置 + launchctl load
trade launchd status   # 状態確認
trade launchd uninstall
```

## 開発
```bash
pytest                  # テスト
ruff check src/         # lint
```

## ディレクトリ
```
trade/
├ NEXT.md                  # 進捗ファイル
├ config/
│   ├ .env.example
│   └ filters.yaml
├ src/
│   ├ scrapers/
│   │   ├ base.py
│   │   └ minna_0en.py
│   ├ db.py, normalize.py, filter.py, notifier_discord.py
│   ├ cli.py, scheduler.py
│   └ web/app.py
├ data/                    # SQLite (gitignore)
├ tests/
└ launchd/                 # 生成済み plist
```
