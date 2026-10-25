"""汲み取り式トイレ・大幅修繕の除外 (2026-10-25 ユーザー指示) のテスト。"""
import sqlite3

import pytest

from src import db, purge
from src.normalize import is_kumitori, needs_major_repair


@pytest.mark.parametrize("text", [
    "上水道 | トイレ: 汲み取り | 駐車場: あり",
    "木造平屋建て トイレ 汲み取り 水道申込費 申込済",
    "#上水道完備 #汲取り #都市計画区域",
    "上水道・LPガス・下水汲取式",
    "トイレは汲み取り式です。",
    "トイレ：くみ取り",
])
def test_kumitori_positive(text):
    assert is_kumitori("古民家", text)[0]


@pytest.mark.parametrize("text", [
    "トイレは汲み取り式から水洗に改修済みです",
    "下水道に接続済み。水洗トイレ",
    "合併浄化槽の汲み取り清掃は年1回",
    "井戸水汲み上げポンプあり",
    "トイレ: 水洗洋式",
])
def test_kumitori_negative(text):
    assert not is_kumitori("古民家", text)[0]


@pytest.mark.parametrize("text", [
    "木造瓦葺２階建 | 専用住宅 | 大幅な補修が必要",
    "築61年 | 大規模改修必要（入居者負担）",
    "古民家130万円★（大規模修繕必要）",
    "大幅に補修必要（入居者負担）",
    "1階・2階ともに床が大きく抜けており、全面的な修繕が必要です。",
    "大規模な修繕・DIYを前提に考えていただく物件です",
    "屋根、外壁には大規模な補修を要します",
    "現状のまますぐに住める状態ではありません",
])
def test_major_repair_positive(text):
    assert needs_major_repair("古民家", text)[0]


@pytest.mark.parametrize("text", [
    "2025年春には大規模修繕を終え、昭和のモダンが息づく",
    "2021年4月に室内大規模リフォーム実施済みです",
    "大規模な補修・修繕が必要な箇所はないと確認しました",
    "多少の補修が必要です",
    "付近に廃屋状態の家も1〜2件あります",
])
def test_major_repair_negative(text):
    assert not needs_major_repair("古民家", text)[0]


def _listing(body):
    return db.Listing(source="t", listing_id="1", url="https://x", title="物件",
                      price=1_000_000, prefecture="岡山県", city="高梁市",
                      address="岡山県高梁市", area_land=None, area_building=None,
                      thumbnail_url=None, body=body, posted_at=None, property_type="house")


def test_should_skip_reasons():
    assert purge.should_skip(_listing("トイレ: 汲み取り")) == "汲み取り"
    assert purge.should_skip(_listing("大幅な補修が必要")) == "大幅修繕"
    assert purge.should_skip(_listing("トイレ: 水洗洋式")) is None


def test_purge_removes_but_keeps_favorites():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)

    def ins(lid, body):
        c.execute("INSERT INTO properties (source, listing_id, url, title, price, city, body,"
                  " first_seen_at, last_seen_at, status, property_type)"
                  " VALUES ('t', ?, 'https://x', '家', 1000000, '高梁市', ?, ?, ?, 'active', 'house')",
                  (lid, body, db.now_iso(), db.now_iso()))
        return c.execute("SELECT id FROM properties WHERE listing_id=?", (lid,)).fetchone()[0]
    a = ins("a", "トイレ: 汲み取り")
    b = ins("b", "大幅な補修が必要")
    fav = ins("fav", "トイレ: 汲み取り")
    ok = ins("ok", "トイレ: 水洗")
    c.execute("INSERT INTO favorites (property_id, starred_at) VALUES (?, ?)", (fav, db.now_iso()))
    st = purge.count_targets(c)
    assert st["kumitori"] == 1 and st["major_repair"] == 1
    purge.purge(c)
    left = {r[0] for r in c.execute("SELECT id FROM properties")}
    assert left == {fav, ok}
    assert a not in left and b not in left
