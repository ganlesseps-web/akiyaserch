"""三重県大台町 空き家バンク (AWA サポートデスク, https://desk.awapj.com/) スクレイパ.

AWA = 奥伊勢ワンダーランド (Okuise Wonder Area)、大台町専用の委託サイト。
URL は `real_list.php` で大台町のみが表示される (他自治体は別ホスト)。

戦略:
- table.def_table の各 <tr> が 1物件 (a href="real_detail.php?t_code=XXXX")
- 列: 物件番号 / サムネ / 地区 / 取引種別+価格 / 土地/建物面積 / 構造+築年 / 登録日 / 状況
- ページネーション: ?s=1&p=N (4ページ程度)
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

BASE_URL = "https://desk.awapj.com"
LIST_URL_TMPL = "https://desk.awapj.com/real_list.php?s=1&p={page}"
MAX_PAGES = 10
T_CODE_RE = re.compile(r"t_code=(\d+)")


class OhdaiAwaScraper:
    source = "ohdai_awa"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL_TMPL.format(page=page)
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("ohdai_awa page=%d failed: %s", page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            rows = soup.select("table.def_table tr")
            page_new = 0
            for tr in rows:
                listing = _parse_row(tr)
                if listing is None or listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                page_new += 1
                yield listing
            logger.info("ohdai_awa: page %d -> %d new (total %d)", page, page_new, len(seen))
            if page_new == 0:
                break


def _parse_row(tr: Tag) -> RawListing | None:
    link = tr.select_one('a[href*="real_detail.php"]')
    if link is None:
        return None
    href = str(link.get("href", ""))
    m = T_CODE_RE.search(href)
    if not m:
        return None
    listing_id = m.group(1)

    detail_url = urljoin(BASE_URL + "/", href)

    # サムネ
    thumb = None
    img = tr.select_one("img")
    if img:
        src = str(img.get("src", ""))
        if src:
            thumb = urljoin(BASE_URL + "/", src)

    # 価格 (list_head9 内)
    price_td = tr.select_one("td.list_head9")
    trade_txt = ""
    price_text: str | None = None
    if price_td:
        pieces = [p.get_text(" ", strip=True) for p in price_td.find_all("p")]
        if pieces:
            trade_txt = pieces[0]  # "売買のみ"
            if len(pieces) >= 2:
                price_text = pieces[1]  # "100万円程度"

    # 賃貸 only はスキップ
    if "賃貸" in trade_txt and "売買" not in trade_txt:
        return None

    # list_head0 td 群を順に: 地区 / 面積 / 構造+築年
    head0_tds = tr.select("td.list_head0")
    area_loc = head0_tds[0].get_text(" ", strip=True) if len(head0_tds) >= 1 else ""
    area_text = head0_tds[1].get_text(" ", strip=True) if len(head0_tds) >= 2 else ""
    structure = head0_tds[2].get_text(" ", strip=True) if len(head0_tds) >= 3 else ""

    # 「321.87/76.85」 → 土地/建物 に分割
    area_land = None
    area_building = None
    if "/" in area_text:
        parts = area_text.split("/")
        area_land = parts[0].strip() + "㎡"
        area_building = parts[1].strip() + "㎡"

    # 住所
    address = f"三重県多気郡大台町{area_loc}" if area_loc else "三重県多気郡大台町"

    title = link.get_text(" ", strip=True) or f"大台 No.{listing_id}"
    body = " | ".join(p for p in [trade_txt, structure] if p)

    return RawListing(
        source="ohdai_awa",
        listing_id=listing_id,
        url=detail_url,
        title=f"大台 No.{title} ({area_loc})" if area_loc else f"大台 No.{title}",
        price_text=price_text,
        address_text=address,
        area_land_text=area_land,
        area_building_text=area_building,
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
