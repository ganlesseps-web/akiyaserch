"""DB layer. ローカルは sqlite3、本番は Turso (libsql) を環境変数で切替。

切替ロジック:
    TURSO_DATABASE_URL が設定されていれば libsql_client を使い、なければ
    sqlite3 でローカルファイルに接続する。両方とも同じ sqlite3 風 API
    (execute / executemany / executescript / fetchall / fetchone / lastrowid)
    で扱えるよう、libsql 側は薄い wrapper でラップする。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

DEFAULT_DB_PATH = Path("data/properties.db")


def db_path() -> Path:
    return Path(os.environ.get("TRADE_DB_PATH", str(DEFAULT_DB_PATH)))


def using_libsql() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    listing_id      TEXT    NOT NULL,
    url             TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    price           INTEGER,
    prefecture      TEXT,
    city            TEXT,
    address         TEXT,
    area_land       REAL,
    area_building   REAL,
    thumbnail_url   TEXT,
    body            TEXT,
    posted_at       TEXT,
    first_seen_at   TEXT    NOT NULL,
    last_seen_at    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'active',
    UNIQUE (source, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_properties_first_seen ON properties (first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_properties_prefecture ON properties (prefecture);

CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id   INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    channel       TEXT    NOT NULL,
    sent_at       TEXT    NOT NULL,
    UNIQUE (property_id, channel)
);

CREATE TABLE IF NOT EXISTS favorites (
    property_id   INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    note          TEXT,
    starred_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS read_status (
    property_id   INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    read_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS dismissed (
    property_id   INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    dismissed_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ratings (
    property_id   INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    rating        INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    rated_at      TEXT    NOT NULL
);

-- AI スコア (preferences.yaml ベースで Claude がつけた 0-10 採点)
CREATE TABLE IF NOT EXISTS ai_scores (
    property_id        INTEGER PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    score              INTEGER NOT NULL,           -- 0-10
    reason             TEXT,                       -- ~30字の根拠
    preferences_hash   TEXT    NOT NULL,           -- 好み文字列のハッシュ。変わったら再スコア。
    model              TEXT    NOT NULL,
    scored_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_scores_score ON ai_scores (score DESC);

CREATE TABLE IF NOT EXISTS drive_cache (
    address       TEXT    PRIMARY KEY,
    origin        TEXT    NOT NULL,
    drive_seconds INTEGER,
    fetched_at    TEXT    NOT NULL
);
"""


@dataclass
class Listing:
    source: str
    listing_id: str
    url: str
    title: str
    price: int | None
    prefecture: str | None
    city: str | None
    address: str | None
    area_land: float | None
    area_building: float | None
    thumbnail_url: str | None
    body: str | None
    posted_at: str | None
    property_type: str | None = None  # house/land/apartment/commercial/unknown
    dilapidated: int = 0  # 1 = オンボロ判定済み、0 = なし
    dilapidation_reason: str | None = None  # ヒットしたキーワード/フレーズ
    settlement_offer: int = 0  # 1 = 定住条件付き譲渡 / 試住制度 / 改修費返済不要 等を検出
    settlement_offer_reason: str | None = None  # ヒットしたキーワード/フレーズ


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------- libsql wrapper (sqlite3-compatible thin layer) ---------

class _LibsqlRow:
    """sqlite3.Row 互換。`row['col']` と `row[0]` と `dict(row)` をサポート。"""
    __slots__ = ("_cols", "_vals")

    def __init__(self, cols: Sequence[str], vals: Sequence[Any]):
        self._cols = cols
        self._vals = vals

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._vals[key]
        return self._vals[self._cols.index(key)]

    def keys(self) -> list[str]:
        return list(self._cols)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._vals)


class _LibsqlCursor:
    def __init__(self, rs: Any):
        self._rs = rs
        self._cols = list(rs.columns) if rs.columns else []
        self._rows = list(rs.rows) if rs.rows else []
        self._idx = 0

    def fetchone(self) -> _LibsqlRow | None:
        if self._idx >= len(self._rows):
            return None
        r = self._rows[self._idx]
        self._idx += 1
        return _LibsqlRow(self._cols, list(r))

    def fetchall(self) -> list[_LibsqlRow]:
        out = [_LibsqlRow(self._cols, list(r)) for r in self._rows[self._idx:]]
        self._idx = len(self._rows)
        return out

    @property
    def lastrowid(self) -> int | None:
        v = getattr(self._rs, "last_insert_rowid", None)
        return int(v) if v is not None else None

    def __iter__(self) -> Iterator[_LibsqlRow]:
        return iter(self.fetchall())


class _LibsqlConn:
    """Connect to libsql/Turso via libsql_client.create_client_sync.

    Exposes the subset of sqlite3.Connection API we actually use.
    """
    def __init__(self, url: str, auth_token: str | None):
        import libsql_client  # local import to avoid hard dep at module load
        self._client = libsql_client.create_client_sync(url=url, auth_token=auth_token)
        self.row_factory = None  # ignored; rows are always _LibsqlRow

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _LibsqlCursor:
        rs = self._client.execute(sql, list(params) if params else None)
        return _LibsqlCursor(rs)

    def executemany(self, sql: str, params_list: Sequence[Sequence[Any]]) -> None:
        for p in params_list:
            self._client.execute(sql, list(p))

    def executescript(self, script: str) -> None:
        for stmt in _split_sql(script):
            self._client.execute(stmt)

    def commit(self) -> None:
        # libsql_client.execute auto-commits each statement.
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self._client.close()


