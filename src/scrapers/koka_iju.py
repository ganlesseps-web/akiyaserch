"""滋賀県甲賀市 移住情報サイト (https://koka-iju.jp/) スクレイパ.

戦略: /bsearch の一覧 (WordPress + VK Blocks)。
.vk_post.vk_post-postType-bukken に物件 24件、ページネーション無し。
table 内に物件種別/価格/売買賃貸 が並ぶ。
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

BASE_URL = "https://koka-iju.jp"
LIST_URL = "https://koka-iju.jp/bsearch"
ID_RE = re.compile(r"/archives/bukken/(\d+)")


class KokaIjuScraper:
    source = "koka_iju"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("koka_iju fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        cards = soup.select(".vk_post.vk_post-postType-bukken")
        logger.info("koka_iju: %d cards found", len(cards))
        for card in cards:
            listing = _parse_card(card)
            if listing is not None:
                yield listing


def _parse_card(card: Tag) -> RawListing | None:
    link = card.select_one("a[href*='/archives/bukken/']")
    if link is None:
        return None
    href = str(link.get("href", ""))
    m = ID_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)

    title_el = card.select_one(".vk_post_title")
    title = ""
    if title_el:
        # New!! ラベルを除去
        for new in title_el.select(".vk_post_title_new"):
            new.decompose()
        title = title_el.get_text(" ", strip=True)

    # サムネ (背景画像 url() or img src)
    thumb = None
    img = card.select_one(".vk_post_imgOuter_img")
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    # table 内属性
    attrs: dict[str, str] = {}
    for tr in card.select("table tr"):
        # th-td ペア or td colspan の 1セル のみ
        th = tr.find("th")
        td = tr.find("td")
        if th and td:
            attrs[th.get_text(strip=True).rstrip("：:")] = td.get_text(" ", strip=True)
        elif td:
            # bukken_trade / address_town / bukken_no / new_mark など class で識別
            cls = " ".join(td.get("class", []))
            text = td.get_text(" ", strip=True)
            if "bukken_trade" in cls:
                attrs["__trade"] = text
            elif "address_town" in cls:
                attrs["__town"] = text
            elif "bukken_no" in cls:
                attrs["__bukken_no"] = text

    # 賃貸はスキップ
    trade = attrs.get("__trade", "")
    if "賃貸" in trade and "売買" not in trade:
        return None

    # 種別: 農地付き戸建住宅 / 戸建住宅 / 土地 等
    shubetsu = attrs.get("物件種別", "")
    if shubetsu and ("戸建" not in shubetsu and "住宅" not in shubetsu):
        # 土地のみ・宅地のみは除外
        return None

    # 住所: bukken_no の方が詳細 (「甲賀町大久保 第129号物件」)、address_town は粗い (「甲賀」)
    town_detail = attrs.get("__bukken_no", "")
    town_area = attrs.get("__town", "")
    # 「第〇号物件」の suffix を除去
    if town_detail:
        addr_core = re.sub(r"\s*第[０-９0-9一二三四五六七八九十百千]+号物件\s*$", "", town_detail).strip()
        address = f"滋賀県甲賀市{addr_core}" if addr_core else f"滋賀県甲賀市{town_area}"
    else:
        address = f"滋賀県甲賀市{town_area}" if town_area else "滋賀県甲賀市"

    price_text = attrs.get("価格") or None

    body_parts = [shubetsu, attrs.get("間取り", ""), attrs.get("築年月", "")]
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="koka_iju",
        listing_id=listing_id,
        url=urljoin(BASE_URL, href),
        title=title or f"(甲賀 {listing_id})",
        price_text=price_text,
        address_text=address,
        area_land_text=attrs.get("敷地面積"),
        area_building_text=attrs.get("建物面積") or attrs.get("延べ床面積"),
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
