"""Discord Webhook 通知。"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
import urllib.parse
from typing import Any

import httpx

from . import db, filter as flt

logger = logging.getLogger(__name__)

CHANNEL = "discord"
EMBED_COLOR = 0x2ECC71  # green
PRICE_DROP_COLOR = 0xE67E22  # orange — 値下げは目立たせる
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


def notify_price_drops(
    conn: sqlite3.Connection,
    cfg: flt.FilterConfig,
    *,
    dry_run: bool = False,
    use_distance_matrix: bool = False,
) -> dict[str, int]:
    """未通知の値下げ (price_drops) を Discord に通知する。

    新着通知 (notify) と同じ filter を通し、対象府県・価格帯・住める物件のみ
    値下げアラートを送る。送信済みは price_drops.notified_at で管理 (二重送信なし)。
    """
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook and not dry_run:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")

    rows = db.unnotified_price_drops(conn)
    passed: list[Any] = []
    for row in rows:
        ok, reason = flt.passes(conn, row, cfg, use_distance_matrix=use_distance_matrix)
        if ok:
            passed.append(row)
        else:
            logger.debug("skip price drop %s: %s", row["url"], reason)

    if not passed:
        return {"scanned": len(rows), "passed": 0, "sent": 0}

    if dry_run:
        for row in passed:
            print(
                f"[dry-run][値下げ] {_format_price(row['drop_old_price'])} → "
                f"{_format_price(row['drop_new_price'])} {row['title']} {row['url']}"
            )
        return {"scanned": len(rows), "passed": len(passed), "sent": 0}

    for row in passed:
        _post_price_drop_embed(webhook, row)
        time.sleep(1.0)  # rate limit politeness

    db.mark_price_drops_notified(conn, [r["drop_id"] for r in passed])
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


def _subsidy_url(prefecture: str | None, city: str | None) -> str | None:
    """その市区町村の空き家リフォーム補助金を Google で検索するリンク。"""
    parts = [p for p in (prefecture, city) if p]
    if not parts:
        return None
    q = " ".join(parts) + " 空き家 補助金 リフォーム"
    return f"https://www.google.com/search?q={urllib.parse.quote(q)}"


def _safe_get(row: Any, key: str, default: Any = None) -> Any:
    """sqlite3.Row / _LibsqlRow どちらでも安全に取得 (キー欠如時 default)。"""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


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
    sub = _subsidy_url(row["prefecture"], row["city"])
    if sub:
        links.append(f"[💰 補助金]({sub})")
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
    # 定住条件付き譲渡 / 試住制度 などのバッジ表示
    settlement_offer = _safe_get(row, "settlement_offer") or 0
    if settlement_offer:
        reason = _safe_get(row, "settlement_offer_reason") or "条件付譲渡の可能性"
        fields.append({
            "name": "🎯 もらえる/譲渡条件あり",
            "value": f"検出語: **{reason}** — 詳細ページで条件を要確認",
            "inline": False,
        })

    # AI スコア (LEFT JOIN ai_scores が無い場合は None)
    ai_score = _safe_get(row, "ai_score")
    if ai_score is not None:
        reason = _safe_get(row, "ai_reason") or ""
        emoji = "🌟" if ai_score >= 8 else "✨" if ai_score >= 6 else "🤔"
        fields.append({
            "name": f"{emoji} AIスコア",
            "value": f"**{ai_score}/10** {reason}",
            "inline": False,
        })

    title_text = (row["title"] or "(タイトルなし)")[:240]
    if settlement_offer:
        title_text = f"🎯 {title_text}"
    embed = {
        "title": title_text[:250],
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


def _post_price_drop_embed(webhook: str, row: Any) -> None:
    """値下げ専用の embed。旧価格→新価格と下げ幅を目立たせる。"""
    location = " ".join(filter(None, [row["prefecture"], row["city"]])) or "—"
    address = row["address"] or location

    old_p = row["drop_old_price"]
    new_p = row["drop_new_price"]
    delta = old_p - new_p
    pct = round(delta / old_p * 100) if old_p else 0
    drop_line = (
        f"~~{_format_price(old_p)}~~ → **{_format_price(new_p)}**"
        f"（−{_format_price(delta)}{f' / {pct}%↓' if pct else ''}）"
    )

    links = []
    if address and address != "—":
        links.append(f"[🗺️ 地図]({_maps_url(address)})")
        links.append(f"[👀 街並み]({_streetview_url(address)})")
    links.append(f"[⚠️ ハザード]({_hazard_url(address)})")
    sub = _subsidy_url(row["prefecture"], row["city"])
    if sub:
        links.append(f"[💰 補助金]({sub})")

    description = f"**🔻 値下げ**\n{drop_line}\n\n" + " ｜ ".join(links)

    fields = [
        {"name": "📍 所在地", "value": location, "inline": True},
    ]
    if _safe_get(row, "area_land"):
        fields.append({"name": "📐 土地", "value": f"{row['area_land']:.0f}㎡", "inline": True})

    title_text = ("🔻 " + (row["title"] or "(タイトルなし)"))[:250]
    embed = {
        "title": title_text,
        "url": row["url"],
        "color": PRICE_DROP_COLOR,
        "description": description[:4000],
        "fields": fields,
        "footer": {"text": f"source: {row['source']}｜値下げ通知"},
    }
    if _safe_get(row, "thumbnail_url"):
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
