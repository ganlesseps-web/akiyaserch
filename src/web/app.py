"""FastAPI + HTMX ダッシュボード. localhost:8000 で全件閲覧・既読・お気に入り.

DASHBOARD_USERNAME / DASHBOARD_PASSWORD 環境変数が設定されていれば Basic 認証を要求。
両方未設定なら認証なし（ローカル開発時のデフォルト）。
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
    """DASHBOARD_USERNAME/PASSWORD 設定時のみ Basic 認証を要求。"""
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


def _query_rows(conn: Any, view: str, limit: int = 100) -> list[Any]:
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
def index(request: Request, view: str = "all", _=Depends(auth)) -> HTMLResponse:
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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
