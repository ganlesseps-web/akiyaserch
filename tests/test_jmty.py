"""ジモティ (jmty.jp) スクレイパのテスト。fixture HTML のみ・通信なし。"""
from datetime import date
from pathlib import Path

from src.scrapers.jmty import JmtyScraper, _created_iso
from src import normalize, purge

FIX = Path(__file__).parent / "fixtures" / "jmty_list.html"
AREA_OKAYAMA = {"pref": "okayama", "pref_ja": "岡山県", "code": "a-648-ibara", "label": "井原市", "towns": ["井原市"]}
AREA_KANZAKI = {"pref": "hyogo", "pref_ja": "兵庫県", "code": "a-1-kanzaki", "label": "神崎郡",
                "towns": ["市川町", "神河町"]}


def _rows(area=AREA_OKAYAMA):
    return list(JmtyScraper()._parse_list(FIX.read_bytes(), area))


def test_direct_posts_only():
    """詳細リンクの無い「提携サイト」転載は取らない。"""
    ids = {r.listing_id for r in _rows()}
    assert "abc123" in ids
    assert not any("小田中" in r.title for r in _rows())


def test_skips_closed_and_rental():
    ids = {r.listing_id for r in _rows()}
    assert "done1" not in ids      # 受付終了
    assert "rent1" not in ids      # 【賃貸】= 家賃を価格と誤認しないため除外


def test_parses_price_city_date():
    r = next(r for r in _rows() if r.listing_id == "abc123")
    assert r.price_text == "68万円"
    assert r.address_text == "岡山県井原市"
    assert r.posted_at is not None and r.posted_at.endswith("-08-10")
    assert r.thumbnail_url and r.thumbnail_url.startswith("https://cdn.jmty.jp")
    assert r.url == "https://jmty.jp/okayama/est-buy/article-abc123"
    n = normalize.normalize(r)
    assert n.price == 680_000 and n.city == "井原市" and n.property_type == "house"
    assert purge.should_skip(n) is None


def test_town_name_completed_from_title():
    """一覧は「神崎郡」までしか載らないので、タイトルの町名で補う。"""
    r = next(r for r in _rows(AREA_KANZAKI) if r.listing_id == "town1")
    assert r.address_text == "兵庫県神崎郡市川町"
    n = normalize.normalize(r)
    assert n.city and "市川町" in n.city
    assert n.price == 180_000


def test_land_giveaway_detected_as_land():
    """価格'-'の土地譲渡は種別=土地として、収集ルールで弾かれる。"""
    r = next(r for r in _rows() if r.listing_id == "land1")
    assert r.property_type_hint == "land"
    n = normalize.normalize(r)
    assert n.price is None
    assert purge.should_skip(n) == "土地"


def test_created_iso_wraps_year():
    """年が無い「作成12月20日」は、今日が1月なら前年として解釈する。"""
    assert _created_iso("作成12月20日", today=date(2026, 1, 5)) == "2025-12-20"
    assert _created_iso("更新8月15日 作成8月10日", today=date(2026, 9, 12)) == "2026-08-10"
    assert _created_iso("日付なし") is None


def test_areas_config_loads():
    from src.scrapers.jmty import _load_areas
    areas = _load_areas()
    assert len(areas) >= 60
    assert all({"pref", "pref_ja", "code", "towns"} <= set(a) for a in areas)
    labels = {a["label"] for a in areas}
    assert "高梁市" in labels and "津山市" in labels
