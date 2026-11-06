"""山梨県身延町 空き家バンク スクレイパ (2026-11-06 ユーザー「山梨の空き家はもっとない？」).

町の移住サイト (www.town.minobu.lg.jp/akiya/) の物件検索。検索フォームの合言葉 (token) を
一覧ページから取り、「空家」かつ「売買」で検索する (10件ずつ・ページ送りあり)。
一覧に値段・所在地・状況 (交渉中など) が出るので一覧から拾い、面積・築年・特記事項は
詳細ページ (/akiya/ijyu/{番号}.html) から取る。水道・トイレの欄は無い。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE = "https://www.town.minobu.lg.jp"
LIST_URL = BASE + "/akiya/"
MAX_PAGES = 5


def _search_url(token: str, page: int) -> str:
    # k_bunrui 1=空家 / k_torihiki 1=売買
    return f"{LIST_URL}?k_bunrui%5B%5D=1&k_torihiki%5B%5D=1&search=1&page={page}&token={token}"


def _detail_field(text: str, label: str, nxt: str) -> str | None:
    m = re.search(rf"{label}\s*(.+?)\s*{nxt}", text)
    return m.group(1).strip() if m else None


def parse_list(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for box in soup.select("div.result_box"):
        a = box.select_one("a.result_title")
        if not a or not a.get("href"):
            continue
        m = re.search(r"/akiya/ijyu/(\d+)\.html", a["href"])
        if not m:
            continue
        price = box.select_one(".data_price dd")
        place = box.select_one(".data_place")
        status = box.select_one(".result_img_status")
        img = box.select_one(".result_img_house img")
        out.append({
            "id": m.group(1),
            "title": a.get_text(strip=True),
            "price": re.sub(r"[（(]売買[）)]", "", price.get_text(strip=True)) if price else None,
            "place": place.get_text(" ", strip=True).replace("所在地", "").strip() if place else None,
            "status": status.get_text(strip=True) if status else "",
            "img": BASE + img["src"] if img and img.get("src", "").startswith("/") else None,
        })
    return out


class MinobuAkiyabankScraper:
    source = "minobu_akiyabank"
    prefecture = "山梨県"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            top = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("%s: list fetch failed: %s", self.source, e)
            return
        tok = BeautifulSoup(top.content, "lxml").find("input", {"name": "token"})
        if not tok or not tok.get("value"):
            logger.warning("%s: search token not found", self.source)
            return

        items: dict[str, dict] = {}
        for page in range(1, MAX_PAGES + 1):
            try:
                resp = polite_get(client, _search_url(tok["value"], page))
            except httpx.HTTPError as e:
                logger.warning("%s: page %d failed: %s", self.source, page, e)
                break
            rows = [r for r in parse_list(resp.content) if r["id"] not in items]
            if not rows:
                break
            items.update({r["id"]: r for r in rows})

        for r in items.values():
            if "成約" in r["status"] or "土地" in r["title"]:
                continue
            url = f"{BASE}/akiya/ijyu/{r['id']}.html"
            detail = ""
            try:
                d = polite_get(client, url)
                detail = re.sub(r"\s+", " ", BeautifulSoup(d.content, "lxml").get_text(" ", strip=True))
            except httpx.HTTPError as e:
                logger.warning("%s: detail %s failed: %s", self.source, url, e)
            i = detail.find("基本情報一覧")
            info = detail[i:detail.find("このページに関するお問い合わせ", i)] if i >= 0 else ""
            place = r["place"] or ""
            yield RawListing(
                source=self.source,
                listing_id=r["id"],
                url=url,
                title=f"{r['title'].replace('New!', '')}（身延町空き家バンク）",
                price_text=r["price"],
                address_text=f"山梨県南巨摩郡{place}" if place else None,
                area_land_text=_detail_field(info, "敷地面積", "築年月"),
                area_building_text=_detail_field(info, "延べ床面積", "敷地面積"),
                thumbnail_url=r["img"],
                body=" | ".join(filter(None, [r["status"], info[:800]])),
                posted_at=None,
                property_type_hint="house",
            )
        logger.info("%s: %d listings", self.source, len(items))
