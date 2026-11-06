"""山梨県の市独自サイト scraper (南アルプス市 / 甲州市) のパーサ単体テスト。ネットワーク不要。"""
from bs4 import BeautifulSoup

from src.scrapers import REGISTRY
from src.scrapers.koshu_akiyabank import KoshuAkiyabankScraper, _ROW_RE
from src.scrapers.minamialps_akiyabank import MinamiAlpsAkiyabankScraper


# ---- 南アルプス市 (カード型) ----

def _malps_card(no, chimei, kind, price):
    return f"""
    <li class="p-bank__negotiable__list__item">
      <a href="/iju/akiyabank/2{no}.html"><img src="/fs/1/photo_{no}.jpg"></a>
      <span class="p-bank__negotiable__tag__text">街なかエリア</span>
      <span class="p-bank__negotiable__tag__text">追加</span>
      <a class="p-bank__negotiable__link" href="/iju/akiyabank/2{no}.html">物件番号:{no}</a>
      <div>所在地: {chimei}</div>
      <div>物件内容: {kind}</div>
      <div>価格: {price}</div>
    </li>
    """


def _parse_malps(html):
    li = BeautifulSoup(html, "lxml").select_one("li.p-bank__negotiable__list__item")
    return MinamiAlpsAkiyabankScraper()._parse_item(li)


def test_malps_building_kept():
    r = _parse_malps(_malps_card("206", "南アルプス市山寺", "土地・建物", "1,775,860円"))
    assert r is not None
    assert r.listing_id == "206"
    assert r.address_text == "山梨県南アルプス市山寺"
    assert r.price_text == "1,775,860円"
    assert r.url.endswith("/iju/akiyabank/2206.html")
    assert r.property_type_hint == "house"
    assert r.thumbnail_url.startswith("https://www.city.minami-alps.yamanashi.jp/")


def test_malps_land_only_filtered():
    assert _parse_malps(_malps_card("300", "南アルプス市徳永", "土地", "500万円")) is None


# ---- 甲州市 (テキスト正規表現) ----

def test_koshu_row_regex():
    text = "新規登録 売買 No.159 山梨県甲州市大和町初鹿野 価格/900万円 交渉中 賃貸 No.160 山梨県甲州市塩山 価格/5万円"
    rows = _ROW_RE.findall(text)
    assert len(rows) == 2
    assert rows[0][1] == "売買" and rows[0][2] == "159" and rows[0][4] == "900万円"


def test_koshu_fetch_filters(monkeypatch):
    html = (
        "<div>新規登録 売買 No.159 山梨県甲州市大和町初鹿野 価格/900万円</div>"
        "<div>交渉中 賃貸 No.160 山梨県甲州市塩山上於曽 価格/5万円</div>"     # 賃貸→除外
        "<div>成約済 売買 No.161 山梨県甲州市勝沼町 価格/300万円</div>"       # 成約→除外
        "<div>募集中 売買 No.162 山梨県甲州市塩山千野 価格/450万円</div>"
    )

    class _Resp:
        content = html.encode("utf-8")

    monkeypatch.setattr("src.scrapers.koshu_akiyabank.polite_get", lambda c, u: _Resp())
    got = list(KoshuAkiyabankScraper().fetch(None))
    assert {r.listing_id for r in got} == {"159", "162"}      # 賃貸・成約は除外
    r159 = next(r for r in got if r.listing_id == "159")
    assert r159.price_text == "900万円"
    assert r159.address_text == "山梨県甲州市大和町初鹿野"
    assert r159.url.endswith("/details/no159.html")


def test_registry_has_yamanashi():
    for k in ("nirasaki_akiyabank", "minamialps_akiyabank", "koshu_akiyabank"):
        assert k in REGISTRY


# ---- 身延町 (一覧の result_box) / 都留市 (記事の見出し) 2026-11-06 ----

def test_minobu_parse_list():
    from src.scrapers.minobu_akiyabank import parse_list
    html = """<div id="results">
    <div class="result_box"><div class="result_img"><div class="result_img_status">交渉中</div>
    <div class="result_img_house"><a href="/akiya/ijyu/10369.html"><img src="/uploaded/life/1.jpg"/></a></div></div>
    <div class="result_txt"><a class="result_title" href="/akiya/ijyu/10369.html">New!（空き家）身延町下山</a>
    <dl class="result_data"><div class="result_data_item data_price"><dt>値段</dt><dd>（売買）3,000,000円</dd></div>
    <div class="result_data_item data_place"><dt>所在地</dt><dd></dd>身延町下山</div></dl></div></div></div>"""
    [r] = parse_list(html)
    assert (r["id"], r["price"], r["place"], r["status"]) == ("10369", "3,000,000円", "身延町下山", "交渉中")
    assert r["img"] == "https://www.town.minobu.lg.jp/uploaded/life/1.jpg"


def test_tsuru_parse_list_sale_only():
    from src.scrapers.tsuru_akiyabank import parse_list
    html = """
    <a href="https://kurashi.osusowake.life/sumai/3831/">住まいについて 売家 物件情報 No.167 大幡の物件【売却：100万円】</a>
    <a href="https://kurashi.osusowake.life/sumai/3775/">No.166 小野の物件【賃貸：1万円】</a>
    <a href="https://kurashi.osusowake.life/sumai/3751/">【空き家内見に便利】1時間330円〜の格安カーシェア</a>
    <a href="https://kurashi.osusowake.life/sumai/2929/">NO149 境の物件 売却【850万】</a>"""
    got = {r["no"]: (r["area"], r["man"]) for r in parse_list(html)}
    assert got == {"167": ("大幡", "100"), "149": ("境", "850")}


def test_registry_has_new_yamanashi():
    for k in ("minobu_akiyabank", "tsuru_akiyabank"):
        assert k in REGISTRY
