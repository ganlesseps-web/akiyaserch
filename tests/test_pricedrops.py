"""値下げ検知 (price_drops) の単体テスト。in-memory SQLite。"""
import sqlite3

import pytest

from src import db


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _listing(price, listing_id="1", **overrides):
    base = dict(
        source="test", listing_id=listing_id, url="https://x", title="物件",
        price=price, prefecture="大阪府", city="大阪市", address="大阪府大阪市",
        area_land=None, area_building=None, thumbnail_url=None, body="",
        posted_at=None,
    )
    base.update(overrides)
    return db.Listing(**base)


def _drops(conn):
    return conn.execute("SELECT * FROM price_drops ORDER BY id").fetchall()


def test_price_drop_recorded_on_decrease(conn):
    pid, is_new = db.upsert_listing(conn, _listing(3_000_000))
    assert is_new
    assert _drops(conn) == []  # 初回は履歴なし

    db.upsert_listing(conn, _listing(2_800_000))  # 値下げ
    rows = _drops(conn)
    assert len(rows) == 1
    assert rows[0]["property_id"] == pid
    assert rows[0]["old_price"] == 3_000_000
    assert rows[0]["new_price"] == 2_800_000
    assert rows[0]["notified_at"] is None


def test_no_drop_on_increase(conn):
    db.upsert_listing(conn, _listing(2_000_000))
    db.upsert_listing(conn, _listing(2_500_000))  # 値上げ
    assert _drops(conn) == []


def test_no_drop_on_same_price(conn):
    db.upsert_listing(conn, _listing(2_000_000))
    db.upsert_listing(conn, _listing(2_000_000))
    assert _drops(conn) == []


def test_no_drop_when_old_price_unknown(conn):
    db.upsert_listing(conn, _listing(None))       # 価格不明で登録
    db.upsert_listing(conn, _listing(1_500_000))  # 価格が判明 (値下げではない)
    assert _drops(conn) == []


def test_multiple_drops_accumulate(conn):
    db.upsert_listing(conn, _listing(3_000_000))
    db.upsert_listing(conn, _listing(2_500_000))
    db.upsert_listing(conn, _listing(2_000_000))
    rows = _drops(conn)
    assert len(rows) == 2
    assert [r["new_price"] for r in rows] == [2_500_000, 2_000_000]


def test_unnotified_and_mark(conn):
    pid, _ = db.upsert_listing(conn, _listing(3_000_000))
    db.upsert_listing(conn, _listing(2_800_000))

    pending = db.unnotified_price_drops(conn)
    assert len(pending) == 1
    r = pending[0]
    assert r["drop_old_price"] == 3_000_000
    assert r["drop_new_price"] == 2_800_000
    assert r["title"] == "物件"          # 物件情報が join されている
    assert r["price"] == 2_800_000        # properties.price は更新後

    db.mark_price_drops_notified(conn, [r["drop_id"]])
    assert db.unnotified_price_drops(conn) == []


def test_unnotified_skips_inactive(conn):
    pid, _ = db.upsert_listing(conn, _listing(3_000_000))
    db.upsert_listing(conn, _listing(2_800_000))
    conn.execute("UPDATE properties SET status = 'inactive' WHERE id = ?", (pid,))
    assert db.unnotified_price_drops(conn) == []
