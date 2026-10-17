"""長崎市の空き家バンク / 農地付き除外 のテスト (通信なし)。"""
from src.normalize import is_farmland_bundled
from src.scrapers.nagasaki_akiyabank import parse_list
from src import db, purge

LIST_HTML = """
<div class="result_box">
  <a href="/akiya/87108.html">【売買】桜馬場中学校近くの2階建て</a>
  物件種別 一戸建て 販売価格 3,000,000円 間取り 4DK 延べ面積 103.78平方メートル
  築年数 49年（1977年8月5日） 長崎市鳴滝1丁目 ※詳細はお問い合わせください。
</div>
<div class="result_box">
  <a href="/akiya/90000.html">【売買】長崎市内が見える眺めの良い2階建て</a>
  物件種別 一戸建て 販売価格 2,000,000円 長崎市立山3丁目 ※詳細はお問い合わせください。
</div>
<div class="result_box">
  <a href="/akiya/89130.html">【売買】見晴らしのいい愛宕4丁目の空き地</a>
  物件種別 土地 販売価格 1,000,000円 長崎市愛宕4丁目
</div>
<div class="result_box">
  <a href="/akiya/36141.html">【賃貸】鳴滝地区の家</a>
  物件種別 一戸建て 長崎市鳴滝2丁目
</div>
""".encode("utf-8")


def test_parse_list_fields():
    cards = {c["id"]: c for c in parse_list(LIST_HTML)}
    c = cards["87108"]
    assert c["price"] == 3_000_000 and c["kind"] == "一戸建て"
    assert c["address"] == "長崎市鳴滝1丁目"
    assert c["area"] == "103.78"


def test_address_not_taken_from_title():
    """題名「長崎市内が見える…」を住所と誤認しない (実際に起きた)。"""
    assert {c["id"]: c for c in parse_list(LIST_HTML)}["90000"]["address"] == "長崎市立山3丁目"


def test_rental_only_has_no_price():
    assert {c["id"]: c for c in parse_list(LIST_HTML)}["36141"]["price"] is None


# ---- 農地付き ----

def test_farmland_positive():
    for t in ("農地付き空き家", "田畑付きの古民家", "畑付き 平屋", "#農地付き",
              "地目：畑 300㎡", "農地法第3条の許可が必要", "農業委員会の許可が必要"):
        assert is_farmland_bundled(t, "")[0], t


def test_farmland_negative():
    for t in ("家庭菜園ができる庭あり", "農地は含みません", "農地転用済みの宅地",
              "地目：宅地", "田舎暮らし 庭付き", "畑仕事が好きな方に",
              "耕作希望者に敷地隣接地の農地あり"):
        assert not is_farmland_bundled(t, "")[0], t


def _listing(title, body=""):
    return db.Listing(
        source="t", listing_id="1", url="u", title=title, price=1_000_000,
        prefecture="岡山県", city="高梁市", address="岡山県高梁市", area_land=None,
        area_building=None, thumbnail_url=None, body=body, posted_at=None,
        property_type="house",
    )


def test_should_skip_farmland():
    assert purge.should_skip(_listing("高台にある農地付き物件")) == "農地付き"
    assert purge.should_skip(_listing("駅近の平屋")) is None
