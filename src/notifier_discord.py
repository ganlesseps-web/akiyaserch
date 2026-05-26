"""Discord Webhook 通知。"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
import urllib.parse

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


# --------- URL builders for quick links ---------

def _maps_url(address: str) -> str:
    """Google Maps 検索リンク。住所そのまま query に渡せる。"""
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(address)}"


def _streetview_url(address: str) -> str:
    """Google ストリートビュー (近隣の最初のパノラマを表示)."""
    return (
        "https://www.google.com/maps/@?api=1&map_action=pano"
        f"&query={urllib.parse.quote(address)}"
    )


def _hazard_url(address: str | None) -> str:
    """国交省「重ねるハザードマップ」ポータル。住所検索 UI 付き。"""
    return "https://disaportal.gsi.go.jp/"


def _format_price(price: int | None) -> str:
    if price is None:
        return "価格不明"
    if price == 0:
        return "0円（無償譲渡）"
    if price >= 10_000:
        man = price // 10_000
        rem = price % 10_000
        if rem == 0:
            return f"{man:,}万円"
        return f"{man:,}万{rem:,}円"
    return f"{price:,}円"


def _post_embed(webhook: str, row: sqlite3.Row) -> None:
    location_parts = list(filter(None, [row["prefecture"], row["city"]]))
    location = " ".join(location_parts) or "—"
    address = row["address"] or location

    # 即タップできるクイックリンク
    links = []
    if address and address != "—":
        links.append(f"[🗺️ 地図]({_maps_url(address)})")
        links.append(f"[👀 街並み]({_streetview_url(address)})")
    links.append(f"[⚠️ ハザード]({_hazard_url(address)})")
    links_line = " ｜ ".join(links)

    body_preview = (row["body"] or "").strip()
    # Discord description 上限 4096 文字、見やすさのため 250 文字程度に
    if len(body_preview) > 250:
        body_preview = body_preview[:250].rstrip() + "…"

    description_parts = [links_line]
    if body_preview:
        description_parts.append(body_preview)
    description = "\n\n".join(description_parts)

    fields = [
        {"name": "💰 価格", "value": _format_price(row["price"]), "inline": True},
        {"name": "📍 所在地", "value": location, "inline": True},
    ]
    if row["area_land"]:
        fields.append({"name": "📐 土地", "value": f"{row['area_land']:.0f}㎡", "inline": True})
    if row["area_building"]:
        fields.append({"name": "🏠 建物", "value": f"{row['area_building']:.0f}㎡", "inline": True})

    embed = {
        "title": (row["title"] or "(タイトルなし)")[:250],
        "url": row["url"],
        "color": EMBED_COLOR,
        "description": description[:4000],
        "fields": fields,
        "footer": {"text": f"source: {row['source']}"},
    }
    if row["thumbnail_url"]:
        # image (大きく表示) — スマホで判断しやすい
        embed["image"] = {"url": row["thumbnail_url"]}

    _post(webhook, {"embeds": [embed]})


def _post_digest(webhook: str, rows: list[sqlite3.Row]) -> None:
    lines = [f"**新着 {len(rows)} 件**"]
    for r in rows:
        price = _format_price(r["price"])
        loc = " ".join(filter(None, [r["prefecture"], r["city"]])) or "—"
        title = (r["title"] or "")[:50]
        addr = r["address"] or loc
        maps = _maps_url(addr) if addr and addr != "—" else None
        line = f"- **{price}** {loc} — {title} <{r['url']}>"
        if maps:
            line += f" [🗺️]({maps})"
        lines.append(line)

    # Discord は1メッセージ2000文字制限
    chunk: list[str] = []
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
