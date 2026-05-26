"""Discord Webhook 通知。"""
from __future__ import annotations

import logging
import os
import sqlite3
import time

import httpx

from . import db, filter as flt

logger = logging.getLogger(__name__)

CHANNEL = "discord"
EMBED_COLOR = 0x2ECC71  # green
DIGEST_THRESHOLD = 10  # この件数を超えたらまとめテキストに切り替え


def notify(
    conn: sqlite3.Connection,
    cfg: flt.FilterConfig,
    *,
    dry_run: bool = False,
    use_distance_matrix: bool = False,
) -> dict[str, int]:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook and not dry_run:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")

    rows = db.unnotified_pass(conn, CHANNEL)
    passed: list[sqlite3.Row] = []
    for row in rows:
        ok, reason = flt.passes(conn, row, cfg, use_distance_matrix=use_distance_matrix)
        if ok:
            passed.append(row)
        else:
            logger.debug("skip %s: %s", row["url"], reason)

    if not passed:
        return {"scanned": len(rows), "passed": 0, "sent": 0}

    if dry_run:
        for row in passed:
            print(f"[dry-run] {row['price']}円 {row['prefecture']} {row['title']} {row['url']}")
        return {"scanned": len(rows), "passed": len(passed), "sent": 0}

    if len(passed) > DIGEST_THRESHOLD:
        _post_digest(webhook, passed)
    else:
        for row in passed:
            _post_embed(webhook, row)
            time.sleep(1.0)  # rate limit politeness

    db.mark_notified(conn, [r["id"] for r in passed], CHANNEL)
    return {"scanned": len(rows), "passed": len(passed), "sent": len(passed)}


def _post_embed(webhook: str, row: sqlite3.Row) -> None:
    price = "0円" if row["price"] == 0 else (f"{row['price']:,}円" if row["price"] else "価格不明")
    area = f"土地 {row['area_land']:.0f}㎡" if row["area_land"] else None
    location = " ".join(filter(None, [row["prefecture"], row["city"]]))

    embed = {
        "title": (row["title"] or "(タイトルなし)")[:250],
        "url": row["url"],
        "color": EMBED_COLOR,
        "fields": [
            {"name": "価格", "value": price, "inline": True},
            {"name": "所在地", "value": location or "—", "inline": True},
        ],
        "footer": {"text": f"source: {row['source']}"},
    }
    if area:
        embed["fields"].append({"name": "面積", "value": area, "inline": True})
    if row["thumbnail_url"]:
        embed["thumbnail"] = {"url": row["thumbnail_url"]}

    _post(webhook, {"embeds": [embed]})


def _post_digest(webhook: str, rows: list[sqlite3.Row]) -> None:
    lines = [f"**新着 {len(rows)} 件**"]
    for r in rows:
        price = "0円" if r["price"] == 0 else (f"{r['price']:,}円" if r["price"] else "価格不明")
        loc = " ".join(filter(None, [r["prefecture"], r["city"]])) or "—"
        title = (r["title"] or "")[:60]
        lines.append(f"- [{price} / {loc}] {title}\n  <{r['url']}>")
    # Discord は1メッセージ2000文字制限
    chunk = []
    cur_len = 0
    for line in lines:
        if cur_len + len(line) + 1 > 1900:
            _post(webhook, {"content": "\n".join(chunk)})
            chunk = [line]
            cur_len = len(line)
            time.sleep(1.0)
        else:
            chunk.append(line)
            cur_len += len(line) + 1
    if chunk:
        _post(webhook, {"content": "\n".join(chunk)})


def _post(webhook: str, payload: dict) -> None:
    for attempt in range(3):
        resp = httpx.post(webhook, json=payload, timeout=15.0)
        if resp.status_code == 429:
            wait = float(resp.json().get("retry_after", 2))
            logger.warning("discord 429, sleep %.1fs", wait)
            time.sleep(wait)
            continue
        if 200 <= resp.status_code < 300:
            return
        logger.error("discord POST failed %d: %s", resp.status_code, resp.text[:200])
        return
