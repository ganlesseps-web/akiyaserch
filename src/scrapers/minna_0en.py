"""みんなの0円物件 (https://zero.estate) スクレイパ — tRPC API 版.

2026年にサイトが React SPA + tRPC API に刷新され、旧 RSS(/feed/) は廃止された
(現在 /feed/ は HTML を返すだけ)。公開 API `property.list` (GET, superjson 形式)
をページングして 0円物件を取得する。

方針:
- 掲載中 (publicStatus == "募集中") のみ収集 (成約済み/受付停止/取引中止は除外)。
  ※ zero.estate は成約済みが大多数 (全体の8割超) なので、これは必須。
- 建物あり (土地・建物 / マンション / 建物のみ) のみ。更地(土地のみ)は「住める空き家」
  ではないため既定で除外 (building_types で変更可)。
- 全国対象。0円物件は希少で件数も少ない(掲載中の建物ありは数十件規模)ため、
  ダッシュボードの「🆓0円物件」タブで都道府県フィルタして見る想定。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator
from urllib.parse import urlencode

import httpx

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

API_URL = "https://zero.estate/api/trpc/property.list"
DETAIL_URL = "https://zero.estate/properties/{id}"
PAGE_LIMIT = 100
MAX_PAGES = 30           # 安全弁 (実際の totalPages は ~20)
OPEN_STATUS = "募集中"
BUILDING_TYPES = {"土地・建物", "マンション", "建物のみ"}  # 更地(土地のみ)は除外


class MinnaZeroEnScraper:
    source = "minna_0en"
    building_types: set[str] = BUILDING_TYPES

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        page = 1
        yielded = 0
        while page <= MAX_PAGES:
            try:
                payload = self._fetch_page(client, page)
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
                logger.warning("minna_0en page %d failed: %s", page, e)
                break

            for it in payload.get("items", []):
                if it.get("publicStatus") != OPEN_STATUS:
                    continue
                if it.get("propertyType") not in self.building_types:
                    continue
                raw = self._item_to_raw(it)
                if raw is not None:
                    yielded += 1
                    yield raw

            total_pages = int(payload.get("totalPages") or page)
            logger.info("minna_0en: page %d/%d (yielded %d)", page, total_pages, yielded)
            if page >= total_pages:
                break
            page += 1

    def _fetch_page(self, client: httpx.Client, page: int) -> dict[str, Any]:
        # tRPC (superjson) の GET クエリ。null フィルタは「送らない」= undefined 扱いにする
        # (null を送るとサーバの zod 検証で 400 になる)。
        inp = {"0": {"json": {"page": page, "limit": PAGE_LIMIT, "sortBy": "newest"}}}
        url = API_URL + "?" + urlencode(
            {"batch": "1", "input": json.dumps(inp, separators=(",", ":"))}
        )
        resp = polite_get(client, url)
        data = resp.json()
        return data[0]["result"]["data"]["json"]

    @staticmethod
    def _item_to_raw(it: dict[str, Any]) -> RawListing | None:
        pid = it.get("id")
        if pid is None:
            return None

        prefecture = it.get("prefecture") or ""
        city = it.get("city") or ""
        address = it.get("address") or (prefecture + city) or None

        ptype = it.get("propertyType") or ""
        if ptype in ("土地・建物", "建物のみ"):
            hint = "house"
        elif ptype == "マンション":
            hint = "apartment"
        else:
            hint = "land"

        # specialNotes は JSON 文字列の配列 (例: '["残置物あり","長期空き家"]')
        tags: list[str] = []
        notes = it.get("specialNotes")
        if notes:
            try:
                parsed = json.loads(notes)
                if isinstance(parsed, list):
                    tags = [str(t) for t in parsed]
            except (ValueError, TypeError):
                pass

        built = it.get("builtYear")
        body = " | ".join(
            x for x in [
                it.get("title") or "",
                f"築:{built}" if built else "",
                " ".join(tags),
                f"種別:{ptype}" if ptype else "",
            ] if x
        )

        # サムネイル: sortOrder 最小の画像
        thumb = None
        imgs = it.get("images") or []
        if imgs:
            first = sorted(imgs, key=lambda im: im.get("sortOrder", 0))[0]
            thumb = first.get("imageUrl")

        return RawListing(
            source="minna_0en",
            listing_id=str(pid),
            url=DETAIL_URL.format(id=pid),
            title=it.get("title") or f"0円物件 {pid}",
            price_text="0円",
            address_text=address,
            area_land_text=None,
            area_building_text=None,
            thumbnail_url=thumb,
            body=body or None,
            posted_at=it.get("approvedAt") or it.get("createdAt"),
            property_type_hint=hint,
        )
