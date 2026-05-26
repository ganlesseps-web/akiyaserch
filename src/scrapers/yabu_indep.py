"""兵庫県養父市 空き家バンク (独立サイト, https://www.yabuakiyabank.jp/) スクレイパ.

akiya-athome.jp 版は売戸建 0 件のため、養父市公式の独立サイトをスクレイプする。

戦略:
- /category/house/ の一覧で全戸建物件を取得 (article.flex_box ごと)
- 一覧にはタイトル + サムネ + 物件番号しか無いので、各物件の詳細ページを
  fetch して <table> から 所在地/築年数/建物構造/宅地面積/延床面積/希望価格 を取得
- 詳細ページ ~40件 → ~1リク/1.2秒 = ~50秒。1自治体としては許容範囲。
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

BASE_URL = "https://www.yabuakiyabank.jp"
LIST_URL = "https://www.yabuakiyabank.jp/category/house/"
ID_RE = re.compile(r"yabuakiyabank\.jp/(\d+)/?")


class YabuIndepScraper:
    source = "yabu_indep"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("yabu_indep list fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        articles = soup.select("article.flex_box")
        if not articles:
            articles = soup.select("article")
        logger.info("yabu_indep: %d articles on list", len(articles))

        for art in articles:
            link = art.select_one("a[href]")
            if link is None:
                continue
            href = str(link.get("href", ""))
            m = ID_RE.search(href)
            if not m:
                continue
            listing_id = m.group(1)

            title_el = art.select_one(".house_title .title, .title")
            title = title_el.get_text(" ", strip=True) if title_el else ""

            # 一覧ページのサムネ (背景画像 url())
            thumb = None
            for tag in art.select("[style]"):
                style = str(tag.get("style", ""))
                bm = re.search(r"url\(([^)]+)\)", style)
                if bm:
                    thumb = bm.group(1).strip("'\"")
                    break
            if not thumb:
                meta = art.find("meta", {"itemprop": "image"})
                if meta:
                    thumb = str(meta.get("content", "")) or None

            # 賃貸 icon があればスキップ (一覧アイコンで判別)
            cat_img = art.select_one(".cats_icon img")
            if cat_img:
                icon = str(cat_img.get("src", ""))
                if "rent" in icon.lower():
                    continue

            # 詳細ページ fetch
            try:
                detail_resp = polite_get(client, href)
            except httpx.HTTPError as e:
                logger.warning("yabu_indep detail fetch failed (%s): %s", listing_id, e)
                continue

            detail_soup = BeautifulSoup(detail_resp.text, "lxml")
            detail = _parse_detail_attrs(detail_soup)
            price_text = _parse_price(detail_soup)
            address = detail.get("所在地", "")
            if address:
                # 「養父市大屋町須西 Google MAPで確認する」のような尻尾を切る
                address = re.split(r"\s*Google", address)[0].strip()
                if not address.startswith("兵庫県"):
                    if address.startswith("養父市"):
                        address = f"兵庫県{address}"
                    else:
                        address = f"兵庫県養父市{address}"

            chiku = detail.get("築年数", "")
            kozo = detail.get("建物構造", "")
            land = detail.get("宅地面積", "")
            building = detail.get("延床面積", "")
            shubetsu = detail.get("建物種別", "")
            shuzen = detail.get("修繕必要の有無", "")

            body = " | ".join(p for p in [chiku, kozo, shubetsu, shuzen] if p)

            yield RawListing(
                source="yabu_indep",
                listing_id=listing_id,
                url=href,
                title=title or f"(養父 {listing_id})",
                price_text=price_text,
                address_text=address or "兵庫県養父市",
                area_land_text=land or None,
                area_building_text=building or None,
                thumbnail_url=thumb,
                body=body,
                posted_at=None,
                property_type_hint="house",
            )


def _parse_price(soup: BeautifulSoup) -> str | None:
    """詳細ページの span.price + span.en (単位) から「200万円」形式を組み立てる."""
    sp = soup.select_one("div.prorerth__info__price span.price") or soup.select_one("span.price")
    if sp is None:
        return None
    num = sp.get_text(strip=True).replace(",", "")
    if not num.isdigit():
        return None
    unit_span = sp.find_next("span", class_="en")
    unit = unit_span.get_text(strip=True) if unit_span else "万円"
    if not unit.endswith("円"):
        unit = unit + "円"
    return f"{num}{unit}"


def _parse_detail_attrs(soup: BeautifulSoup) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for table in soup.select("table"):
        # 行ごとに th-td ペアを順番に。複数 th-td を含む行もある
        for tr in table.select("tr"):
            cells = list(tr.children)
            buf: list[Tag] = [c for c in cells if hasattr(c, "name") and c.name in ("th", "td")]
            i = 0
            while i < len(buf) - 1:
                if buf[i].name == "th" and buf[i + 1].name == "td":
                    key = buf[i].get_text(" ", strip=True)
                    val = buf[i + 1].get_text(" ", strip=True)
                    attrs[key] = val
                    i += 2
                else:
                    i += 1
    return attrs
