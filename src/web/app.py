"""FastAPI + HTMX ダッシュボード.

DASHBOARD_USERNAME / DASHBOARD_PASSWORD 環境変数が設定されていれば Basic 認証を要求。
両方未設定なら認証なし（ローカル開発時のデフォルト）。

View / Sort / Search:
- view = all / unread / favorites / notified / dismissed / rated
- sort = new (default) / price_asc / price_desc / area_desc
- q   = 部分一致検索 (title + address)
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .. import db

app = FastAPI(title="trade dashboard")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_security = HTTPBasic(auto_error=False)


def auth(credentials: HTTPBasicCredentials | None = Depends(_security)) -> None:
    expected_user = os.environ.get("DASHBOARD_USERNAME")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD")
    if not expected_user or not expected_pass:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Basic auth required",
            headers={"WWW-Authenticate": "Basic"},
        )
    ok_user = secrets.compare_digest(credentials.username, expected_user)
    ok_pass = secrets.compare_digest(credentials.password, expected_pass)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


SORT_OPTIONS = {
    "new": "p.first_seen_at DESC",
    "price_asc": "(p.price IS NULL) ASC, p.price ASC, p.first_seen_at DESC",
    "price_desc": "(p.price IS NULL) ASC, p.price DESC, p.first_seen_at DESC",
    "area_desc": "(p.area_land IS NULL) ASC, p.area_land DESC, p.first_seen_at DESC",
    "score_desc": (
        "(SELECT score FROM ai_scores WHERE property_id = p.id) IS NULL ASC, "
        "(SELECT score FROM ai_scores WHERE property_id = p.id) DESC, "
        "p.first_seen_at DESC"
    ),
}


def _query_rows(
    conn: Any,
    view: str,
    sort: str,
    q: str | None,
    pref: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    limit: int = 200,
) -> list[Any]:
    base = """
        SELECT p.*,
            (SELECT 1 FROM favorites WHERE property_id = p.id) AS is_fav,
            (SELECT 1 FROM read_status WHERE property_id = p.id) AS is_read,
            (SELECT 1 FROM dismissed WHERE property_id = p.id) AS is_dismissed,
            (SELECT 1 FROM notifications WHERE property_id = p.id) AS was_notified,
            (SELECT rating FROM ratings WHERE property_id = p.id) AS rating,
            (SELECT score FROM ai_scores WHERE property_id = p.id) AS ai_score,
            (SELECT reason FROM ai_scores WHERE property_id = p.id) AS ai_reason
        FROM properties p
        WHERE p.status = 'active'
    """
    params: list[Any] = []

    # property_type ビュー (house/land/apartment/all)
    if view in ("house", "land", "apartment", "commercial"):
        base += " AND p.property_type = ?"
        params.append(view)

    # view フィルタ — dismissed は dismissed ビュー以外では基本除外
    if view == "unread":
        base += (
            " AND NOT EXISTS (SELECT 1 FROM read_status WHERE property_id = p.id)"
            " AND NOT EXISTS (SELECT 1 FROM dismissed WHERE property_id = p.id)"
        )
    elif view == "favorites":
        base += " AND EXISTS (SELECT 1 FROM favorites WHERE property_id = p.id)"
    elif view == "notified":
        base += " AND EXISTS (SELECT 1 FROM notifications WHERE property_id = p.id)"
    elif view == "dismissed":
        base += " AND EXISTS (SELECT 1 FROM dismissed WHERE property_id = p.id)"
    elif view == "rated":
        base += " AND EXISTS (SELECT 1 FROM ratings WHERE property_id = p.id)"
    else:  # all
        base += " AND NOT EXISTS (SELECT 1 FROM dismissed WHERE property_id = p.id)"

    if q:
        base += " AND (p.title LIKE ? OR p.address LIKE ? OR p.city LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])

    # 都道府県フィルタ (完全一致)
    if pref:
        base += " AND p.prefecture = ?"
        params.append(pref)

    # 価格フィルタ。price が NULL (価格不明) の物件は範囲指定時に自動的に外れる
    # (SQLite では NULL >= x / NULL <= x はいずれも偽になるため)。
    if price_min is not None:
        base += " AND p.price >= ?"
        params.append(price_min)
    if price_max is not None:
        base += " AND p.price <= ?"
        params.append(price_max)

    sort_sql = SORT_OPTIONS.get(sort, SORT_OPTIONS["new"])
    base += f" ORDER BY {sort_sql} LIMIT ?"
    params.append(limit)
    return conn.execute(base, params).fetchall()


def _counts(conn: Any) -> dict[str, int]:
    return {
        "all": conn.execute(
            "SELECT COUNT(*) FROM properties p WHERE p.status='active'"
            " AND NOT EXISTS (SELECT 1 FROM dismissed WHERE property_id = p.id)"
        ).fetchone()[0],
        "unread": conn.execute(
            "SELECT COUNT(*) FROM properties p WHERE p.status='active'"
            " AND NOT EXISTS (SELECT 1 FROM read_status WHERE property_id = p.id)"
            " AND NOT EXISTS (SELECT 1 FROM dismissed WHERE property_id = p.id)"
        ).fetchone()[0],
        "favorites": conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
        "notified": conn.execute(
            "SELECT COUNT(DISTINCT property_id) FROM notifications"
        ).fetchone()[0],
        "rated": conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0],
        "dismissed": conn.execute("SELECT COUNT(*) FROM dismissed").fetchone()[0],
        "house": conn.execute(
            "SELECT COUNT(*) FROM properties WHERE property_type = 'house' AND status='active'"
        ).fetchone()[0],
        "land": conn.execute(
            "SELECT COUNT(*) FROM properties WHERE property_type = 'land' AND status='active'"
        ).fetchone()[0],
        "apartment": conn.execute(
            "SELECT COUNT(*) FROM properties WHERE property_type = 'apartment' AND status='active'"
        ).fetchone()[0],
    }


def _prefectures(conn: Any) -> list[tuple[str, int]]:
    """アクティブ (未却下) 物件に存在する都道府県を、件数の多い順に返す。

    プルダウンの選択肢用。実際にデータがある県だけを出す。
    """
    rows = conn.execute(
        "SELECT prefecture, COUNT(*) AS cnt FROM properties p"
        " WHERE p.status = 'active'"
        "   AND p.prefecture IS NOT NULL AND p.prefecture != ''"
        "   AND NOT EXISTS (SELECT 1 FROM dismissed WHERE property_id = p.id)"
        " GROUP BY prefecture ORDER BY cnt DESC, prefecture"
    ).fetchall()
    return [(r["prefecture"], r["cnt"]) for r in rows]


def _man_to_yen(val: str | None) -> int | None:
    """「万円」単位の入力文字列を円に変換する。

    空欄・非数値・負数は None を返す (= フィルタを掛けない)。
    例: "100" -> 1_000_000、"" -> None、"abc" -> None。
    """
    if not val:
        return None
    try:
        man = float(val)
    except (TypeError, ValueError):
        return None
    if man < 0:
        return None
    return int(man * 10_000)


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    view: str = "all",
    sort: str = "new",
    q: str | None = None,
    pref: str | None = None,
    price_min: str | None = None,
    price_max: str | None = None,
    _=Depends(auth),
) -> HTMLResponse:
    with db.connect() as conn:
        rows = _query_rows(
            conn, view, sort, q,
            pref=pref or None,
            price_min=_man_to_yen(price_min),
            price_max=_man_to_yen(price_max),
        )
        counts = _counts(conn)
        prefectures = _prefectures(conn)
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "rows": rows, "view": view, "sort": sort, "q": q or "",
            "pref": pref or "",
            "price_min": price_min or "", "price_max": price_max or "",
            "prefectures": prefectures,
            "counts": counts,
            "sort_options": [
                ("new", "新着順"),
                ("price_asc", "安い順"),
                ("price_desc", "高い順"),
                ("area_desc", "広い順"),
                ("score_desc", "AIスコア高い順"),
            ],
        },
    )


@app.post("/property/{pid}/read", response_class=HTMLResponse)
def toggle_read(pid: int, _=Depends(auth)) -> HTMLResponse:
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM read_status WHERE property_id = ?", (pid,)).fetchone()
        if row:
            conn.execute("DELETE FROM read_status WHERE property_id = ?", (pid,))
            return HTMLResponse("未読")
        conn.execute(
            "INSERT INTO read_status (property_id, read_at) VALUES (?, ?)",
            (pid, db.now_iso()),
        )
        return HTMLResponse("既読")


@app.post("/property/{pid}/favorite", response_class=HTMLResponse)
def toggle_favorite(pid: int, _=Depends(auth)) -> HTMLResponse:
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM favorites WHERE property_id = ?", (pid,)).fetchone()
        if row:
            conn.execute("DELETE FROM favorites WHERE property_id = ?", (pid,))
            return HTMLResponse("☆")
        conn.execute(
            "INSERT INTO favorites (property_id, note, starred_at) VALUES (?, ?, ?)",
            (pid, "", db.now_iso()),
        )
        return HTMLResponse("★")


@app.post("/property/{pid}/dismiss", response_class=HTMLResponse)
def toggle_dismiss(pid: int, _=Depends(auth)) -> HTMLResponse:
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM dismissed WHERE property_id = ?", (pid,)).fetchone()
        if row:
            conn.execute("DELETE FROM dismissed WHERE property_id = ?", (pid,))
            return HTMLResponse("✕")
        conn.execute(
            "INSERT INTO dismissed (property_id, dismissed_at) VALUES (?, ?)",
            (pid, db.now_iso()),
        )
        return HTMLResponse("却下")


@app.post("/property/{pid}/rate/{rating}", response_class=HTMLResponse)
def set_rating(pid: int, rating: int, _=Depends(auth)) -> HTMLResponse:
    if rating < 0 or rating > 5:
        raise HTTPException(400, "rating 0..5")
    with db.connect() as conn:
        current = conn.execute(
            "SELECT rating FROM ratings WHERE property_id = ?", (pid,)
        ).fetchone()
        # 同じ星をもう一度押したらクリア (トグル)
        if current and current["rating"] == rating:
            conn.execute("DELETE FROM ratings WHERE property_id = ?", (pid,))
            new_rating = 0
        elif rating == 0:
            conn.execute("DELETE FROM ratings WHERE property_id = ?", (pid,))
            new_rating = 0
        else:
            conn.execute(
                "INSERT OR REPLACE INTO ratings (property_id, rating, rated_at) VALUES (?, ?, ?)",
                (pid, rating, db.now_iso()),
            )
            new_rating = rating
    return HTMLResponse(_render_stars(pid, new_rating))


def _render_stars(pid: int, rating: int) -> str:
    parts = []
    for n in range(1, 6):
        ch = "★" if n <= rating else "☆"
        parts.append(
            f'<button class="star" hx-post="/property/{pid}/rate/{n}" '
            f'hx-target="closest .stars" hx-swap="outerHTML">{ch}</button>'
        )
    return f'<span class="stars" data-pid="{pid}">{"".join(parts)}</span>'


# expose to templates
TEMPLATES.env.globals["render_stars"] = _render_stars


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
