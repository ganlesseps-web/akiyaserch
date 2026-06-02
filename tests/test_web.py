"""ダッシュボード (src/web/app) の検索・フィルタの単体テスト。in-memory SQLite。"""
import sqlite3

import pytest

from src import db
from src.web import app as webapp


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)  # property_type / settlement_offer 等の追加列を反映
    yield c
    c.close()


def _insert(conn, listing_id, **overrides):
    fields = dict(
        source="test", listing_id=listing_id, url="https://x", title="物件",
        price=1_000_000, prefecture="大阪府", city="大阪市", address="大阪府大阪市",
        area_land=None, area_building=None, thumbnail_url=None, body="",
        posted_at=None, first_seen_at=db.now_iso(), last_seen_at=db.now_iso(),
    )
    fields.update(overrides)
    cols = ",".join(fields.keys())
    qs = ",".join("?" * len(fields))
    conn.execute(f"INSERT INTO properties ({cols}) VALUES ({qs})", tuple(fields.values()))
    return conn.execute(
        "SELECT id FROM properties WHERE source=? AND listing_id=?",
        ("test", listing_id),
    ).fetchone()["id"]


def _dismiss(conn, pid):
    conn.execute(
        "INSERT INTO dismissed (property_id, dismissed_at) VALUES (?, ?)",
        (pid, db.now_iso()),
    )


# ---- 都道府県フィルタ ----

def test_pref_filter_matches_only_selected(conn):
    _insert(conn, "1", prefecture="大阪府")
    _insert(conn, "2", prefecture="兵庫県")
    _insert(conn, "3", prefecture="兵庫県")
    rows = webapp._query_rows(conn, "all", "new", None, pref="兵庫県")
    assert len(rows) == 2
    assert all(r["prefecture"] == "兵庫県" for r in rows)


def test_pref_none_returns_all(conn):
    _insert(conn, "1", prefecture="大阪府")
    _insert(conn, "2", prefecture="兵庫県")
    rows = webapp._query_rows(conn, "all", "new", None, pref=None)
    assert len(rows) == 2


# ---- 価格フィルタ ----

def test_price_min(conn):
    _insert(conn, "1", price=500_000)
    _insert(conn, "2", price=2_000_000)
    rows = webapp._query_rows(conn, "all", "new", None, price_min=1_000_000)
    assert {r["price"] for r in rows} == {2_000_000}


def test_price_max(conn):
    _insert(conn, "1", price=500_000)
    _insert(conn, "2", price=2_000_000)
    rows = webapp._query_rows(conn, "all", "new", None, price_max=1_000_000)
    assert {r["price"] for r in rows} == {500_000}


def test_price_range(conn):
    _insert(conn, "1", price=300_000)
    _insert(conn, "2", price=1_500_000)
    _insert(conn, "3", price=5_000_000)
    rows = webapp._query_rows(
        conn, "all", "new", None, price_min=1_000_000, price_max=3_000_000
    )
    assert {r["price"] for r in rows} == {1_500_000}


def test_price_filter_excludes_unknown_price(conn):
    """価格でしぼると価格不明 (NULL) は外れる。"""
    _insert(conn, "1", price=None)
    _insert(conn, "2", price=1_000_000)
    rows = webapp._query_rows(conn, "all", "new", None, price_max=3_000_000)
    assert {r["price"] for r in rows} == {1_000_000}


def test_no_price_filter_keeps_unknown(conn):
    """価格指定なしなら価格不明も残る。"""
    _insert(conn, "1", price=None)
    _insert(conn, "2", price=1_000_000)
    rows = webapp._query_rows(conn, "all", "new", None)
    assert len(rows) == 2


def test_pref_and_price_combined(conn):
    _insert(conn, "1", prefecture="兵庫県", price=800_000)
    _insert(conn, "2", prefecture="兵庫県", price=4_000_000)
    _insert(conn, "3", prefecture="大阪府", price=800_000)
    rows = webapp._query_rows(
        conn, "all", "new", None, pref="兵庫県", price_max=1_000_000
    )
    assert len(rows) == 1
    assert rows[0]["prefecture"] == "兵庫県" and rows[0]["price"] == 800_000


# ---- _prefectures (プルダウンの選択肢) ----

def test_prefectures_counts_and_order(conn):
    _insert(conn, "1", prefecture="兵庫県")
    _insert(conn, "2", prefecture="兵庫県")
    _insert(conn, "3", prefecture="大阪府")
    prefs = webapp._prefectures(conn)
    assert prefs[0] == ("兵庫県", 2)  # 件数の多い順
    assert ("大阪府", 1) in prefs


def test_prefectures_excludes_dismissed(conn):
    p1 = _insert(conn, "1", prefecture="奈良県")
    _insert(conn, "2", prefecture="奈良県")
    _dismiss(conn, p1)
    prefs = dict(webapp._prefectures(conn))
    assert prefs["奈良県"] == 1


def test_prefectures_skips_null_and_empty(conn):
    _insert(conn, "1", prefecture=None)
    _insert(conn, "2", prefecture="")
    _insert(conn, "3", prefecture="京都府")
    prefs = dict(webapp._prefectures(conn))
    assert prefs == {"京都府": 1}


# ---- settlement ビュー / 市区町村フィルタ / _cities ----

