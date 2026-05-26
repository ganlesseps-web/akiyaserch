"""滋賀県高島市 移住情報サイト (https://move-takashima.jp/) スクレイパ.

戦略: /?post_type=house の一覧 (WordPress + カスタムテーマ)。
li.c-entries__item 内に h2 タイトル + サムネ + カテゴリ。
タイトル形式: 「３３３：朽木柏　売買価格：600万円」 → 物件番号 / 地区 / 価格を分離。
詳細ページ /house/{id} は fetch しない (タイトルで必要情報が取れる)。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup, Tag

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

LIST_URL = "https://move-takashima.jp/?post_type=house"
ID_RE = re.compile(r"/house/(\d+)")
# 「３３３：朽木柏 売買価格：600万円」
TITLE_RE = re.compile(r"^([０-９\d]+)[：:]\s*([^\s]+)\s*売買価格[：:]\s*(.+)$")
RENT_RE = re.compile(r"(賃貸|家賃)")


class TakashimaAkiyaScraper:
    source = "takashima_akiya"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("takashima_akiya fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        items = soup.select("li.c-entries__item")
        logger.info("takashima_akiya: %d items found", len(items))
        for li in items:
            listing = _parse_item(li)
            if listing is not None:
                yield listing


def _parse_item(li: Tag) -> RawListing | None:
    link = li.select_one("a[href*='/house/']")
    if link is None:
        return None
    href = str(link.get("href", ""))
    m = ID_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)

    title_el = li.select_one(".c-entry-summary__title")
    title = title_el.get_text(" ", strip=True) if title_el else ""

    # カテゴリ (田舎暮らし / 売買・賃貸物件 等)
    cats = [t.get_text(strip=True) for t in li.select(".c-entry-summary__term")]
    cat_text = " ".join(cats)

    # 賃貸は除外
    if RENT_RE.search(cat_text) or RENT_RE.search(title):
        return None

    # サムネ
    img = li.select_one("img.wp-post-image, img")
    thumb = None
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    # タイトル分解
    price_text: str | None = None
    area_part = ""
    no_part = ""
    tm = TITLE_RE.match(title)
    if tm:
        no_part = tm.group(1)
        area_part = tm.group(2)
        price_text = tm.group(3).replace(" ", "")
    else:
        # ヒットしない時はタイトルから万円を緩く抽出
        pm = re.search(r"([\d,]+)\s*万円", title)
        if pm:
            price_text = pm.group(0).replace(" ", "")

    address = f"滋賀県高島市{area_part}" if area_part else "滋賀県高島市"
    body = " | ".join([p for p in [cat_text, no_part] if p])
    type_hint = "house"  # 高島市 move-takashima は基本田舎暮らし戸建て

    return RawListing(
        source="takashima_akiya",
        listing_id=listing_id,
        url=href,
        title=title or f"(高島 {listing_id})",
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint=type_hint,
    )
