"""高梁市 空き家バンク scraper のパーサ単体テスト (固定HTML、ネットワーク不要)。

サイト改装で壊れたら気付けるよう、また「中部〜南部」フィルタが効くことを確認する。
"""
from bs4 import BeautifulSoup

from src.scrapers import REGISTRY
from src.scrapers.akiya_athome import AkaiwaAkiyabankScraper
from src.scrapers.takahashi_akiyabank import TakahashiAkiyabankScraper


def _card(area, num, sale, status="受付中", title="サンプル物件", rent="-"):
    return f"""
    <li class="bank__list-item">
      <h4>{title}</h4>
      <div class="bank__gallery-large"><img src="https://takahashi-akiyabank.com/wp/{num}.jpg"></div>
      <span class="bank__tag-item">#農地付き</span>
      <div class="bank__info-status"><span class="bank__info-value">{status}</span></div>
      <table class="bank__info-table">
        <tr><th class="bank__info-table-th">エリア</th><td class="bank__info-table-td">{area}</td></tr>
        <tr><th class="bank__info-table-th">物件番号</th><td class="bank__info-table-td">{num}</td></tr>
        <tr><th class="bank__info-table-th">賃貸</th><td class="bank__info-table-td">{rent}</td></tr>
        <tr><th class="bank__info-table-th">売買</th><td class="bank__info-table-td">{sale}</td></tr>
      </table>
      <a class="bank__info-link" href="https://takahashi-akiyabank.com/bank/{num}/">詳細</a>
    </li>
    """


def _parse(html):
    li = BeautifulSoup(html, "lxml").select_one(".bank__list-item")
    return TakahashiAkiyabankScraper()._parse_item(li)


def test_parse_shigaichi_kept():
    r = _parse(_card("市街地", "745", "1650万円"))
    assert r is not None
    assert r.listing_id == "745"
    assert r.price_text == "1650万円"
    assert r.address_text == "岡山県高梁市"          # 市街地は地名でないので市まで
    assert r.url == "https://takahashi-akiyabank.com/bank/745/"
    assert r.property_type_hint == "house"
    assert r.thumbnail_url.endswith("745.jpg")


def test_parse_nariwa_appends_town():
    r = _parse(_card("成羽町", "743", "100万円"))
    assert r is not None
    assert r.address_text == "岡山県高梁市成羽町"      # 実在の町名は住所に足す


def test_area_outside_range_filtered():
    """北部(有漢町)・西の山間(川上町/備中町)は中部〜南部フィルタで除外。"""
    assert _parse(_card("有漢町", "1", "500万円")) is None
    assert _parse(_card("川上町", "2", "500万円")) is None
    assert _parse(_card("備中町", "3", "500万円")) is None


def test_closed_status_filtered():
    assert _parse(_card("市街地", "9", "500万円", status="成約済")) is None


def test_rental_only_has_no_price():
    r = _parse(_card("高梁地域", "741", "-", rent="2万円"))
    assert r is not None
    assert r.price_text is None                       # 売買が無ければ価格不明
    assert "賃貸:2万円" in (r.body or "")


def test_registry_has_new_sources():
    assert "takahashi_akiyabank" in REGISTRY
    assert "akaiwa_akiyabank" in REGISTRY


def test_akaiwa_config():
    s = AkaiwaAkiyabankScraper()
    assert s.subdomain == "akaiwa-c33213"
    assert s.prefecture == "岡山県"
    assert s.area_path == ""