def test_settlement_view(conn):
    _insert(conn, "1", settlement_offer=1, title="もらえる家")
    _insert(conn, "2", settlement_offer=0, title="普通の家")
    rows = webapp._query_rows(conn, "settlement", "new", None)
    assert len(rows) == 1
    assert rows[0]["title"] == "もらえる家"


def test_city_filter(conn):
    _insert(conn, "1", prefecture="兵庫県", city="姫路市")
    _insert(conn, "2", prefecture="兵庫県", city="神戸市")
    rows = webapp._query_rows(conn, "all", "new", None, pref="兵庫県", city="姫路市")
    assert len(rows) == 1
    assert rows[0]["city"] == "姫路市"


def test_cities_for_pref(conn):
    _insert(conn, "1", prefecture="兵庫県", city="姫路市")
    _insert(conn, "2", prefecture="兵庫県", city="姫路市")
    _insert(conn, "3", prefecture="兵庫県", city="神戸市")
    _insert(conn, "4", prefecture="大阪府", city="大阪市")
    cities = webapp._cities(conn, "兵庫県")
    assert cities[0] == ("姫路市", 2)              # 件数の多い順
    assert ("神戸市", 1) in cities
    assert all(c[0] != "大阪市" for c in cities)    # 他県は含まない


def test_cities_empty_without_pref(conn):
    _insert(conn, "1", prefecture="兵庫県", city="姫路市")
    assert webapp._cities(conn, None) == []


def test_cities_excludes_dismissed(conn):
    p1 = _insert(conn, "1", prefecture="奈良県", city="奈良市")
    _insert(conn, "2", prefecture="奈良県", city="奈良市")
    _dismiss(conn, p1)
    cities = dict(webapp._cities(conn, "奈良県"))
    assert cities["奈良市"] == 1


# ---- _man_to_yen (万円入力 → 円) ----

@pytest.mark.parametrize("val,expected", [
    ("100", 1_000_000),
    ("50", 500_000),
    ("0", 0),
    ("", None),
    (None, None),
    ("abc", None),
    ("-5", None),
])
def test_man_to_yen(val, expected):
    assert webapp._man_to_yen(val) == expected


# ---- 画面が実際にレンダリングされるか (TestClient スモーク) ----

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setenv("TRADE_DB_PATH", str(tmp_path / "demo.db"))
    db.init_db()
    seed = [
        ("兵庫県", "姫路市", 800_000, "姫路の戸建て", 0),
        ("大阪府", "大東市", 2_500_000, "大東の家", 0),
        ("京都府", "伊根町", 500_000, "伊根の古民家", 0),
        ("奈良県", "東吉野村", 5_000_000, "東吉野の家(定住で譲渡)", 1),
    ]
    with db.connect() as c:
        for i, (pref, city, price, title, settle) in enumerate(seed):
            c.execute(
                "INSERT INTO properties (source, listing_id, url, title, price,"
                " prefecture, city, address, settlement_offer,"
                " first_seen_at, last_seen_at, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,'active')",
                ("demo", str(i), "https://x", title, price, pref, city,
                 f"{pref}{city}", settle, db.now_iso(), db.now_iso()),
            )
    from fastapi.testclient import TestClient
    from src.web.app import app
    return TestClient(app)


def test_index_renders_filters(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "全ての都道府県" in r.text       # 都道府県プルダウン
    assert 'name="price_min"' in r.text     # 価格・下限
    assert 'name="price_max"' in r.text     # 価格・上限


def test_index_pref_filter(client):
    r = client.get("/", params={"pref": "兵庫県"})
    assert r.status_code == 200
    assert "姫路の戸建て" in r.text
    assert "大東の家" not in r.text


def test_index_price_max_filter(client):
    r = client.get("/", params={"price_max": "100"})  # 100万円以下
    assert "伊根の古民家" in r.text     # 50万 → 残る
    assert "東吉野の家" not in r.text    # 500万 → 消える


def test_index_filters_combine_with_view_tabs(client):
    # タブ (view) と都道府県フィルタが両立する
    r = client.get("/", params={"view": "all", "pref": "京都府"})
    assert r.status_code == 200
    assert "伊根の古民家" in r.text
    assert "姫路の戸建て" not in r.text


def test_index_settlement_tab(client):
    r = client.get("/", params={"view": "settlement"})
    assert r.status_code == 200
    assert "東吉野の家" in r.text             # settlement_offer=1
    assert "姫路の戸建て" not in r.text         # settlement_offer=0


def test_index_city_dropdown_appears_only_with_pref(client):
    r = client.get("/", params={"pref": "兵庫県"})
    assert 'name="city"' in r.text             # 県を選ぶと市町村プルダウンが出る
    assert "姫路市" in r.text
    r2 = client.get("/")
    assert 'name="city"' not in r2.text         # 県未選択なら市町村プルダウンは無い


def test_index_city_filter(client):
    r = client.get("/", params={"pref": "兵庫県", "city": "姫路市"})
    assert r.status_code == 200
    assert "姫路の戸建て" in r.text


def test_index_price_dropdown_present(client):
    r = client.get("/")
    assert 'name="price_min"' in r.text
    assert 'name="price_max"' in r.text
    assert "〜100万" in r.text                  # プルダウンのラベル
