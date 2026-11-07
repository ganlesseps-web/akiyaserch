"""上下水道の判別 (src/utilities.py)。各サイトの詳細ページで実際に見た書き方で確かめる。"""
import sqlite3

import pytest

from src import db, utilities
from src.utilities import judge, judge_listing
from src.web import app as webapp


@pytest.mark.parametrize("text, water, sewage", [
    # 丹波篠山 (クラッソ)
    ("設備 ガス（プロパン）, 上水道, 下水道（接続済）", "public", "public"),
    # 下市町・五條市: 汲み取りは汲み取り (簡易水洗と並んでいても)
    ("水道 公営上水道 トイレ 洋式 汲取り 非水洗", "public", "kumitori"),
    ("水道：公営上水道 トイレ：洋式 / 汲取り/ 簡易水洗", "public", "kumitori"),
    # 宇陀市: 井戸、浄化槽の汲み取り (清掃) は汲み取り式トイレではない
    ("水道 私設水道（井戸） トイレ 浄化槽、汲取り", "well", "septic"),
    ("水道 上水道 電気 トイレ 水洗（浄化槽）", "public", "septic"),
    # 東吉野村: 「水道申込費」は設備の話ではない
    ("トイレ 簡易水洗 水道申込費 申込済み", "unknown", "simple"),
    # 家いちば: 海の名前は数えない
    ("公営水道完備 豊後水道を望む", "public", "unknown"),
    ("下水道 公共下水道 設備 上水道・下水道", "public", "public"),
    ("水道 水道 トイレ 水洗和式 下水道接続済み", "public", "public"),
    # ジモティー: メニューの「下水内郡」は数えない
    ("長野県下水内郡 公共下水", "unknown", "public"),
    # 京丹後市
    ("水道 未接続（敷地内引込あり）※現在は地下水利用 下水道 未接続 トイレ 汲み取り式トイレ",
     "well", "kumitori"),
    ("水道 上水道接続済 下水道 無し トイレ 簡易水洗トイレ", "public", "simple"),
    ("下水接続不可（市浄化槽設置エリアですが浄化槽は未設置）", "unknown", "none"),
    # 南アルプス市: 否定を読む
    ("上下水道が接続されておらず", "none", "none"),
    ("上下水道の接続があり", "public", "public"),
    ("設備 電気 都市ガス 上下水道 公共下水道", "public", "public"),
    ("水道：市営水道 トイレ：水洗（公共下水）", "public", "public"),
    ("水道 上水道 下水道 浄化槽 トイレ 水洗式", "public", "septic"),
    ("下水道 その他 トイレ 汲み取", "unknown", "kumitori"),
    ("トイレ 水洗（下水道） 水道 市水道", "public", "public"),
    # 高島市: 公共下水があれば、別棟の汲み取りより優先
    ("設備 上水道 下水道（水洗） 北側のトイレ：汲み取り", "public", "public"),
    ("公共下水接続済トイレ有り、使っていない汲取りトイレ有り", "unknown", "public"),
    ("水道 共同飲料水 トイレ 洋式／汲取り", "well", "kumitori"),
    ("水道：上水道 下水道：下水道", "public", "public"),
    ("水道・電気・ガス廃止中", "unknown", "unknown"),
    # 次の欄 (ガス) の「なし」を水道の否定と読まない
    ("上水道 ガス なし", "public", "unknown"),
    ("浄化槽の汲み取りは年1回", "unknown", "septic"),
    # 京丹後市: 「市設置浄化槽の区域」は浄化槽がある意味ではない
    ("水道 市水道 下水道 無し（市設置浄化槽の区域） 風呂 専用", "public", "none"),
    ("水道 上水道 下水道 市設置浄化槽の区域（設置できます） 風呂", "public", "unknown"),
    ("水道 上水道接続済 下水道 未接続 その他の特記事項 公共浄化槽市設置区域 分担金27万円", "public", "none"),
    ("水道 市上水道 下水道 無し 浄化槽設置時には補助金が出る地域です", "public", "none"),
    # 宇陀市
    ("水道：公営上水道 風呂：電気 トイレ：洋式・下水・水洗 駐車場：なし", "public", "public"),
    # 温水洗浄便座は水洗の根拠にしない
    ("水回りは（トイレ温水洗浄便座付き）", "unknown", "unknown"),
    # SUUMO: 「本下水」は公共下水
    ("設備：公営水道、本下水、都市ガス、駐車場：無", "public", "public"),
    ("設備：公営水道、個別LPG、駐車場：無", "public", "unknown"),
])
def test_judge(text, water, sewage):
    u = judge(text)
    assert (u.water, u.sewage) == (water, sewage)


def test_takahashi_only_active_marks_count():
    html = """
    <form><label>上水道完備</label><label>下水道完備</label><label>汲取り</label></form>
    <span class="detail__meta-facility detail__meta-facility--active">上水道完備</span>
    <span class="detail__meta-facility">下水道完備</span>
    <span class="detail__meta-facility detail__meta-facility--active">浄化槽</span>
    """
    u = judge_listing("高梁の家", "", html)
    assert (u.water, u.sewage) == ("public", "septic")


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _add(conn, lid, water=None, sewage=None):
    now = db.now_iso()
    conn.execute(
        "INSERT INTO properties (source, listing_id, url, title, price, first_seen_at,"
        " last_seen_at, water_supply, sewage, utilities_checked_at)"
        " VALUES ('t', ?, 'https://x', ?, 1000000, ?, ?, ?, ?, ?)",
        (lid, f"家{lid}", now, now, water, sewage, now if water else None),
    )


def test_dashboard_filters_and_hides_kumitori(conn):
    _add(conn, "a", "public", "public")
    _add(conn, "b", "public", "septic")
    _add(conn, "c", "public", "kumitori")
    _add(conn, "d", "well", "septic")
    _add(conn, "e")  # 未確認

    def titles(ws=None):
        return sorted(r["title"] for r in webapp._query_rows(conn, "all", "new", None, ws=ws))

    assert titles() == ["家a", "家b", "家d", "家e"]          # 汲み取りは一覧に出さない
    assert titles("public") == ["家a"]
    assert titles("septic") == ["家a", "家b"]
    assert titles("unknown") == ["家e"]
    assert webapp._counts(conn)["all"] == 4


def test_badge():
    assert utilities.badge({"utilities_checked_at": None})["text"] == "上下水道 未確認"
    b = utilities.badge({"utilities_checked_at": "x", "water_supply": "public",
                         "sewage": "septic", "utilities_note": ""})
    assert b["good"] and b["text"] == "水道:公営水道 / 下水:浄化槽"
