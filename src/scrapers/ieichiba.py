"""家いちば (https://www.ieichiba.com) スクレイパ.

戦略:
- 公式の JSON API `/api/properties?orderby=price_asc&page=N` を直接叩く
  (HTML パースより速い・正確・サイト負荷も低い)
- price 昇順で page 1 から順に取得
- 全カードの price > SCRAPE_PRICE_CEILING になったページ以降は break
- pager.hasNext が False or page > MAX_PAGES でも break
"""
from __future__ import annotations

import logging
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ieichiba.com"
API_URL_TEMPLATE = "https://www.ieichiba.com/api/properties?orderby=price_asc&page={page}"
MAX_PAGES = 20  # 200件、約240秒。SCRAPE_PRICE_CEILING で早期 break が普通。
SCRAPE_PRICE_CEILING = 5_000_000  # 500万円。filter.price_max より広めに取って scrape する。


class IeichibaScraper:
    source = "ieichiba"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        for page in range(1, MAX_PAGES + 1):
            url = API_URL_TEMPLATE.format(page=page)
            try:
                resp = polite_get(client, url)
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning("ieichiba page %d failed: %s", page, e)
                break

            properties = data.get("properties") or []
            if not properties:
                logger.info("ieichiba page %d: empty, stop", page)
                break

            page_listings: list[RawListing] = []
            for p in properties:
                listing = _parse_property(p)
                if listing is not None:
                    page_listings.append(listing)

            logger.info("ieichiba page %d: %d/%d parsed", page, len(page_listings), len(properties))
            for lst in page_listings:
                yield lst

            # 価格昇順ソート → このページの最安値が ceiling 超えなら次ページ以降も全部超え。
            min_price = _min_parsed_price(page_listings)
            if min_price is not None and min_price > SCRAPE_PRICE_CEILING:
                logger.info("ieichiba page %d min price %d > ceiling, stop", page, min_price)
                break

            if not data.get("pager", {}).get("hasNext", True):
                logger.info("ieichiba page %d: no more pages", page)
                break


def _parse_property(p: dict[str, Any]) -> RawListing | None:
    listing_id = p.get("id") or p.get("property_id")
    if not listing_id:
        return None

    detail_path = p.get("url") or ""
    detail_url = urljoin(BASE_URL, detail_path) if detail_path else BASE_URL

    title = (p.get("title") or p.get("name") or "").strip() or "(タイトルなし)"

    # label_address (例: "群馬県高崎市") の方が google_map_address (フル住所) より
    # normalize の都道府県抽出と相性が良い
    address_text = (p.get("label_address") or p.get("google_map_address") or "").strip() or None

    price_text = (p.get("view_price") or "").strip() or None

    image_url = p.get("image_url") or None

    body = (p.get("body") or p.get("body_middle") or "").strip()[:2000] or None

    return RawListing(
        source="ieichiba",
        listing_id=str(listing_id),
        url=detail_url,
        title=title,
        price_text=price_text,
        address_text=address_text,
        area_land_text=None,  # 詳細ページに含まれる、次フェーズで取得
        area_building_text=None,
        thumbnail_url=image_url,
        body=body,
        posted_at=None,  # API には postedAt が無い
    )


def _min_parsed_price(listings: list[RawListing]) -> int | None:
    from ..normalize import _parse_price
    prices = []
    for lst in listings:
        v = _parse_price(lst.price_text)
        if v is not None and v > 0:
            prices.append(v)
    return min(prices) if prices else None
