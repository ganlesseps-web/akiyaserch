"""移住者コミュニティの印と並び替え (2026-10-25) のテスト。"""
import sqlite3

import pytest

from src import communities, db
from src.web import app as webapp


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _insert(conn, lid, city, address, price=1_500_000):
    conn.execute("INSERT INTO properties (source, listing_id, url, title, price, city, address,"
                 " first_seen_at, last_seen_at, status, property_type)"
                 " VALUES ('t', ?, 'u', ?, ?, ?, ?, ?, ?, 'active', 'house')",
                 (lid, f"物件{lid}", price, city, address, db.now_iso(), db.now_iso()))
    return conn.execute("SELECT id FROM properties WHERE listing_id=?", (lid,)).fetchone()[0]


def test_all_classified():
    """48市町村調査 + 物件の多い39市町村 (2026-10-25)。"""
    assert len(communities.load()) == 87
    assert communities.lookup("吉野郡下市", "")[0] == 2      # DB の city が「下市」で終わる
    assert communities.lookup("仁多郡奥出雲町", "")[0] == 2


def test_lookup_levels_and_ward():
    assert communities.lookup("綾部市", "京都府綾部市志賀郷町")[0] == 3
    assert communities.lookup("上田市", "長野県上田市手塚")[0] == 2
    assert communities.lookup("新潟市", "新潟県新潟市西蒲区巻甲")[0] == 1
    assert communities.lookup("新潟市", "新潟県新潟市中央区")[0] == 0
    assert communities.lookup("大東市", "大阪府大東市")[0] == 0


def test_badge():
    b = communities.badge({"city": "燕市", "address": "新潟県燕市花見"})
    assert b["mark"] == "◎" and "交流" in b["note"]
    assert communities.badge({"city": "大東市", "address": ""}) is None


def test_sort_by_community(conn):
    none = _insert(conn, "a", "大東市", "大阪府大東市")
    mid = _insert(conn, "b", "上田市", "長野県上田市")
    top = _insert(conn, "c", "綾部市", "京都府綾部市")
    rows = webapp._query_rows(conn, "all", "community_desc", None)
    assert [r["id"] for r in rows] == [top, mid, none]


def test_city_name_variants(conn):
    assert communities.lookup("丹波篠山市西紀南地区", "")[0] == 3
    a = _insert(conn, "x", "丹波篠山市西紀南地区", "兵庫県丹波篠山市")
    b = _insert(conn, "y", "大東市", "大阪府大東市")
    rows = webapp._query_rows(conn, "all", "community_desc", None)
    assert [r["id"] for r in rows] == [a, b]
