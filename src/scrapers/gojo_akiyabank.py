"""奈良県五條市 空き家情報バンク (https://gojocity-akiyabank.com/) スクレイパ.

戦略: /bank/ の一覧。各物件は div.akiyainfo 内の <table> で属性。
ページネーション: /bank/page/N/ 形式。
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

BASE_URL = "https://gojocity-akiyabank.com"
LIST_URL_TMPL = "https://gojocity-akiyabank.com/bank/{page}"
MAX_PAGES = 10
GJ_ID_RE = re.compile(r"/bank/([a-z]+\d+)/?$", re.I)


class GojoAkiyabankScraper:
    source = "gojo_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL_TMPL.format(page="") if page == 1 else LIST_URL_TMPL.format(page=f"page/{page}/")
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("gojo_akiyabank page=%d failed: %s", page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            boxes = soup.select("div.akiyainfo")
            if not boxes:
                break

            page_new = 0
            for box in boxes:
                listing = _parse_box(box)
                if listing is None or listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                page_new += 1
                yield listing
            logger.info("gojo_akiyabank: page %d -> %d new (total %d)", page, page_new, len(seen))
            if page_new == 0:
                break


def _parse_box(box: Tag) -> RawListing | None:
    title_el = box.find("h4")
    title = title_el.get_text(" ", strip=True) if title_el else ""

    detail_link = box.select_one("p.detailbtn a")
    if detail_link is None:
        return None
    href = str(detail_link.get("href", ""))
    m = GJ_ID_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1).upper()

    attrs: dict[str, str] = {}
    for row in box.select("table tr"):
        th = row.find("th")
        td = row.find("td")
        if th and td:
            attrs[th.get_text(strip=True)] = td.get_text(" ", strip=True)

    # 取引: 価格 td 内の <p>売買 480万円</p>
    price_raw = attrs.get("価格", "")
    if "賃貸" in price_raw and "売買" not in price_raw and "売却" not in price_raw:
        return None
    # "売買 480万円" → "480万円" だけ抜き出す
    pm = re.search(r"([\d,]+\s*[億万]?\s*円)", price_raw)
    price_text = pm.group(1).replace(" ", "") if pm else (price_raw or None)

    address_raw = attrs.get("所在地", "")
    if address_raw and not address_raw.startswith(("奈良県", "五條市")):
        address = f"奈良県五條市{address_raw}"
    elif address_raw.startswith("五條市"):
        address = f"奈良県{address_raw}"
    else:
        address = address_raw or "奈良県五條市"

    # サムネ
    thumb = None
    img = box.select_one("div.infoimg img")
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    body_parts = [attrs.get("エリア", ""), attrs.get("交渉状況", ""), attrs.get("登録番号", "")]
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="gojo_akiyabank",
        listing_id=listing_id,
        url=urljoin(BASE_URL, href),
        title=title or f"(五條 {listing_id})",
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
