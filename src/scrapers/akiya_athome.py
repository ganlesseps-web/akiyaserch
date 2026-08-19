"""akiya-athome.jp プラットフォーム汎用スクレイパ.

複数自治体が同じ akiya-athome.jp の自治体カスタムサブドメインで運営しており、
HTML 構造が共通 (.building-info + .room-list table)。サブクラスで
(source, subdomain, area_path, prefecture) のみ override する。

戦略:
- /buy/house/area/<prefecture>/<city>/list の HTML を 1リクエストで取得
- .building-info ごとに 1物件 (タイトル/住所/サムネ/築年) を抽出
- 続く .room-list table の最初の <tr> から (価格/間取り/面積) を抽出
- listing_id は href の末尾数字、または checkbox value=<id>
- 売戸建のみ対象 (sbt_kbn=house 固定、賃貸/土地/事業はスキップ)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .base import (
    DEFAULT_TIMEOUT,
    INTER_REQUEST_SECONDS,
    RawListing,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

LISTING_ID_RE = re.compile(r"-(\d+)$")


MAX_PAGES = 20  # 1ページ20件想定で最大 ~400件まで対応 (大半の自治体はこれ未満)


def _make_relaxed_client() -> httpx.Client:
    """akiya-athome.jp 専用クライアント.

    akiya-athome.jp は中間証明書 (Cybertrust Japan SureServer CA G4) を
    送ってこないため、Ubuntu 等のシステム CA ストアにこの中間 CA が無い
    環境では SSL 検証が失敗する (curl は AIA で自動取得するが Python ssl
    はしない)。truststore でも GitHub Actions Ubuntu では同様に失敗。

    自治体公式の空き家バンクサイトであり MITM リスクは極小、応答は HTML
    の物件情報のみで credentials も送信しないため、ここでは verify=False
    として接続を成立させる。本変更の影響範囲は akiya-athome.jp 配下のみ。
    """
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        verify=False,
    )


def _polite_get_relaxed(client: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(3):
        resp = client.get(url)
        if resp.status_code == 429:
            wait = 2 ** (attempt + 2)
            logger.warning("429 from %s, backing off %ds", url, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        time.sleep(INTER_REQUEST_SECONDS)
        return resp
    raise RuntimeError(f"giving up on {url} after 429s")


class AkiyaAthomeBaseScraper:
    """サブクラスで以下のクラス変数を override すること."""

    source: str = ""
    subdomain: str = ""   # 例: "kamikawa-t28446"
    area_path: str = ""   # 例: "hyogoken/kanzakigunkamikawacho"
    prefecture: str = ""  # 例: "兵庫県" (住所先頭に補完)

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.akiya-athome.jp"

    @property
    def list_url(self) -> str:
        # area_path 指定があれば area 絞り URL、空なら自治体全体の list を使う
        # (小規模自治体専用サブドメインの場合、area 指定が無くても自治体内のみが出る)
        if self.area_path:
            return f"{self.base_url}/buy/house/area/{self.area_path}/list"
        return f"{self.base_url}/buy/house/list"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        # 共有 client は使わず、akiya-athome 向け verify=False client を都度作る。
        # (httpx の SSL コンテキストは client 作成時に確定するため、共有不可)
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        with _make_relaxed_client() as own_client:
            yield from self._fetch_with(own_client)

    def _fetch_with(self, client: httpx.Client) -> Iterator[RawListing]:
        seen_ids: set[str] = set()
        total = 0
        for page in range(1, MAX_PAGES + 1):
            url = self.list_url if page == 1 else f"{self.list_url}?page={page}"
            try:
                resp = _polite_get_relaxed(client, url)
            except httpx.HTTPError as e:
                logger.warning("%s page=%d fetch failed: %s", self.source, page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            items = soup.select("li:has(> .building-info)")
            if not items:
                items = [info.parent for info in soup.select(".building-info") if info.parent and info.parent.name == "li"]

            if not items:
                if page == 1:
                    logger.info("%s: 0 items at %s (empty bank)", self.source, url)
                break

            page_new = 0
            for li in items:
                listing = self._parse_item(li)
                if listing is None:
                    continue
                if listing.listing_id in seen_ids:
                    continue
                seen_ids.add(listing.listing_id)
                page_new += 1
                yield listing
            total += page_new
            logger.info("%s: page %d -> %d new (total %d)", self.source, page, page_new, total)
            # ページに新規が無ければ終了 (akiya-athome は範囲外 page を最終ページに redirect する)
            if page_new == 0:
                break

    def _parse_item(self, li: Tag) -> RawListing | None:
        info = li.select_one(".building-info")
        if info is None:
            return None

        # listing_id: 詳細リンクの末尾数字
        link = info.select_one('a[href*="/bukken/detail/buy/"]')
        if link is None:
            return None
        href = str(link.get("href", ""))
        m = LISTING_ID_RE.search(href)
        if not m:
            return None
        listing_id = m.group(1)
        detail_url = urljoin(self.base_url, href)

        title = link.get_text(strip=True) or f"({self.source} {listing_id})"

        # 種別 (中古売戸建住宅 / 土地 / 事業用 等)
        sbt_el = info.select_one(".bk-sbt-icon")
        sbt = sbt_el.get_text(strip=True) if sbt_el else ""
        if sbt and "戸建" not in sbt and "住宅" not in sbt and "古民家" not in sbt:
            # 土地・事業用・マンション等はスキップ
            return None

        # 住所
        addr_el = info.select_one('[data-column="address"]')
        address = addr_el.get_text(" ", strip=True) if addr_el else None
        if address and self.prefecture and not address.startswith(self.prefecture):
            address = f"{self.prefecture}{address}" if not address.startswith(("北海道", "東京都", "京都府", "大阪府")) and not address[:3].endswith("県") else address

        # サムネ (data-column="gaikan-image" の img)
        thumb = None
        img_el = info.select_one('[data-column="gaikan-image"] img')
        if img_el:
            src = str(img_el.get("src", ""))
            if src.startswith("//"):
                thumb = "https:" + src
            elif src.startswith("http"):
                thumb = src
            elif src and not src.endswith("noimage.gif"):
                thumb = urljoin(self.base_url, src)

        # 築年・構造・staff コメント
        chiku_el = info.select_one('[data-column="chiku_ymd"]')
        chiku = chiku_el.get_text(" ", strip=True) if chiku_el else ""
        kozo_el = info.select_one('[data-column="tate_kozo_kbn"]')
        kozo = kozo_el.get_text(" ", strip=True) if kozo_el else ""
        msg_el = info.select_one(".staff-message")
        msg = msg_el.get_text(" ", strip=True) if msg_el else ""

        # .room-list table から価格/間取り/面積
        price_text: str | None = None
        layout_text = ""
        area_text: str | None = None

        table = li.select_one(".room-list")
        if table:
            # データ行 (tbody > tr) のうち data-column を持つ最初の tr
            for tr in table.select("tbody tr"):
                price_td = tr.select_one('td[data-column="price"]')
                if price_td:
                    # spans が "280" "" "万円" の3つ。連結する
                    price_text = price_td.get_text("", strip=True)
                    madori_td = tr.select_one('td[data-column="madori"]')
                    if madori_td:
                        layout_text = madori_td.get_text(" ", strip=True)
                    menseki_td = tr.select_one('td[data-column="menseki"]')
                    if menseki_td:
                        area_text = menseki_td.get_text(" ", strip=True)
                    break

        body = " | ".join(filter(None, [layout_text, kozo, chiku, msg]))
        # 売戸建住宅と明示されている / 間取り情報があれば house 確定
        type_hint = "house" if (sbt and ("戸建" in sbt or "住宅" in sbt)) or layout_text else None

        return RawListing(
            source=self.source,
            listing_id=listing_id,
            url=detail_url,
            title=title,
            price_text=price_text,
            address_text=address,
            area_land_text=area_text,
            area_building_text=None,
            thumbnail_url=thumb,
            body=body,
            posted_at=None,
            property_type_hint=type_hint,
        )


# ===== 自治体別サブクラス =====

class KamikawaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県神河町 (kamikawa-t28446.akiya-athome.jp)"""
    source = "kamikawa_akiyabank"
    subdomain = "kamikawa-t28446"
    area_path = "hyogoken/kanzakigunkamikawacho"
    prefecture = "兵庫県"


class TakaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県多可町 (taka-t28365.akiya-athome.jp)"""
    source = "taka_akiyabank"
    subdomain = "taka-t28365"
    area_path = "hyogoken/takaguntakacho"
    prefecture = "兵庫県"


class TatsunoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県たつの市 (tatsuno-c28229.akiya-athome.jp)"""
    source = "tatsuno_akiyabank"
    subdomain = "tatsuno-c28229"
    area_path = "hyogoken/tatsunoshi"
    prefecture = "兵庫県"


class YabuAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県養父市 (yabu-c28222.akiya-athome.jp)"""
    source = "yabu_akiyabank"
    subdomain = "yabu-c28222"
    area_path = "hyogoken/yabushi"
    prefecture = "兵庫県"


class FukuchiyamaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """京都府福知山市 (fukuchiyama-c26201.akiya-athome.jp).
    現在登録 0 件だが将来増える可能性があるので scraper は用意する。"""
    source = "fukuchiyama_akiyabank"
    subdomain = "fukuchiyama-c26201"
    area_path = "kyotofu/fukuchiyamashi"
    prefecture = "京都府"


class MimasakaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県美作市 (mimasaka-c33215.akiya-athome.jp)"""
    source = "mimasaka_akiyabank"
    subdomain = "mimasaka-c33215"
    area_path = "okayamaken/mimasakashi"
    prefecture = "岡山県"


