"""三重県名張市 空き家バンク (https://www.city.nabari.lg.jp/akiyabank/) スクレイパ.

戦略: /akiyabank/search/all.html の一覧 (XHTML)。各物件は <dl class="compact">
で dt-dd ペアの属性 (物件名/所在地/敷地面積/建物面積/建築時期/取引形態/価格)。
詳細ページ ../property/{id}/{ts}.html は fetch しない (一覧で必要情報が揃う)。
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

BASE_URL = "https://www.city.nabari.lg.jp"
LIST_URL = "https://www.city.nabari.lg.jp/akiyabank/search/all.html"
# detail URL: ../property/373/20260512171023.html
PROPERTY_ID_RE = re.compile(r"property/(\d+)/")


class NabariAkiyabankScraper:
    source = "nabari_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("nabari_akiyabank fetch failed: %s", e)
            return

        # XHTML を html.parser で扱う (lxml だと XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.content, "html.parser")
        dls = soup.select("dl.compact")
        logger.info("nabari_akiyabank: %d dl.compact found", len(dls))
        for dl in dls:
            listing = _parse_dl(dl, soup)
            if listing is not None:
                yield listing


def _parse_dl(dl: Tag, soup: BeautifulSoup) -> RawListing | None:
    attrs: dict[str, str] = {}
    detail_href = ""

    children = list(dl.find_all(["dt", "dd"]))
    for i in range(0, len(children) - 1, 2):
        dt = children[i]
        dd = children[i + 1]
        if dt.name != "dt" or dd.name != "dd":
            continue
        key = dt.get_text(strip=True)
        # 物件名 dd には a タグが入っている
        link = dd.find("a")
        if link and not detail_href:
            detail_href = str(link.get("href", ""))
        attrs[key] = dd.get_text(" ", strip=True)

    if not detail_href:
        return None
    m = PROPERTY_ID_RE.search(detail_href)
    if not m:
        return None
    listing_id = m.group(1)
    detail_url = urljoin(LIST_URL, detail_href)

    # 取引形態: 売却(媒介)/直接取引/賃貸 等。賃貸はスキップ
    kind = attrs.get("取引形態", "")
    if "賃貸" in kind and "売却" not in kind and "売買" not in kind:
        return None

    title = attrs.get("物件名", f"(名張 {listing_id})")
    address_raw = attrs.get("所在地", "")
    if address_raw and not address_raw.startswith(("三重県", "名張市")):
        address = f"三重県名張市{address_raw}"
    elif address_raw.startswith("名張市"):
        address = f"三重県{address_raw}"
    else:
        address = address_raw or "三重県名張市"

    body_parts = [
        attrs.get("建築時期", ""),
        attrs.get("取引形態", ""),
        attrs.get("構造", ""),
    ]
    body = " | ".join(p for p in body_parts if p)

    # サムネは dl の近隣 img を取得 (ページ構造によっては dl 外の場合あり)
    thumb = None
    img = dl.find_previous("img") or dl.find_next("img")
    if img:
        src = str(img.get("src", ""))
        if src and not src.startswith("data:"):
            thumb = urljoin(LIST_URL, src)

    return RawListing(
        source="nabari_akiyabank",
        listing_id=listing_id,
        url=detail_url,
        title=title,
        price_text=attrs.get("価格"),
        address_text=address,
        area_land_text=attrs.get("敷地面積"),
        area_building_text=attrs.get("建物面積"),
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",  # 名張市バンクは戸建てのみ
    )
