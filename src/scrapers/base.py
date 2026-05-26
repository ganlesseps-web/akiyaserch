"""Common scraper interface. Each source implements fetch() to yield RawListing."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterator, Protocol

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "trade-bot/0.1 (+personal property monitor; contact via repo)"
DEFAULT_TIMEOUT = 20.0
INTER_REQUEST_SECONDS = 1.2  # politeness delay between requests to same host


@dataclass
class RawListing:
    """Pre-normalization listing data as scraped from a source."""
    source: str
    listing_id: str
    url: str
    title: str
    price_text: str | None        # "0円" など、未パース文字列
    address_text: str | None      # 住所そのまま
    area_land_text: str | None    # "294.52㎡" など
    area_building_text: str | None
    thumbnail_url: str | None
    body: str | None              # NG ワード判定用テキスト
    posted_at: str | None         # ISO8601
    property_type_hint: str | None = None
    """ソース側が判定したタイプ (例: 物件分類="土地" → 'land')。
    normalize はこのヒントを優先し、None ならキーワード分類にフォールバック。"""


class Scraper(Protocol):
    source: str

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        ...


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )


def polite_get(client: httpx.Client, url: str) -> httpx.Response:
    """GET with politeness delay and 429 backoff."""
    for attempt in range(3):
        resp = client.get(url)
        if resp.status_code == 429:
            wait = 2 ** (attempt + 2)  # 4, 8, 16s
            logger.warning("429 from %s, backing off %ds", url, wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        time.sleep(INTER_REQUEST_SECONDS)
        return resp
    raise RuntimeError(f"giving up on {url} after 429s")
