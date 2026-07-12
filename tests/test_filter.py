"""filter の単体テスト。in-memory SQLite で動作確認。"""
import sqlite3

import pytest

from src import db, filter as flt


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)  # dilapidated / needs_repair 等の追加列を反映
    yield c
    c.close()


@pytest.fixture
def cfg():
    return flt.FilterConfig(
        price_max=3_000_000,
        price_min=0,
        prefectures={"大阪府", "兵庫県", "京都府", "和歌山県"},
        borderline_prefectures={"岡山県"},
        drive_origin="大阪駅",
        drive_max_seconds=7200,
        ng_keywords=["事故物件"],
        min_ai_score=0,
        property_types=set(),  # 空 set = 全タイプ許可
        exclude_dilapidated=False,
        exclude_needs_repair=False,
        city_blacklist=set(),
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


def test_city_blacklist_blocks(conn, cfg):
    """blacklist 市町村は丸ごと除外される (海沿いリスク自治体用)."""
    import dataclasses
    cfg_with_blacklist = dataclasses.replace(cfg, city_blacklist={"太地町", "串本町"})
    row = _insert(conn, prefecture="和歌山県", city="太地町", address="和歌山県東牟婁郡太地町")
    ok, reason = flt.passes(conn, row, cfg_with_blacklist)
    assert not ok and "blacklist" in reason


def test_city_blacklist_allows_non_listed(conn, cfg):
    """blacklist 外の市町村は通る."""
    import dataclasses
    cfg_with_blacklist = dataclasses.replace(cfg, city_blacklist={"太地町"})
    row = _insert(conn, prefecture="大阪府", city="大阪市", address="大阪府大阪市北区")
    ok, _ = flt.passes(conn, row, cfg_with_blacklist)
    assert ok


def test_exclude_needs_repair_blocks(conn, cfg):
    """exclude_needs_repair=True なら修繕必要物件は通知対象外。"""
    import dataclasses
    strict = dataclasses.replace(cfg, exclude_needs_repair=True)
    row = _insert(conn, price=1_000_000, needs_repair=1, needs_repair_reason="要リフォーム")
    ok, reason = flt.passes(conn, row, strict)
    assert not ok and "needs_repair" in reason


def test_needs_repair_allowed_when_flag_off(conn, cfg):
    """exclude_needs_repair=False なら修繕必要物件も通る (既定 cfg)。"""
    row = _insert(conn, price=1_000_000, needs_repair=1)
    ok, _ = flt.passes(conn, row, cfg)
    assert ok
