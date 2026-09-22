"""売れた物件 (掲載終了) の自動検知。

仕組み:
  毎朝の収集で「今日も一覧に載っていた」物件は last_seen_at が更新される。
  逆に更新されなかった物件 = 一覧から消えた = 売れた/取り下げ の可能性が高い。

誤判定を防ぐ安全装置 (ここが肝):
  1. **その日に収集元から1件も取れなかった場合は、その収集元の物件を判定しない**。
     サイトが落ちた・構造が変わって取れなくなった日に、全物件が「売れた」扱いに
     なる事故を防ぐ。判定は「収集が成功した収集元」の物件だけ。
  2. 価格300万以上などで**わざとスキップした物件も「見かけた」扱い**にする
     (掲載は続いている)。scrape が touch_seen() で印を付ける。
  3. 1回見かけないだけでは切り替えない。**連続 N 日 (既定3日)** 見かけなかったら
     status を 'sold' にする。一覧ページの一時的な取りこぼしを吸収する。
  4. 削除はしない。status を変えるだけなので、再掲載されたら upsert が
     'active' に戻す (復活)。

status の値:
  active = 掲載中 / sold = 掲載終了 (売れた or 取り下げ)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from . import db

logger = logging.getLogger(__name__)

# 連続何日見かけなかったら「掲載終了」にするか
MISSING_DAYS = 3


def touch_seen(conn: Any, source: str, listing_id: str) -> None:
    """DB に入れない (スキップした) 物件でも「今日見かけた」印を付ける。

    価格が300万以上に上がった/土地判定になった物件が既に DB にある場合、
    掲載は続いているのに last_seen_at が止まって sold 扱いになるのを防ぐ。
    """
    conn.execute(
        "UPDATE properties SET last_seen_at = ? WHERE source = ? AND listing_id = ?",
        (db.now_iso(), source, listing_id),
    )


def mark_missing(
    conn: Any,
    *,
    succeeded_sources: set[str],
    missing_days: int = MISSING_DAYS,
    today: date | None = None,
) -> dict[str, int]:
    """連続 missing_days 日見かけなかった物件を 'sold' にする。

    succeeded_sources に含まれる収集元の物件だけを判定する
    (収集に失敗した収集元は判定しない = 安全装置1)。
    Returns: {"checked": 判定対象件数, "marked": 今回 sold にした件数, "revived": 復活件数}
    """
    ref = today or date.today()
    cutoff = (ref - timedelta(days=missing_days)).isoformat()
    stats = {"checked": 0, "marked": 0, "revived": 0}
    if not succeeded_sources:
        logger.warning("sold: 成功した収集元が無いため判定をスキップ")
        return stats

    placeholders = ",".join("?" * len(succeeded_sources))
    srcs = tuple(sorted(succeeded_sources))

    stats["checked"] = conn.execute(
        f"SELECT COUNT(*) FROM properties WHERE status='active' AND source IN ({placeholders})",
        srcs,
    ).fetchone()[0]

    # last_seen_at は ISO 日時 ('2026-09-22T06:00:00+09:00')。先頭10文字が日付。
    # 「最後に見たのが N 日前以前」= 「N 日連続で見ていない」なので <= で判定。
    rows = conn.execute(
        f"""
        SELECT id, source, title, price, last_seen_at FROM properties
        WHERE status = 'active'
          AND source IN ({placeholders})
          AND substr(last_seen_at, 1, 10) <= ?
        """,
        (*srcs, cutoff),
    ).fetchall()

    now = db.now_iso()
    for r in rows:
        conn.execute(
            "UPDATE properties SET status = 'sold', sold_at = ? WHERE id = ?", (now, r["id"])
        )
        stats["marked"] += 1
        logger.info(
            "sold: %s %s (%s円) 最終確認 %s", r["source"], (r["title"] or "")[:30],
            r["price"], str(r["last_seen_at"])[:10],
        )
    return stats


def revive_if_seen(conn: Any, property_id: int) -> bool:
    """upsert で再び見かけた物件が sold なら active に戻す。戻したら True。"""
    row = conn.execute("SELECT status FROM properties WHERE id = ?", (property_id,)).fetchone()
    if row and row["status"] == "sold":
        conn.execute(
            "UPDATE properties SET status = 'active', sold_at = NULL WHERE id = ?", (property_id,)
        )
        return True
    return False


def recent_sold(conn: Any, *, days: int = 7) -> list[Any]:
    """直近 days 日に sold になった物件 (ダッシュボード/統計用)。"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    return conn.execute(
        "SELECT * FROM properties WHERE status = 'sold' AND sold_at >= ?"
        " ORDER BY sold_at DESC",
        (cutoff,),
    ).fetchall()
