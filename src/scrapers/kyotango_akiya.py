"""京都府京丹後市 空き家情報バンク (https://kyotango-akiya.jp/) スクレイパ.

戦略: /akiya/ の一覧ページに全件 (~130件) が静的HTML で並ぶ。
.akiyalist_box ごとに title/area/form/kind/floor/price/idno を抽出する。
詳細ページ fetch は不要 (一覧で必要な情報が揃っている)。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup, Tag

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

LIST_URL = "https://kyotango-akiya.jp/akiya/"
ID_RE = re.compile(r"/akiya/(\d+)/?")


class KyotangoAkiyaScraper:
    source = "kyotango_akiya"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("kyotango_akiya fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        boxes = soup.select(".akiyalist_box")
        logger.info("kyotango_akiya: %d boxes found", len(boxes))
        for box in boxes:
            listing = _parse_box(box)
            if listing is not None:
                yield listing


def _parse_box(box: Tag) -> RawListing | None:
    title_link = box.select_one(".al_title a")
    if title_link is None:
        return None
    href = str(title_link.get("href", ""))
    m = ID_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)
    title = title_link.get_text(strip=True)

    img = box.select_one(".al_img img")
    thumb = None
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    meta = box.select_one(".al_meta")
    area = form = kind = floor = price_text = idno = ""
    if meta:
        for span in meta.select("span"):
            cls = " ".join(span.get("class", []))
            txt = span.get_text(" ", strip=True)
            if "area" in cls:
                area = txt
            elif "form" in cls:
                form = txt
            elif "kind" in cls:
                kind = txt
            elif "floor" in cls:
                floor = txt
            elif "price" in cls:
                price_text = txt
            elif "idno" in cls:
                idno = txt

    # 賃貸はスキップ
    if "賃貸" in kind and "売買" not in kind:
        return None
    # 土地のみはスキップ
    if "土地" in form and "戸建" not in form and "住宅" not in form:
        return None

    # 住所: 「久美浜」だけだと粗いので市名を補完
    address = f"京都府京丹後市{area}" if area else "京都府京丹後市"

    # タイトル + meta から body 構築
    body_parts = [form, kind, floor, idno]
    body = " | ".join(p for p in body_parts if p)

    # 戸建て or 田舎暮らし → house
    type_hint = "house" if ("戸建" in form or "住宅" in form) else None

    return RawListing(
        source="kyotango_akiya",
        listing_id=listing_id,
        url=str(title_link.get("href")),
        title=title or f"(京丹後 {listing_id})",
        price_text=price_text or None,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint=type_hint,
    )
