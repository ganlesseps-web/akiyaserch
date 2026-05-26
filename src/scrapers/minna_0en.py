"""みんなの0円物件 (https://zero.estate) スクレイパ.

戦略:
1. RSS フィード (/feed/) で最新10件を取得 — 新着検知の高速経路
2. 各エントリのURLから listing_id を抽出 (/zero/<region>/<ID>_<city>/)
3. DB に既存なら詳細ページ skip、新規だけ詳細ページを取得して属性を補完
"""
from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from .base import RawListing, polite_get

logger = logging.getLogger(__name__)

FEED_URL = "https://zero.estate/feed/"
LISTING_URL_RE = re.compile(r"/zero/[^/]+/(\d+)_[^/]+/?$")


class MinnaZeroEnScraper:
    source = "minna_0en"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        # RSS 取得
        resp = polite_get(client, FEED_URL)
        parsed = feedparser.parse(resp.text)
        logger.info("minna_0en RSS: %d entries", len(parsed.entries))

        for entry in parsed.entries:
            url = entry.get("link", "")
            listing_id = _extract_listing_id(url)
            if not listing_id:
                logger.warning("skip non-listing url: %s", url)
                continue

            # 詳細ページ取得して属性パース
            try:
                detail_resp = polite_get(client, url)
            except httpx.HTTPError as e:
                logger.warning("detail fetch failed %s: %s", url, e)
                # 最小限の情報だけで返す
                yield RawListing(
                    source=self.source,
                    listing_id=listing_id,
                    url=url,
                    title=entry.get("title", "").strip(),
                    price_text=None,
                    address_text=None,
                    area_land_text=None,
                    area_building_text=None,
                    thumbnail_url=None,
                    body=entry.get("summary", ""),
                    posted_at=_to_iso(entry.get("published")),
                )
                continue

            yield _parse_detail(
                listing_id=listing_id,
                url=url,
                html=detail_resp.text,
                fallback_title=entry.get("title", "").strip(),
                fallback_body=entry.get("summary", ""),
                posted_at=_to_iso(entry.get("published")),
            )


def _extract_listing_id(url: str) -> str | None:
    path = urlparse(url).path
    m = LISTING_URL_RE.search(path)
    return m.group(1) if m else None


def _to_iso(rfc822: str | None) -> str | None:
    if not rfc822:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(rfc822)
        return dt.astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _parse_detail(
    *,
    listing_id: str,
    url: str,
    html: str,
    fallback_title: str,
    fallback_body: str,
    posted_at: str | None,
) -> RawListing:
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.find(["h1", "h2"])
    title = (title_el.get_text(strip=True) if title_el else "") or fallback_title

    # 物件概要テーブル: ラベル列とデータ列のペア
    fields = _extract_field_table(soup)

    price_text = _find_field(fields, ["希望価格", "販売価格", "売出価格", "募集価格", "譲渡価格", "価格"])
    address_text = fields.get("所在地")
    area_land_text = fields.get("土地面積")
    area_building_text = _find_field(fields, ["建物面積", "延床面積", "床面積"])

    # 物件分類フィールドからタイプを判定 (本文ベース分類より信頼できる)
    bunrui = (fields.get("物件分類") or "").strip()
    property_type_hint = _map_bunrui_to_type(bunrui)

    # サムネ: 最初の wp-content/uploads 配下の画像
    thumb = None
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if "wp-content/uploads" in src and not src.endswith(".svg"):
            thumb = src
            break

    # body は 物件概要テーブルのフィールドを連結したものを使う。
    # soup.get_text 全体だとサイドバーやナビゲーション、他物件カードが混入し、
    # キーワード分類や NG 判定で false positive を引き起こす (例: 他物件の
    # "リゾートマンション" が拾われて apartment 判定される)。
    body_parts: list[str] = [title]
    for k, v in fields.items():
        if v and v.strip() not in ("---", "／---", ""):
            body_parts.append(f"{k}: {v}")
    body_text = " | ".join(body_parts)[:2500]

    return RawListing(
        source="minna_0en",
        listing_id=listing_id,
        url=url,
        title=title,
        price_text=price_text,
        address_text=address_text,
        area_land_text=area_land_text,
        area_building_text=area_building_text,
        thumbnail_url=thumb,
        body=body_text or fallback_body,
        posted_at=posted_at,
        property_type_hint=property_type_hint,
    )


def _map_bunrui_to_type(bunrui: str) -> str | None:
    """zero.estate の '物件分類' を property_type に変換。空文字なら None。"""
    if not bunrui:
        return None
    # よくある値: 土地 / 土地・建物 / 中古住宅 / 中古一戸建 / マンション / etc.
    if "マンション" in bunrui or "アパート" in bunrui:
        return "apartment"
    if "店舗" in bunrui or "事業" in bunrui or "ビル" in bunrui:
        return "commercial"
    if "建物" in bunrui or "住宅" in bunrui or "一戸" in bunrui or "戸建" in bunrui or "古民家" in bunrui:
        return "house"
    if bunrui == "土地" or "更地" in bunrui or "山林" in bunrui or "農地" in bunrui:
        return "land"
    return None


def _find_field(fields: dict[str, str], candidates: list[str]) -> str | None:
    """完全一致を試したあと、最後の手段として '...価格' / '...面積' などの suffix 一致。"""
    for c in candidates:
        if c in fields:
            return fields[c]
    # suffix 一致 (例: '希望価格' を探すために '価格' で終わるキー全部見る)
    for c in candidates:
        for k, v in fields.items():
            if k.endswith(c):
                return v
    return None


def _extract_field_table(soup: BeautifulSoup) -> dict[str, str]:
    """物件概要テーブルから {label: value} 辞書を作る。

    WP テーマによって <table>/<dl>/<div class=row> のどれかになりうるので
    全部試して、それっぽいキー (販売価格/所在地/土地面積など) があれば採用。
    """
    expected_keys = {"販売価格", "価格", "所在地", "土地面積", "建物面積", "延床面積",
                     "物件分類", "現況", "土地権利", "地目"}

    candidates: list[dict[str, str]] = []

    # <table> 形式
    for table in soup.find_all("table"):
        d: dict[str, str] = {}
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True)
                value = cells[1].get_text(" ", strip=True)
                if label:
                    d[label] = value
        if d:
            candidates.append(d)

    # <dl> 形式
    for dl in soup.find_all("dl"):
        d = {}
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            label = dt.get_text(strip=True)
            value = dd.get_text(" ", strip=True)
            if label:
                d[label] = value
        if d:
            candidates.append(d)

    # 最も多く expected_keys を含むものを採用
    best: dict[str, str] = {}
    best_score = 0
    for d in candidates:
        score = sum(1 for k in expected_keys if k in d)
        if score > best_score:
            best, best_score = d, score
    return best
