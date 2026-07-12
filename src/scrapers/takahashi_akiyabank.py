"""岡山県高梁市 空き家バンク (takahashi-akiyabank.com) スクレイパ.

高梁市はアットホーム空き家バンクに戸建てを載せておらず、市独自の WordPress
サイト (takahashi-akiyabank.com) で運営している。一覧 /bank/ を 1ページ10件で
ページング (/bank/page/N/)、各 .bank__list-item から
(タイトル / エリア(町名) / 物件番号 / 賃貸・売買価格 / タグ / サムネ) を抽出する。

ユーザー要望により「中部〜南部」のみ収集する。サイトのエリア区分のうち
市街地・高梁地域・成羽町を対象とし、北部(有漢町)・西の山間(川上町・備中町)は
除外する (allowed_areas)。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup, Tag

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

_BANK_ID_RE = re.compile(r"/bank/(\d+)")


class TakahashiAkiyabankScraper:
    source = "takahashi_akiyabank"
    base_url = "https://takahashi-akiyabank.com"
    prefecture = "岡山県"
    city = "高梁市"

    # 「中部〜南部」= 市街地・高梁地域・成羽町のみ収集 (北部/山間は除外)。
    allowed_areas: set[str] = {"市街地", "高梁地域", "成羽町"}
    # エリア表記が実在の町名ならそれを住所に足す (市街地/高梁地域 は地名でないため市までに留める)。
    _real_towns: set[str] = {"成羽町", "川上町", "有漢町", "備中町"}

    max_pages = 20  # 1ページ10件、実際は ~12ページ。安全側に20。

    def _list_url(self, page: int) -> str:
        return f"{self.base_url}/bank/" if page == 1 else f"{self.base_url}/bank/page/{page}/"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = self._list_url(page)
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                # 範囲外ページは 404 になる (正常な終了条件)
                logger.info("%s: stop at page %d (%s)", self.source, page, e)
                break

            soup = BeautifulSoup(resp.content, "lxml")
            items = soup.select(".bank__list-item")
            if not items:
                break

            page_new = 0
            for li in items:
                listing = self._parse_item(li)
                if listing is None:
                    continue
                if listing.listing_id in seen:
                    continue
                seen.add(listing.listing_id)
                page_new += 1
                yield listing
            logger.info("%s: page %d -> %d new (total %d)", self.source, page, page_new, len(seen))

    def _parse_item(self, li: Tag) -> RawListing | None:
        # 詳細リンク & 物件番号
        link = li.select_one('a[href*="/bank/"]')
        href = str(link.get("href", "")) if link else ""
        m = _BANK_ID_RE.search(href)

        # info-table を dict 化 (エリア / 物件番号 / 賃貸 / 売買)
        info: dict[str, str] = {}
        for tr in li.select(".bank__info-table tr"):
            th = tr.select_one(".bank__info-table-th")
            td = tr.select_one(".bank__info-table-td")
            if th and td:
                info[th.get_text(strip=True)] = td.get_text(" ", strip=True)

        listing_id = info.get("物件番号") or (m.group(1) if m else "")
        if not listing_id:
            return None
        detail_url = href or f"{self.base_url}/bank/{listing_id}/"

        # 成約済み等は除外 (受付中のみ通す)
        status_el = li.select_one(".bank__info-status")
        status = status_el.get_text(" ", strip=True) if status_el else ""
        if "成約" in status or "終了" in status:
            return None

        # 中部〜南部フィルタ
        area = info.get("エリア", "").strip()
        if self.allowed_areas and area not in self.allowed_areas:
            return None

        # タイトル
        title_el = li.select_one("h2, h3, h4, .bank__ttl, .bank__title")
        title = title_el.get_text(" ", strip=True) if title_el else f"高梁市空き家 {listing_id}"

        # 価格: 売買を優先。無ければ None (賃貸のみ物件は価格不明扱い)
        sale = info.get("売買", "").strip()
        price_text = sale if ("万円" in sale or "円" in sale) else None

        # 住所: 実在の町名なら市の後ろに足す。市街地/高梁地域 は市までに留める。
        address = f"{self.prefecture}{self.city}"
        if area in self._real_towns:
            address += area

        # サムネイル
        thumb = None
        img = li.select_one(".bank__gallery-large img, .bank__gallery img")
        if img:
            src = str(img.get("src", ""))
            if src.startswith("http"):
                thumb = src
            elif src.startswith("//"):
                thumb = "https:" + src

        # タグ (#農地付き 等) と 賃貸/売買 を body に (判定材料)
        tags = [t.get_text(strip=True) for t in li.select(".bank__tag-item")]
        rent = info.get("賃貸", "").strip()
        body = " | ".join(
            filter(None, [" ".join(tags), f"エリア:{area}" if area else "",
                          f"賃貸:{rent}" if rent and rent != "-" else "",
                          f"売買:{sale}" if sale and sale != "-" else ""])
        )

        return RawListing(
            source=self.source,
            listing_id=listing_id,
            url=detail_url,
            title=title,
            price_text=price_text,
            address_text=address,
            area_land_text=None,
            area_building_text=None,
            thumbnail_url=thumb,
            body=body or None,
            posted_at=None,
            property_type_hint="house",  # 空き家(戸建)バンク
        )
