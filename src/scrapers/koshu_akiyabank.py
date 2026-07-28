"""山梨県甲州市 空き家バンク (甲州らいふ) スクレイパ.

甲州市はアットホームの受け皿が空で、市の移住ポータル「甲州らいふ」
(www.city.koshu.yamanashi.jp/iju/akiya/) で運営している。物件の詳細ページは
利用登録が必要だが、一覧ページには各物件の
「{状況} {種別} No.{番号} {所在地} 価格/{価格}」が公開されている。
一覧のみをテキストで拾う (画像・面積は詳細ページ側で登録要のため取得しない)。

「土地だけは不要」に沿い、売買(戸建て空き家)のみ収集、賃貸・成約済みは除外。
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

LIST_URL = "https://www.city.koshu.yamanashi.jp/iju/akiya/"
DETAIL_URL = "https://www.city.koshu.yamanashi.jp/iju/akiya/details/no{no}.html"

# 例: "新規登録 売買 No.159 山梨県甲州市大和町初鹿野 価格/900万円"
_ROW_RE = re.compile(
    r"(新規登録|交渉中|成約済?|変更|募集中)?\s*(売買|賃貸)\s*No\.?\s*(\d+)\s*"
    r"(山梨県甲州市[^\s|]+)\s*価格[／/]\s*([0-9,]+\s*万?円|[^\s|]+)"
)


class KoshuAkiyabankScraper:
    source = "koshu_akiyabank"
    prefecture = "山梨県"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        try:
            resp = polite_get(client, LIST_URL)
        except httpx.HTTPError as e:
            logger.warning("%s: list fetch failed: %s", self.source, e)
            return
        text = BeautifulSoup(resp.content, "lxml").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)

        seen: set[str] = set()
        for m in _ROW_RE.finditer(text):
            status, kind, no, address, price = m.groups()
            if kind != "売買":            # 賃貸は除外 (購入向け)
                continue
            if status and "成約" in status:  # 売却済みは除外
                continue
            if no in seen:
                continue
            seen.add(no)
            yield RawListing(
                source=self.source,
                listing_id=no,
                url=DETAIL_URL.format(no=no),
                title=f"{address}（甲州市空き家 No.{no}）",
                price_text=price,
                address_text=address,
                area_land_text=None,
                area_building_text=None,
                thumbnail_url=None,
                body=" | ".join(filter(None, [status or "", kind])),
                posted_at=None,
                property_type_hint="house",
            )
        logger.info("%s: %d listings", self.source, len(seen))
