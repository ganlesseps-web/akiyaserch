"""山梨県都留市 空き家バンク スクレイパ (2026-11-06 ユーザー「山梨の空き家はもっとない？」).

都留市の空き家バンクは移住サイト「つる暮らし」(kurashi.osusowake.life) に記事として載る。
一覧の見出しが「No.167 大幡の物件【売却：100万円】」の形なので、見出しから番号・地区・価格を取る。
賃貸だけの物件 (【賃貸：1万円】) と、物件ではない記事 (カーシェアの案内など) は除く。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

LIST_URL = "https://kurashi.osusowake.life/sumai-category/%e9%83%bd%e7%95%99%e5%b8%82%e7%a9%ba%e3%81%8d%e5%ae%b6%e3%83%90%e3%83%b3%e3%82%af/"

# 例: "No.167 大幡の物件【売却：100万円】" / "NO149 境の物件 売却【850万】"
_TITLE_RE = re.compile(
    r"No\.?\s*(\d+)\s*(\S+?)の物件\s*(?:【\s*売却[：:]\s*([0-9,]+)\s*万円?\s*】|売却\s*【\s*([0-9,]+)\s*万円?\s*】)",
    re.IGNORECASE,
)


def parse_list(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        if not re.search(r"/sumai/\d+/?$", a["href"]):
            continue
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        m = _TITLE_RE.search(text)
        if not m or m.group(1) in out:
            continue
        img = a.find("img")
        out[m.group(1)] = {
            "no": m.group(1), "area": m.group(2), "man": (m.group(3) or m.group(4)).replace(",", ""),
            "url": a["href"], "title": m.group(0),
            "img": (img.get("data-src") or img.get("src")) if img else None,
        }
    return list(out.values())


class TsuruAkiyabankScraper:
    source = "tsuru_akiyabank"
    prefecture = "山梨県"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("%s: list fetch failed: %s", self.source, e)
            return
        rows = parse_list(resp.content)
        for r in rows:
            yield RawListing(
                source=self.source,
                listing_id=r["no"],
                url=r["url"],
                title=f"都留市{r['area']}の物件（都留市空き家バンク No.{r['no']}）",
                price_text=f"{r['man']}万円",
                address_text=f"山梨県都留市{r['area']}",
                area_land_text=None,
                area_building_text=None,
                thumbnail_url=r["img"],
                body=r["title"],
                posted_at=None,
                property_type_hint="house",
            )
        logger.info("%s: %d listings", self.source, len(rows))
