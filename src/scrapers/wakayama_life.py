"""わかやまLIFE 住まいポータル (https://www.wakayamagurashi.jp/) スクレイパ.

戦略: /category/akiya で和歌山県全域の物件一覧が取れる (akiya_area パラメータは
サーバー側で効かないため、全件取って住所で絞り込む)。
取得対象: 古座川町・有田川町 (ユーザー指定の2自治体のみ通す)。

各物件は .property-list 内の直下 <a> ごと。価格は <strong>800</strong> 形式で
単位非明示 (万円暗黙)。賃料の <a> は除外。
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

LIST_URL = "https://www.wakayamagurashi.jp/category/akiya"
DETAIL_RE = re.compile(r"search/(\d+)")
# 通知対象の自治体 (住所文字列に含まれるなら通す)
TARGET_MUNICIPALITIES = ("古座川町", "有田川町")


class WakayamaLifeScraper:
    source = "wakayama_life"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("wakayama_life fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        pl = soup.select_one(".property-list")
        if pl is None:
            logger.info("wakayama_life: no .property-list found")
            return

        cards = pl.find_all("a", recursive=False)
        logger.info("wakayama_life: %d total cards (will filter for %s)",
                    len(cards), TARGET_MUNICIPALITIES)

        kept = 0
        for card in cards:
            listing = _parse_card(card)
            if listing is None:
                continue
            kept += 1
            yield listing
        logger.info("wakayama_life: kept %d after municipality filter", kept)


def _parse_card(card: Tag) -> RawListing | None:
    href = str(card.get("href", ""))
    if not href:
        return None
    m = DETAIL_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)
    detail_url = urljoin(LIST_URL, href)

    # property-id (T-... or A-...)
    pid_el = card.select_one(".property-id")
    property_id = pid_el.get_text(strip=True) if pid_el else ""

    # txt > ul > li> 所在地/価格/賃料/間取り/建築年
    attrs: dict[str, str] = {}
    is_rent = False
    for li in card.select(".txt ul li"):
        span = li.find("span")
        if span is None:
            continue
        key = span.get_text(strip=True)
        # span 以降のテキスト
        value = ""
        for sib in span.next_siblings:
            if hasattr(sib, "get_text"):
                value += sib.get_text(" ", strip=True)
            elif isinstance(sib, str):
                value += sib.strip()
        value = value.strip()
        attrs[key] = value
        if key == "賃料":
            is_rent = True

    if is_rent:
        return None

    address = attrs.get("所在地", "")
    if not address:
        return None
    if not any(m in address for m in TARGET_MUNICIPALITIES):
        return None  # 古座川町・有田川町以外は捨てる

    # 住所先頭に和歌山県を補完
    if not address.startswith("和歌山県"):
        address = f"和歌山県{address}"

    # 価格: "800" → 800万円扱い (サイトUI が万円表示)
    price_raw = attrs.get("価格", "")
    price_text = None
    if price_raw:
        # 数字のみなら万円補完
        if re.fullmatch(r"[\d,]+", price_raw):
            price_text = f"{price_raw}万円"
        else:
            price_text = price_raw

    layout = attrs.get("間取り", "")
    built = attrs.get("建築年", "")

    # サムネ
    img = card.select_one("p.img img")
    thumb = None
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    title = f"{address} {layout}".strip() if layout else address
    body = " | ".join(p for p in [layout, built, property_id] if p)

    return RawListing(
        source="wakayama_life",
        listing_id=listing_id,
        url=detail_url,
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
