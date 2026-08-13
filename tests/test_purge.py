"""土地/300万以上の「入れない・消す」ルールと、見送りの非表示のテスト。"""
import sqlite3

import pytest

from src import db, purge
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
        source="t", listing_id="1", url="https://x", title="物件", price=1_000_000,
        prefecture="岡山県", city="高梁市", address="岡山県高梁市", area_land=None,
        area_building=None, thumbnail_url=None, body="", posted_at=None,
        property_type="house",
    )
    base.update(over)
    return db.Listing(**base)


def _insert(conn, lid, **over):
    fields = dict(
        source="t", listing_id=lid, url="https://x", title=f"物件{lid}", price=1_000_000,
        prefecture="岡山県", city="高梁市", address="岡山県高梁市", property_type="house",
        first_seen_at=db.now_iso(), last_seen_at=db.now_iso(), status="active",
    )
    fields.update(over)
    cols = ",".join(fields)
    qs = ",".join("?" * len(fields))
    conn.execute(f"INSERT INTO properties ({cols}) VALUES ({qs})", tuple(fields.values()))
    return conn.execute(
        "SELECT id FROM properties WHERE source='t' AND listing_id=?", (lid,)
    ).fetchone()["id"]


# ---- 収集時スキップ (これが無いと purge しても翌朝復活する) ----

def test_skip_land():
    assert purge.should_skip(_listing(property_type="land")) == "土地"


def test_skip_expensive():
    assert purge.should_skip(_listing(price=3_000_000)) == "300万円以上"
    assert purge.should_skip(_listing(price=9_999_999)) == "300万円以上"


def test_keep_cheap_and_house():
    assert purge.should_skip(_listing(price=2_999_999)) is None
    assert purge.should_skip(_listing(price=0)) is None          # 0円物件は残す


def test_keep_unknown_price():
    """価格不明は「300万以上と確定していない」ので入れる。"""
    assert purge.should_skip(_listing(price=None)) is None


def test_keep_unknown_type():
    """種別unknown(判定不能)は土地扱いにしない (誤爆防止)。"""
    assert purge.should_skip(_listing(property_type="unknown")) is None
    assert purge.should_skip(_listing(property_type=None)) is None


def test_cutoff_matches_filters_yaml():
    """通知の price_max と削除しきい値がズレていないこと。"""
    import yaml
    from pathlib import Path
    data = yaml.safe_load(Path("config/filters.yaml").read_text(encoding="utf-8"))
    assert purge.PRICE_CUTOFF_YEN == int(data["price_max"])


# ---- 削除 ----

def test_purge_deletes_land_and_expensive(conn):
    _insert(conn, "keep", price=1_000_000, property_type="house")
    _insert(conn, "land", property_type="land")
    _insert(conn, "pricey", price=5_000_000)
    _insert(conn, "nullprice", price=None)
    purge.purge(conn)
    left = {r["listing_id"] for r in conn.execute("SELECT listing_id FROM properties")}
    assert left == {"keep", "nullprice"}


def test_purge_protects_favorites(conn):
    pid = _insert(conn, "fav", price=5_000_000)
    conn.execute("INSERT INTO favorites (property_id, note, starred_at) VALUES (?,'',?)",
                 (pid, db.now_iso()))
    purge.purge(conn)
    assert conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0] == 1


def test_purge_protects_rated(conn):
    pid = _insert(conn, "rated", price=5_000_000)
    conn.execute("INSERT INTO ratings (property_id, rating, rated_at) VALUES (?,5,?)",
                 (pid, db.now_iso()))
    purge.purge(conn)
    assert conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0] == 1


def test_purge_deletes_child_rows(conn):
    """本番(Turso)は CASCADE が効かないので、子テーブルも明示的に消えること。"""
    pid = _insert(conn, "pricey", price=5_000_000)
    conn.execute("INSERT INTO resale_ai (property_id, verdict, prompt_hash, model, assessed_at)"
                 " VALUES (?,'検討可','h','m',?)", (pid, db.now_iso()))
    conn.execute("INSERT INTO price_drops (property_id, old_price, new_price, dropped_at)"
                 " VALUES (?,6000000,5000000,?)", (pid, db.now_iso()))
    conn.execute("INSERT INTO read_status (property_id, read_at) VALUES (?,?)",
                 (pid, db.now_iso()))
    purge.purge(conn)
    for t in ("resale_ai", "price_drops", "read_status"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, f"{t} に孤児が残った"


def test_purge_is_idempotent(conn):
    """途中で落ちても再実行で完了できる (libsql はトランザクションが無い)。"""
    _insert(conn, "pricey", price=5_000_000)
    purge.purge(conn)
    purge.purge(conn)      # 2回目も落ちない
    assert conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0] == 0


