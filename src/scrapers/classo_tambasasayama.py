"""兵庫県丹波篠山市 空き家バンク (CLasso, https://classo.jp/) スクレイパ.

戦略: /housesearch/ の一覧。
.box.relative ごとに価格/種別/地区/物件番号 が並ぶ (シンプル構造)。
詳細ページは /house/{name}/ で別途取得が必要だが、一覧で十分な情報が取れる。
ページネーション: ?paged=N (最大13ページ)。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup, Tag

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

LIST_URL_TMPL = "https://classo.jp/housesearch/?paged={page}"
MAX_PAGES = 20
HOUSE_PATH_RE = re.compile(r"/house/([^/]+)/?")


class ClassoTambasasayamaScraper:
    source = "classo_tambasasayama"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL_TMPL.format(page=page)
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("classo_tambasasayama page=%d failed: %s", page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            boxes = soup.select("#house-search-list .box.relative") or soup.select(".box.relative")
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
            logger.info("classo_tambasasayama: page %d -> %d new (total %d)", page, page_new, len(seen))
            if page_new == 0:
                break


def _parse_box(box: Tag) -> RawListing | None:
    link = box.select_one("a[href*='/house/']")
    if link is None:
        return None
    href = str(link.get("href", ""))
    m = HOUSE_PATH_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)

    # 種別 (売買/賃貸)
    type_el = box.select_one(".price_type")
    type_text = type_el.get_text(" ", strip=True) if type_el else ""
    type_classes = " ".join(type_el.get("class", [])) if type_el else ""
    # rent クラスがあれば賃貸 → スキップ
    if "rent" in type_classes or ("賃貸" in type_text and "売買" not in type_text):
        return None

    # 地区
    area_el = box.select_one(".area")
    area = area_el.get_text(" ", strip=True) if area_el else ""

    # 物件番号 / 名
    name_el = box.select_one(".name")
    name = name_el.get_text(" ", strip=True) if name_el else listing_id

    # 価格 (数字 span + "万円")
    price_text: str | None = None
    price_el = box.select_one(".price")
    if price_el:
        num_el = price_el.select_one(".num")
        if num_el:
            num = num_el.get_text(strip=True).replace(",", "")
            # ".price" は "<span class='num'>560</span>万円" 構造
            full = price_el.get_text("", strip=True)
            price_text = full if "円" in full else f"{num}万円"

    # サムネ
    img = box.select_one(".image img")
    thumb = None
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    address = f"兵庫県丹波篠山市{area}" if area else "兵庫県丹波篠山市"
    title = f"丹波篠山 {name} ({area})" if area else f"丹波篠山 {name}"
    body = f"{type_text} | {area} | {name}".strip(" |")

    return RawListing(
        source="classo_tambasasayama",
        listing_id=listing_id,
        url=href,
        title=title,
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
