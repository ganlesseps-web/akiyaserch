"""長野県 楽園信州空き家バンク (rakuen-akiya.jp) スクレイパ.

長野県内の多数の自治体が参加する県横断の空き家バンク。市町村別は
housesearch/area/?vender_jiscode[]=<JISコード> で絞れる。物件ブロックは
div.boxStyleE で、種別は class で分かる:
  chuko=中古住宅(売買) / kashiya=貸家(賃貸) / tenpo=店舗事務所 / tochi=土地
「土地だけは不要」「購入向け」に沿い、chuko(中古住宅・売買)のみ収集する。
自治体を増やすときは jiscode を指定したサブクラスを足すだけ。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE_URL = "https://rakuen-akiya.jp"
AREA_URL = "https://rakuen-akiya.jp/housesearch/area/?vender_jiscode%5B%5D={jiscode}"

_BUKKEN_RE = re.compile(r"/bukken/(\d+)/")
_PRICE_RE = re.compile(r"価格\s*([\d,]+)\s*万円")
_LAND_RE = re.compile(r"土地面積\s*([\d,\.]+)\s*(?:m|㎡)")
_BLD_RE = re.compile(r"建物面積\s*([\d,\.]+)\s*(?:m|㎡)")
_CHIKU_RE = re.compile(r"築年月\s*([^\s　]+)")
_MADORI_RE = re.compile(r"間取\s*([^\s　]+)")


class RakuenShinshuBaseScraper:
    """サブクラスで source / jiscode を override する。"""

    source: str = ""
    jiscode: str = ""
    prefecture: str = "長野県"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        url = AREA_URL.format(jiscode=self.jiscode)
        try:
            resp = polite_get(client, url)
        except httpx.HTTPError as e:
            logger.warning("%s: fetch failed: %s", self.source, e)
            return
        soup = BeautifulSoup(resp.content, "lxml")
        seen: set[str] = set()
        for block in soup.select("div.boxStyleE.chuko"):  # 中古住宅(売買)のみ
            listing = self._parse(block)
            if listing is not None and listing.listing_id not in seen:
                seen.add(listing.listing_id)
                yield listing
        logger.info("%s: %d listings (中古住宅売買)", self.source, len(seen))

    def _parse(self, block: Tag) -> RawListing | None:
        # 1ブロックに /bukken/ リンクが複数ある (画像リンク=テキスト無し, 住所リンク 等)。
        bukken_links = block.find_all("a", href=_BUKKEN_RE)
        if not bukken_links:
            return None
        m = _BUKKEN_RE.search(str(bukken_links[0].get("href", "")))
        if not m:
            return None
        listing_id = m.group(1)
        detail_url = urljoin(BASE_URL, str(bukken_links[0].get("href")))

        text = re.sub(r"\s+", " ", block.get_text(" ", strip=True))

        # 住所: bukken リンクのうちテキストが住所になっているもの (例 "松本市波田")。
        addr = ""
        for a in bukken_links:
            t = a.get_text(strip=True)
            if any(x in t for x in ("市", "町", "村")):
                addr = t
                break
        address = f"{self.prefecture}{addr}" if addr else None

        mp = _PRICE_RE.search(text)
        price_text = f"{mp.group(1)}万円" if mp else None
        ml = _LAND_RE.search(text)
        land = f"{ml.group(1)}㎡" if ml else None
        mb = _BLD_RE.search(text)
        bld = f"{mb.group(1)}㎡" if mb else None

        img = block.find("img")
        thumb = None
        if img and img.get("src"):
            src = str(img.get("src"))
            thumb = src if src.startswith("http") else urljoin(BASE_URL, src)

        mc = _CHIKU_RE.search(text)
        mm = _MADORI_RE.search(text)
        body = " | ".join(filter(None, [
            "中古住宅",
            f"築:{mc.group(1)}" if mc else "",
            f"間取:{mm.group(1)}" if mm else "",
        ]))

        return RawListing(
            source=self.source,
            listing_id=listing_id,
            url=detail_url,
            title=addr or f"長野の空き家 {listing_id}",
            price_text=price_text,
            address_text=address,
            area_land_text=land,
            area_building_text=bld,
            thumbnail_url=thumb,
            body=body or None,
            posted_at=None,
            property_type_hint="house",
        )


class MatsumotoRakuenScraper(RakuenShinshuBaseScraper):
    """長野県松本市 (JIS 20202)。"""
    source = "matsumoto_rakuen"
    jiscode = "20202"


class ShiojiriRakuenScraper(RakuenShinshuBaseScraper):
    """長野県塩尻市 (JIS 20215)。"""
    source = "shiojiri_rakuen"
    jiscode = "20215"


class InaRakuenScraper(RakuenShinshuBaseScraper):
    """長野県伊那市 (JIS 20209)。"""
    source = "ina_rakuen"
    jiscode = "20209"
