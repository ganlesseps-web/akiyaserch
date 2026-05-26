"""FastAPI + HTMX ダッシュボード. localhost:8000 で全件閲覧・既読・お気に入り."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import db

app = FastAPI(title="trade dashboard")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _query_rows(
    conn: sqlite3.Connection, view: str, limit: int = 100
) -> list[sqlite3.Row]:
    base = """
        SELECT p.*,
            (SELECT 1 FROM favorites WHERE property_id = p.id) AS is_fav,
            (SELECT 1 FROM read_status WHERE property_id = p.id) AS is_read,
            (SELECT 1 FROM notifications WHERE property_id = p.id) AS was_notified
        FROM properties p
        WHERE p.status = 'active'
    """
    if view == "unread":
        sql = base + " AND NOT EXISTS (SELECT 1 FROM read_status WHERE property_id = p.id)"
    elif view == "favorites":
        sql = base + " AND EXISTS (SELECT 1 FROM favorites WHERE property_id = p.id)"
    elif view == "notified":
        sql = base + " AND EXISTS (SELECT 1 FROM notifications WHERE property_id = p.id)"
    else:
        sql = base
    sql += " ORDER BY p.first_seen_at DESC LIMIT ?"
    return conn.execute(sql, (limit,)).fetchall()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, view: str = "all") -> HTMLResponse:
    with db.connect() as conn:
        rows = _query_rows(conn, view)
        counts = {
            "all": conn.execute("SELECT COUNT(*) FROM properties WHERE status='active'").fetchone()[0],
            "unread": conn.execute(
                "SELECT COUNT(*) FROM properties p WHERE p.status='active' "
                "AND NOT EXISTS (SELECT 1 FROM read_status WHERE property_id = p.id)"
            ).fetchone()[0],
            "favorites": conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
            "notified": conn.execute("SELECT COUNT(DISTINCT property_id) FROM notifications").fetchone()[0],
        }
    return TEMPLATES.TemplateResponse(
        request, "index.html",
        {"rows": rows, "view": view, "counts": counts},
    )


@app.post("/property/{pid}/read", response_class=HTMLResponse)
def toggle_read(pid: int) -> HTMLResponse:
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
def toggle_favorite(pid: int) -> HTMLResponse:
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
