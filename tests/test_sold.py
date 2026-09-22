"""売れた物件(掲載終了)の自動検知のテスト。安全装置を重点的に検証する。"""
import sqlite3
from datetime import date, timedelta

import pytest

from src import db, sold
from src.web import app as webapp


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


TODAY = date(2026, 9, 22)


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat() + "T06:00:00+09:00"


def _insert(conn, lid, *, source="src_a", seen_days_ago=0, status="active", **over):
    fields = dict(
        source=source, listing_id=lid, url="https://x", title=f"物件{lid}", price=1_000_000,
        prefecture="岡山県", city="高梁市", address="岡山県高梁市", property_type="house",
        first_seen_at=_iso(30), last_seen_at=_iso(seen_days_ago), status=status,
    )
    fields.update(over)
    cols = ",".join(fields)
    qs = ",".join("?" * len(fields))
    conn.execute(f"INSERT INTO properties ({cols}) VALUES ({qs})", tuple(fields.values()))
    return conn.execute(
        "SELECT id FROM properties WHERE source=? AND listing_id=?", (source, lid)
    ).fetchone()["id"]


def _status(conn, pid):
    return conn.execute("SELECT status FROM properties WHERE id=?", (pid,)).fetchone()["status"]


# ---- 基本: 連続3日見かけなければ sold ----

def test_marks_missing_after_3_days(conn):
    fresh = _insert(conn, "fresh", seen_days_ago=0)
    old = _insert(conn, "old", seen_days_ago=3)
    st = sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)
    assert st["marked"] == 1
    assert _status(conn, fresh) == "active"
    assert _status(conn, old) == "sold"


def test_two_days_missing_is_not_enough(conn):
    """一覧の一時的な取りこぼしを吸収する: 2日では切り替えない。"""
    pid = _insert(conn, "p", seen_days_ago=2)
    sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)
    assert _status(conn, pid) == "active"


def test_sold_at_is_recorded(conn):
    pid = _insert(conn, "p", seen_days_ago=5)
    sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)
    row = conn.execute("SELECT sold_at FROM properties WHERE id=?", (pid,)).fetchone()
    assert row["sold_at"] is not None


# ---- 安全装置1: 収集に失敗した収集元は判定しない ----

def test_failed_source_is_not_judged(conn):
    """★最重要: サイトが落ちた日に全物件が sold になる事故を防ぐ。"""
    pid = _insert(conn, "p", source="src_down", seen_days_ago=10)
    st = sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)  # src_down は失敗
    assert st["marked"] == 0
    assert _status(conn, pid) == "active"


def test_no_succeeded_sources_skips_everything(conn):
    pid = _insert(conn, "p", seen_days_ago=10)
    st = sold.mark_missing(conn, succeeded_sources=set(), today=TODAY)
    assert st["marked"] == 0 and st["checked"] == 0
    assert _status(conn, pid) == "active"


def test_only_succeeded_source_is_judged(conn):
    a = _insert(conn, "a", source="src_a", seen_days_ago=10)
    b = _insert(conn, "b", source="src_b", seen_days_ago=10)
    sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)
    assert _status(conn, a) == "sold"
    assert _status(conn, b) == "active"     # src_b は今日取れなかったので触らない


# ---- 安全装置2: スキップした物件も「見かけた」扱い ----

def test_touch_seen_prevents_false_sold(conn):
    """300万以上に値上げされた物件 = DBには入れないが掲載は続いている。"""
    pid = _insert(conn, "p", seen_days_ago=10)
    sold.touch_seen(conn, "src_a", "p")          # scrape がスキップ時に呼ぶ
    sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)
    assert _status(conn, pid) == "active"


def test_touch_seen_ignores_unknown_listing(conn):
    sold.touch_seen(conn, "src_a", "no-such")    # 落ちないこと
    assert conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0] == 0


# ---- 復活: 再掲載されたら active に戻る ----

def test_upsert_revives_sold_listing(conn):
    pid = _insert(conn, "p", seen_days_ago=10)
    sold.mark_missing(conn, succeeded_sources={"src_a"}, today=TODAY)
    assert _status(conn, pid) == "sold"
    listing = db.Listing(
        source="src_a", listing_id="p", url="https://x", title="物件p", price=1_000_000,
        prefecture="岡山県", city="高梁市", address="岡山県高梁市", area_land=None,
        area_building=None, thumbnail_url=None, body="", posted_at=None, property_type="house",
    )
    _, is_new = db.upsert_listing(conn, listing)
    assert not is_new
    assert _status(conn, pid) == "active"
    assert conn.execute("SELECT sold_at FROM properties WHERE id=?", (pid,)).fetchone()["sold_at"] is None


# ---- 既存の除外・通知経路との整合 ----

def test_sold_hidden_from_all_view(conn):
    _insert(conn, "live", seen_days_ago=0)
    _insert(conn, "gone", seen_days_ago=0, status="sold", sold_at=db.now_iso())
    titles = {r["title"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert titles == {"物件live"}


def test_sold_tab_shows_recent_only(conn):
    _insert(conn, "recent", status="sold", sold_at=db.now_iso())
    _insert(conn, "ancient", status="sold",
            sold_at=(date.today() - timedelta(days=60)).isoformat() + "T00:00:00")
    titles = {r["title"] for r in webapp._query_rows(conn, "sold", "new", None)}
    assert titles == {"物件recent"}
    assert webapp._counts(conn)["sold"] == 1


def test_sold_not_in_notification_queue(conn):
    """通知の候補 (unnotified_pass) は status='active' しか見ないこと。"""
    _insert(conn, "gone", status="sold", sold_at=db.now_iso())
    rows = db.unnotified_pass(conn, "discord")
    assert rows == []


def test_recent_sold_helper(conn):
    _insert(conn, "a", status="sold", sold_at=db.now_iso())
    assert len(sold.recent_sold(conn, days=7)) == 1
