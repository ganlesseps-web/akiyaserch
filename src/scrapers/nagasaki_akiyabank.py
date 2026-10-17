"""長崎県長崎市 空き家・空き地情報バンク (https://www.city.nagasaki.lg.jp/akiya/) スクレイパ.

市の移住サイト「ながさき人になろう」内の独自バンク (アットホームには未参加)。
2026-10 実測: 全53件 (一戸建て28・土地25)・11ページ、うち一戸建て300万未満が15件。

戦略:
- 一覧 /akiya/?page_sale=N を新規が出なくなるまで辿る (1ページ5件)
- 一覧カード (div.result_box) に 題名/物件種別/販売価格/間取り/延べ面積/築年数/町名 がある
- 一戸建てで 300万未満 (=取り込み対象) の物件だけ詳細ページを読み、
  「条件・設備」(上下水道/汲み取り等) と写真を本文に足す
- 賃貸のみ (販売価格なし) の物件は取らない。土地は種別ヒントで land にして収集ルールで弾く

注意 (ダッシュボード利用者向け):
- 内覧には市の利用登録が必要 (建築指導課・申請から約2週間)。所在地の番地も登録後に開示
- 長崎市は「坂の町」で、斜面地の家は車が入らない(駐車場なし)ことが多い
- 海沿いの漁村・離島地区 (野母崎/式見/伊王島/高島/池島 等) は filters.yaml の
  district_blacklist で除外する
"""
from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

BASE = "https://www.city.nagasaki.lg.jp"
LIST_URL = BASE + "/akiya/?page_sale={page}"
MAX_PAGES = 30
DETAIL_PRICE_LIMIT = 3_000_000
ID_RE = re.compile(r"/akiya/(\d+)\.html")
PRICE_RE = re.compile(r"販売価格\s*([\d,]+)\s*円")
KIND_RE = re.compile(r"物件種別\s*(\S+)")
ADDR_RE = re.compile(r"(長崎市[^\s※／]+)")
LAYOUT_RE = re.compile(r"間取り\s*(\S+)")
AREA_RE = re.compile(r"延べ面積\s*([\d.]+)\s*平方メートル")
BUILT_RE = re.compile(r"築年数\s*(\d+年[（(][^）)]+[）)])")


def parse_list(html: bytes) -> list[dict]:
    """一覧ページのカードを辞書で返す。"""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for box in soup.select("div.result_box"):
        a = box.find("a", href=ID_RE)
        if a is None:
            continue
        m = ID_RE.search(str(a["href"]))
        text = re.sub(r"\s+", " ", box.get_text(" ", strip=True))
        title = a.get_text(" ", strip=True)
        # 題名に「長崎市内が見える…」のような文言があると住所と誤認するので、
        # 住所は題名を取り除いた残りから探す
        rest = text.replace(title, " ")
        price = PRICE_RE.search(text)
        kind = KIND_RE.search(text)
        addr = ADDR_RE.search(rest)
        layout = LAYOUT_RE.search(text)
        area = AREA_RE.search(text)
        built = BUILT_RE.search(text)
        img = box.select_one("img")
        out.append({
            "id": m.group(1),
            "url": urljoin(BASE, str(a["href"])),
            "title": title,
            "kind": kind.group(1) if kind else "",
            "price": int(price.group(1).replace(",", "")) if price else None,
            "price_text": f"{price.group(1)}円" if price else None,
            "address": addr.group(1) if addr else "長崎市",
            "area": area.group(1) if area else None,
            "body": " | ".join(x for x in (
                f"間取り:{layout.group(1)}" if layout else "",
                f"築:{built.group(1)}" if built else "",
            ) if x),
            "thumb": urljoin(BASE, str(img["src"])) if img and img.get("src") else None,
        })
    return out


def parse_detail(html: bytes) -> tuple[str, str | None]:
    """詳細ページから (判定に使う本文, 写真URL) を返す。"""
    soup = BeautifulSoup(html, "lxml")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    parts: list[str] = []
    m = re.search(r"条件・設備\s*(.+?)\s*備考", text)
    if m:
        parts.append(f"設備:{m.group(1)[:200]}")
    m = re.search(r"おすすめポイント\s*(.+?)\s*条件・設備", text)
    if m and "PDF" not in m.group(1):
        parts.append(m.group(1)[:300])
    m = re.search(r"築年月\s*(\d{4}年\d{1,2}月)", text)
    if m:
        parts.append(f"築年月:{m.group(1)}")
    img = soup.select_one("img[src*='/uploaded/']")
    return " | ".join(parts), (urljoin(BASE, str(img["src"])) if img else None)


class NagasakiAkiyabankScraper:
    source = "nagasaki_akiyabank"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            try:
                resp = polite_get(client, LIST_URL.format(page=page))
            except httpx.HTTPError as e:
                logger.warning("nagasaki list page=%d fetch failed: %s", page, e)
                break
            cards = [c for c in parse_list(resp.content) if c["id"] not in seen]
            if not cards:
                break
            for c in cards:
                seen.add(c["id"])
                if c["price"] is None:   # 賃貸のみ
                    continue
                is_house = "一戸建" in c["kind"]
                body, thumb = c["body"], c["thumb"]
                if is_house and c["price"] < DETAIL_PRICE_LIMIT:
                    try:
                        extra, photo = parse_detail(polite_get(client, c["url"]).content)
                        body = " | ".join(x for x in (body, extra) if x)
                        thumb = photo or thumb
                    except httpx.HTTPError as e:
                        logger.warning("nagasaki detail %s failed: %s", c["id"], e)
                yield RawListing(
                    source=self.source,
                    listing_id=c["id"],
                    url=c["url"],
                    title=c["title"],
                    price_text=c["price_text"],
                    address_text=f"長崎県{c['address']}",
                    area_land_text=None,
                    area_building_text=f"{c['area']}㎡" if c["area"] else None,
                    thumbnail_url=thumb,
                    body=f"{c['title']} | {body}" if body else c["title"],
                    posted_at=None,
                    property_type_hint="house" if is_house else (
                        "land" if "土地" in c["kind"] else None),
                )
