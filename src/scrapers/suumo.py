"""SUUMO 中古一戸建て スクレイパ (2026-11-07 ユーザー「SUUMOでも山梨・長崎市で物件を探すようにしてほしい」).

市区郡ごとの一覧 (/chukoikkodate/{県}/sc_{市}/?page=N) を読む。一覧は先頭の数件 (広告枠) の後、
値段の安い順に並ぶので、300万円を超える家が出てきたページで止める (多くは1ページで済む)。
並び替え・値段の絞り込みは robots.txt で禁止された /jj/bukken/ichiran/ を通るので使わない。
一覧に値段・所在地・面積・写真があるので詳細ページは見ない
(上下水道は utilities が詳細ページを見て判定する)。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE = "https://suumo.jp"
MAX_PAGES = 5
PRICE_STOP_MAN = 300   # これを超える家が出たら次のページは見ない

# (県のローマ字, 市区郡のローマ字)
AREAS: list[tuple[str, str]] = [
    ("yamanashi", s) for s in (
        "kofu", "fujiyoshida", "tsuru", "yamanashi", "otsuki", "nirasaki", "minamialps",
        "hokuto", "kai", "fuefuki", "uenohara", "koshu", "chuo",
        "nishiyatsushirogun", "minamikomagun", "nakakomagun", "minamitsurugun",
    )
] + [("nagasaki", "nagasaki")]


def _man(price: str | None) -> float | None:
    """「1億2000万円」「480万円」「60万円」→ 万円の数。"""
    if not price:
        return None
    t = price.replace(",", "")
    m = re.search(r"(?:(\d+)億)?\s*(\d+(?:\.\d+)?)?万", t)
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 10000 + float(m.group(2) or 0)


def _field(unit, label: str) -> str | None:
    for dl in unit.select("dl"):
        dt = dl.find("dt")
        if dt and dt.get_text(strip=True) == label:
            dd = dl.find("dd")
            return dd.get_text("", strip=True) if dd else None
    return None


def parse_list(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for unit in soup.select("div.property_unit"):
        a = unit.select_one("h2.property_unit-title a")
        if not a or not a.get("href"):
            continue
        m = re.search(r"/nc_(\d+)/", a["href"])
        if not m:
            continue
        img = unit.select_one("img[rel^='http']")
        out.append({
            "id": m.group(1),
            "url": BASE + a["href"] if a["href"].startswith("/") else a["href"],
            "title": a.get_text(" ", strip=True),
            "price": _field(unit, "販売価格"),
            "address": _field(unit, "所在地"),
            "station": _field(unit, "沿線・駅"),
            "land": _field(unit, "土地面積"),
            "building": _field(unit, "建物面積"),
            "layout": _field(unit, "間取り"),
            "built": _field(unit, "築年月"),
            "img": img["rel"] if img else None,
        })
    return out


class SuumoScraper:
    source = "suumo"
    prefecture = None   # 山梨県と長崎県。住所は一覧の所在地 (県名から) をそのまま使う

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for pref, city in AREAS:
            for page in range(1, MAX_PAGES + 1):
                url = f"{BASE}/chukoikkodate/{pref}/sc_{city}/" + (f"?page={page}" if page > 1 else "")
                try:
                    resp = polite_get(client, url)
                except httpx.HTTPError as e:
                    logger.warning("%s: %s page %d failed: %s", self.source, city, page, e)
                    break
                rows = parse_list(resp.content)
                if not rows:
                    break
                for r in rows:
                    if r["id"] in seen:
                        continue
                    man = _man(r["price"])
                    if man is None or man > PRICE_STOP_MAN:
                        continue
                    seen.add(r["id"])
                    body = " | ".join(filter(None, [
                        r["station"] and f"沿線・駅 {r['station']}",
                        r["layout"] and f"間取り {r['layout']}",
                        r["built"] and f"築年月 {r['built']}",
                    ]))
                    yield RawListing(
                        source=self.source,
                        listing_id=r["id"],
                        url=r["url"],
                        title=f"{r['title']}（SUUMO）",
                        price_text=r["price"],
                        address_text=r["address"],
                        area_land_text=r["land"],
                        area_building_text=r["building"],
                        thumbnail_url=r["img"],
                        body=body,
                        posted_at=None,
                        property_type_hint="house",
                    )
                # 広告枠を除いた最後の家が上限を超えていれば、以降のページはもっと高い
                last = _man(rows[-1]["price"])
                if last is not None and last > PRICE_STOP_MAN:
                    break
        logger.info("%s: %d listings", self.source, len(seen))
