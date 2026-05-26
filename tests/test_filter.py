"""filter の単体テスト。in-memory SQLite で動作確認。"""
import sqlite3

import pytest

from src import db, filter as flt


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    yield c
    c.close()


@pytest.fixture
def cfg():
    return flt.FilterConfig(
        price_max=3_000_000,
        prefectures={"大阪府", "兵庫県", "京都府"},
        borderline_prefectures={"岡山県"},
        drive_origin="大阪駅",
        drive_max_seconds=7200,
        ng_keywords=["事故物件"],
    )


def _insert(conn, **overrides):
    fields = dict(
        source="test", listing_id="1", url="https://x", title="物件",
        price=0, prefecture="大阪府", city=None, address="大阪府大阪市",
        area_land=None, area_building=None, thumbnail_url=None, body="",
        posted_at=None, first_seen_at=db.now_iso(), last_seen_at=db.now_iso(),
    )
    fields.update(overrides)
    cols = ",".join(fields.keys())
    qs = ",".join("?" * len(fields))
    conn.execute(f"INSERT INTO properties ({cols}) VALUES ({qs})", tuple(fields.values()))
    return conn.execute("SELECT * FROM properties WHERE id = last_insert_rowid()").fetchone()


def test_passes_basic(conn, cfg):
    row = _insert(conn)
    ok, _ = flt.passes(conn, row, cfg)
    assert ok


def test_price_over_max_blocks(conn, cfg):
    row = _insert(conn, price=5_000_000)
    ok, reason = flt.passes(conn, row, cfg)
    assert not ok and "price" in reason


def test_prefecture_not_in_allowlist(conn, cfg):
    row = _insert(conn, prefecture="北海道", address="北海道札幌市")
    ok, reason = flt.passes(conn, row, cfg)
    assert not ok and "allowlist" in reason


def test_ng_keyword_in_body_blocks(conn, cfg):
    row = _insert(conn, body="この物件は事故物件です")
    ok, reason = flt.passes(conn, row, cfg)
    assert not ok and "NG" in reason


def test_prefecture_unknown_blocks(conn, cfg):
    row = _insert(conn, prefecture=None)
    ok, reason = flt.passes(conn, row, cfg)
    assert not ok and "unknown" in reason
