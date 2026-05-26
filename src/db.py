"""SQLite layer. Single file, WAL mode for safe concurrent read/write."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path("data/properties.db")


def db_path() -> Path:
    return Path(os.environ.get("TRADE_DB_PATH", str(DEFAULT_DB_PATH)))


SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    listing_id      TEXT    NOT NULL,
    url             TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    price           INTEGER,            -- yen, NULL if unknown
    prefecture      TEXT,
    city            TEXT,
    address         TEXT,
    area_land       REAL,               -- m^2
    area_building   REAL,               -- m^2
    thumbnail_url   TEXT,
    body            TEXT,               -- full text snippet for NG word match
    posted_at       TEXT,               -- ISO8601, source publication time
    first_seen_at   TEXT    NOT NULL,   -- ISO8601, when we first fetched it
    last_seen_at    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'active',  -- active / closed / removed
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

-- Distance Matrix results cache: address -> drive seconds from origin
CREATE TABLE IF NOT EXISTS drive_cache (
    address       TEXT    PRIMARY KEY,
    origin        TEXT    NOT NULL,
    drive_seconds INTEGER,            -- NULL if API returned no route
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
    posted_at: str | None  # ISO8601


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def upsert_listing(conn: sqlite3.Connection, listing: Listing) -> tuple[int, bool]:
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
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.source, listing.listing_id, listing.url, listing.title,
                listing.price, listing.prefecture, listing.city, listing.address,
                listing.area_land, listing.area_building, listing.thumbnail_url,
                listing.body, listing.posted_at, now, now,
            ),
        )
        return cur.lastrowid, True
    conn.execute(
        """
        UPDATE properties SET
            url = ?, title = ?, price = ?, prefecture = ?, city = ?, address = ?,
            area_land = ?, area_building = ?, thumbnail_url = ?, body = ?,
            posted_at = ?, last_seen_at = ?
        WHERE id = ?
        """,
        (
            listing.url, listing.title, listing.price, listing.prefecture, listing.city,
            listing.address, listing.area_land, listing.area_building, listing.thumbnail_url,
            listing.body, listing.posted_at, now, row["id"],
        ),
    )
    return row["id"], False


def unnotified_pass(conn: sqlite3.Connection, channel: str) -> list[sqlite3.Row]:
    """Properties not yet notified on this channel. Filtering happens in src.filter."""
    return conn.execute(
        """
        SELECT p.* FROM properties p
        LEFT JOIN notifications n
            ON n.property_id = p.id AND n.channel = ?
        WHERE n.id IS NULL
          AND p.status = 'active'
        ORDER BY p.first_seen_at ASC
        """,
        (channel,),
    ).fetchall()


def mark_notified(conn: sqlite3.Connection, property_ids: list[int], channel: str) -> None:
    now = now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO notifications (property_id, channel, sent_at) VALUES (?, ?, ?)",
        [(pid, channel, now) for pid in property_ids],
    )


def cached_drive_seconds(
    conn: sqlite3.Connection, address: str, origin: str
) -> int | None | object:
    """Returns drive seconds, None (no route), or a sentinel `MISS` if uncached."""
    row = conn.execute(
        "SELECT drive_seconds FROM drive_cache WHERE address = ? AND origin = ?",
        (address, origin),
    ).fetchone()
    if row is None:
        return MISS
    return row["drive_seconds"]


def cache_drive(
    conn: sqlite3.Connection, address: str, origin: str, drive_seconds: int | None
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO drive_cache (address, origin, drive_seconds, fetched_at)
        VALUES (?, ?, ?, ?)
        """,
        (address, origin, drive_seconds, now_iso()),
    )


MISS = object()  # sentinel returned by cached_drive_seconds when uncached
