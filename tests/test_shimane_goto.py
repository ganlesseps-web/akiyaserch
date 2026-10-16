"""出雲市・五島市 空き家バンク scraper のパーサ単体テスト (固定HTML、ネットワーク不要)。

サイト改装で壊れたら気付けるよう、また 賃貸除外/土地判定/離島除外 が効くことを確認する。
"""
from src import purge
from src.scrapers import REGISTRY
from src.scrapers.akiya_athome import AkiyaAthomeBaseScraper
from src.scrapers.goto_akiyabank import build_listing as goto_build
from src.scrapers.goto_akiyabank import parse_detail as goto_detail
from src.scrapers.goto_akiyabank import parse_list as goto_list
from src.scrapers.izumo_akiyabank import build_listing as izumo_build
from src.scrapers.izumo_akiyabank import parse_detail as izumo_detail
from src.scrapers.izumo_akiyabank import parse_list as izumo_list


# ---------- 出雲市 ----------

def _izumo_card(num, price, address, layout="5LDK以上", area="大社地域"):
    layout_row = f"<tr><th>間取り</th><td>{layout}</td></tr>" if layout else ""
    return f"""
    <li data-marker-link="https://izumo-akiyataisaku.jp/vacant_house/{num}/"
        data-marker-image="https://i0.wp.com/izumo-akiyataisaku.jp/{num}.jpeg">
      <div class="content_listhed"><a href="https://izumo-akiyataisaku.jp/vacant_house/{num}/">
        <div class="area_box">{area}</div><div class="contentlist_taitl">{num}</div></a></div>
      <div class="contentlist_data"><table><tbody>
        {layout_row}
        <tr><th>宅地面積</th><td>263.71㎡</td></tr>
        <tr><th>価格</th><td>{price}</td></tr>
        <tr><th>所在地</th><td>{address}</td></tr>
      </tbody></table></div>
    </li>"""


def _izumo_detail(trade="売買", bunrui="建物", toilet="汲み取り"):
    return f"""<table>
      <tr><th>売買・賃貸</th><td>{trade}</td></tr>
      <tr><th>金額</th><td>1,000,000円</td></tr>
      <tr><th>分類</th><td>{bunrui}</td></tr>
      <tr><th>延床面積</th><td>120㎡</td></tr>
      <tr><th>トイレ</th><td>{toilet}</td></tr>
      <tr><th>駐車場</th><td>あり</td></tr>
    </table>"""


def test_izumo_list_parse():
    cards = izumo_list("<ul>" + _izumo_card("6-053", "1,000,000円", "出雲市大社町杵築西1875") + "</ul>")
    assert len(cards) == 1
    c = cards[0]
    assert c["id"] == "6-053"
    assert c["price"] == "1,000,000円"
    assert c["area"] == "大社地域"
    assert c["layout"] == "5LDK以上"


def test_izumo_sale_house_with_detail():
    card = izumo_list(_izumo_card("6-053", "1,000,000円", "出雲市大社町杵築西1875"))[0]
    r = izumo_build(card, izumo_detail(_izumo_detail()))
    assert r is not None
    assert r.address_text == "島根県出雲市大社町杵築西1875"
    assert r.price_text == "1,000,000円"
    assert r.property_type_hint == "house"
    assert "トイレ: 汲み取り" in r.body          # 汲み取り判定が効くよう本文に入る
    assert r.area_building_text == "120㎡"


def test_izumo_rental_dropped():
    card = izumo_list(_izumo_card("6-052", "40,000円", "出雲市大社町杵築南1202-2"))[0]
    assert izumo_build(card, izumo_detail(_izumo_detail(trade="賃貸"))) is None


def test_izumo_land_hint():
    card = izumo_list(_izumo_card("10-013", "800,000円", "出雲市外園町247", layout=""))[0]
    r = izumo_build(card, izumo_detail(_izumo_detail(bunrui="土地")))
    assert r.property_type_hint == "land"


def test_izumo_expensive_without_detail():
    """300万以上は詳細を読まない。間取りの有無で 建物/土地 を推定する。"""
    card = izumo_list(_izumo_card("1-178", "9,000,000円", "出雲市里方町22-1"))[0]
    assert izumo_build(card, None).property_type_hint == "house"
    card = izumo_list(_izumo_card("10-016", "6,900,000円", "出雲市小山町395-9", layout=""))[0]
    assert izumo_build(card, None).property_type_hint == "land"


# ---------- 五島市 ----------

