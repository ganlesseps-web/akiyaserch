"""奈良県宇陀市 空き家バンク (https://udacity-akiyabank.com/) スクレイパ.

戦略: /bank/ の一覧。各物件は article.akiyainfo 内の <table> で属性 (エリア/登録番号/賃貸/売買/所在地)。
ページネーション: /bank/page/N/ (最大7ページ程度)。
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

BASE_URL = "https://udacity-akiyabank.com"
LIST_URL_TMPL = "https://udacity-akiyabank.com/bank/{page}"
MAX_PAGES = 10
DETAIL_RE = re.compile(r"/bank/([^/]+)/?$")


class UdaAkiyabankScraper:
    source = "uda_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL_TMPL.format(page="") if page == 1 else LIST_URL_TMPL.format(page=f"page/{page}/")
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("uda_akiyabank page=%d failed: %s", page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            arts = soup.select("article.akiyainfo")
            if not arts:
                break

            page_new = 0
            for art in arts:
                listing = _parse_article(art)
                if listing is None or listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                page_new += 1
                yield listing
            logger.info("uda_akiyabank: page %d -> %d new (total %d)", page, page_new, len(seen))
            if page_new == 0:
                break


def _parse_article(art: Tag) -> RawListing | None:
    detail_btn = art.select_one("a.btn[href*='/bank/']") or art.select_one("a[href*='/bank/']")
    href = ""
    if detail_btn:
        href = str(detail_btn.get("href", "")).rstrip("/")
    m = DETAIL_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)
    # ページネーション (page/N) を物件IDと誤判定しないようガード
    if listing_id == "page" or listing_id.isdigit() and len(listing_id) <= 2 and href.endswith(f"/page/{listing_id}"):
        return None

    title_el = art.select_one(".catch")
    title = title_el.get_text(" ", strip=True) if title_el else ""

    img = art.select_one("p.img1 img") or art.select_one("img")
    thumb = None
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    attrs: dict[str, str] = {}
    for tr in art.select("table tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td:
            attrs[th.get_text(strip=True)] = td.get_text(" ", strip=True)

    # 賃貸 only はスキップ (賃貸価格があり売買が空なら賃貸専用)
    rent = attrs.get("賃貸", "")
    sale = attrs.get("売買", "")
    if rent and not sale:
        return None

    price_text = sale or rent or None

    addr_raw = attrs.get("所在地", "")
    if addr_raw and not addr_raw.startswith(("奈良県", "宇陀市")):
        address = f"奈良県宇陀市{addr_raw}"
    elif addr_raw.startswith("宇陀市"):
        address = f"奈良県{addr_raw}"
    else:
        address = addr_raw or "奈良県宇陀市"

    body_parts = [attrs.get("エリア", ""), attrs.get("登録番号", "")]
    status_el = art.select_one(".status")
    if status_el:
        body_parts.append(status_el.get_text(" ", strip=True))
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="uda_akiyabank",
        listing_id=listing_id,
        url=urljoin(BASE_URL, href),
        title=title or f"(宇陀 {listing_id})",
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
