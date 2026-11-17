"""SUUMO 賃貸一戸建て スクレイパ (2026-11-17 ユーザー「賃貸も探して欲しい」「家賃は6-7万円前後で」
「間取りは3LDK以上で。寝室・仕事部屋が2つ欲しい」).

山梨県の市区郡ごとの賃貸一覧 (/chintai/yamanashi/sc_{市}/) を、SUUMO の絞り込み
(ts=3 一戸建て・その他 / ct=7.5 家賃7.5万円以下 / md=08〜14 3K以上) を付けて読む。
これらは robots.txt で禁止されていない /chintai/ の一覧ページの項目なので使ってよい。
1つの建物に複数の部屋 (行) が並ぶことがあるので、行ごとに1件にする (id は SUUMO の物件番号 bc)。
price は家賃＋管理費 (円/月)。上限 (rental.RENT_MAX) を超える家は取り込み時に外す。
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get
from .suumo import AREAS

logger = logging.getLogger(__name__)

BASE = "https://suumo.jp"
MAX_PAGES = 5
QUERY = "ts=3&ct=7.5" + "".join(f"&md={c:02d}" for c in range(8, 15))
CITIES = [c for p, c in AREAS if p == "yamanashi"]


def _yen(text: str | None) -> int | None:
    """「6.5万円」→ 65000、「3000円」→ 3000、「-」→ 0。"""
    if not text:
        return None
    t = unicodedata.normalize("NFKC", text).replace(",", "").strip()
    if t in ("-", ""):
        return 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", t)
    if m:
        return round(float(m.group(1)) * 10000)
    m = re.search(r"(\d+)\s*円", t)
    return int(m.group(1)) if m else None


def _clean(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def parse_list(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for item in soup.select("div.cassetteitem"):
        label = _clean(item.select_one(".cassetteitem_content-label"))
        name = _clean(item.select_one(".cassetteitem_content-title"))
        cols = item.select("ul.cassetteitem_detail > li")
        address = _clean(cols[0]) if cols else ""
        station = " / ".join(filter(None, (_clean(d) for d in item.select(".cassetteitem_detail-col2 .cassetteitem_detail-text"))))
        built = " ".join(_clean(d) for d in item.select(".cassetteitem_detail-col3 div"))
        img = item.select_one("img[rel^='http']")
        for tr in item.select("tr.js-cassette_link"):
            cb = tr.select_one("input[name=bc]")
            link = tr.select_one("a[href*='/chintai/jnc_']")
            if not cb or not link:
                continue
            rent = _yen(_clean(tr.select_one(".cassetteitem_price--rent")) or None)
            fee = _yen(_clean(tr.select_one(".cassetteitem_price--administration")) or None)
            layout = _clean(tr.select_one(".cassetteitem_madori"))
            menseki = _clean(tr.select_one(".cassetteitem_menseki"))
            deposit = _clean(tr.select_one(".cassetteitem_price--deposit"))
            gratuity = _clean(tr.select_one(".cassetteitem_price--gratuity"))
            out.append({
                "id": cb["value"],
                "url": BASE + link["href"].split("?")[0] if link["href"].startswith("/") else link["href"],
                "kind": label, "name": name, "address": address, "station": station,
                "built": built, "rent": rent, "fee": fee or 0,
                "layout": layout, "menseki": menseki,
                "deposit": deposit, "gratuity": gratuity,
                "img": img["rel"] if img else None,
            })
    return out


class SuumoChintaiScraper:
    source = "suumo_chintai"
    prefecture = "山梨県"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        same: set[tuple] = set()   # 同じ家を複数の不動産会社が出していることがある
        for city in CITIES:
            for page in range(1, MAX_PAGES + 1):
                url = f"{BASE}/chintai/yamanashi/sc_{city}/?{QUERY}" + (f"&page={page}" if page > 1 else "")
                try:
                    resp = polite_get(client, url)
                except httpx.HTTPError as e:
                    logger.warning("%s: %s page %d failed: %s", self.source, city, page, e)
                    break
                rows = parse_list(resp.content)
                if not rows:
                    break
                for r in rows:
                    key = (r["name"], r["address"], r["rent"], r["layout"], r["menseki"])
                    if r["id"] in seen or r["rent"] is None or key in same:
                        continue
                    seen.add(r["id"])
                    same.add(key)
                    total = r["rent"] + r["fee"]
                    body = " | ".join(filter(None, [
                        r["kind"],
                        f"間取り {r['layout']}" if r["layout"] else "",
                        r["menseki"] and f"専有面積 {r['menseki']}",
                        f"家賃 {r['rent']:,}円" + (f" ＋ 管理費 {r['fee']:,}円" if r["fee"] else ""),
                        f"敷金 {r['deposit']} / 礼金 {r['gratuity']}",
                        r["station"] and f"沿線・駅 {r['station']}",
                        r["built"],
                    ]))
                    yield RawListing(
                        source=self.source,
                        listing_id=r["id"],
                        url=r["url"],
                        title=f"【賃貸】{r['name']} {r['layout']}（SUUMO賃貸）",
                        price_text=f"{total}円",
                        address_text=r["address"],
                        area_land_text=None,
                        area_building_text=r["menseki"].replace("m 2", "㎡").replace("m2", "㎡") or None,
                        thumbnail_url=r["img"],
                        body=body,
                        posted_at=None,
                        property_type_hint="house",
                        deal_type="rent",
                    )
                if f"page={page + 1}".encode() not in resp.content:
                    break
        logger.info("%s: %d listings", self.source, len(seen))
