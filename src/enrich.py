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


def _client() -> httpx.Client:
    # akiya-athome は中間証明書を返さないため verify=False (既存 scraper と同じ理由)
    ssl.create_default_context()
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
        timeout=25.0, follow_redirects=True, verify=False,
    )


def enrich_missing(conn: Any, *, limit: int = 200) -> dict[str, int]:
    """掲載日が未取得の物件について、詳細ページを1回だけ見に行く。"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    rows = conn.execute(
        """
        SELECT id, url FROM properties
        WHERE status = 'active'
          AND listed_at IS NULL
          AND enriched_at IS NULL
          AND url LIKE '%akiya-athome.jp%'
        ORDER BY first_seen_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    stats = {"target": len(rows), "found": 0, "no_date": 0, "failed": 0}
    if not rows:
        return stats

    now = db.now_iso()
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

            listed = parse_listed_at(resp.content)
            # enriched_at は「見に行った」印。日付が無いページを毎回叩かないため。
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
