"""賃貸 (山梨・SUUMO賃貸一戸建て) のテスト (2026-11-17)。"""
import sqlite3

import pytest

from src import db, filter as flt, purge
from src.scrapers import suumo_chintai
from src.web import app as webapp

HTML = """
<div class="cassetteitem">
 <div class="cassetteitem_content-label"><span>賃貸一戸建て</span></div>
 <div class="cassetteitem_content-title">石原邸</div>
 <ul class="cassetteitem_detail">
  <li class="cassetteitem_detail-col1">山梨県甲府市富竹１</li>
  <li class="cassetteitem_detail-col2"><div class="cassetteitem_detail-text">ＪＲ中央線/甲府駅 歩38分</div><div class="cassetteitem_detail-text"></div></li>
  <li class="cassetteitem_detail-col3"><div>築54年</div><div>2階建</div></li>
 </ul>
 <div class="cassetteitem_object-item"><img rel="https://img01.suumo.com/a.jpg"></div>
 <table><tbody><tr class="js-cassette_link">
  <td><input name="bc" value="100536905331"></td>
  <td><span class="cassetteitem_price--rent">6.5万円</span><span class="cassetteitem_price--administration">3000円</span></td>
  <td><span class="cassetteitem_price--deposit">12万円</span><span class="cassetteitem_price--gratuity">-</span></td>
  <td><span class="cassetteitem_madori">3LDK</span><span class="cassetteitem_menseki">69.56m<sup>2</sup></span></td>
  <td><a href="/chintai/jnc_000110480475/?bc=100536905331">詳細</a></td>
 </tr></tbody></table>
</div>
"""


def test_parse_list_reads_rent_and_layout():
    rows = suumo_chintai.parse_list(HTML)
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "100536905331"
    assert r["rent"] == 65000 and r["fee"] == 3000
    assert r["layout"] == "3LDK"
    assert r["url"] == "https://suumo.jp/chintai/jnc_000110480475/"
    assert r["station"] == "ＪＲ中央線/甲府駅 歩38分"


def test_yen():
    assert suumo_chintai._yen("7万円") == 70000
    assert suumo_chintai._yen("-") == 0
    assert suumo_chintai._yen("3,000円") == 3000


def test_purge_skips_expensive_or_small_rent():
    assert purge.should_skip(_raw(price_text="90000円"))
    assert purge.should_skip(_raw(body="間取り 2LDK"))
    assert not purge.should_skip(_raw())


def _raw(price_text="70000円", body="間取り 3LDK"):
    from src.normalize import normalize
    from src.scrapers.base import RawListing
    return normalize(RawListing(
        source="suumo_chintai", listing_id="1", url="https://x", title="【賃貸】家",
        price_text=price_text, address_text="山梨県甲府市", area_land_text=None,
        area_building_text=None, thumbnail_url=None, body=body, posted_at=None,
        property_type_hint="house", deal_type="rent",
    ))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db._run_migrations(c)
    yield c
    c.close()


def _insert(conn, lid, **kw):
    f = dict(source="t", listing_id=lid, url="https://x", title="家", price=70000,
             prefecture="山梨県", city="甲府市", address="山梨県甲府市", body="",
             first_seen_at=db.now_iso(), last_seen_at=db.now_iso())
    f.update(kw)
    conn.execute(f"INSERT INTO properties ({','.join(f)}) VALUES ({','.join('?'*len(f))})", tuple(f.values()))


def test_rent_only_in_rent_tab(conn):
    _insert(conn, "r1", deal_type="rent", layout_rooms=3)
    _insert(conn, "r2", deal_type="rent", layout_rooms=2)
    _insert(conn, "b1", price=1_000_000)
    assert [r["listing_id"] for r in webapp._query_rows(conn, "rent", "new", None)] == ["r1"]
    assert [r["listing_id"] for r in webapp._query_rows(conn, "all", "new", None)] == ["b1"]
    c = webapp._counts(conn)
    assert c["rent"] == 1 and c["all"] == 1


def test_filter_rent(conn):
    _insert(conn, "r1", deal_type="rent", layout_rooms=4)
    _insert(conn, "r2", deal_type="rent", price=80000)
    cfg = flt.FilterConfig.load()
    rows = {r["listing_id"]: r for r in conn.execute("SELECT * FROM properties")}
    assert flt.passes(conn, rows["r1"], cfg)[0] is ("山梨県" in cfg.prefectures)
    assert flt.passes(conn, rows["r2"], cfg)[0] is False
