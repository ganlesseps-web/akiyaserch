"""RawListing -> db.Listing 正規化。価格・面積・住所の文字列をパース。"""
from __future__ import annotations

import re

from .db import Listing
from .scrapers.base import RawListing

# 全47都道府県
PREFECTURES = [
    "北海道",
    "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
    "沖縄県",
]
_PREF_RE = re.compile("|".join(re.escape(p) for p in PREFECTURES))

# 市区町村抽出。3 パターン:
#   (A) 郡+町村:           幌泉郡えりも町
#   (B) 市 (+政令指定区):    大阪市北区, 桶川市
#   (C) 23区:               千代田区
# non-greedy にして 市/町/村 の最初の出現で止める (字レベルを誤って吸わないため)。
_CITY_RE = re.compile(
    r"(?:"
    r"(?:[一-龥々ヵヶ]+郡)?[一-龥々ヵヶぁ-んァ-ヶー]+?[市町村](?:[一-龥々ヵヶぁ-んァ-ヶー]+区)?"
    r"|[一-龥々ヵヶぁ-んァ-ヶー]+?区"
    r")"
)

# 数値抽出（小数あり）
_NUM_RE = re.compile(r"[\d,]+\.?\d*")


def normalize(raw: RawListing) -> Listing:
    address = (raw.address_text or "").strip()
    # "①住所A / ②住所B" のような複数表記は最初の住所のみ取る
    first_addr = _take_first_address(address)

    prefecture = _extract_prefecture(first_addr)
    city = _extract_city(first_addr, prefecture)

    return Listing(
        source=raw.source,
        listing_id=raw.listing_id,
        url=raw.url,
        title=raw.title or "(タイトルなし)",
        price=_parse_price(raw.price_text),
        prefecture=prefecture,
        city=city,
        address=first_addr or None,
        area_land=_parse_area(raw.area_land_text),
        area_building=_parse_area(raw.area_building_text),
        thumbnail_url=raw.thumbnail_url,
        body=raw.body,
        posted_at=raw.posted_at,
    )


def _take_first_address(address: str) -> str:
    """"①xxx / ②yyy" のような複数住所表記は先頭だけ採用。"""
    # 丸数字や区切り文字 / 改行 で分割
    parts = re.split(r"[/／\n]|[①-⑳]|[（(]\s*", address)
    for p in parts:
        s = p.strip().lstrip("：:、,").strip()
        if _PREF_RE.search(s):
            return s
    return address


def _extract_prefecture(address: str) -> str | None:
    m = _PREF_RE.search(address)
    return m.group(0) if m else None


def _extract_city(address: str, prefecture: str | None) -> str | None:
    if prefecture:
        idx = address.find(prefecture)
        if idx >= 0:
            address = address[idx + len(prefecture):]
    m = _CITY_RE.search(address)
    return m.group(0) if m else None


def _parse_price(text: str | None) -> int | None:
    if not text:
        return None
    s = text.replace(",", "").replace(" ", "").replace("　", "")
    if "0円" in s or s.startswith("0") and "円" in s:
        return 0
    m = re.search(r"(\d+)\s*億", s)
    oku = int(m.group(1)) * 100_000_000 if m else 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", s)
    man = int(float(m.group(1)) * 10_000) if m else 0
    m = re.search(r"(\d+)\s*円", s)
    yen = int(m.group(1)) if m else 0
    total = oku + man + yen
    if total > 0:
        return total
    # フォールバック: 純粋な数字
    m = _NUM_RE.search(s)
    return int(float(m.group(0).replace(",", ""))) if m else None


def _parse_area(text: str | None) -> float | None:
    if not text:
        return None
    m = _NUM_RE.search(text.replace(",", ""))
    return float(m.group(0)) if m else None
