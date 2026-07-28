"""長野県 楽園信州空き家バンク scraper のパーサ／種別フィルタ単体テスト。ネットワーク不要。"""
from bs4 import BeautifulSoup

from src.scrapers import REGISTRY
from src.scrapers.rakuen_shinshu import MatsumotoRakuenScraper


def _block(kind_class, city_addr, bukken_id, price_man):
    return f"""
    <div class="boxStyleE {kind_class} clearfix">
      <a href="/bukken/{bukken_id}/"><img src="/img/bukken/1/{bukken_id}.jpg"></a>
      <a href="/bukken/{bukken_id}/">{city_addr}</a>
      価格 {price_man} 万円 土地面積 300.50m2 建物面積 90.00m2 築年月 1985年 間取 4DK
      <a href="/bukken/{bukken_id}/">▶詳しく見る</a>
    </div>
    """


def test_parse_chuko_house():
    html = _block("chuko", "松本市波田", "455947", "100")
    block = BeautifulSoup(html, "lxml").select_one("div.boxStyleE.chuko")
    r = MatsumotoRakuenScraper()._parse(block)
    assert r is not None
    assert r.listing_id == "455947"
    assert r.address_text == "長野県松本市波田"
    assert r.price_text == "100万円"
    assert r.area_land_text == "300.50㎡"
    assert r.area_building_text == "90.00㎡"
    assert r.url == "https://rakuen-akiya.jp/bukken/455947/"
    assert r.property_type_hint == "house"
    assert r.thumbnail_url == "https://rakuen-akiya.jp/img/bukken/1/455947.jpg"


def test_fetch_keeps_only_chuko(monkeypatch):
    """中古住宅(chuko)だけ収集し、貸家/店舗/土地は除外する。"""
    page = (
        "<html><body>"
        + _block("chuko", "松本市中央", "111", "300")
        + _block("kashiya", "松本市波田", "222", "5")      # 貸家 → 除外
        + _block("tochi", "松本市梓川", "333", "200")       # 土地 → 除外
        + _block("tenpo", "松本市島立", "444", "800")       # 店舗 → 除外
        + _block("chuko", "松本市寿", "555", "480")
        + "</body></html>"
    )

    class _Resp:
        content = page.encode("utf-8")

    monkeypatch.setattr("src.scrapers.rakuen_shinshu.polite_get", lambda c, u: _Resp())
    got = list(MatsumotoRakuenScraper().fetch(None))
    assert {r.listing_id for r in got} == {"111", "555"}


def test_registry_has_nagano():
    for k in ("matsumoto_rakuen", "shiojiri_rakuen", "ina_rakuen", "azumino_rakuen"):
        assert k in REGISTRY
