"""値引き交渉の候補 (48市町村の300万〜400万円) のテスト。"""
import sqlite3
from datetime import date

import pytest

from src import db, negotiation, purge
from src.web import app as webapp


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _listing(**over):
    base = dict(
        source="t", listing_id="1", url="https://x", title="物件", price=3_500_000,
        prefecture="岡山県", city="津山市", address="岡山県津山市林田", area_land=None,
        area_building=None, thumbnail_url=None, body="", posted_at=None,
        property_type="house",
    )
    base.update(over)
    return db.Listing(**base)


def _insert(conn, lid, **over):
    fields = dict(
        source="t", listing_id=lid, url="https://x", title=f"物件{lid}", price=3_500_000,
        prefecture="岡山県", city="津山市", address="岡山県津山市林田", property_type="house",
        first_seen_at=db.now_iso(), last_seen_at=db.now_iso(), status="active",
    )
    fields.update(over)
    cols = ",".join(fields)
    conn.execute(f"INSERT INTO properties ({cols}) VALUES ({','.join('?' * len(fields))})",
                 tuple(fields.values()))
    return conn.execute("SELECT id FROM properties WHERE listing_id=?", (lid,)).fetchone()["id"]


def test_config_lists_48_areas():
    cfg = negotiation.load()
    assert len(cfg.areas) == 48
    assert cfg.price_max == 4_000_000
    assert ("新潟市", "西蒲区") in cfg.areas
    assert ("五島市", "") in cfg.areas


# ---- 収集 (should_skip) ----

def test_keep_band_in_area():
    assert purge.should_skip(_listing(price=3_000_000)) is None
    assert purge.should_skip(_listing(price=3_999_999)) is None


def test_skip_above_band():
    assert purge.should_skip(_listing(price=4_000_000)) == "300万円以上"


def test_skip_band_outside_area():
    out = _listing(city="高梁市", address="岡山県高梁市")
    assert purge.should_skip(out) == "300万円以上"


def test_ward_must_match():
    """新潟市は西蒲区だけ。他の区の300万円台は従来通り入れない。"""
    assert purge.should_skip(_listing(prefecture="新潟県", city="新潟市",
                                      address="新潟県新潟市西蒲区巻甲")) is None
    assert purge.should_skip(_listing(prefecture="新潟県", city="新潟市",
                                      address="新潟県新潟市中央区")) == "300万円以上"


def test_band_still_respects_other_rules():
    assert purge.should_skip(_listing(property_type="land")) == "土地"
    assert purge.should_skip(_listing(title="農地付き古民家")) == "農地付き"


# ---- 削除 (purge) は収集と同じ判定 ----

def test_purge_keeps_band(conn):
    keep = _insert(conn, "keep")
    gone = _insert(conn, "gone", city="高梁市", address="岡山県高梁市")
    high = _insert(conn, "high", price=4_200_000)
    stats = purge.count_targets(conn)
    assert stats["pricey"] == 2
    purge.purge(conn)
    left = {r["id"] for r in conn.execute("SELECT id FROM properties")}
    assert keep in left and gone not in left and high not in left


# ---- ダッシュボード ----

def test_band_hidden_from_normal_views(conn):
    band = _insert(conn, "band")
    cheap = _insert(conn, "cheap", price=1_500_000)
    ids = {r["id"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert cheap in ids and band not in ids
    assert webapp._counts(conn)["all"] == 1


def test_nego_tab_shows_band_and_200_300(conn):
    band = _insert(conn, "band")
    mid = _insert(conn, "mid", price=2_500_000)
    cheap = _insert(conn, "cheap", price=1_500_000)
    other = _insert(conn, "other", price=2_500_000, city="高梁市", address="岡山県高梁市")
    ids = {r["id"] for r in webapp._query_rows(conn, "nego", "new", None)}
    assert ids == {band, mid}
    assert cheap not in ids and other not in ids
    assert webapp._counts(conn)["nego"] == 2


def test_nego_tab_keeps_stale(conn):
    """5年以上売れ残りは通常の一覧では隠すが、交渉候補では出す。"""
    old = _insert(conn, "old", price=2_500_000, listed_at="2019-01-01")
    assert old not in {r["id"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert old in {r["id"] for r in webapp._query_rows(conn, "nego", "new", None)}


def test_nego_sort_marks_first(conn):
    plain = _insert(conn, "plain", price=2_200_000)
    dropped = _insert(conn, "dropped", price=3_800_000)
    conn.execute("INSERT INTO price_drops (property_id, old_price, new_price, dropped_at)"
                 " VALUES (?, 4500000, 3800000, ?)", (dropped, db.now_iso()))
    rows = webapp._query_rows(conn, "nego", "new", None)
    assert [r["id"] for r in rows] == [dropped, plain]


def test_marks():
    today = date(2026, 10, 23)
    row = {"listed_at": "2024-10-01", "first_seen_at": "2026-10-01",
           "drop_old_price": 4_000_000, "drop_new_price": 3_500_000,
           "title": "古民家", "body": "価格は応相談です"}
    assert negotiation.marks(row, today=today) == [
        "📅 掲載2.1年", "🔻 値下げ歴あり", "💬 価格相談の記載"]
    seen_only = {"listed_at": None, "first_seen_at": "2026-03-01"}
    assert negotiation.marks(seen_only, today=today) == ["📅 7か月以上掲載"]
    assert negotiation.marks({"listed_at": "2026-09-01", "first_seen_at": "2026-09-01"},
                             today=today) == []


def test_page_renders_nego_tab(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setenv("TRADE_DB_PATH", str(tmp_path / "demo.db"))
    db.init_db()
    with db.connect() as c:
        _insert(c, "band", body="価格相談可", listed_at="2023-01-01")
    r = TestClient(webapp.app).get("/?view=nego")
    assert r.status_code == 200
    assert "🤝交渉候補 (1)" in r.text
    assert "💬 価格相談の記載" in r.text
    assert "📅 掲載" in r.text
    # 通常の一覧には出ない
    assert "物件band" not in TestClient(webapp.app).get("/").text


# ---- 京丹後市の掲載開始日 (「掲載が長い」の印の材料) ----

def test_kyotango_slash_date():
    from src.enrich import parse_listed_at
    html = "<div><p>京丹後市</p><p>公開日：&nbsp;2018/07/12 <a href='x'>戻る</a></p></div>"
    assert parse_listed_at(html) == "2018-07-12"


def test_kyotango_blank_date_is_none():
    from src.enrich import parse_listed_at
    html = "<div><p>公開日：&nbsp; <a href='x'>2020/01/01 のお知らせ</a></p></div>"
    assert parse_listed_at(html) is None
