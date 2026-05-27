"""京都府南丹市 移住・定住ポータル (https://www.nancla.jp/) スクレイパ.

戦略: /houses/ の一覧 (WordPress カスタム投稿)。
.bukken_entry に物件、タイトル `New！No561.美山町田歌の物件　2880万円` 形式で
価格・物件番号が埋め込み。icon img alt で売買/賃貸判定。
ページネーション: /houses/page/N/ (8ページ程度)。
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

BASE_URL = "https://www.nancla.jp"
LIST_URL_TMPL = "https://www.nancla.jp/houses/{page}"
MAX_PAGES = 15
NO_RE = re.compile(r"No\.?\s*(\d+)", re.I)
PRICE_RE = re.compile(r"([\d,]+万[\d,]*\s*円|[\d,]+\s*円)")
ADDRESS_RE = re.compile(r"【住所】\s*([^\n【]+)")


class NanclaScraper:
    source = "nancla"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL_TMPL.format(page="") if page == 1 else LIST_URL_TMPL.format(page=f"page/{page}/")
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("nancla page=%d failed: %s", page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            entries = soup.select(".bukken_entry")
            if not entries:
                break

            page_new = 0
            for entry in entries:
                listing = _parse_entry(entry)
                if listing is None or listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                page_new += 1
                yield listing
            logger.info("nancla: page %d -> %d new (total %d)", page, page_new, len(seen))
            if page_new == 0:
                break


def _parse_entry(entry: Tag) -> RawListing | None:
    title_el = entry.select_one("h3")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    if not title:
        return None

    # listing_id: タイトルから "No561" を取得 (詳細 URL は日本語 escape で長く unstable)
    nm = NO_RE.search(title)
    if not nm:
        # fallback: post-id from div id="post-17575"
        post_id = entry.get("id", "")
        nm2 = re.search(r"(\d+)", str(post_id))
        if not nm2:
            return None
        listing_id = nm2.group(1)
    else:
        listing_id = nm.group(1)

    # 詳細リンク (もし無ければ画像 link を使う)
    detail_url = ""
    more_link = entry.select_one(".bukken_more a") or entry.select_one("a[href*='/houses/']")
    if more_link:
        detail_url = str(more_link.get("href", ""))
    if not detail_url:
        # entry 内任意リンク
        a = entry.select_one("a")
        if a:
            detail_url = str(a.get("href", ""))
    detail_url = urljoin(BASE_URL, detail_url) if detail_url else f"{BASE_URL}/houses/"

    # icon img alt から 売買/賃貸 判定
    icon_alts = [str(img.get("alt", "")) for img in entry.select(".bukken_icon img")]
    icon_text = " ".join(icon_alts)
    if "賃貸" in icon_text and "売買" not in icon_text:
        return None
    # 「土地」 only もスキップ
    if "土地" in icon_text and "空き家" not in icon_text and "戸建" not in icon_text:
        return None

    # 価格: title 内に「2880万円」のように埋め込み
    price_text: str | None = None
    pm = PRICE_RE.search(title)
    if pm:
        price_text = pm.group(0).replace(",", "")

    # 住所
    body_el = entry.select_one(".bukken_text")
    body_full = body_el.get_text(" ", strip=True) if body_el else ""
    addr_m = ADDRESS_RE.search(body_full)
    address_raw = addr_m.group(1).strip() if addr_m else ""
    # 「南丹市美山町田歌」 → 「京都府南丹市美山町田歌」
    if address_raw and not address_raw.startswith(("京都府", "南丹市")):
        address = f"京都府南丹市{address_raw}"
    elif address_raw.startswith("南丹市"):
        address = f"京都府{address_raw}"
    else:
        address = address_raw or "京都府南丹市"

    # サムネ
    img = entry.select_one(".bukken_img img")
    thumb = None
    if img:
        src = str(img.get("src", ""))
        if src.startswith("http"):
            thumb = src

    body_short = body_full[:200] if body_full else ""

    return RawListing(
        source="nancla",
        listing_id=listing_id,
        url=detail_url,
        title=title,
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=None,
        thumbnail_url=thumb,
        body=body_short,
        posted_at=None,
        property_type_hint="house",
    )
