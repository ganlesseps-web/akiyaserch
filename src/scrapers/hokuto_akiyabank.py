"""山梨県北杜市 空き家バンク スクレイパ (2026-11-16 ユーザー「北杜市も追加して」).

市のサイトの「売却物件」一覧 (/teijyu_ijyu/bank/genre/baikyaku/) を読む。1ページに全件が並ぶ。
各物件は <article> の中に 見出し「空き家バンク登録物件【売245】」・価格・場所 がある。
場所の後ろに「※土砂災害警戒区域…」などの注意書きが付くことがあるので、住所と注意書きに分ける。
賃貸物件 (【賃…】) は売却一覧に出ないが、念のため【売…】の番号が無いものは除く。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE = "https://www.city.hokuto.yamanashi.jp"
LIST_URL = BASE + "/teijyu_ijyu/bank/genre/baikyaku/"

_NO_RE = re.compile(r"【\s*売\s*(\d+)\s*】")


def parse_list(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict] = {}
    for art in soup.select("section.bukken_list article"):
        a = art.find("a", href=True)
        h3 = art.find("h3")
        if not a or not h3:
            continue
        m = _NO_RE.search(h3.get_text(" ", strip=True))
        if not m or m.group(1) in out:
            continue
        price_el = art.select_one(".bukken_price")
        place_el = art.select_one(".bukken_place")
        price = price_el.get_text("", strip=True).replace("価格", "").strip() if price_el else None
        place = place_el.get_text("", strip=True).replace("場所", "", 1).strip() if place_el else ""
        place = place.replace("　", " ")
        addr, _, note = place.partition("※")
        img = art.find("img")
        src = img.get("src") if img else None
        out[m.group(1)] = {
            "no": m.group(1),
            "url": BASE + a["href"] if a["href"].startswith("/") else a["href"],
            "price": price,
            "area": addr.strip(),
            "note": ("※" + note.strip()) if note else "",
            "reform": bool(art.select_one(".teijyu_ijyu-bank-genre-reform")),
            "img": (BASE + src if src and src.startswith("/") else src),
        }
    return list(out.values())


class HokutoAkiyabankScraper:
    source = "hokuto_akiyabank"
    prefecture = "山梨県"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("%s: list fetch failed: %s", self.source, e)
            return
        rows = parse_list(resp.content)
        for r in rows:
            body = " | ".join(filter(None, [
                "要リフォーム物件" if r["reform"] else "",
                r["note"],
            ]))
            yield RawListing(
                source=self.source,
                listing_id=r["no"],
                url=r["url"],
                title=f"北杜市{r['area']}の物件（北杜市空き家バンク 売{r['no']}）",
                price_text=r["price"],
                address_text=f"山梨県北杜市{r['area']}",
                area_land_text=None,
                area_building_text=None,
                thumbnail_url=r["img"],
                body=body or None,
                posted_at=None,
                property_type_hint="house",
            )
        logger.info("%s: %d listings", self.source, len(rows))
