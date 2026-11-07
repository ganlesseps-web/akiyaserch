"""SUUMO 中古一戸建て (src/scrapers/suumo.py)。一覧の作りは 2026-11-07 の長崎市のページから。"""
from src.scrapers import REGISTRY
from src.scrapers.suumo import AREAS, SuumoScraper, _man, parse_list


def _unit(nc: str, price: str) -> str:
    return f"""<div class="property_unit "><div class="property_unit-content">
    <h2 class="property_unit-title"><a href="/chukoikkodate/nagasaki/sc_nagasaki/nc_{nc}/">西小島２ {price}</a></h2>
    <img src="data:image/gif;base64,R0l" rel="https://img01.suumo.com/jj/resizeImage?src=a.jpg"/>
    <div class="dottable-line"><dl><dt class="dottable-vm">販売価格</dt><dd><span>{price}</span></dd></dl></div>
    <div class="dottable-line"><dl><dt>所在地</dt><dd>長崎県長崎市西小島２</dd></dl>
    <dl><dt>沿線・駅</dt><dd>長崎バス「浜の町」徒歩12分</dd></dl></div>
    <div class="dottable-line"><dl><dt>土地面積</dt><dd>26.31m<sup>2</sup>（登記）</dd></dl>
    <dl><dt>間取り</dt><dd>3DK</dd></dl></div>
    <div class="dottable-line"><dl><dt>建物面積</dt><dd>18.18m<sup>2</sup>（登記）</dd></dl>
    <dl><dt>築年月</dt><dd>1965年4月</dd></dl></div></div></div>"""


def test_parse_list():
    [r] = parse_list(_unit("20709276", "60万円"))
    assert r["id"] == "20709276"
    assert r["url"] == "https://suumo.jp/chukoikkodate/nagasaki/sc_nagasaki/nc_20709276/"
    assert (r["price"], r["address"], r["land"], r["building"]) == (
        "60万円", "長崎県長崎市西小島２", "26.31m2（登記）", "18.18m2（登記）")
    assert r["img"] == "https://img01.suumo.com/jj/resizeImage?src=a.jpg"


def test_man():
    assert _man("60万円") == 60
    assert _man("1億2000万円") == 12000
    assert _man("価格未定") is None


class _Resp:
    def __init__(self, html):
        self.content = html.encode()


def test_fetch_keeps_cheap_and_stops_after_expensive(monkeypatch):
    from src.scrapers import suumo
    pages = {
        # 広告枠 (高い) → 安い順。最後が300万円超なので2ページ目は見ない
        "https://suumo.jp/chukoikkodate/nagasaki/sc_nagasaki/":
            _unit("1", "1449万円") + _unit("2", "60万円") + _unit("3", "300万円") + _unit("4", "480万円"),
    }
    asked = []

    def fake_get(client, url):
        asked.append(url)
        return _Resp(pages.get(url, ""))

    monkeypatch.setattr(suumo, "polite_get", fake_get)
    monkeypatch.setattr(suumo, "AREAS", [("nagasaki", "nagasaki")])
    got = [r.listing_id for r in SuumoScraper().fetch(None)]
    assert got == ["2", "3"]
    assert asked == ["https://suumo.jp/chukoikkodate/nagasaki/sc_nagasaki/"]


def test_areas_and_registry():
    assert ("nagasaki", "nagasaki") in AREAS
    assert sum(p == "yamanashi" for p, _ in AREAS) == 17
    assert "suumo" in REGISTRY