class AyabeAkiyabankScraper(AkiyaAthomeBaseScraper):
    """京都府綾部市 (ayabe-c26203.akiya-athome.jp).
    自治体専用サブドメインなので area_path 不要 (/buy/house/list で全件)."""
    source = "ayabe_akiyabank"
    subdomain = "ayabe-c26203"
    area_path = ""
    prefecture = "京都府"


class AkaiwaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県赤磐市 (akaiwa-c33213.akiya-athome.jp).
    岡山市の北東・ベッドタウン、内陸。自治体専用サブドメインなので area_path 不要."""
    source = "akaiwa_akiyabank"
    subdomain = "akaiwa-c33213"
    area_path = ""
    prefecture = "岡山県"


class NishiawakuraAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県西粟倉村 (nishiawakura-v33643.akiya-athome.jp).
    自治体専用サブドメインなので area_path 不要."""
    source = "nishiawakura_akiyabank"
    subdomain = "nishiawakura-v33643"
    area_path = ""
    prefecture = "岡山県"


class NagiAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県奈義町 (nagi-t33623.akiya-athome.jp).
    自治体公式が akiya-athome に物件管理を委託している。"""
    source = "nagi_akiyabank"
    subdomain = "nagi-t33623"
    area_path = ""
    prefecture = "岡山県"


class AsagoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県朝来市 (asago-c28225.akiya-athome.jp).
    現在は売戸建 0 件だが、改修補助多数で将来追加が期待される。"""
    source = "asago_akiyabank"
    subdomain = "asago-c28225"
    area_path = ""
    prefecture = "兵庫県"


class MaizuruAkiyabankScraper(AkiyaAthomeBaseScraper):
    """京都府舞鶴市 (maizuru-c26202.akiya-athome.jp)."""
    source = "maizuru_akiyabank"
    subdomain = "maizuru-c26202"
    area_path = ""
    prefecture = "京都府"


class MatsusakaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """三重県松阪市 (matsusaka-c24204.akiya-athome.jp)."""
    source = "matsusaka_akiyabank"
    subdomain = "matsusaka-c24204"
    area_path = ""
    prefecture = "三重県"


class ShisoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県宍粟市 (shiso-c28227.akiya-athome.jp).
    林業の町、改修補助上限130万・子育て移住支援強化中。"""
    source = "shiso_akiyabank"
    subdomain = "shiso-c28227"
    area_path = ""
    prefecture = "兵庫県"


class MiyoshiAkiyabankScraper(AkiyaAthomeBaseScraper):
    """徳島県三好市 (miyoshi-c36208.akiya-athome.jp).
    祖谷渓・大歩危、四国の山間、移住補助あり。"""
    source = "miyoshi_akiyabank"
    subdomain = "miyoshi-c36208"
    area_path = ""
    prefecture = "徳島県"


class MotoyamaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """高知県本山町 (motoyama-t39341.akiya-athome.jp).
    嶺北・ゆず、移住補助多数。現在登録 0 件だが将来用。"""
    source = "motoyama_akiyabank"
    subdomain = "motoyama-t39341"
    area_path = ""
    prefecture = "高知県"


class MineAkiyabankScraper(AkiyaAthomeBaseScraper):
    """山口県美祢市 (mine-c35213.akiya-athome.jp).
    秋吉台、内陸、補助金あり。"""
    source = "mine_akiyabank"
    subdomain = "mine-c35213"
    area_path = ""
    prefecture = "山口県"


class HokutoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """山梨県北杜市 (hokuto-c19209.akiya-athome.jp).
    八ヶ岳移住メッカ、改修補助手厚い。"""
    source = "hokuto_akiyabank"
    subdomain = "hokuto-c19209"
    area_path = ""
    prefecture = "山梨県"


class HashimotoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """和歌山県橋本市 (hashimoto-c30203.akiya-athome.jp).
    大阪通勤圏、高野山麓、内陸。"""
    source = "hashimoto_akiyabank"
    subdomain = "hashimoto-c30203"
    area_path = ""
    prefecture = "和歌山県"


# --- セッション13追加: 対象府県の内陸自治体をまとめて拡充 (安い古民家の在庫を増やす) ---

class NiimiAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県新見市 (niimi-c33210.akiya-athome.jp). 中国山地・内陸。"""
    source = "niimi_akiyabank"
    subdomain = "niimi-c33210"
    area_path = ""
    prefecture = "岡山県"


class KyotambaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """京都府京丹波町 (kyotamba-t26407.akiya-athome.jp). 内陸・高速道路沿い。"""
    source = "kyotamba_akiyabank"
    subdomain = "kyotamba-t26407"
    area_path = ""
    prefecture = "京都府"


class WakeAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県和気町 (wake-c33346.akiya-athome.jp). 岡山市の北東・内陸。"""
    source = "wake_akiyabank"
    subdomain = "wake-t33346"
    area_path = ""
    prefecture = "岡山県"


class KibichuoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県吉備中央町 (kibichuo-t33681.akiya-athome.jp). 吉備高原・内陸。"""
    source = "kibichuo_akiyabank"
    subdomain = "kibichuo-t33681"
    area_path = ""
    prefecture = "岡山県"


class KamigoriAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県上郡町 (kamigori-t28481.akiya-athome.jp). 西播磨・内陸。"""
    source = "kamigori_akiyabank"
    subdomain = "kamigori-t28481"
    area_path = ""
    prefecture = "兵庫県"


class KagaminoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県鏡野町 (kagamino-t33606.akiya-athome.jp). 岡山北部・内陸。"""
    source = "kagamino_akiyabank"
    subdomain = "kagamino-t33606"
    area_path = ""
    prefecture = "岡山県"


class IchikawaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県市川町 (ichikawa-t28442.akiya-athome.jp). 中播磨・内陸。"""
    source = "ichikawa_akiyabank"
    subdomain = "ichikawa-t28442"
    area_path = ""
    prefecture = "兵庫県"


class SayoAkiyabankScraper(AkiyaAthomeBaseScraper):
    """兵庫県佐用町 (sayo-t28501.akiya-athome.jp). 西播磨・内陸。現在少数だが将来用。"""
    source = "sayo_akiyabank"
    subdomain = "sayo-t28501"
    area_path = ""
    prefecture = "兵庫県"


class IbaraAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県井原市 (ibara-c33207.akiya-athome.jp). 岡山西部・内陸。現在少数だが将来用。"""
    source = "ibara_akiyabank"
    subdomain = "ibara-c33207"
    area_path = ""
    prefecture = "岡山県"


class NirasakiAkiyabankScraper(AkiyaAthomeBaseScraper):
    """山梨県韮崎市 (nirasaki-c19207.akiya-athome.jp). 甲府盆地北西・内陸。"""
    source = "nirasaki_akiyabank"
    subdomain = "nirasaki-c19207"
    area_path = ""
    prefecture = "山梨県"


class KirishimaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """鹿児島県霧島市 (kirishima-c46218.akiya-athome.jp).

    2026-08 6県調査で採用。京セラ国分工場(5,169人)・ソニー半導体・陸自国分駐屯地と
    賃貸需要の核が硬い。ただし対象は平地の国分・隼人のみで、標高500-600mの山間部
    (霧島田口/牧園町 等) は config/filters.yaml の district_blacklist で収集時に除外。
    予算内(50-300万)の玉は現状1-2件と少ないが、追加コストほぼゼロの「網張り」枠。
    ※民泊出口は不可と判断済み (新燃岳が15年で4回噴火、宿泊需要の変動が大きすぎる)。"""
    source = "kirishima_akiyabank"
    subdomain = "kirishima-c46218"
    area_path = ""
    prefecture = "鹿児島県"


# --- セッション22追加: 岡山の抜け3 + 広島2 (2026-08 実測で予算内約60件の上積み) ---

class TsuyamaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県津山市 (tsuyama-c33203.akiya-athome.jp). 県北最大の都市(約9.4万人)・内陸盆地。
    実測: 掲載68件・予算内11件・最安50万。これまで見落としていた大物。"""
    source = "tsuyama_akiyabank"
    subdomain = "tsuyama-c33203"
    area_path = ""
    prefecture = "岡山県"


class MisakiAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県美咲町 (misaki-t33666.akiya-athome.jp). 内陸・津山圏。
    実測: 掲載33件中 予算内18件・最安30万と、規模の割に予算帯が厚い。
    ※過去に misaki-t33663 (誤JIS=久米南町の番号) を試して0件と誤判定していた。"""
    source = "misaki_akiyabank"
    subdomain = "misaki-t33666"
    area_path = ""
    prefecture = "岡山県"


class ShooAkiyabankScraper(AkiyaAthomeBaseScraper):
    """岡山県勝央町 (shoo-t33622.akiya-athome.jp). 津山圏の工業団地の町・内陸。"""
    source = "shoo_akiyabank"
    subdomain = "shoo-t33622"
    area_path = ""
    prefecture = "岡山県"


class MiyoshiHiroshimaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """広島県三次市 (miyoshi-c34209.akiya-athome.jp). 県北の盆地・内陸。
    実測: 掲載61件・予算内29件と今回最厚。雪は松本と同程度とみられる(未検証)点は
    ユーザー了承済み。※source 名は徳島県三好市(miyoshi_akiyabank)と衝突するため別名。"""
    source = "miyoshi_hiroshima_akiyabank"
    subdomain = "miyoshi-c34209"
    area_path = ""
    prefecture = "広島県"


class HigashihiroshimaAkiyabankScraper(AkiyaAthomeBaseScraper):
    """広島県東広島市 (higashihiroshima-c34212.akiya-athome.jp). 内陸盆地。
    広島大学 + マイクロン半導体工場 = 賃貸需要の核が非常に強い。予算内は2件と
    薄いが網張り枠。"""
    source = "higashihiroshima_akiyabank"
    subdomain = "higashihiroshima-c34212"
    area_path = ""
    prefecture = "広島県"
