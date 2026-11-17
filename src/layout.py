"""間取り (2026-11-17 ユーザー「間取りは3LDK以上で。寝室・仕事部屋が2つ欲しい」
「空き家も3LDK以上の間取りのみにして。2LDK以下は不要です」).

- 物件の文章 (題名・本文) か詳細ページから「4DK」「3LDK」「2SLDK」などを読み、部屋数を数える
- 部屋数は数字の部分だけ (S=納戸 は数えない)。3K・3DK・3LDK 以上を「足りる」とする
- 2部屋以下と分かった家は一覧・通知に出さない (消しはしない)。分からない家は「間取り 未確認」で出す
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

MIN_ROOMS = 3

_RE = re.compile(r"(?<![\d.,])(\d{1,2})\s*(?:S\s*)?(LDK|DK|LK|K)(?:\s*\+\s*S)?(?![A-Za-z])")
_NEAR = re.compile(r"間取")
_ONE_ROOM = re.compile(r"ワンルーム|(?<![\d.,A-Za-z])1R(?![A-Za-z])")


def parse(text: str | None) -> tuple[str, int] | None:
    """文章から (間取りの表記, 部屋数) を返す。見つからなければ None。

    「間取り」の語のすぐ後ろにあるものを優先し、無ければ最初に出てくるものを使う。
    """
    if not text:
        return None
    t = unicodedata.normalize("NFKC", text)
    best = None
    for m in _RE.finditer(t):
        rooms = int(m.group(1))
        if not 1 <= rooms <= 30:
            continue
        label = m.group(0).replace(" ", "")
        before = t[max(0, m.start() - 12):m.start()]
        if _NEAR.search(before):
            return label, rooms
        if best is None:
            best = (label, rooms)
    if best is None and _ONE_ROOM.search(t):
        return "1R", 1
    return best


def enough(rooms: int | None) -> bool:
    """部屋数が足りるか (分からなければ True = 一覧に残す)。"""
    return rooms is None or rooms >= MIN_ROOMS


# 一覧・件数から外す条件 (2部屋以下と分かっている家)
EXCLUSION_SQL = f" AND (p.layout_rooms IS NULL OR p.layout_rooms >= {MIN_ROOMS})"

# ダッシュボードの「間取り」しぼり込み
LAY_FILTERS = {
    "known": f" AND p.layout_rooms >= {MIN_ROOMS}",   # 3部屋以上と分かっている家だけ
    "unknown": " AND p.layout_rooms IS NULL",          # 間取りが未確認の家
}


def fill_from_text(conn: Any, property_id: int, title: str | None, body: str | None) -> None:
    """題名・本文から読めたら保存する (まだ間取りが入っていない物件だけ)。"""
    got = parse(f"{title or ''} {body or ''}")
    if got:
        conn.execute(
            "UPDATE properties SET layout = ?, layout_rooms = ? WHERE id = ? AND layout IS NULL",
            (got[0], got[1], property_id),
        )


def badge(row: Any) -> str | None:
    """カードに出す短い表示。"""
    try:
        label, rooms = row["layout"], row["layout_rooms"]
    except (KeyError, IndexError, ValueError):
        return None
    if rooms is None:
        return "間取り 未確認"
    return f"間取り {label}"


def check_missing(conn: Any, *, limit: int = 300, sources: set[str] | None = None,
                  exclude: set[str] | None = None) -> dict[str, int]:
    """間取りがまだ分からない物件の詳細ページを1回だけ見に行く。

    開けなかった物件は次の回にもう一度見る。開けたのに書いていない物件は「未確認」のまま
    (layout_checked_at を入れて二度は見に行かない)。
    """
    import time

    import httpx
    import urllib3

    from . import db
    from .enrich import INTER_REQUEST_SECONDS, _client
    from .utilities import page_text
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 先に文章だけで読めるものを埋める (取り込み前からある物件のため)
    for r in conn.execute(
        "SELECT id, title, body FROM properties WHERE layout IS NULL AND layout_checked_at IS NULL"
    ).fetchall():
        fill_from_text(conn, r["id"], r["title"], r["body"])

    sql = ("SELECT p.id, p.url FROM properties p WHERE p.status = 'active'"
           " AND p.layout IS NULL AND p.layout_checked_at IS NULL")
    params: list = []
    if sources:
        sql += f" AND p.source IN ({', '.join('?' * len(sources))})"
        params += sorted(sources)
    if exclude:
        sql += f" AND p.source NOT IN ({', '.join('?' * len(exclude))})"
        params += sorted(exclude)
    sql += " ORDER BY p.first_seen_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    stats = {"target": len(rows), "found": 0, "unknown": 0, "failed": 0}
    with _client() as client:
        for i, r in enumerate(rows):
            if i:
                time.sleep(INTER_REQUEST_SECONDS)
            try:
                resp = client.get(r["url"])
            except httpx.HTTPError:
                stats["failed"] += 1
                continue
            if resp.status_code != 200:
                stats["failed"] += 1
                continue
            got = parse(page_text(resp.content))
            conn.execute(
                "UPDATE properties SET layout = ?, layout_rooms = ?, layout_checked_at = ?"
                " WHERE id = ?",
                (got[0] if got else None, got[1] if got else None, db.now_iso(), r["id"]),
            )
            stats["found" if got else "unknown"] += 1
    return stats
