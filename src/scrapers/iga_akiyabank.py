"""三重県伊賀市 空き家バンク (https://iga-akiyabank.com/) スクレイパ.

戦略:
- /bukken/ の一覧 HTML を 1リクエストで取得 (~30件以下、ページネーション無し)
- 各カードから listing_id (?no=XXX) / 価格 / 立地 / 間取り / サムネを抽出
- 詳細ページは fetch しない (1リク=軽量、本文要らない)
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

BASE_URL = "https://iga-akiyabank.com"
LIST_URL = "https://iga-akiyabank.com/bukken/"
LISTING_NO_RE = re.compile(r"no=(\d+)")
LAYOUT_RE = re.compile(r"[\d０-９]+(?:LDK|LK|DK|K|R)|^[KLDR]+$")


class IgaAkiyabankScraper:
    source = "iga_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("iga_akiyabank list fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("a.card[href*='/bukken/detail.php']")
        logger.info("iga_akiyabank: %d cards found", len(cards))
        for card in cards:
            listing = _parse_card(card)
            if listing is not None:
                yield listing


def _parse_card(card: Tag) -> RawListing | None:
    href = card.get("href", "")
    m = LISTING_NO_RE.search(str(href))
    if not m:
        return None
    listing_id = m.group(1)
    detail_url = urljoin(BASE_URL, str(href))

    title_el = card.select_one(".card-title")
    city_text = title_el.get_text(" ", strip=True) if title_el else ""

    layout_el = card.select_one(".bukken_kibo")
    layout = layout_el.get_text(strip=True) if layout_el else ""

    price_el = card.select_one(".bukken_kakaku")
    price_text = price_el.get_text(strip=True) if price_el else None

    ctg_el = card.select_one(".bukken_ctg")
    ctg = ctg_el.get_text(strip=True) if ctg_el else ""  # 売却 / 賃貸

    # 賃貸物件はスキップ (購入対象でない)
    if "賃貸" in ctg and "売却" not in ctg:
        return None

    comment_el = card.select_one(".bukken_comment")
    comment = comment_el.get_text(" ", strip=True) if comment_el else ""

    img_el = card.select_one(".card-img img")
    thumb = None
    if img_el:
        src = img_el.get("src", "")
        if src:
            thumb = urljoin(BASE_URL, str(src))

    title = f"{city_text} {layout}".strip()
    body = f"{layout} | {ctg} | {comment}"

    # 間取り (DK/LDK 等) があれば確実に house。なければ classify に委ねる。
    type_hint = "house" if LAYOUT_RE.search(layout) else None

    # 住所: 「伊賀市〇〇（よみ）」 → 「三重県伊賀市〇〇」 に変換
    address = _normalize_address(city_text)

    return RawListing(
        source="iga_akiyabank",
        listing_id=listing_id,
        url=detail_url,
        title=title or "(タイトルなし)",
        price_text=price_text,
        address_text=address,
        area_land_text=None,    # 詳細ページにある、後で拡張
        area_building_text=None,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint=type_hint,
    )


def _normalize_address(city_text: str) -> str | None:
    """「伊賀市下神戸（しもかんべ）」 → 「三重県伊賀市下神戸」"""
    if not city_text:
        return None
    # 読み仮名の括弧除去
    s = re.sub(r"[（(].*?[)）]", "", city_text).strip()
    if not s:
        return None
    # 県名が無ければ付与
    if not s.startswith(("三重県", "伊賀市")):
        return None
    if s.startswith("伊賀市"):
        s = "三重県" + s
    return s
