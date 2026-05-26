"""奈良県下市町 空き家バンク (https://shimoichi-akiyabank.com/) スクレイパ.

戦略: /bank/ の一覧。各物件は div.akiya_unit 内の <dl> で dt-dd 属性。
ページネーション: /bank/page/N/ (最大 8ページ程度)。
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

BASE_URL = "https://shimoichi-akiyabank.com"
LIST_URL_TMPL = "https://shimoichi-akiyabank.com/bank/{page}"
MAX_PAGES = 12
SI_ID_RE = re.compile(r"/bank/([a-z]+\d+)/?", re.I)


class ShimoichiAkiyabankScraper:
    source = "shimoichi_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL_TMPL.format(page="") if page == 1 else LIST_URL_TMPL.format(page=f"page/{page}/")
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("shimoichi_akiyabank page=%d failed: %s", page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            units = soup.select("div.akiya_unit")
            if not units:
                break

            page_new = 0
            for unit in units:
                listing = _parse_unit(unit)
                if listing is None or listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                page_new += 1
                yield listing
            logger.info("shimoichi_akiyabank: page %d -> %d new (total %d)", page, page_new, len(seen))
            if page_new == 0:
                break


def _parse_unit(unit: Tag) -> RawListing | None:
    title_el = unit.find("h4")
    title = title_el.get_text(" ", strip=True) if title_el else ""

    attrs: dict[str, str] = {}
    detail_href = ""

    dl = unit.find("dl")
    if dl is None:
        return None
    children = list(dl.find_all(["dt", "dd"]))
    for i in range(0, len(children) - 1, 2):
        dt = children[i]
        dd = children[i + 1]
        if dt.name == "dt" and dd.name == "dd":
            attrs[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)

    # detail href: 詳細ボタンや画像リンクから
    for link in unit.select("a[href]"):
        href = str(link.get("href", ""))
        if "/bank/" in href and SI_ID_RE.search(href):
            detail_href = href
            break

    if not detail_href:
        return None
    m = SI_ID_RE.search(detail_href)
    if not m:
        return None
    listing_id = m.group(1).upper()

    # 売却/賃貸: dt のキーがそのまま属性名となる ("売却" or "賃貸")
    is_rent = False
    for key in attrs.keys():
        if "賃貸" in key and "売却" not in key and "売買" not in key:
            is_rent = True
    if is_rent:
        return None

    # 価格は売却 or 賃貸の dt の次の dd に入っている。すでに attrs に入っている
    price_text = attrs.get("売却") or attrs.get("売買") or attrs.get("賃貸") or None

    address_raw = attrs.get("物件の所在地") or attrs.get("所在地", "")
    if address_raw and not address_raw.startswith(("奈良県", "下市町")):
        address = f"奈良県吉野郡下市町{address_raw}"
    elif address_raw.startswith("下市町"):
        address = f"奈良県吉野郡{address_raw}"
    else:
        address = address_raw or "奈良県吉野郡下市町"

    thumb = None
    img = unit.select_one("div.infoImg img")
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    body_parts = [attrs.get("登録番号", ""), attrs.get("交渉状況", "")]
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="shimoichi_akiyabank",
        listing_id=listing_id,
        url=urljoin(BASE_URL, detail_href),
        title=title or f"(下市 {listing_id})",
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
