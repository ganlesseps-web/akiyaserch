"""奈良県十津川村 空き家バンク (https://www.vill.totsukawa.lg.jp/akiyabank/) スクレイパ.

国内最大村、過疎対策補助あり。物件は table 形式の一覧 (1ページ) + 詳細ページ。
詳細ページから 契約形態 / 価格・賃料 / 補修 等を取得する必要がある (一覧には設備のみ)。

戦略:
- 一覧 ?c=akiya_list から各 tr (pk 付き) を取得 (~20件)
- 各詳細 ?c=akiya_view&pk=N を fetch して属性抽出 (~20リク = 25秒)
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

BASE_URL = "https://www.vill.totsukawa.lg.jp"
LIST_URL = "https://www.vill.totsukawa.lg.jp/akiyabank/index.php?c=akiya_list"
PK_RE = re.compile(r"pk=(\d+)")
# 詳細ページから抽出するラベル
DETAIL_LABELS = ("住所", "契約形態", "種類", "価格・賃料", "建築時期",
                 "延床面積", "補修", "電気", "ガス", "水道", "風呂",
                 "トイレ", "駐車場", "その他", "備考")


class TotsukawaScraper:
    source = "totsukawa"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("totsukawa list fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        rows = soup.select("table tr")
        seen: set[str] = set()
        count = 0
        for tr in rows:
            link = tr.select_one('a[href*="pk="]')
            if link is None:
                continue
            href = str(link.get("href", ""))
            m = PK_RE.search(href)
            if not m:
                continue
            pk = m.group(1)
            if pk in seen:
                continue
            seen.add(pk)
            no = link.get_text(strip=True)
            detail_url = urljoin(BASE_URL + "/akiyabank/", href)

            try:
                detail = polite_get(client, detail_url)
            except httpx.HTTPError as e:
                logger.warning("totsukawa detail %s failed: %s", pk, e)
                continue

            listing = _parse_detail(detail.text, pk, no, detail_url)
            if listing is not None:
                count += 1
                yield listing
        logger.info("totsukawa: %d listings", count)


def _parse_detail(html: str, pk: str, no: str, detail_url: str) -> RawListing | None:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    if body:
        for tag in body.select("script, style, nav, header, footer"):
            tag.decompose()
        text = body.get_text(" ", strip=True)
    else:
        text = ""

    attrs: dict[str, str] = {}
    for lbl in DETAIL_LABELS:
        # ラベル直後 → 次のラベルまでの間
        next_labels = "|".join(DETAIL_LABELS + ("空き家・空き地をお探しの方", "問い合わせ先"))
        pattern = rf"{lbl}\s+([^\s].*?)(?=\s+(?:{next_labels})|$)"
        m = re.search(pattern, text)
        if m:
            attrs[lbl] = m.group(1).strip()

    contract = attrs.get("契約形態", "")
    # 賃貸 only はスキップ (filter でも弾かれるが scraper 段階で省略)
    if "賃貸" in contract and "売" not in contract:
        return None

    addr_raw = attrs.get("住所", "")
    if addr_raw and "十津川村" not in addr_raw:
        address = f"奈良県吉野郡十津川村{addr_raw}"
    else:
        address = f"奈良県吉野郡十津川村{addr_raw}" if addr_raw else "奈良県吉野郡十津川村"

    title = f"十津川村 No.{no} ({addr_raw})" if addr_raw else f"十津川村 No.{no}"
    price_text = attrs.get("価格・賃料")
    # 賃貸の場合は price を None にして filter で価格比較を無効化 (settlement_offer は body で判定)
    if contract and "賃貸" in contract:
        price_text = None

    body_parts = [
        attrs.get("種類", ""),
        attrs.get("建築時期", "") and f"築:{attrs.get('建築時期')}",
        attrs.get("補修", "") and f"補修:{attrs.get('補修')}",
        attrs.get("備考", ""),
        contract,
    ]
    body_str = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="totsukawa",
        listing_id=pk,
        url=detail_url,
        title=title,
        price_text=price_text,
        address_text=address,
        area_land_text=None,
        area_building_text=attrs.get("延床面積"),
        thumbnail_url=None,
        body=body_str,
        posted_at=None,
        property_type_hint="house",
    )
