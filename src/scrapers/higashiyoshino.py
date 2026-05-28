"""奈良県東吉野村 空き家バンク (http://www.vill.higashiyoshino.nara.jp/moving/) スクレイパ.

東吉野村は「賃料表示+定住条件相談」型が多い。一覧ページ (.thumb-post) には
画像と詳細URL のみで属性が無いため、各詳細ページを fetch して

  所在地 / 賃料 / 部屋数 / 構造 / トイレ / 修繕必要箇所 / 備考

をラベル付きテキストから抽出する。

戦略:
- 一覧 /moving/house/ で listing_id + thumb URL
- 各詳細ページから タイトル + ラベル属性を抽出
- 賃料 only は raw を取るが price は None (filter 側で「価格不明」として扱い、
  body に「譲渡」等あれば settlement_offer 検出で拾う)
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

BASE_URL = "http://www.vill.higashiyoshino.nara.jp"
LIST_URL = "http://www.vill.higashiyoshino.nara.jp/moving/house/"
HOUSE_ID_RE = re.compile(r"/house/(\d+)")
LABELS = ("所在地", "賃料", "売買価格", "希望価格", "価格", "部屋数", "間取り",
          "構造", "敷地面積", "建物面積", "築年", "修繕必要箇所", "備考")


class HigashiyoshinoScraper:
    source = "higashiyoshino"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("higashiyoshino list fetch failed: %s", e)
            return

        soup = BeautifulSoup(resp.content, "lxml")
        posts = soup.select(".thumb-post")
        logger.info("higashiyoshino: %d posts", len(posts))

        for post in posts:
            link = post.select_one("a[href*='/house/']")
            if link is None:
                continue
            href = str(link.get("href", ""))
            m = HOUSE_ID_RE.search(href)
            if not m:
                continue
            listing_id = m.group(1)
            detail_url = urljoin(BASE_URL, href)

            img = post.select_one("img")
            thumb = None
            if img:
                src = str(img.get("src", ""))
                if src.startswith("http"):
                    thumb = src

            try:
                detail = polite_get(client, detail_url)
            except httpx.HTTPError as e:
                logger.warning("higashiyoshino detail %s failed: %s", listing_id, e)
                continue

            yield _parse_detail(detail.text, listing_id, detail_url, thumb)


def _parse_detail(html: str, listing_id: str, detail_url: str, thumb: str | None) -> RawListing:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find("title")
    title = title_el.text.strip() if title_el else f"東吉野 No.{listing_id}"
    title = re.sub(r"\s*\|\s*移住\s*$", "", title)

    body_el = soup.find("body")
    if body_el:
        for tag in body_el.select("nav, header, footer, script, style"):
            tag.decompose()
        body_text = body_el.get_text(" ", strip=True)
    else:
        body_text = ""

    attrs: dict[str, str] = {}
    for i, lbl in enumerate(LABELS):
        # ラベル直後 (次のラベルか改行までの間) を value として抽出
        pattern = rf"{lbl}\s+([^\s].*?)(?=\s+(?:{'|'.join(LABELS)}|その他のお家|空き家一覧)|$)"
        m = re.search(pattern, body_text)
        if m:
            attrs[lbl] = m.group(1).strip()

    # 住所
    addr_raw = attrs.get("所在地", "")
    if addr_raw and "東吉野村" in addr_raw and not addr_raw.startswith("奈良県"):
        address = f"奈良県吉野郡{addr_raw}" if not addr_raw.startswith("吉野郡") else f"奈良県{addr_raw}"
    elif addr_raw and not addr_raw.startswith("奈良県"):
        address = f"奈良県吉野郡東吉野村{addr_raw}"
    else:
        address = addr_raw or "奈良県吉野郡東吉野村"

    # 価格: 売買価格 / 価格 / 希望価格 のいずれかが優先、無ければ賃料 (賃料は通常 filter で弾かれる)
    price_text = (attrs.get("売買価格") or attrs.get("希望価格") or attrs.get("価格") or attrs.get("賃料"))

    body_parts = [
        attrs.get("構造", ""),
        attrs.get("部屋数", "") and f"部屋数:{attrs.get('部屋数')}",
        attrs.get("修繕必要箇所", "") and f"修繕:{attrs.get('修繕必要箇所')}",
        attrs.get("備考", ""),
    ]
    body = " | ".join(p for p in body_parts if p)

    return RawListing(
        source="higashiyoshino",
        listing_id=listing_id,
        url=detail_url,
        title=title,
        price_text=price_text,
        address_text=address,
        area_land_text=attrs.get("敷地面積"),
        area_building_text=attrs.get("建物面積"),
        thumbnail_url=thumb,
        body=body,
        posted_at=None,
        property_type_hint="house",
    )
