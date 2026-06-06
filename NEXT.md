# 進捗 — trade (0円・格安物件 監視＆通知システム)

## Now
セッション9 (2026-06-06): 「修繕が必要な空き家もリストから除外して」要望に対応。セッション8 は“明らかに住めない物件 (dilapidated)”だけ除外していたが、それより軽い「住めるが手を入れる必要がある」物件（説明文に 要リフォーム/改修が必要/修繕が必要/手直しが必要 等と明記）が一覧に残っていた（ローカル641件中 43件が該当）。normalize に needs_repair 判定を新設（完了形「リフォーム済」や否定形「リフォーム不要/必要ありません」は対象外）。DB に needs_repair / needs_repair_reason 列を追加 (migration)、cli reclassify で backfill。ダッシュボードの発見系ビュー（すべて/未読/0円/一軒家/土地 等）の除外条件に needs_repair を追加（dilapidated と同じ扱い、お気に入り等の手動一覧は従来どおり全件表示）。即入居OKタブ・タブ件数も同条件に統一。全71テスト緑（+10）。ローカル reclassify: dilapidated=10 / needs_repair=48（うち4件は dilapidated と重複）→「すべて」タブは 641→587件、「即入居OK」は 55→54件。**本番反映**: claude/wip→main ff マージ→push（Vercel 自動デプロイ）＋ GitHub Actions scrape 手動起動で本番 Turso に backfill（下記 Recent decisions / Next 参照）。残る限界はセッション8と同じ: 状態を書いていない物件は判定不能のため一覧に残る（「修繕ゼロ保証」は不可）。さらに厳しくしたい場合は「即入居OK の物件だけ表示」に切替も可能（件数は大きく減る）。

## Now (旧)
セッション8 (2026-06-06): 「修繕が必要なく住める空き家だけを集めたい」要望に対応。方針はユーザー選択で『両方』: ①普段の一覧（すべて/未読/0円/一軒家/土地 等の発見系タブ）から「明らかに住めない物件」(dilapidated=1: 廃屋/雨漏り/シロアリ/解体前提/大規模リフォーム必要 等) を非表示に。お気に入り/通知済み/評価済み/却下 は従来どおり全件表示。②新タブ「✨即入居OK」を追加し、リフォーム済/即入居可/築浅 等とはっきり書かれた物件 (move_in_ready=1) だけを表示。normalize に is_move_in_ready 判定を新設（「要リフォーム」「リフォームが必要」等の“これから直す”文言は弾く／完了形シグナルのみ拾う）。DB に move_in_ready / move_in_ready_reason 列を追加 (migration)、cli reclassify で既存物件に backfill。物件カードに ✨即入居OK バッジ（理由を tooltip 表示）を追加。タブ件数 (_counts) も同条件に揃え、表示件数と一致。全61テスト緑（+13）。ローカル641件で reclassify 実行: dilapidated=10（一覧から非表示化）/ move_in_ready=55（即入居OKタブに表示）。コミット2本（①検出+保存+backfill ②ダッシュボード）。重要な限界: データ性質上「修繕ゼロ保証」は不可（状態が書かれていない物件が最多）なので、“明らかに壊れた物件を除外”＋“はっきり住めると書かれた物件を厳選”の2層で実現している。**本番反映済み**: `claude/wip` → `main` を ff マージ → push（Vercel 自動デプロイ）。本番データへの move_in_ready backfill は GitHub Actions の scrape を手動起動（run 27057286611, 成功 10m13s）で実施 = 本番 Turso のマイグレーション（move_in_ready 列追加）も適用済み。本番稼働確認: `/healthz`=200, `/`=401（Basic 認証）, noindex ヘッダ有り。

## Now (旧)
セッション7 (2026-06-02): ダッシュボードの検索・フィルタ強化。「都道府県でしぼる」プルダウン（実際にデータがある県だけを件数付きで表示）と「価格でしぼる」入力（下限〜上限、万円単位）を追加。タブ切替や並べ替えをしてもフィルタ条件が維持されるようにし、該当件数も表示。tests/test_web.py を新規追加（_query_rows のフィルタ／_prefectures 集計／_man_to_yen 万円換算／TestClient で画面レンダリングと絞り込みのスモーク）、全36テスト緑。ローカルの仮想環境 (.venv) が trade→akiyaserch のフォルダ名変更で壊れていたため `uv sync` で作り直し（pytest は dev extra なので `uv run --extra dev pytest`）。フィルタは main にマージ済み・Vercel デプロイ成功で本番反映完了。あわせてリポジトリを private→public 化（パスワード変更済みのため過去履歴の旧パスワードは無効、安全）。public 化で GitHub Actions も無制限になり、無料枠の懸念が完全解消。さらに同日、ユーザー要望でダッシュボードに3機能を追加: ①「🆓0円物件」タブ（価格0円の物件だけ表示。当初「もらえる家」=定住条件検出だったが誤検出多発のため0円ベースに変更）②市区町村プルダウン（都道府県を選ぶと出る）③価格を数値入力からプルダウンに変更。全45テスト緑で本番反映済み。

