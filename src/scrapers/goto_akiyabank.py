"""長崎県五島市 空き家バンク (https://goto.nagasaki-tabinet.com/iju/vacant-house/) スクレイパ.

市の移住サイト。福江島 (福江/富江/玉之浦/三井楽/岐宿地区) と奈留島 (奈留地区) が対象。
嵯峨島・久賀島 などそれ以外の小島は config/filters.yaml の district_blacklist で除外する。

※購入できるのは「五島市民(1年以上居住)・移住者・新婚家庭」のみ (国家/地方公務員の
  世帯・転勤等の一時転入は不可)。ユーザー本人が移住する前提で採用 (2026-10)。

戦略:
- 一覧 index.html → rel="next" (index_2_4___0_.html …) を辿る。1ページ40件
- 一覧カードには 題名(物件No.+町名)/価格(売却・賃貸)/地区 しか無い
- 購入可で 400万円未満 (交渉候補を含む) or 要相談 の物件だけ詳細ページを読む
  (トイレ=汲み取り / 海までの距離 / 空き家になった年 / 補修の要否 を本文に入れる)
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

LIST_URL = "https://goto.nagasaki-tabinet.com/iju/vacant-house/index.html"
MAX_PAGES = 10
DETAIL_PRICE_LIMIT = 4_000_000  # 五島市は値引き交渉の対象地域 (negotiation) なので400万未満まで読む
ID_RE = re.compile(r"detail_(\d+)\.html")
# 「売却：2,000,000円」「購入：要相談」
SALE_RE = re.compile(r"(?:売却|購入)[：:]\s*([\d,.]+円|要相談)")
# 題名「【NEW】物件No.781（五島市民・移住者・新婚家庭）向町」→ 末尾の町名
TOWN_RE = re.compile(r"[）)]\s*([^（）()]+?)\s*$")

DETAIL_FIELDS = (
    "状況", "補修の要否", "建築年", "利用状況", "主要施設等までの距離",
    "水道", "トイレ", "駐車場", "特記事項",
)


class GotoAkiyabankScraper:
    source = "goto_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        url: str | None = LIST_URL
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            if url is None:
                break
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("goto list %s fetch failed: %s", url, e)
                break
            cards, next_url = parse_list(resp.content, url)
            for card in cards:
                if card["id"] in seen or card["sale"] is None:
                    continue  # 賃貸のみ
                seen.add(card["id"])
                detail = None
                if card["price"] is None or card["price"] < DETAIL_PRICE_LIMIT:
                    try:
                        detail = parse_detail(polite_get(client, card["url"]).content)
                    except httpx.HTTPError as e:
                        logger.warning("goto detail %s failed: %s", card["id"], e)
                        continue
                listing = build_listing(card, detail)
                if listing is not None:
                    yield listing
            logger.info("goto: %s -> %d cards (sale total %d)", url, len(cards), len(seen))
            url = next_url


def _yen(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text.split("円")[0].split(".")[0]) if "円" in text else ""
    return int(digits) if digits else None


def parse_list(html: bytes | str, base_url: str = LIST_URL) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(html, "lxml")
    # カード=「h3 と詳細リンク1つ」を持つ section (外側の囲み section は除く)
    sections = [s for s in soup.select("section") if s.find("h3") and len(s.select("a[href*='detail_']")) == 1]
    cards = [c for c in (_parse_card(s, base_url) for s in sections) if c]
    nxt = soup.select_one("a[rel=next]")
    next_url = urljoin(base_url, str(nxt["href"])) if nxt and nxt.get("href") else None
    return cards, next_url


def _parse_card(sec: Tag, base_url: str) -> dict | None:
    link = sec.select_one("a[href*='detail_']")
    if link is None:
        return None
    href = urljoin(base_url, str(link.get("href", "")))
    m = ID_RE.search(href)
    if not m:
        return None
    h3 = sec.find("h3")
    title = h3.get_text(" ", strip=True) if h3 else ""
    price_p = sec.find("p")
    price_line = price_p.get_text(" ", strip=True) if price_p else ""
    sm = SALE_RE.search(price_line)
    sale = sm.group(1) if sm else None
    tags = [li.get_text(strip=True) for li in sec.select("ul li")]
    district = next((t for t in tags if t.endswith("地区")), "")
    img = sec.select_one("figure img")
    thumb = urljoin(base_url, str(img["src"])) if img and img.get("src") else None
    return {
        "id": m.group(1),
        "url": href,
        "title": title,
        "sale": sale,
        "price": _yen(sale) if sale else None,
        "district": district,
        "negotiating": "交渉中" in tags,
        "thumb": thumb,
    }


def parse_detail(html: bytes | str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for dt in soup.select("dl dt"):
        dd = dt.find_next_sibling("dd")
        key = dt.get_text(strip=True)
        if key and dd:
            out.setdefault(key, dd.get_text(" ", strip=True))
    return out


def build_listing(card: dict, detail: dict[str, str] | None) -> RawListing | None:
    status = (detail or {}).get("状況", "")
    if "成約" in status:
        return None

    town = (detail or {}).get("所在地", "")
    if not town:
        m = TOWN_RE.search(card["title"])
        town = m.group(1) if m else ""
        if town and not town.startswith("五島市"):
            town = f"五島市{town}"
    address = f"長崎県{town}" if town else "長崎県五島市"

    title = re.sub(r"^【NEW】", "", card["title"]).strip() or f"五島市 物件 {card['id']}"
    if card["negotiating"] or "交渉中" in status:
        title = f"【交渉中】{title}"

    body_parts = [card["district"]]
    if detail:
        body_parts += [f"{k}: {detail[k]}" for k in DETAIL_FIELDS if detail.get(k)]
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="goto_akiyabank",
        listing_id=card["id"],
        url=card["url"],
        title=title,
        price_text=card["sale"],
        address_text=address,
        area_land_text=(detail or {}).get("土地面積"),
        area_building_text=(detail or {}).get("建物面積"),
        thumbnail_url=card["thumb"],
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
