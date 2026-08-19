"""掲載開始日(情報公開日)の取得と、長期売れ残りの扱いのテスト。"""
import sqlite3
from datetime import date, timedelta

import pytest

from src import db, enrich
from src.web import app as webapp


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _insert(conn, lid, **over):
    fields = dict(
        source="t", listing_id=lid, url="https://x", title=f"物件{lid}", price=1_000_000,
        prefecture="兵庫県", city="宍粟市", address="兵庫県宍粟市", property_type="house",
        first_seen_at=db.now_iso(), last_seen_at=db.now_iso(), status="active",
    )
    fields.update(over)
    cols = ",".join(fields)
    qs = ",".join("?" * len(fields))
    conn.execute(f"INSERT INTO properties ({cols}) VALUES ({qs})", tuple(fields.values()))
    return conn.execute(
        "SELECT id FROM properties WHERE source='t' AND listing_id=?", (lid,)).fetchone()["id"]


# ---- 日付のパース ----

def test_parse_table_format():
    html = "<table><tr><th>情報公開日</th><td>2021年5月20日</td></tr></table>"
    assert enrich.parse_listed_at(html) == "2021-05-20"


def test_parse_other_labels():
    for label in ("情報登録日", "登録日", "掲載日", "公開日"):
        html = f"<table><tr><th>{label}</th><td>2023年12月1日</td></tr></table>"
        assert enrich.parse_listed_at(html) == "2023-12-01"


def test_parse_missing_returns_none():
    assert enrich.parse_listed_at("<table><tr><th>価格</th><td>200万円</td></tr></table>") is None


def test_parse_invalid_date_is_safe():
    html = "<table><tr><th>情報公開日</th><td>2021年13月45日</td></tr></table>"
    assert enrich.parse_listed_at(html) is None


# ---- 経過年数と警告ラベル ----

def test_listed_years():
    today = date(2026, 8, 19)
    assert round(enrich.listed_years("2021-05-20", today=today), 1) == 5.2
    assert enrich.listed_years(None) is None
    assert enrich.listed_years("こわれた日付") is None


def test_stale_label_threshold():
    today = date(2026, 8, 19)
    assert enrich.stale_label("2021-05-20", today=today).startswith("長期売れ残り")
    assert enrich.stale_label("2024-06-01", today=today) is None   # 2.2年 → 警告なし
    assert enrich.stale_label(None) is None                        # 未取得は警告しない


# ---- 一覧からの除外 ----

def _iso(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_stale_over_5years_hidden(conn):
    _insert(conn, "fresh", listed_at=_iso(365))
    _insert(conn, "stale", listed_at=_iso(365 * 6))
    titles = {r["title"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert titles == {"物件fresh"}


def test_unknown_listed_at_still_visible(conn):
    """掲載日が未取得(NULL)の物件は消えない = デフォルト通過。"""
    _insert(conn, "unknown")                      # listed_at なし
    _insert(conn, "stale", listed_at=_iso(365 * 6))
    titles = {r["title"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert titles == {"物件unknown"}


def test_counts_match_after_stale_exclusion(conn):
    _insert(conn, "fresh", listed_at=_iso(100))
    _insert(conn, "stale", listed_at=_iso(365 * 6))
    assert webapp._counts(conn)["all"] == 1


def test_warning_chip_for_long_listed(conn):
    _insert(conn, "old3y", listed_at=_iso(int(365.25 * 4)))   # 4年 → 表示はされるが警告
    row = webapp._query_rows(conn, "all", "new", None)[0]
    chips = webapp._warning_chips(row)
    assert any("長期売れ残り" in c for c in chips)


def test_no_chip_for_recent(conn):
    _insert(conn, "new", listed_at=_iso(200))
    row = webapp._query_rows(conn, "all", "new", None)[0]
    assert not any("長期売れ残り" in c for c in webapp._warning_chips(row))


# ---- 取得対象の選び方 ----

def test_enrich_targets_only_missing(conn, monkeypatch):
    _insert(conn, "done", url="https://x.akiya-athome.jp/a", listed_at="2024-01-01",
            enriched_at=db.now_iso())
    _insert(conn, "todo", url="https://x.akiya-athome.jp/b")
    _insert(conn, "other", url="https://ieichiba.com/c")     # 対象サイト外

    seen = []

    class _FakeResp:
        content = "<table><tr><th>情報公開日</th><td>2022年3月4日</td></tr></table>".encode("utf-8")
        def raise_for_status(self): pass

    class _FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url):
            seen.append(url)
            return _FakeResp()

    monkeypatch.setattr(enrich, "_client", lambda: _FakeClient())
    monkeypatch.setattr(enrich.time, "sleep", lambda s: None)
    st = enrich.enrich_missing(conn)
    assert st["target"] == 1 and st["found"] == 1
    assert seen == ["https://x.akiya-athome.jp/b"]           # 未取得の1件だけ見に行く
    got = conn.execute("SELECT listed_at FROM properties WHERE listing_id='todo'").fetchone()
    assert got["listed_at"] == "2022-03-04"