## Now (旧)
セッション6 (2026-06-01): 「Mac 起動なしで24時間・完全無料」要望に対応。調査の結果、システムは既に完全クラウド化済み (GHA scrape+notify、Turso、Vercel) で Mac 不要・.env も launchd も無しと判明。唯一の懸念だった GitHub Actions 無料枠 (private repo = 月2000分) に対し、30分間隔 scrape が月~3600-4000分で超過リスクがあった。ユーザー選択で「非公開のまま頻度を1日1回に下げる」方針。scrape を `*/30` → `0 21 * * *` (06:00 JST 毎朝1回)、notify を毎時 → `30 21` + `0 9` (06:30 + 18:00 JST の2回、idempotent なので二重通知なし) に変更。月使用量 ~360分 = 無料枠の18% に収まり、完全無料24時間を確定。コードに秘密情報ゼロ (全て GitHub Secrets 経由) も確認済み、将来 public 化したくなれば即可能。

## Now (旧)
セッション5 (2026-05-30): 「9府県の全市区町村の空き家バンク取得」要望に対応。海沿い市町村 blacklist 機能を実装 (filter.py + filters.yaml + tests)。和歌山県南紀沿岸 8自治体 + 三重県南伊勢〜熊野沿岸 7自治体 + 京都伊根町 + 大阪岬町 + 山口長門市 を default で blacklist。akiya-athome 全国版検索 API (`/bukken/search/list/?pref_cd=XX`) は現在メンテ中で HTTP 500、復旧後に scraper 実装予定。LIFULL HOME's は CloudFront WAF で 403 + 商用サイト規約懸念で見送り。本日 GHA scrape は前回 1回 Turso 502 で失敗、次回 cron で自動回復 (一過性)。

## Now (旧)
さらに 6自治体追加 + 「定住条件付き譲渡」検出機能を実装 (2026-05-28 セッション3)。akiya-athome 系: 朝来0/舞鶴7/松阪9/宍粟16 = 32件 + 独自: 東吉野24/十津川8 = 32件 = 計+64件。熊野市 (Jimdo) と真庭市 (cocomaniwa.com) は構造複雑のため次セッション送り。normalize.detect_settlement_offer() で「無償譲渡/定住条件付/試住制度/改修費返済不要/賃貸後譲渡/○年定住で…/譲渡可」等を検出、DB に settlement_offer 列追加、Discord embed の title に 🎯 prefix + 専用フィールド表示。現在 27自治体 scraper。セッション4 (2026-05-28): 「空き家率高い県 (山梨/和歌山/徳島/高知/山口) で内陸・補助金あり」要望に対応。filter allowlist に山梨/高知/山口 を追加、5自治体 scraper 追加 (北杜/橋本/三好/本山/美祢、全 akiya-athome 系 = サブクラス追加だけで対応)。神山町は専用バンク無し (全国版に登録のみ) で見送り。実物件は三好25 + 美祢49 = +74件、他3自治体 (北杜/橋本/本山) は現在 0 件だが scraper は登録済 (将来追加時に自動取得)。総自治体数 27→32。本番反映完了: GHA scrape 12分・三好25+美祢49=新規74件投入、notify は `scanned=629 passed=49 sent=49` で Discord に49件のダイジェスト送信成功。

## Next (Mac)
- [x] **「住める空き家だけ」を本番反映 (セッション8)** — 2026-06-06 完了。`claude/wip` → `main` ff マージ → push（Vercel 自動デプロイ）。ボロ物件の非表示＋「✨即入居OK」タブが本番反映。
- [x] **本番データに即入居判定を埋める** — 2026-06-06 完了。GitHub Actions の scrape を手動起動（`gh workflow run scrape.yml --ref main`, run 27057286611 成功）で本番 Turso に move_in_ready を backfill（列追加マイグレーションも適用済み）。以降は毎朝06:00 JST の自動巡回でも維持される。
- [ ] (任意) スマホで本番ダッシュボードの「✨即入居OK」タブを開いて表示を目視確認（Basic 認証が要るため自動確認はできていない）。
- [x] **フィルタ機能を本番反映** — 2026-06-02 完了。main へ ff マージ → Vercel デプロイ成功。
- [x] Turso DB 作成、Vercel デプロイ、GitHub Secrets 登録、Basic 認証セット、家いちば追加、UI 強化、AIスコアリング実装 (2026-05-26 完了)
- [ ] **(オフ中) AI スコアリング再開** — `config/preferences.yaml` の `score_threshold` を 6 に戻す + `.github/workflows/score.yml` の `schedule` コメント外す。既存スコアは残っているので新規物件のみ採点 → 月 $0.05 程度。
- [ ] **(オフ中) preferences カスタマイズ** — `config/preferences.yaml` の description を自分の好みに編集 → preferences_hash が変わるので再開時に全件再採点 ($0.31 程度)。
- [ ] (任意) ANTHROPIC_API_KEY が不要なら https://console.anthropic.com/settings/keys で revoke
- [ ] スマホで Web 操作確認 (★レーティング・却下ボタン・検索)
- [ ] 1日回して通知量を観察、必要なら `config/filters.yaml` の府県allowlist / NGワード調整
- [ ] (推奨) Discord Webhook URL / Basic auth password を revoke & 再発行 (会話履歴に平文で残っているため)
- [ ] (任意) Google Maps Distance Matrix API キー → 境界府県の本物のドライブ時間判定
- [ ] (任意) Vercel access token (vcp_...) を https://vercel.com/account/tokens で revoke (不要)

