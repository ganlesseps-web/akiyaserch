"""ジモティ (https://jmty.jp) 不動産売買スクレイパ.

位置づけ:
  空き家バンクに載らない「個人の直接投稿」の掘り出し物を逃さないための網。
  件数は少ないが、駅徒歩5分の古民家180万・断熱DIY済み450万 のような
  バンク外の物件が時々出る (2026-09 実測)。

戦略:
- config/jmty_areas.yaml の市区町村コードごとに
  /{pref}/est-buy/g-214/{code} (中古・売買) を1ページだけ読む
  (1エリアあたりの直接投稿は数件なので、2ページ目以降はほぼ転載のみ)
- **「提携サイト」(不動産会社広告の転載) は取らない**: 詳細リンク
  /est-buy/article-xxx が無いカードがそれ。価格帯も予算外が大半。
- 「受付終了」の付いたカードは取らない (売れた/取り下げ)
- 一覧カードに タイトル/価格/市名/本文冒頭/作成日 が全て載っているので
  詳細ページは読まない (サイト負荷を最小にする)
- robots.txt は `Allow: /` (2026-09-12 確認)。UA は本物のブラウザ風にしないと
  一部ページで空HTMLが返るため、通常ブラウザのUAを使う。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Iterator

import httpx
import yaml
from bs4 import BeautifulSoup, Tag

from .base import INTER_REQUEST_SECONDS, RawListing

logger = logging.getLogger(__name__)

AREAS_PATH = Path("config/jmty_areas.yaml")
LIST_URL = "https://jmty.jp/{pref}/est-buy/g-214/{code}"
# ジモティは bot 風 UA に空ページを返すことがあるため、一般的なブラウザ UA を使う
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
ARTICLE_RE = re.compile(r"/est-buy/article-([a-z0-9]+)")
# 「作成8月15日」→ (8, 15)。年は載らないので「今日以前の直近」として補う
CREATED_RE = re.compile(r"作成\s*(\d{1,2})月\s*(\d{1,2})日")


def _load_areas(path: Path = AREAS_PATH) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("areas") or [])


def _created_iso(text: str, today: date | None = None) -> str | None:
    """「作成8月15日」を ISO 日付にする。年が無いので直近の過去日付として解釈。"""
    m = CREATED_RE.search(text)
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    ref = today or date.today()
    for year in (ref.year, ref.year - 1):
        try:
            cand = date(year, mo, d)
        except ValueError:
            continue
        if cand <= ref:
            return cand.isoformat()
    return None


class JmtyScraper:
    source = "jmty"

    def fetch(self, client: httpx.Client) -> Iterator[RawListing]:
        areas = _load_areas()
        if not areas:
            logger.warning("jmty: config/jmty_areas.yaml が無いか空です")
            return
        seen: set[str] = set()
        with httpx.Client(
            headers={"User-Agent": BROWSER_UA, "Accept-Language": "ja,en;q=0.8"},
            timeout=25.0, follow_redirects=True,
        ) as own:
            for area in areas:
                url = LIST_URL.format(pref=area["pref"], code=area["code"])
                try:
                    resp = own.get(url)
                    if resp.status_code == 404:
                        # ジモティは「そのジャンルに投稿ゼロ」の地域を 404 で返す (仕様)
                        logger.info("jmty %s: 投稿なし (404)", area.get("label"))
                        time.sleep(INTER_REQUEST_SECONDS)
                        continue
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    logger.warning("jmty %s: %s", area.get("label"), e)
                    time.sleep(INTER_REQUEST_SECONDS)
                    continue
                n = 0
                for raw in self._parse_list(resp.content, area):
                    if raw.listing_id in seen:
                        continue
                    seen.add(raw.listing_id)
                    n += 1
                    yield raw
                logger.info("jmty %s: %d 件 (直接投稿のみ)", area.get("label"), n)
                time.sleep(INTER_REQUEST_SECONDS)

    def _parse_list(self, html: bytes, area: dict) -> Iterator[RawListing]:
        soup = BeautifulSoup(html, "lxml")
        for li in soup.select("li.p-articles-list-item"):
            raw = self._parse_item(li, area)
            if raw:
                yield raw

    def _parse_item(self, li: Tag, area: dict) -> RawListing | None:
        # 直接投稿だけ: 詳細リンクがあるもの。「提携サイト」の転載はリンクが無い
        link = li.select_one("a[href*='/est-buy/article-']")
        if link is None:
            return None
        m = ARTICLE_RE.search(str(link.get("href", "")))
        if not m:
            return None
        listing_id = m.group(1)
        href = str(link.get("href"))
        url = href if href.startswith("http") else f"https://jmty.jp{href}"

        text = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
        # 受付終了 (売れた/取り下げ) は取らない
        if "受付終了" in text:
            return None

        title_el = li.select_one(".p-item-title")
        title = title_el.get_text(" ", strip=True) if title_el else text[:60]
        # 売買カテゴリに「【賃貸】」の投稿が混ざることがある (家賃を価格と誤認するため除外)
        if re.search(r"【?賃貸】?|家賃|月額", title):
            return None

        price_el = li.select_one(".p-item-most-important")
        price_text = price_el.get_text(strip=True) if price_el else None

        # 「津山市 中古（マンション/一戸建て）」→ 市名部分。県名を前置して住所にする
        supp_el = li.select_one(".p-item-supplementary-info")
        city_part = ""
        if supp_el:
            city_part = supp_el.get_text(" ", strip=True).split(" ")[0]
        # 町村は一覧に「神崎郡」までしか載らない。タイトルに町村名があれば補う
        # (例: 「神崎郡市川町小谷 戸建」→ 市川町)。towns は config の対象町村。
        if city_part.endswith("郡"):
            for town in area.get("towns") or []:
                if town in title:
                    city_part = city_part + town
                    break
        address = f"{area['pref_ja']}{city_part}" if city_part else area["pref_ja"]

        detail_el = li.select_one(".p-item-detail")
        body = detail_el.get_text(" ", strip=True) if detail_el else ""
        # タイトルに「○○市△△町」のような所在地が入っていることが多いので本文に含める
        body = f"{title} {body}".strip()

        img = li.select_one("img.p-item-image")
        thumb = str(img.get("src")) if img and img.get("src") else None

        hist_el = li.select_one(".p-item-history")
        posted = _created_iso(hist_el.get_text(" ", strip=True)) if hist_el else None

        # ジモティの「中古(マンション/一戸建て)」はマンションも混ざる。
        # 本文にマンション語があれば apartment、なければ house に寄せる
        if re.search(r"(㎡|坪|筆)の土地|土地[（(]|土地を|土地、|更地|宅地[（(]", title):
            hint = "land"
        elif re.search(r"マンション|アパート|号室", title + body):
            hint = "apartment"
        else:
            hint = "house"

        return RawListing(
            source=self.source,
            listing_id=listing_id,
            url=url,
            title=title,
            price_text=price_text,
            address_text=address,
            area_land_text=None,
            area_building_text=None,
            thumbnail_url=thumb,
            body=body,
            posted_at=posted,
            property_type_hint=hint,
        )
