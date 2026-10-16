"""島根県出雲市 いずも空き家バンク (https://izumo-akiyataisaku.jp/vacant_house/) スクレイパ.

市の独自サイト (WordPress)。アットホーム系ではない。
NPO の akiya.izumo-city.jp も同じ物件を載せているが転載なので使わない。

戦略:
- 一覧 /vacant_house/page/N/ (1ページ12件・全9ページ程度) に 地域/物件番号/間取り/
  宅地面積/価格/所在地 が全部載る
- ただし 売買か賃貸か・建物か土地か は一覧に無い (賃貸の家賃 4万円 が価格欄に並ぶ)。
  → 価格が 300万円未満の物件だけ詳細ページを読み、売買・建物かを確認する
  (300万以上は収集時に捨てられるので詳細を読む必要がない。毎朝40件前後)
- 詳細ページの トイレ/水道/駐車場/建築時期/交通 を本文に入れ、汲み取り等の判定を効かせる
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup, Tag

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE_URL = "https://izumo-akiyataisaku.jp"
LIST_URL = f"{BASE_URL}/vacant_house/"
MAX_PAGES = 20
DETAIL_PRICE_LIMIT = 3_000_000  # これ未満だけ詳細ページを読む
ID_RE = re.compile(r"/vacant_house/([^/]+)/?$")
YEN_RE = re.compile(r"([\d,]+)\s*円")

# 詳細ページから本文に取り込む項目 (汲み取り/駐車場なし 等のキーワード判定用)
DETAIL_FIELDS = ("用途", "構造", "延床面積", "建築時期", "駐車場", "水道", "トイレ", "交通", "土砂災害警戒区域", "特徴")


def _yen(text: str | None) -> int | None:
    if not text:
        return None
    m = YEN_RE.search(text)
    return int(m.group(1).replace(",", "")) if m else None


class IzumoAkiyabankScraper:
    source = "izumo_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = LIST_URL if page == 1 else f"{LIST_URL}page/{page}/"
            try:
                resp = polite_get(client, url)
            except httpx.HTTPError as e:
                # 最終ページの次は 404 になる
                if page > 1 and isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                    break
                logger.warning("izumo page=%d fetch failed: %s", page, e)
                break
            cards = parse_list(resp.content)
            new = [c for c in cards if c["id"] not in seen]
            if not new:
                break
            for card in new:
                seen.add(card["id"])
                detail = None
                price = _yen(card["price"])
                if price is not None and price < DETAIL_PRICE_LIMIT:
                    try:
                        detail = parse_detail(polite_get(client, card["url"]).content)
                    except httpx.HTTPError as e:
                        logger.warning("izumo detail %s failed: %s", card["id"], e)
                        continue
                listing = build_listing(card, detail)
                if listing is not None:
                    yield listing
            logger.info("izumo: page %d -> %d cards (total %d)", page, len(new), len(seen))


def parse_list(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for li in soup.select("li[data-marker-link]"):
        card = _parse_card(li)
        if card:
            cards.append(card)
    return cards


def _parse_card(li: Tag) -> dict | None:
    href = str(li.get("data-marker-link", ""))
    m = ID_RE.search(href)
    if not m:
        return None
    attrs: dict[str, str] = {}
    for tr in li.select(".contentlist_data tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            attrs[th.get_text(strip=True)] = td.get_text(" ", strip=True)
    area_el = li.select_one(".area_box")
    thumb = str(li.get("data-marker-image", "")) or None
    return {
        "id": m.group(1),
        "url": href,
        "area": area_el.get_text(strip=True) if area_el else "",
        "layout": attrs.get("間取り", ""),
        "land": attrs.get("宅地面積"),
        "price": attrs.get("価格"),
        "address": attrs.get("所在地", ""),
        "thumb": thumb if thumb and thumb.startswith("http") else None,
    }


def parse_detail(html: bytes | str) -> dict[str, str]:
    """詳細ページの「詳細情報」表 (th/td または dt/dd) を辞書にする。"""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for tr in soup.select("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            out.setdefault(th.get_text(strip=True), td.get_text(" ", strip=True))
    for dt in soup.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            out.setdefault(dt.get_text(strip=True), dd.get_text(" ", strip=True))
    return out


def build_listing(card: dict, detail: dict[str, str] | None) -> RawListing | None:
    if detail is not None:
        trade = detail.get("売買・賃貸", "")
        if trade and "売買" not in trade:
            return None  # 賃貸のみ
        bunrui = detail.get("分類", "")
        hint = "land" if "土地" in bunrui and "建物" not in bunrui else "house"
        price_text = detail.get("金額") or card["price"]
    else:
        # 詳細を読んでいない (=300万以上) 物件。間取りが無ければ土地とみなす
        hint = "house" if card["layout"] else "land"
        price_text = card["price"]

    address = card["address"]
    if address and not address.startswith("島根県"):
        address = f"島根県{address}"

    body_parts = [card["area"], card["layout"]]
    if detail:
        body_parts += [f"{k}: {detail[k]}" for k in DETAIL_FIELDS if detail.get(k)]
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="izumo_akiyabank",
        listing_id=card["id"],
        url=card["url"],
        title=f"出雲市 {card['area']} {card['id']} {card['layout']}".strip(),
        price_text=price_text,
        address_text=address or "島根県出雲市",
        area_land_text=card["land"],
        area_building_text=(detail or {}).get("延床面積"),
        thumbnail_url=card["thumb"],
        body=body,
        posted_at=None,
        property_type_hint=hint,
    )
