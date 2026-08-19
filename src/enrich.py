"""詳細ページから「情報公開日(掲載開始日)」を取得する。

なぜ必要か:
  一覧ページには掲載日が無く、詳細ページにしかない。
  「何年売れ残っているか」は再販目線で強いシグナル
  (5年200万円で買い手がつかない = 相場より高いか現地に理由がある)。

なぜ scrape と分けるか:
  詳細ページは1物件1リクエストかかる。毎朝全件取り直すと重いので、
  **まだ取っていない物件だけ**を後から1回だけ取りに行く (assess と同じ発想)。
  一度取れば掲載日は変わらないので取り直し不要。
"""
from __future__ import annotations

import logging
import re
import ssl
import time
from datetime import date, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from . import db

logger = logging.getLogger(__name__)

USER_AGENT = "trade-bot/0.1 (+personal property monitor; contact via repo)"
INTER_REQUEST_SECONDS = 1.2

# 「情報公開日」「登録日」などの隣のセルにある和暦なし日付
_DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_LABELS = ("情報公開日", "情報登録日", "登録日", "掲載日", "公開日")


def parse_listed_at(html: bytes | str) -> str | None:
    """詳細ページのHTMLから掲載開始日 (YYYY-MM-DD) を取り出す。"""
    soup = BeautifulSoup(html, "lxml")
    for tr in soup.select("tr"):
        cells = tr.select("th,td")
        for i, cell in enumerate(cells):
            label = cell.get_text(" ", strip=True)
            if any(lb in label for lb in _LABELS) and i + 1 < len(cells):
                m = _DATE_RE.search(cells[i + 1].get_text(" ", strip=True))
                if m:
                    y, mo, d = (int(x) for x in m.groups())
                    try:
                        return date(y, mo, d).isoformat()
                    except ValueError:
                        return None
    # テーブル以外のレイアウト向けフォールバック (ラベルの直後にある日付)
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    for lb in _LABELS:
        idx = text.find(lb)
        if idx >= 0:
            m = _DATE_RE.search(text[idx: idx + 60])
            if m:
                y, mo, d = (int(x) for x in m.groups())
                try:
                    return date(y, mo, d).isoformat()
                except ValueError:
                    pass
    return None


# 家いちば の物件IDは P{西暦}{連番} 形式 (実測: 2018〜2026年まで全件一貫)。
# 詳細ページに日付表記が無いので、ここから掲載年を導く (追加リクエスト不要)。
_IEICHIBA_ID_RE = re.compile(r"^P(20\d{2})\d{3,6}$")


def listed_at_from_ieichiba_id(listing_id: str | None) -> str | None:
    """家いちばの物件IDから掲載日を推定する。

    年までしか分からないため **その年の12月31日** として扱う (最も新しい可能性)。
    こうすると経過年数を過大に見積もらず、「5年超」の除外で誤って消すことがない。
    """
    if not listing_id:
        return None
    m = _IEICHIBA_ID_RE.match(str(listing_id).strip())
    if not m:
        return None
    year = int(m.group(1))
    if not (2000 <= year <= date.today().year):
        return None
    return f"{year}-12-31"


def listed_years(listed_at: str | None, *, today: date | None = None) -> float | None:
    """掲載開始からの経過年数。取れていなければ None。"""
    if not listed_at:
        return None
    try:
        d = datetime.fromisoformat(listed_at).date()
    except (TypeError, ValueError):
        return None
    ref = today or date.today()
    return max(0.0, (ref - d).days / 365.25)


def stale_label(listed_at: str | None, *, today: date | None = None) -> str | None:
    """長期売れ残りの警告文。3年未満なら None (警告しない)。"""
    yrs = listed_years(listed_at, today=today)
    if yrs is None or yrs < 3.0:
        return None
    return f"長期売れ残り(掲載{yrs:.1f}年)"


