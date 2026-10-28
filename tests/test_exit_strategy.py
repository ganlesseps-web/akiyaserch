"""出口戦略 (民泊/賃貸/再販) の AI 判定 (2026-10-28 ユーザー指示) のテスト。"""
import pytest

from src import resale_ai


@pytest.mark.parametrize("vals,expected", [
    (("見込める", "厳しい", "見込める"), True),
    (("厳しい", "見込める", "不明"), True),        # 賃貸で出口あり・再販は不明でも可
    (("見込める", "見込める", "厳しい"), False),    # 最悪0円でも手放せない家は外す
    (("厳しい", "厳しい", "不明"), False),
    (("不明", "不明", "不明"), True),              # 判断材料不足 → 要確認で残す
    ((None, None, None), None),                    # 未判定 = 判定待ち
])
def test_exit_ok(vals, expected):
    row = dict(zip(resale_ai.EXIT_KEYS, vals))
    assert resale_ai.exit_ok(row) is expected


def test_clamp_exit_fields():
    out = resale_ai._clamp({"verdict": "検討可", "exit_minpaku": "見込める",
                            "exit_rental": "たぶん", "exit_reason": "温泉街で民泊向き"})
    assert out["exit_minpaku"] == "見込める"
    assert out["exit_rental"] == "不明"           # 想定外の値は不明に丸める
    assert out["exit_resale"] == "不明"
    assert out["exit_reason"] == "温泉街で民泊向き"


def test_prompt_includes_municipality_info():
    text = resale_ai.format_property({"title": "家", "price": 1000000, "city": "高梁市",
                                       "address": "岡山県高梁市"})
    assert "市町村の情報: 高梁市" in text and "観光資源あり" in text


# ---- 一覧への反映 ----
import sqlite3  # noqa: E402

from src import db  # noqa: E402
from src.web import app as webapp  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _prop(conn, lid, exits=None):
    conn.execute("INSERT INTO properties (source, listing_id, url, title, price, city, address,"
                 " first_seen_at, last_seen_at, status, property_type)"
                 " VALUES ('t', ?, 'u', ?, 1500000, '津山市', '岡山県津山市', ?, ?, 'active', 'house')",
                 (lid, f"物件{lid}", db.now_iso(), db.now_iso()))
    pid = conn.execute("SELECT id FROM properties WHERE listing_id=?", (lid,)).fetchone()[0]
    if exits:
        conn.execute("INSERT INTO resale_ai (property_id, verdict, prompt_hash, model, assessed_at,"
                     " exit_minpaku, exit_rental, exit_resale, exit_reason)"
                     " VALUES (?, '検討可', 'h', 'm', ?, ?, ?, ?, '理由')",
                     (pid, db.now_iso(), *exits))
    return pid


def test_list_hides_no_exit_keeps_pending(conn):
    ok = _prop(conn, "ok", ("厳しい", "見込める", "見込める"))
    ng = _prop(conn, "ng", ("見込める", "見込める", "厳しい"))
    pending = _prop(conn, "p")
    old = _prop(conn, "old")   # 旧仕様で判定済み (exit_* が空) = 判定待ち
    conn.execute("INSERT INTO resale_ai (property_id, verdict, prompt_hash, model, assessed_at)"
                 " VALUES (?, '検討可', 'old', 'm', ?)", (old, db.now_iso()))
    ids = {r["id"] for r in webapp._query_rows(conn, "all", "new", None)}
    assert ids == {ok, pending, old}
    assert {r["id"] for r in webapp._query_rows(conn, "noexit", "new", None)} == {ng}
    c = webapp._counts(conn)
    assert c["all"] == 3 and c["noexit"] == 1


def test_exit_badge(conn):
    _prop(conn, "ok", ("厳しい", "見込める", "見込める"))
    _prop(conn, "p")
    rows = {r["listing_id"]: r for r in webapp._query_rows(conn, "all", "new", None)}
    b = webapp._exit_badge(rows["ok"])
    assert b["judged"] and b["ok"] and b["parts"][0] == ("民泊", "×")
    assert webapp._exit_badge(rows["p"]) == {"judged": False}


def test_exit_state():
    assert resale_ai.exit_state(dict(zip(resale_ai.EXIT_KEYS, ("不明",) * 3))) == "check"
    assert resale_ai.exit_state(dict(zip(resale_ai.EXIT_KEYS, ("見込める", "不明", "不明")))) == "ok"
    assert resale_ai.exit_state(dict(zip(resale_ai.EXIT_KEYS, ("厳しい", "不明", "不明")))) == "ng"
    assert resale_ai.exit_state({}) == "pending"


def test_unknown_listed_with_check(conn):
    pid = _prop(conn, "u", ("不明", "不明", "不明"))
    rows = webapp._query_rows(conn, "all", "new", None)
    assert [r["id"] for r in rows] == [pid]
    assert webapp._exit_badge(rows[0])["check"] is True