def test_count_targets_reports_breakdown(conn):
    _insert(conn, "keep", price=1_000_000)
    _insert(conn, "land", property_type="land", price=None)
    _insert(conn, "pricey", price=5_000_000)
    _insert(conn, "both", property_type="land", price=5_000_000)
    s = purge.count_targets(conn)
    assert s["total"] == 3 and s["land"] == 2 and s["pricey"] == 2 and s["both"] == 1
    assert s["remaining"] == 1
    assert s["land_no_price"] == 1


# ---- 見送りの非表示 (NULL比較の罠の回帰テスト) ----

def _set_verdict(conn, pid, verdict):
    conn.execute("INSERT OR REPLACE INTO resale_ai"
                 " (property_id, verdict, prompt_hash, model, assessed_at) VALUES (?,?,?,?,?)",
                 (pid, verdict, "h", "m", db.now_iso()))


def test_skipped_hidden_from_list(conn):
    a = _insert(conn, "ok")
    _set_verdict(conn, a, "検討可")
    b = _insert(conn, "ng")
    _set_verdict(conn, b, "見送り")
    titles = {r["title"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert titles == {"物件ok"}


def test_unassessed_still_visible(conn):
    """★重要な回帰テスト: AI未判定の物件が見送り除外に巻き込まれて消えないこと。

    `verdict != '見送り'` と書くと NULL 比較が偽になり未判定が全部消える。
    """
    _insert(conn, "unassessed")            # resale_ai に行なし
    b = _insert(conn, "ng")
    _set_verdict(conn, b, "見送り")
    titles = {r["title"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert titles == {"物件unassessed"}


def test_skipped_tab_shows_them(conn):
    """隠した見送りを確認できる逃げ道タブがあること。"""
    b = _insert(conn, "ng")
    _set_verdict(conn, b, "見送り")
    rows = webapp._query_rows(conn, "skipped", "new", None)
    assert {r["title"] for r in rows} == {"物件ng"}


def test_counts_match_list(conn):
    a = _insert(conn, "ok")
    _set_verdict(conn, a, "検討可")
    _insert(conn, "unassessed")
    b = _insert(conn, "ng")
    _set_verdict(conn, b, "見送り")
    counts = webapp._counts(conn)
    assert counts["all"] == 2        # 一覧と件数が一致 (見送りは除外)
    assert counts["skipped"] == 1


def test_verdict_filter(conn):
    a = _insert(conn, "ok")
    _set_verdict(conn, a, "検討可")
    c = _insert(conn, "warn")
    _set_verdict(conn, c, "警告")
    _insert(conn, "none")
    assert {r["title"] for r in webapp._query_rows(conn, "all", "new", None, verdict="検討可")} == {"物件ok"}
    assert {r["title"] for r in webapp._query_rows(conn, "all", "new", None, verdict="警告")} == {"物件warn"}
    assert {r["title"] for r in webapp._query_rows(conn, "all", "new", None, verdict="未判定")} == {"物件none"}


def test_verdict_filter_rejects_unknown_value(conn):
    """未知の値は無視される (SQLインジェクション対策の確認)。"""
    _insert(conn, "a")
    rows = webapp._query_rows(conn, "all", "new", None, verdict="'; DROP TABLE properties;--")
    assert len(rows) == 1
    assert conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0] == 1


def test_verdict_sort_orders_best_first(conn):
    c = _insert(conn, "warn")
    _set_verdict(conn, c, "警告")
    a = _insert(conn, "ok")
    _set_verdict(conn, a, "検討可")
    _insert(conn, "none")
    titles = [r["title"] for r in webapp._query_rows(conn, "all", "verdict_best", None)]
    assert titles.index("物件ok") < titles.index("物件warn") < titles.index("物件none")