## Next (Mac) — ローカル運用したい場合のみ
- [ ] `cp config/.env.example .env` → `DISCORD_WEBHOOK_URL` だけ設定
- [ ] `.venv/bin/trade launchd install` で 15分scrape + 毎時notify を仕掛ける

## Next (Remote-safe)
- [x] `src/scrapers/ieichiba.py`: 家いちば JSON API 経由 (2026-05-26 完了、200件取得実績)
- [x] `src/scrapers/iga_akiyabank.py`: 三重県伊賀市公式空き家バンク (2026-05-26 完了、18件取得)
- [x] 自治体scraper 13本追加 (2026-05-27 完了): 神河/多可/たつの/養父独立/京丹後/福知山/名張/高島/五條/下市/わかやまLIFE/美作 + akiya-athome 汎用ベース
- [x] 補助金充実 8自治体追加 (2026-05-27 セッション2 完了): 綾部/西粟倉/奈義/甲賀/宇陀/大台/南丹/丹波篠山
- [x] 補助金充実 6自治体追加 + 定住条件検出 (2026-05-28 セッション3 完了): 朝来/舞鶴/松阪/宍粟/東吉野/十津川 + 🎯 バッジ
- [x] 空き家率高い5県カバー (2026-05-28 セッション4 完了): allowlist 拡張 + 北杜/橋本/三好/本山/美祢 scraper
- [ ] (任意) 北杜市・橋本市・本山町は現在 0 件。空き家バンクに物件登録される時点で自動取得される
- [ ] (任意) 神山町 (徳島・IT移住メッカ) は専用バンク無しのため別データソース要検討
- [ ] (任意) 三重県 熊野市 (Jimdo CMS, kumanoijunet.jimdofree.com) — URLが日本語パス + 構造が深く、独自実装に~1時間
- [ ] (任意) 岡山県 真庭市 (cocomaniwa.com) — 物件 一覧の HTML 構造未把握、JS依存の可能性。要再調査
- [ ] (任意) 与謝野町の akiya-athome subdomain or 一覧 URL 発見 → scraper 追加
- [ ] (任意) 米原市の空き家バンク (現在公開バンク無し、市役所相談ベース運用らしい)。公開された時点で追加検討
- [ ] (任意) classo (丹波篠山) のページネーション。サイト側で page/2/ も page/1/ と同じ12件返してくる挙動。総13ページあるはずなのでURL pattern を再調査
- [ ] (任意) ダッシュボードに「🎯 定住条件付き」フィルタタブを追加 (現状 Discord 通知でしか可視化されていない)
- [ ] (任意) iga_akiyabank で詳細ページから area_land / area_building 取得 (現状は list 1リクのみ)
- [ ] (任意) 福知山市が物件追加されたとき自動取得可 (現状 0 件で scraper 待機)
- [ ] (任意) わかやまLIFE のフィルタ URL を再調査 (akiya_area パラメータが効かないため全和歌山県取得→住所で絞り込み中)。古座川/有田川が登録された時に動くが、和歌山県他自治体の物件も増えたら住所filter は重くなる
- [ ] (任意) たつの市 ページネーション現状 page=1,2 で 44件取れているが、サイト全体で 180件と公称あり (戸建以外も含む全集計の可能性)
- [ ] (任意) `src/scrapers/akiya_bank.py`: 全国版空き家バンク (LIFULL/アットホーム) — Playwright 必須
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
- 2026-06-06: セッション9。「修繕が必要な物件」も一覧から除外。dilapidated(住めないレベル)とは別に needs_repair(要リフォーム/改修が必要 等の明示シグナル)を新設し、発見系タブで両方を除外。判定できるのは“修繕が必要と明記された物件”のみで、状態未記載の物件は対象外（=一覧に残る）。さらに厳格化したい場合は「即入居OK だけ表示」へ切替できるが件数が激減するため、まずは明示シグナル除外にとどめる方針。
- 2026-06-06: セッション8 を本番反映。コードは main へ ff マージ→Vercel 自動デプロイ。本番データの backfill は「ローカルに .env が無い（完全クラウド運用で鍵は GitHub Secrets 側）」ため、GitHub Actions の scrape を `gh workflow run scrape.yml --ref main` で手動起動して実施（scrape の upsert が既存物件を再判定して move_in_ready を埋める）。今後 backfill が必要な時もこの手順が使える。
- 2026-06-06: 「修繕不要で住める空き家だけ」を『両方』方式で実装。発見系タブは dilapidated を隠し、別途「✨即入居OK」タブで move_in_ready を厳選表示。データの性質上「修繕ゼロ保証」は不可（説明文に状態が書かれていない物件が最多）なため、“明らかに壊れた物件の除外”＋“はっきり住めると書かれた物件の厳選”の2層で対応する方針に決定。判定はキーワードベース（完了形シグナルのみ拾い「要リフォーム」等は弾く）。将来さらに精度を上げたいときは AI スコアリング（現在オフ）を「即入居できるか」基準で再開する選択肢あり。
- 2026-06-06: 収集（DB保存）自体は全件継続し、表示・通知の段階で絞る設計を維持（データを捨てない＝後から方針を変えても再判定できる）。dilapidated 除外は発見系タブのみ、ユーザーが明示的に作った一覧（お気に入り/通知済み/評価済み/却下）には適用しない。
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
- 2026-05-26: ダッシュボードの Basic 認証情報 (admin / パスワードは伏せ字化済み) はパスワードマネージャに保存推奨。※2026-06-01 セッション6で公開リポ化に伴い、平文パスワードを NEXT.md から redact (過去履歴には残るため Vercel 側でパスワード rotate 推奨、詳細は同日 Recent decisions 参照)。
- 2026-05-26: 家いちばスクレイパは公式 JSON API `/api/properties?orderby=price_asc&page=N` を採用。HTML パースより速い・正確・サイト負荷小。1リクエスト10件、500件総数、20ページ MAX_PAGES + SCRAPE_PRICE_CEILING (500万) で早期 break。
- 2026-05-26: 家いちば初回スクレイプで関西圏 24件が price ≤ 300万でヒット → Discord に digest 2分割で送信成功。神戸90万円農地、京都伊根町80万円、兵庫赤穂35万円山林、大阪大東270万円戸建てなど良物件多数。
- 2026-05-26: B (通知強化) 実装。Discord Embed の thumbnail → image (大画像)、description にクイックリンク [🗺️地図] [👀街並み] [⚠️ハザード] を追加、価格を "1,000万円" 形式に整形、AI スコアフィールドも対応。
- 2026-05-26: C (UI 強化) 実装。ソート (新着/安い順/高い順/広い順/AIスコア降順)、住所/タイトル/市区町村部分一致検索、却下ボタン (dismissed テーブル)、★レーティング 1-5 (同じ星もう一度押しでクリア)、評価済み/却下タブ。
- 2026-05-26: D (AI スコアリング) 実装。Claude Haiku 4.5 で preferences.yaml ベースの 0-10 採点、ai_scores テーブル + preferences_hash で再採点判定、score.yml ワークフロー (10/40分)、filter に min_ai_score (preferences.score_threshold 連動) ゲート、Discord/Dashboard にスコアバッジ表示。ANTHROPIC_API_KEY 未設定時は scoring がスキップされ filter も score 要求しない (graceful degradation)。
- 2026-05-26: _split_sql のコメント処理バグ修正 (旧版は `-- foo\nCREATE TABLE...` 全体をスキップ、ai_scores migration が失敗していた)。
- 2026-05-26: ANTHROPIC_API_KEY 登録 → 全210件をスコアリング ($0.31、Haiku 4.5)。スコア分布: 8+ 7件、7 17件、6 30件、それ以下 156件。関西圏 price≤300万 で threshold≥6 ヒットは 8件 (三重松阪 190万 8/10 が最有力)。
- 2026-05-26: ユーザー判断で AI スコアリングを一旦オフ。score.yml の schedule をコメントアウト (manual `gh workflow run score` のみ)、preferences.yaml の score_threshold を 6→0 に (filter ゲート無効)。既存210件のスコアと理由は DB に保持、ダッシュボードで「AIスコア高い順」で見られる。再開はこの2ファイルを戻すだけ。
- 2026-05-26: 「農地・山林は不要、一軒家のみ」要件に対応。normalize.classify_property_type で title+body から house/land/apartment/commercial/unknown を判定、property_types: [house] を filters.yaml に追加して通知対象を一軒家に限定。zero.estate は 物件分類 を hint として直接マップ (土地→land 等)。minna_0en の body 抽出を 物件概要 テーブル連結に変更 (旧版は HTML 全体を get_text して他物件の "リゾートマンション" が混入し apartment 誤判定するバグあり)。reclassify CLI で既存210件を再分類: house 140, land 47, apartment 19, unknown 4。ダッシュボードに property_type 別タブ追加。
- 2026-05-26: 「オンボロ物件 (大幅修繕しないと住めない家) を除外」要件に対応。normalize.is_dilapidated で確実な指標 (住める状態ではあり/解体前提/廃屋/倒壊 等) と文脈依存指標 (雨漏り/腐食/シロアリ被害 — 否定文脈 "対策済/重大な瑕疵は見受けられません" を確認) で判定。filters.yaml に exclude_dilapidated: true。DB に dilapidated (INT) と dilapidation_reason (TEXT) 列追加。house 140件中 9件 (5.7%) がオンボロ判定: 三重大台町 母屋住めない、千葉野田 雨漏りあり、兵庫宝塚 雨漏り腐食、兵庫姫路 大規模リフォーム必要、和歌山白浜 腐食、ほか4件。
- 2026-05-26: 「初心者向け費用最小化」相談に対応。filters.yaml に price_min: 500000 追加 (0円物件は本体無料でも修繕費+取得税で結局500-1500万かかるため、リフォーム済 50-300万帯が実用的にお得)。海沿いNG keywords を「海の絶景/海絶景/オーシャンビュー/海一望」等まで強化 (淡路島自体は OK 残し、海フロント物件のみ除外)。Discord embed に💰補助金検索リンク追加 (Google で「<市区町村> 空き家 補助金」検索する shortcut)。
- 2026-05-26: 自治体scraper 1本目として三重県伊賀市公式 (iga-akiyabank.com) を追加。18件取得、house のみ、賃貸はスキップ、address は 「伊賀市〇〇」→「三重県伊賀市〇〇」 正規化。filter pass 4件: 伊勢路 200万 / 上神戸 250万 / 大内 300万 / 島ヶ原 300万。残り 5自治体 (神河/多可/たつの/養父/名張) はユーザー指定済、次セッションで追加。
- 2026-05-27: ユーザー指定14自治体すべてカバーするため scraper 13本を一気に追加。並列偵察 (Explore agent 4並列) で各サイト構造を解析し、6自治体が akiya-athome.jp プラットフォームで共通の HTML 構造 (.building-info + .room-list table) を持つことを発見 → AkiyaAthomeBaseScraper を作って (subdomain, area_path, prefecture) 違いをサブクラスの class 変数で表現する設計に。これで実装数を 6本→1本に削減。
- 2026-05-27: akiya-athome.jp は中間証明書を送ってこないため certifi 単体では SSL 検証失敗。truststore (Python 3.10+) を依存に追加し base.make_client() で `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` を httpx の verify に渡す形に変更。これで OS の trust store (curl と同じ) を使用、全 scraper が中間証明書欠落サイトに対応可能になった。
- 2026-05-27: わかやまLIFE (wakayamagurashi.jp) はクエリ `?akiya_area=aridagawacho` がサーバー側で効かず全和歌山県物件が出る (12件サンプル中、有田川/古座川 0件)。scraper 側で住所文字列に「古座川町」or「有田川町」を含むものだけ yield する形に。現状は古座川/有田川とも登録 0 件のため通過する物件無し、将来登録時に自動取得される設計。
- 2026-05-27: 養父市は akiya-athome 版 (yabu-c28222) で売戸建 0 件 → 独立サイト yabuakiyabank.jp に切替実装。一覧 (article.flex_box) は title+サムネしか出ないため詳細ページを 1物件ずつ fetch して `<table>` から所在地/築年/構造/宅地面積/延床面積を取得、価格は `<span class="price">200</span><span class="en">万円</span>` から組み立て。39件取得、価格・面積すべて取れることを確認。
- 2026-05-27: たつの市 (akiya-athome) はクエリ `?page=N` でページネーション動作。MAX_PAGES=20 + 重複検出 (seen_ids) + page_new=0 で早期break の汎用ループを akiya_athome.py に組み込んだ。実測 page1=20件 + page2=20件 + page3=4件 = 44件。
- 2026-05-27: scraper 全体実行で raw 660件 (うち new 410件) ローカル sqlite に投入成功。filters.yaml の prefectures allowlist は既に必要府県 (京都/兵庫/奈良/和歌山/滋賀/三重/岡山) を含むため変更不要。Turso への反映は GitHub Actions の次回 scrape 時 (cron 30分間隔)。
- 2026-05-27: GitHub Actions Ubuntu で akiya-athome.jp が CERTIFICATE_VERIFY_FAILED (truststore でも救えない、Cybertrust Japan SureServer CA G4 が Ubuntu の trust store にない)。akiya_athome.py 内に `verify=False` 専用 client + `_polite_get_relaxed()` を設置し、共有 client を無視して自前 client を使う形に変更。自治体公式の空き家サイトで credentials も扱わないため MITM リスク許容。他 scraper への影響なし (truststore のままで動作)。
- 2026-05-27: scrape workflow の timeout を 5→10 分に拡張。13自治体追加で yabu_indep の詳細 fetch (~50s) など増え 5 分上限で打ち切られた。timeout は保険値で通常実行時間 (5-7分) は変わらないため Actions 枠消費は実質増えない。
- 2026-05-27: 本番反映完了。手動 trigger した scrape で全 14自治体 (akiya-athome 6本含む) が動作確認、raw 640件 Turso に投入。続けて notify を手動 trigger し `scanned=614 passed=205 sent=205` で Discord に205件分のダイジェスト送信成功 (6 POST、204 No Content)。以降は cron (scrape 30分毎、notify 毎時00分) で自動更新。
- 2026-05-27 (セッション2): ユーザー要望「補助金充実+住みやすい自治体を追加」に対応。Web 調査で関西圏 14候補 (★1-3) を発掘、★★★ 10件を実装範囲に。うち綾部市/西粟倉村/奈義町/与謝野町は実は akiya-athome.jp プラットフォーム委託と判明 → AkiyaAthomeBaseScraper に subclass 追加のみ (与謝野は subdomain 未発見で見送り)。AkiyaAthomeBaseScraper.list_url は area_path 空なら `/buy/house/list` にフォールバックする形に拡張 (自治体専用サブドメイン用)。
- 2026-05-27 (セッション2): 独自 scraper 5本を追加。koka_iju (甲賀市 24件, WordPress VK Blocks), uda_akiyabank (宇陀市 31件, article.akiyainfo, 7ページネーション), ohdai_awa (大台町 28件, AWA サポートデスク委託 desk.awapj.com, t_code listing_id, 4ページ), nancla (南丹市 57件, WordPress bukken_entry, 8ページ), classo_tambasasayama (丹波篠山市 12件, classo.jp box.relative, ※サイト側 paginationが broken のため 1ページのみ取得)。
- 2026-05-27 (セッション2): 米原市は空き家バンクが公開されておらず (相談ベース運用)、与謝野町は akiya-athome subdomain 探索失敗のため両方見送り。総自治体数 14 → 21、scraper 数 16 → 21。
- 2026-05-28 (セッション3): ユーザー要望「住みやすい + 補助金あり自治体」+「何年か住めばもらえる家」の2軸対応。Web 調査 agent で関西圏 補助金充実 8自治体を候補化、ユーザー選択で 8自治体全部実装方針 (★★★ 朝来/舞鶴/熊野/松阪 + ★★ 宍粟/東吉野/十津川/真庭)。並列偵察の結果、朝来/舞鶴/松阪/宍粟は akiya-athome 系で AkiyaAthomeBaseScraper のサブクラス追加だけで完了。
- 2026-05-28 (セッション3): 東吉野村 (vill.higashiyoshino.nara.jp) は WordPress + 詳細fetch型、十津川村 (vill.totsukawa.lg.jp) は PHP CMS + 詳細fetch型として独自実装。熊野市 (Jimdo, 日本語URL) と真庭市 (cocomaniwa.com, articles 0件で構造未把握) は構造調査に追加時間必要 → 次セッション送り。
- 2026-05-28 (セッション3): 「定住条件付き譲渡」検出機能を実装。normalize.detect_settlement_offer() で「無償譲渡/定住条件付/試住制度/お試し移住/賃貸後譲渡/改修費返済不要/○年定住で…/譲渡可」等のキーワードを検出 (確実シグナル 18個 + 文脈ベース判定)。DB に settlement_offer (INT) と settlement_offer_reason (TEXT) 列を追加。Discord embed の title に 🎯 prefix + 「🎯 もらえる/譲渡条件あり」フィールドで検出語を表示。ダッシュボード側のフィルタタブは未実装 (次セッション)。
- 2026-05-28 (セッション3): GHA scrape の timeout を 10→15 分に拡張。27 source + 詳細fetch型 4本 (yabu_indep ~50s + higashiyoshino ~50s + totsukawa ~30s + ieichiba ~30s) で計 8-10 分かかるため。timeout は上限値で実消費時間 (10分27秒) は実 Actions 枠を圧迫しない。
- 2026-05-28 (セッション3): 本番反映完了。GHA scrape 27 source 全動作 (raw 670件、当セッションの新規分は前回 cancel された run で既に投入済みのため new=0/全 updated 表示)、notify trigger で `scanned=582 passed=34 sent=34` → Discord に 34件のダイジェスト送信成功。総自治体数 21 → 27、scraper 数 21 → 27。
- 2026-05-28 (セッション4): 「空き家率高い 山梨/和歌山/徳島/高知/山口 で内陸・補助金あり・住みやすい自治体」要望に対応。知識ベース + Web偵察で候補 14自治体を提示、ユーザー選択で ★★★ 6自治体実装方針 (北杜/橋本/神山/三好/本山/美祢)。並列偵察結果: 5自治体 (北杜/橋本/三好/本山/美祢) は全て akiya-athome 系 → AkiyaAthomeBaseScraper サブクラス追加で対応、神山町は専用バンク無し (全国版 akiya-athome に登録のみ、独立サブドメイン無し) で見送り。
- 2026-05-28 (セッション4): filter.yaml の prefectures allowlist に 山梨県/高知県/山口県 を追加 (大阪駅2時間圏外だが移住目的で取得対象)。borderline_prefectures には入れず Distance Matrix での距離判定をスキップ。
- 2026-05-28 (セッション4): 実物件取得は三好25 + 美祢49 = +74件。北杜/橋本/本山は現在 0件だがサイト自体は稼働中で、将来物件登録時に自動取得される。総自治体数 27 → 32、scraper 数 27 → 32。
- 2026-05-28 (セッション4): 本番反映完了。GHA scrape 32 source 全動作 (raw 909件、new 75件 = 三好25+美祢49+ieichiba 1件)、notify trigger で `scanned=629 passed=49 sent=49` → Discord に49件のダイジェスト送信成功。これで関西圏+空き家率高い5県の自治体公式空き家バンクをほぼ網羅。
- 2026-05-30 (セッション5): ユーザー要望「9府県の全市区町村空き家バンク取得 (海沿い・シロアリリスク除外)」に対応。①海沿い市町村 blacklist 機能を実装 (filter.FilterConfig に city_blacklist、filter.passes で city 単位除外、tests 2件追加)、filters.yaml に default で和歌山県南紀沿岸 8 + 三重県南伊勢〜熊野沿岸 7 + 京都伊根町 + 大阪岬町 + 山口長門市 を設定。②akiya-athome 全国版検索 API は本日メンテ中 (HTTP 500、トップは復旧)、復旧後に scraper 実装予定。③LIFULL HOME's は CloudFront WAF で 403、商用サイト規約懸念で見送り。Turso 502 一過性エラーは次回 cron で自動回復確認 (放置方針)。
- 2026-05-30 (セッション5): city_blacklist の選定方針 = 「市の大半が海沿いで内陸エリアがほとんどない小自治体」のみ。京丹後/舞鶴/与謝野/古座川/田辺/新宮/萩/下関などはユーザー指定または内陸エリア豊富のため blacklist 対象外、ng_keywords (オーシャンビュー等) と is_dilapidated で個別判定。
- 2026-06-01 (セッション6): システム調査で「既に完全クラウド24時間稼働・Mac不要」を確認。GHA scrape は GitHub サーバーの schedule トリガーで動作 (直近 runner は全て schedule/main)、ローカルに .env / launchd / playwright 依存なし。コード全文走査で Discord webhook / Turso token / パスワードのハードコード無し (全て GitHub Secrets / Vercel env var 経由)、git 履歴にも秘密ファイル未コミット → public 化しても安全と確認。
- 2026-06-01 (セッション6): GitHub Actions 無料枠 (private repo 月2000分) 対策。観測値で scrape 30分間隔は GitHub のスケジュール throttle で実際 ~11回/日だが、それでも月 ~3000-4000分で枠超過リスク (今月6/1リセット直後なので今は動作中だが月後半で停止の恐れ)。ユーザー判断で頻度を1日1回に削減: scrape `0 21 * * *` (06:00 JST)、notify `30 21` + `0 9` (06:30 + 18:00 JST 保険2回)。月 ~360分 = 枠の18%。空き家バンクは良物件でも数日残るため1日1回で取りこぼしほぼ無し。完全無料24時間を確定。手動即時実行は Actions タブの workflow_dispatch。
- 2026-06-01 (セッション6 続き): リポ公開化の前検査。全 git 履歴を走査し、Discord webhook URL / Turso トークンはコミットされていない (変数名と .example プレースホルダのみ) ことを確認 ✅。唯一 NEXT.md にダッシュボードの Basic 認証パスワードが平文で残っていた (現行 + 過去 commit 49601e8/0592e3a) ため、現行 NEXT.md は redact 済。過去履歴には残るため、公開前に Vercel の DASHBOARD_PASSWORD を rotate する方針 (ユーザー選択「先にパスワード変更してから公開」)。深刻度は低 (ダッシュボードは公開情報の物件一覧 + ★評価のみ、金銭/個人情報/アカウント乗っ取り無し) だが本筋対応として rotate。rotate 完了後にリポを public 化予定。集めている空き家情報自体は全て公開情報、scraped データは Turso 側で repo には入らない。
- 2026-06-02 (セッション7): ダッシュボードに都道府県・価格フィルタを追加。app.py の _query_rows に pref/price_min/price_max を追加（価格は NULL を範囲指定時に自動除外）、_prefectures() で実データのある都道府県を件数降順で取得しプルダウン化、_man_to_yen() で万円入力を円換算（空/非数値/負は無視）。index.html に都道府県プルダウン＋下限〜上限（万円）入力＋該当件数表示を追加、タブ/検索リンクが pref/price/sort/q を urlencode で引き継ぐように。tests/test_web.py 新規（フィルタ・集計・変換・TestClient スモーク）で全36緑。本番反映は main マージ待ち。
- 2026-06-02 (セッション7): ローカル .venv が trade→akiyaserch のフォルダ名変更で壊れていた（pyvenv の shebang が旧パス /Users/owner/Desktop/trade/... を指す）。rm -rf .venv → uv sync で再構築。pytest は optional-dependencies の dev extra にあるため `uv run --extra dev pytest` で実行する点に注意。
- 2026-06-02 (セッション7): 都道府県・価格フィルタを本番反映。claude/wip は origin/main を完全に含み2コミット先行だったため `git merge --ff-only` でクリーンに main へ ff、push で Vercel が自動デプロイ → commit status success 確認。本番反映完了。
- 2026-06-02 (セッション7): リポジトリを private → public 化 (`gh repo edit --visibility public`)。前提のダッシュボードパスワード変更は藤本さんが Vercel 側で完了済みのため、過去履歴に残る旧 Basic 認証パスワードは無効化済みで安全。public 化により GitHub Actions 実行枠が無制限になり無料枠超過の懸念も恒久解消。集めている空き家情報は全て公開情報、scraped データは Turso 側で repo には含まれない。
- 2026-06-02 (セッション7 続き): ユーザー要望でダッシュボードに3機能追加。①「🎯もらえる家」タブ（view=settlement、settlement_offer=1 のみ）②市区町村プルダウン（_cities で県内市町村を件数付き取得、県プルダウン選択時のみ表示・県変更時は JS で city を空にリセット）③価格を数値入力→プルダウン化（下限/上限プリセット、内部は既存 _man_to_yen 万円ロジック流用で app.py の価格処理は変更不要）。app.py に city パラメータ・settlement view・_cities 追加、index.html にタブ・各プルダウン。tests/test_web.py に settlement/city/_cities/TestClient スモークを追加し全45緑。conn fixture に db._run_migrations を追加（settlement_offer は SCHEMA でなく MIGRATIONS にあるため）。
- 2026-06-02 (セッション7 続き): リポ公開に伴い、ダッシュボードを検索避け (noindex) に。app.py に `X-Robots-Tag: noindex, nofollow` を全レスポンスへ付ける middleware を追加、index.html の <head> に `<meta name=robots content=noindex,nofollow>`。robots.txt の Disallow は使わない（Google に noindex 指示を読ませるため、クロール自体はブロックしない方針）。test_web.py に noindex ヘッダ/meta テスト追加で全48緑。Basic 認証で元々中身は読まれないが、URL ごと検索結果に出ないよう明示。
- 2026-06-02 (セッション7 続き): 「もらえる家」タブが有料物件を誤検出する問題を修正。detect_settlement_offer の「無償でお譲り」等のキーワードが、建物が有料でも付属の土地が無償というだけで True になっていた（再現: 「販売価格300万円。土地も欲しい方には無償でお譲り」→ 誤って True）。ユーザー選択で曖昧なキーワード判定をやめ、「🆓0円物件」タブ（view=free、price=0 のみ）に変更。タブ名「🎯もらえる家」→「🆓0円物件」。app.py の view 分岐・_counts、index.html タブ、tests を price=0 ベースに。全48緑。settlement_offer 列と detect_settlement_offer 関数は Discord 通知用に残置（Discord の🎯バッジも同じ誤検出をするため、将来 Discord 側も同様の見直しが必要）。
- 2026-06-02 (セッション7 続き): 藤本さんが GitHub Web 上で README.md の中身を空に編集 (main 8e2d016)。公開リポだが個人運用で README 不要との判断。claude/wip を origin/main に同期後、空になった README.md をファイルごと git rm で削除。README はアプリ動作に無関係（案内文のみ）なのでシステムへの影響なし。