def _goto_card(num, title, price_line, tags):
    lis = "".join(f"<li>{t}</li>" for t in tags)
    return f"""
    <section><h3>{title}</h3>
      <div><p>{price_line}</p><ul>{lis}</ul>
        <a href="https://goto.nagasaki-tabinet.com/iju/vacant-house/detail_{num}.html">link</a></div>
      <figure><img src="/iju/lsc/upfile/spot/{num}_1_m.jpg"></figure>
    </section>"""


GOTO_LIST = f"""<html><body><section class="wrap">
  {_goto_card("10220", "【NEW】物件No.781（五島市民・移住者・新婚家庭）向町", "売却：2,000,000円", ["購入", "福江地区"])}
  {_goto_card("10214", "物件No.773（五島市民）松山町", "賃貸：36,000円", ["賃貸", "福江地区"])}
  {_goto_card("10166", "物件No.735（移住者）富江町黒瀬", "売却：3,000,000円", ["購入", "交渉中", "富江地区"])}
  {_goto_card("10216", "物件No.776（移住者）玉之浦町玉之浦", "売却：要相談", ["購入", "玉之浦地区"])}
</section>
<ul><li><a href="index_2_4___0_.html" rel="next">次へ</a></li></ul></body></html>"""

GOTO_DETAIL = """<section id="detailBasic"><dl>
  <dt>状況</dt><dd>受付中</dd>
  <dt>所在地</dt><dd>五島市向町</dd>
  <dt>土地面積</dt><dd>387.29平方ｍ</dd>
  <dt>建物面積</dt><dd>115.7平方ｍ</dd>
  <dt>利用状況</dt><dd>2020年（令和2年）頃から空き家</dd>
  <dt>トイレ</dt><dd>汲み取り</dd>
</dl></section>"""


def test_goto_list_parse_and_next_page():
    cards, nxt = goto_list(GOTO_LIST)
    assert [c["id"] for c in cards] == ["10220", "10214", "10166", "10216"]   # 外側の section は数えない
    assert nxt == "https://goto.nagasaki-tabinet.com/iju/vacant-house/index_2_4___0_.html"
    by_id = {c["id"]: c for c in cards}
    assert by_id["10220"]["price"] == 2_000_000
    assert by_id["10220"]["district"] == "福江地区"
    assert by_id["10214"]["sale"] is None            # 賃貸のみ → fetch で読み飛ばす
    assert by_id["10216"]["sale"] == "要相談"
    assert by_id["10216"]["price"] is None
    assert by_id["10166"]["negotiating"] is True


def test_goto_build_with_detail():
    card = goto_list(GOTO_LIST)[0][0]
    r = goto_build(card, goto_detail(GOTO_DETAIL))
    assert r.address_text == "長崎県五島市向町"
    assert r.title.startswith("物件No.781")          # 【NEW】は外す
    assert "トイレ: 汲み取り" in r.body
    assert "2020年" in r.body
    assert r.area_land_text == "387.29平方ｍ"


def test_goto_build_without_detail_uses_title_town():
    card = goto_list(GOTO_LIST)[0][2]
    r = goto_build(card, None)
    assert r.address_text == "長崎県五島市富江町黒瀬"
    assert r.title.startswith("【交渉中】")


def test_goto_sold_dropped():
    card = goto_list(GOTO_LIST)[0][0]
    assert goto_build(card, {"状況": "成約済"}) is None


def test_small_islands_excluded_by_district():
    """嵯峨島・久賀島などは除外。福江島・奈留島は通す。"""
    assert purge.district_skip_reason("五島市", "長崎県五島市三井楽町嵯峨島") is not None
    assert purge.district_skip_reason("五島市", "長崎県五島市蕨町") is not None
    assert purge.district_skip_reason("五島市", "長崎県五島市向町") is None
    assert purge.district_skip_reason("五島市", "長崎県五島市奈留町浦") is None


def test_izumo_north_coast_excluded():
    assert purge.district_skip_reason("出雲市", "島根県出雲市大社町鵜峠110") is not None
    assert purge.district_skip_reason("出雲市", "島根県出雲市斐川町坂田1742") is None


# ---------- 登録 ----------

def test_registered_and_grouped():
    for name in ("izumo_akiyabank", "goto_akiyabank", "matsue_akiyabank",
                 "unnan_akiyabank", "okuizumo_akiyabank"):
        assert name in REGISTRY
    # アットホーム系 (Mac担当) か それ以外 (GitHub担当) か
    for name in ("matsue_akiyabank", "unnan_akiyabank", "okuizumo_akiyabank"):
        assert issubclass(REGISTRY[name], AkiyaAthomeBaseScraper)
    for name in ("izumo_akiyabank", "goto_akiyabank"):
        assert not issubclass(REGISTRY[name], AkiyaAthomeBaseScraper)
