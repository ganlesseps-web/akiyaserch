"""normalize の単体テスト。住所/価格/面積パースの境界を確認。"""
from src.normalize import normalize, _parse_price, _parse_area, _extract_prefecture, _extract_city
from src.scrapers.base import RawListing


def _raw(**kwargs) -> RawListing:
    base = dict(
        source="minna_0en",
        listing_id="3378",
        url="https://zero.estate/zero/kanto/3378_okegawa/",
        title="埼玉県桶川市 0円物件",
        price_text="0円",
        address_text="埼玉県桶川市大字加納字後谷2693番3",
        area_land_text="294.52㎡ (89.09坪)",
        area_building_text=None,
        thumbnail_url=None,
        body=None,
        posted_at=None,
    )
    base.update(kwargs)
    return RawListing(**base)


def test_normalize_basic():
    listing = normalize(_raw())
    assert listing.price == 0
    assert listing.prefecture == "埼玉県"
    assert listing.city == "桶川市"
    assert listing.area_land == 294.52


def test_multi_address_takes_first():
    listing = normalize(_raw(
        address_text="①埼玉県桶川市大字加納字後谷2693番3 / ②埼玉県加納字後谷2693番4"
    ))
    assert listing.prefecture == "埼玉県"
    assert listing.address == "埼玉県桶川市大字加納字後谷2693番3"


def test_parse_price_man():
    assert _parse_price("100万円") == 1_000_000
    assert _parse_price("1,200万円") == 12_000_000
    assert _parse_price("3億2,000万円") == 320_000_000
    assert _parse_price("0円") == 0
    assert _parse_price(None) is None


def test_parse_area():
    assert _parse_area("294.52㎡ (89.09坪)") == 294.52
    assert _parse_area("12,345.67㎡") == 12345.67
    assert _parse_area(None) is None


def test_prefecture_extraction():
    assert _extract_prefecture("大阪府大阪市北区梅田") == "大阪府"
    assert _extract_prefecture("北海道札幌市") == "北海道"
    assert _extract_prefecture("ない住所") is None


def test_city_extraction():
    assert _extract_city("大阪府大阪市北区梅田", "大阪府") == "大阪市北区"
    assert _extract_city("兵庫県神戸市", "兵庫県") == "神戸市"
    assert _extract_city("徳島県美馬郡つるぎ町", "徳島県") == "美馬郡つるぎ町"
    # 字レベルを誤って吸わない (greedy bug 再発防止)
    assert _extract_city("宮崎県串間市大字西方字下タ町15020番地1", "宮崎県") == "串間市"
    assert _extract_city("北海道幌泉郡えりも町字本町20", "北海道") == "幌泉郡えりも町"
    assert _extract_city("秋田県秋田市八橋本町1丁目", "秋田県") == "秋田市"


def test_tokyo_to():
    listing = normalize(_raw(address_text="東京都千代田区丸の内"))
    assert listing.prefecture == "東京都"
    assert listing.city == "千代田区"
