"""山梨県南アルプス市 空き家バンク (市公式サイト) スクレイパ.

南アルプス市はアットホーム空き家バンクに専用サブドメインが無く、市公式サイト
(www.city.minami-alps.yamanashi.jp) の空き家バンクで運営している。カード型の
一覧 (li.p-bank__negotiable__list__item) から
(物件番号 / 所在地 / 物件内容 / 価格 / 画像 / 詳細URL) をログイン無しで取得できる。

「土地だけは不要」の要望に沿い、建物を含むカテゴリ (土地・建物, 建物) のみ収集し、
更地(土地のみ)は対象外とする。
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

_ID_RE = re.compile(r"/iju/akiyabank/(\d+)\.html")
_NO_RE = re.compile(r"物件番号[:：]\s*(\d+)")
_ADDR_RE = re.compile(r"所在地[:：]\s*(南アルプス市[^\s|]+)")
_KIND_RE = re.compile(r"物件内容[:：]\s*([^\s|]+)")
_PRICE_RE = re.compile(r"価格[:：]\s*([0-9,]+\s*万?円|[0-9,]+円|要相談|[^\s|]+)")


class MinamiAlpsAkiyabankScraper:
    source = "minamialps_akiyabank"
    base_url = "https://www.city.minami-alps.yamanashi.jp"
    prefecture = "山梨県"
    # 建物を含むカテゴリのみ (土地のみ /lb/land/ は除外)
    category_paths = ("/iju/akiyabank/lb/land-building/", "/iju/akiyabank/lb/building/")

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for path in self.category_paths:
            url = self.base_url + path
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("%s: %s failed: %s", self.source, path, e)
                continue
            soup = BeautifulSoup(resp.content, "lxml")
            items = soup.select("li.p-bank__negotiable__list__item")
            for li in items:
                listing = self._parse_item(li)
                if listing is None or listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                yield listing
            logger.info("%s: %s -> %d (total %d)", self.source, path, len(items), len(seen))

    def _parse_item(self, li: Tag) -> RawListing | None:
        text = li.get_text(" ", strip=True)

        link = li.find("a", href=_ID_RE)
        href = link.get("href", "") if link else ""
        m_id = _ID_RE.search(str(href))

        m_no = _NO_RE.search(text)
        listing_id = (m_no.group(1) if m_no else None) or (m_id.group(1) if m_id else None)
        if not listing_id:
            return None
        detail_url = urljoin(self.base_url, str(href)) if href else f"{self.base_url}/iju/akiyabank/"

        # 物件内容: 建物を含むものだけ (更地は除外)
        m_kind = _KIND_RE.search(text)
        kind = m_kind.group(1) if m_kind else ""
        if "建物" not in kind:
            return None

        m_addr = _ADDR_RE.search(text)
        chimei = m_addr.group(1) if m_addr else "南アルプス市"
        address = f"{self.prefecture}{chimei}"

        m_price = _PRICE_RE.search(text)
        price_text = m_price.group(1) if m_price else None

        # エリア/ステータスタグ (街なかエリア/里山エリア, 追加/変更/交渉中)
        tags = [t.get_text(strip=True) for t in li.select(".p-bank__negotiable__tag__text")]

        thumb = None
        img = li.find("img")
        if img and img.get("src"):
            thumb = urljoin(self.base_url, str(img.get("src")))

        title = f"{chimei}の空き家（物件番号{listing_id}）"
        body = " | ".join(filter(None, [" ".join(tags), f"物件内容:{kind}" if kind else ""]))

        return RawListing(
            source=self.source,
            listing_id=listing_id,
            url=detail_url,
            title=title,
            price_text=price_text,
            address_text=address,
            area_land_text=None,
            area_building_text=None,
            thumbnail_url=thumb,
            body=body or None,
            posted_at=None,
            property_type_hint="house",
        )
