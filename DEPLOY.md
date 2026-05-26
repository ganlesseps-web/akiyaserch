# DEPLOY — Vercel + Turso + GitHub Actions

完全クラウド構成のセットアップ手順。所要時間 30〜45 分。Mac OFF でも稼働、PC/スマホどちらからでもダッシュボード閲覧可。

## 構成図

```
[GitHub Actions cron]
  ├ scrape.yml   30分おき → Turso にUPSERT
  └ notify.yml   毎時00分 → 未通知 & filter pass を Discord 通知

[Vercel Hobby]
  └ FastAPI ダッシュボード → Turso 読み出し
       ↳ Basic認証 (DASHBOARD_USERNAME / DASHBOARD_PASSWORD)

[Turso] libsql-server, SQLite互換, 9GB無料
[Discord] Webhook URL に POST
```

---

## 1. Turso セットアップ

### 1-1. アカウント作成

https://turso.tech にアクセスして GitHub アカウントでサインアップ（無料）。

### 1-2. Turso CLI インストール

```bash
brew install tursodatabase/tap/turso
turso auth login
```

ブラウザが開いて GitHub OAuth 完了。

### 1-3. DB 作成

```bash
turso db create akiyaserch --location nrt    # nrt = 東京リージョン
```

### 1-4. 接続情報を取得

```bash
# 接続URL
turso db show akiyaserch --url
# → libsql://akiyaserch-<your-username>.turso.io  ← これが TURSO_DATABASE_URL

# 認証トークン (永続)
turso db tokens create akiyaserch
# → eyJhbGciOi...  (長い JWT) ← これが TURSO_AUTH_TOKEN
```

2つの値を **メモ帳に保存**（後で Vercel と GitHub に登録）。

### 1-5. （任意）ローカルから接続テスト

```bash
cd /Users/owner/Desktop/trade
source .venv/bin/activate
export TURSO_DATABASE_URL='libsql://...'
export TURSO_AUTH_TOKEN='eyJ...'
python -m src.cli db init       # スキーマ作成
python -m src.cli scrape         # ローカルから Turso に書き込む
turso db shell akiyaserch        # SQL シェルでデータ確認
> SELECT COUNT(*) FROM properties;
> .exit
```

---

## 2. GitHub Secrets 登録

GitHub の akiyaserch リポジトリで:

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

次の 3 つ（Distance Matrix 使うなら 4 つ）を登録:

| Name | Value |
|---|---|
| `TURSO_DATABASE_URL` | `libsql://akiyaserch-...turso.io` |
| `TURSO_AUTH_TOKEN` | `eyJ...` (Turso CLI で取得した JWT) |
| `DISCORD_WEBHOOK_URL` | Discord サーバー設定 > 連携サービス > ウェブフックで発行 |
| `GOOGLE_MAPS_API_KEY` | （任意）境界府県を距離で詰めるなら |

または `gh` CLI で一括登録:

```bash
gh secret set TURSO_DATABASE_URL --body 'libsql://...'
gh secret set TURSO_AUTH_TOKEN --body 'eyJ...'
gh secret set DISCORD_WEBHOOK_URL --body 'https://discord.com/api/webhooks/...'
```

### 動作確認

`Actions` タブで `scrape` ワークフローを開いて `Run workflow` を手動実行。
緑になれば OK。Turso の properties テーブルに行が入っているはず。

---

## 3. Vercel デプロイ

### 3-1. Vercel アカウント作成

https://vercel.com にアクセス、GitHub でサインアップ。

### 3-2. プロジェクト import

`Add New...` → `Project` → akiyaserch リポジトリを Import

設定:
- **Framework Preset**: Other （Vercel が自動検出するはず）
- **Root Directory**: そのまま (リポジトリルート)
- **Build Command**: 空欄 (vercel.json で指定済み)
- **Install Command**: 空欄
- **Output Directory**: 空欄

### 3-3. Environment Variables

Deploy 前に `Environment Variables` を追加:

| Name | Value | Environment |
|---|---|---|
| `TURSO_DATABASE_URL` | (Turso の URL) | Production, Preview, Development |
| `TURSO_AUTH_TOKEN` | (Turso の JWT) | Production, Preview, Development |
| `DASHBOARD_USERNAME` | 好きなユーザー名 | Production, Preview |
| `DASHBOARD_PASSWORD` | **強いパスワード** | Production, Preview |