def _split_sql(script: str) -> Iterator[str]:
    """SCHEMA を ; で分割。各文の中の `-- コメント` 行は除去。
    文字列リテラル中の ; / -- は今回のスキーマでは使わないので素朴に処理。"""
    for stmt in script.split(";"):
        # コメント行を除去 (-- ...\n)
        lines = [ln for ln in stmt.splitlines() if not ln.strip().startswith("--")]
        s = "\n".join(lines).strip()
        if s:
            yield s


@contextmanager
def connect(path: Path | None = None) -> Iterator[Any]:
    """sqlite3.Connection または _LibsqlConn を yield する。

    どちらも sqlite3.Row 互換のオブジェクトを返す。
    """
    if using_libsql():
        conn = _LibsqlConn(
            url=os.environ["TURSO_DATABASE_URL"],
            auth_token=os.environ.get("TURSO_AUTH_TOKEN"),
        )
        try:
            yield conn
        finally:
            conn.close()
        return

    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    sqlite_conn = sqlite3.connect(p)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_conn.execute("PRAGMA journal_mode = WAL")
    sqlite_conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield sqlite_conn
        sqlite_conn.commit()
    except Exception:
        sqlite_conn.rollback()
        raise
    finally:
        sqlite_conn.close()


def init_db(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _run_migrations(conn)


# 新規追加カラムは ALTER TABLE で。idempotent (重複カラムエラーは無視)。
MIGRATIONS = [
    "ALTER TABLE properties ADD COLUMN property_type TEXT",
    "ALTER TABLE properties ADD COLUMN dilapidated INTEGER DEFAULT 0",
    "ALTER TABLE properties ADD COLUMN dilapidation_reason TEXT",
    "ALTER TABLE properties ADD COLUMN settlement_offer INTEGER DEFAULT 0",
    "ALTER TABLE properties ADD COLUMN settlement_offer_reason TEXT",
]


def _run_migrations(conn: Any) -> None:
    import logging
    log = logging.getLogger(__name__)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except Exception as e:
            err = str(e).lower()
            # SQLite: "duplicate column name", libsql: 似たメッセージ
            if "duplicate column" in err or "already exists" in err:
                continue
            log.warning("migration skip: %s (%s)", sql, e)


# --------- domain operations (work with both backends) ---------

def upsert_listing(conn: Any, listing: Listing) -> tuple[int, bool]:
    """Insert or update. Returns (property_id, is_new)."""
    row = conn.execute(
        "SELECT id FROM properties WHERE source = ? AND listing_id = ?",
        (listing.source, listing.listing_id),
    ).fetchone()
    now = now_iso()
    if row is None:
        cur = conn.execute(
            """
            INSERT INTO properties (
                source, listing_id, url, title, price, prefecture, city, address,
                area_land, area_building, thumbnail_url, body, posted_at,
                property_type, dilapidated, dilapidation_reason,
                settlement_offer, settlement_offer_reason,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.source, listing.listing_id, listing.url, listing.title,
                listing.price, listing.prefecture, listing.city, listing.address,
                listing.area_land, listing.area_building, listing.thumbnail_url,
                listing.body, listing.posted_at, listing.property_type,
                listing.dilapidated, listing.dilapidation_reason,
                listing.settlement_offer, listing.settlement_offer_reason,
                now, now,
            ),
        )
        return cur.lastrowid, True
    conn.execute(
        """
        UPDATE properties SET
            url = ?, title = ?, price = ?, prefecture = ?, city = ?, address = ?,
            area_land = ?, area_building = ?, thumbnail_url = ?, body = ?,
            posted_at = ?, property_type = ?,
            dilapidated = ?, dilapidation_reason = ?,
            settlement_offer = ?, settlement_offer_reason = ?,
            last_seen_at = ?
        WHERE id = ?
        """,
        (
            listing.url, listing.title, listing.price, listing.prefecture, listing.city,
            listing.address, listing.area_land, listing.area_building, listing.thumbnail_url,
            listing.body, listing.posted_at, listing.property_type,
            listing.dilapidated, listing.dilapidation_reason,
            listing.settlement_offer, listing.settlement_offer_reason,
            now, row["id"],
        ),
    )
    return row["id"], False


def unnotified_pass(conn: Any, channel: str) -> list[Any]:
    return conn.execute(
        """
        SELECT p.*,
               s.score AS ai_score,
               s.reason AS ai_reason
        FROM properties p
        LEFT JOIN notifications n
            ON n.property_id = p.id AND n.channel = ?
        LEFT JOIN ai_scores s
            ON s.property_id = p.id
        WHERE n.id IS NULL
          AND p.status = 'active'
        ORDER BY p.first_seen_at ASC
        """,
        (channel,),
    ).fetchall()


def mark_notified(conn: Any, property_ids: list[int], channel: str) -> None:
    now = now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO notifications (property_id, channel, sent_at) VALUES (?, ?, ?)",
        [(pid, channel, now) for pid in property_ids],
    )


MISS = object()


def cached_drive_seconds(conn: Any, address: str, origin: str) -> int | None | object:
    row = conn.execute(
        "SELECT drive_seconds FROM drive_cache WHERE address = ? AND origin = ?",
        (address, origin),
    ).fetchone()
    if row is None:
        return MISS
    return row["drive_seconds"]


def cache_drive(conn: Any, address: str, origin: str, drive_seconds: int | None) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO drive_cache (address, origin, drive_seconds, fetched_at)
        VALUES (?, ?, ?, ?)
        """,
        (address, origin, drive_seconds, now_iso()),
    )