# 楽園信州(長野)は掲載開始日を公開していないが、詳細ページに
# 駐車場 / 下水道 / 土地権利 など**ユーザーの条件そのもの**が明記されている。
# これを本文に取り込むと、既存のキーワード判定(汲み取り/井戸/駐車場なし等)が効く。
_RAKUEN_FIELDS = ("駐車場", "下水道", "土地権利", "設備", "構造", "完成年月", "備考／防災情報")


def parse_rakuen_details(html: bytes | str) -> str | None:
    """楽園信州の詳細ページから、判定に使える項目を1行にまとめて返す。"""
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, str] = {}
    for tr in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
        for i in range(0, len(cells) - 1, 2):
            key, val = cells[i], cells[i + 1]
            if key in _RAKUEN_FIELDS and val and key not in found:
                found[key] = val[:200]
    if not found:
        return None
    return " | ".join(f"{k}:{v}" for k, v in found.items())


def _client() -> httpx.Client:
    # akiya-athome は中間証明書を返さないため verify=False (既存 scraper と同じ理由)
    ssl.create_default_context()
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
        timeout=25.0, follow_redirects=True, verify=False,
    )


def enrich_missing(conn: Any, *, limit: int = 200) -> dict[str, int]:
    """まだ情報を補っていない物件を、ソースごとの方法で1回だけ補完する。

    - アットホーム系 : 詳細ページの「情報公開日」を取得
    - 家いちば       : 物件ID (P{西暦}...) から掲載年を導く (通信不要)
    - 楽園信州(長野) : 掲載日は非公開。代わりに詳細ページの
                       駐車場/下水道/土地権利 を本文に足す (判定に効く)
    """
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    stats = {"target": 0, "found": 0, "no_date": 0, "failed": 0, "ieichiba": 0, "rakuen": 0}
    now = db.now_iso()

    # --- 家いちば: 通信せずIDから年を入れる (先に済ませる = 一番安い) ---
    rows = conn.execute(
        "SELECT id, listing_id FROM properties"
        " WHERE status='active' AND listed_at IS NULL AND source='ieichiba' LIMIT ?",
        (limit,),
    ).fetchall()
    for row in rows:
        listed = listed_at_from_ieichiba_id(row["listing_id"])
        if listed:
            conn.execute(
                "UPDATE properties SET listed_at = ?, enriched_at = ? WHERE id = ?",
                (listed, now, row["id"]),
            )
            stats["ieichiba"] += 1
            stats["found"] += 1

    # --- 通信が必要なもの (アットホーム系 / 楽園信州) ---
    rows = conn.execute(
        """
        SELECT id, url, body, source FROM properties
        WHERE status = 'active'
          AND enriched_at IS NULL
          AND (url LIKE '%akiya-athome.jp%' OR url LIKE '%rakuen-akiya.jp%')
        ORDER BY first_seen_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    stats["target"] = len(rows)
    if not rows:
        return stats

    with _client() as client:
        for row in rows:
            try:
                resp = client.get(row["url"])
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("enrich failed for %s: %s", row["id"], e)
                stats["failed"] += 1
                time.sleep(INTER_REQUEST_SECONDS)
                continue

            if "rakuen-akiya.jp" in (row["url"] or ""):
                # 掲載日は無い。判定材料 (駐車場/下水道 等) を本文に足す。
                extra = parse_rakuen_details(resp.content)
                if extra:
                    body = (row["body"] or "").strip()
                    merged = f"{body} | {extra}" if body else extra
                    conn.execute(
                        "UPDATE properties SET body = ?, enriched_at = ? WHERE id = ?",
                        (merged[:4000], now, row["id"]),
                    )
                    stats["rakuen"] += 1
                else:
                    conn.execute(
                        "UPDATE properties SET enriched_at = ? WHERE id = ?", (now, row["id"])
                    )
                stats["no_date"] += 1
            else:
                listed = parse_listed_at(resp.content)
                conn.execute(
                    "UPDATE properties SET listed_at = ?, enriched_at = ? WHERE id = ?",
                    (listed, now, row["id"]),
                )
                if listed:
                    stats["found"] += 1
                else:
                    stats["no_date"] += 1
            time.sleep(INTER_REQUEST_SECONDS)
    return stats