### 3-4. Deploy

`Deploy` をクリック。1〜2 分で完了。

`https://akiyaserch-<random>.vercel.app` のような URL が払い出される。
（後で `Settings` → `Domains` で `akiyaserch.vercel.app` に変えられる）

ブラウザで開くと Basic 認証ダイアログ。設定したユーザー名/パスワードを入力。

---

## 4. iPhone / Android からアクセス

Vercel URL をブックマーク or ホーム画面に追加すれば PWA 的に使える:

**iPhone (Safari)**:
1. Vercel URL を開く → 認証
2. 共有ボタン → `ホーム画面に追加`
3. ホーム画面のアイコンをタップ = 全画面表示

**Android (Chrome)**:
1. 同様に URL を開く
2. メニュー → `アプリをインストール` または `ホーム画面に追加`

---

## 5. 監視・メンテ

### GitHub Actions 利用枠

private repo の無料枠は **2000 分/月**。本構成の見積:
- scrape (30分間隔, ~30秒/回): ~720 分/月
- notify (毎時, ~30秒/回): ~360 分/月
- **計 ~1080 分/月** → 余裕で枠内

枠超過しそうなら:
- リポジトリを public にする → Actions 無制限
- scrape を 60 分間隔に下げる

### Turso 無料枠

- 9 GB ストレージ
- 1 B (10億) row reads / 月
- 25 M row writes / 月

物件は数千件程度なので余裕でずっと無料。

### Vercel 無料枠

- 100 GB 帯域 / 月
- 100k 関数呼び出し / 月（個人利用なら十分）

### ログ確認

| どこで | 何が見られる |
|---|---|
| GitHub `Actions` タブ | scrape / notify の実行履歴・ログ・失敗時の stack trace |
| Vercel `Deployments` → ログ | ダッシュボード関数の Runtime ログ |
| Turso `turso db shell akiyaserch` | DB 直接クエリ |
| Discord 投稿チャンネル | 通知履歴 |

---

## 6. ローカル開発（Vercel デプロイ後も）

`.env` で Turso 接続して同じデータを触る:

```bash
cp config/.env.example .env
# .env に編集:
#   TURSO_DATABASE_URL=libsql://...
#   TURSO_AUTH_TOKEN=...
#   DISCORD_WEBHOOK_URL=...
#   DASHBOARD_USERNAME=admin
#   DASHBOARD_PASSWORD=test

source .venv/bin/activate
python -m src.cli scrape          # Turso に書き込み
python -m src.cli notify --dry-run
python -m src.cli web             # http://localhost:8000 (Basic auth あり)
```

`TURSO_DATABASE_URL` を unset すれば自動でローカル SQLite (`data/properties.db`) にフォールバック。

---

## 7. トラブルシューティング

### Vercel デプロイ失敗 `ModuleNotFoundError: src`

`vercel.json` の builds 設定が読まれていない。リポジトリルートに置いてあるか確認。

### Vercel 関数 timeout

Hobby は 10 秒。Turso へのコールドスタートで超える場合は Pro ($20/mo)。
普段は数百ミリ秒で返るので、初回アクセスのみ問題が出ることがある。

### GitHub Actions が走らない

- リポジトリが long-inactive だと cron が自動停止する（60日無操作）
- Settings → Actions で workflow が enabled か確認
- secrets 名のタイポ確認

### Discord に通知が来ない

```bash
gh workflow run notify --ref main
gh run watch
```
で手動実行 → ログ確認。よくある原因:
- `DISCORD_WEBHOOK_URL` の typo
- `config/filters.yaml` の府県allowlist に該当物件が0件 → 仕様通り

### Basic 認証ダイアログがループする

ブラウザに古い認証情報がキャッシュされている。
- macOS Safari: 環境設定 → パスワードから該当 URL を削除
- Chrome: シークレットウィンドウで開きなおし

### Turso の row が増えない

`turso db shell akiyaserch` で `SELECT * FROM properties ORDER BY first_seen_at DESC LIMIT 5;` を実行して確認。0行なら scrape ジョブが Turso ではなくローカル SQLite に書いている可能性 → secrets を再確認。
