"""再販目線フィルタ (ハード除外 / ⚠️警告 / 自治体マスタ / AI判定) の単体テスト。"""
import pytest

from src import municipalities as M
from src import resale_ai
from src.normalize import detect_resale_ng, detect_resale_warnings, normalize
from src.scrapers.base import RawListing


def _raw(body, title="物件"):
    return RawListing(
        source="t", listing_id="1", url="https://x", title=title, price_text="100万円",
        address_text="岡山県高梁市成羽町", area_land_text=None, area_building_text=None,
        thumbnail_url=None, body=body, posted_at=None,
    )


# ---- ハード除外 ----

@pytest.mark.parametrize("body,reason_part", [
    ("再建築不可の物件です", "再建築不可"),
    ("間口が2m以下のため、単独では再建築ができません。", "再建築ができません"),
    ("接道なしのため要注意", "接道なし"),
    ("本物件は借地物件です。毎月の地代が必要", "借地"),
    ("共有持分の売却となります", "共有持分"),
    ("水道は井戸水のみです", "井戸水のみ"),
    ("浸水想定 3.5m の区域内", "浸水想定3.5m"),
    ("家屋倒壊等氾濫想定区域に該当します", "家屋倒壊等氾濫想定区域"),
    ("土砂災害特別警戒区域に指定", "土砂災害特別警戒区域"),
])
def test_resale_ng_positive(body, reason_part):
    ng, reason = detect_resale_ng(None, body)
    assert ng, f"should be NG: {body}"
    assert reason_part in reason


@pytest.mark.parametrize("body", [
    "接道良好、再建築可能です",                      # 肯定形
    "鎌倉市審査会の承認があれば再建築ができます。",      # 「できます」を誤検知しない
    "隣地を購入できれば再建築可能になります",
    "土地権利は所有権です。借地ではありません",
    "合併浄化槽、上水道あり",
    "井戸あり、上水道も引込済みです",                 # 井戸+上水道の併用はOK
    "浸水想定 1.0m の区域",                        # 3m未満はハード除外しない
    "",
])
def test_resale_ng_negative(body):
    ng, _ = detect_resale_ng(None, body)
    assert not ng, f"should NOT be NG: {body}"


def test_resale_ng_empty():
    assert detect_resale_ng(None, None) == (False, "")


# ---- ⚠️警告 ----

@pytest.mark.parametrize("body,tag", [
    ("トイレは和式です", "和式トイレ"),
    ("駐車場なしです", "駐車場なし"),
    ("汲み取り式トイレ", "汲み取り式"),
    ("単独浄化槽です", "単独浄化槽"),
    ("市街化調整区域内", "市街化調整区域"),
    ("擁壁のある土地", "擁壁・傾斜地"),
    ("告知事項ありの物件", "告知事項あり"),
    ("長期空き家となっています", "長期空き家"),
    ("バス便のみの立地", "バス便のみ"),
    ("建物に傾きあり", "傾きあり"),
    ("空き家となって7年経過", "空き家5年超"),
    ("浸水想定 1.0m", "浸水想定あり(民泊不向き)"),
])
def test_warning_tags(body, tag):
    assert tag in detect_resale_warnings(None, body)


def test_warning_negative_context():
    """打ち消し文脈は警告にしない。"""
    assert "和式トイレ" not in detect_resale_warnings(None, "和式から洋式に交換済みです")
    assert "井戸あり(上水道要確認)" not in detect_resale_warnings(None, "井戸あり、上水道も引込済")


def test_warnings_empty():
    assert detect_resale_warnings(None, None) == []
    assert detect_resale_warnings(None, "普通の一軒家です") == []


def test_normalize_sets_resale_fields():
    listing = normalize(_raw("再建築不可の物件"))
    assert listing.resale_ng == 1 and listing.resale_ng_reason

    listing2 = normalize(_raw("和式トイレ、汲み取り式です"))
    assert listing2.resale_ng == 0
    assert "和式トイレ" in (listing2.resale_warnings or "")
    assert "汲み取り式" in (listing2.resale_warnings or "")

    listing3 = normalize(_raw("きれいな一軒家です"))
    assert listing3.resale_ng == 0 and listing3.resale_warnings is None


# ---- 自治体マスタ ----

def test_municipality_lookup_normalizes_names():
    assert M.lookup("多可郡多可町加美区").name == "多可町"   # 郡+区を落とす
    assert M.lookup("神崎郡神河町").name == "神河町"
    assert M.lookup("吉野郡下市").name == "下市町"           # alias 経由
    assert M.lookup("高梁市").name == "高梁市"
    assert M.lookup("架空の市") is None
    assert M.lookup(None) is None


def test_user_requested_cities_are_not_warned():
    """ユーザーが自ら指定した市が小規模警告で潰れないこと (人口3万カット廃止の趣旨)。"""
    for city in ("高梁市", "韮崎市", "甲州市", "南アルプス市", "松本市",
                 "安曇野市", "塩尻市", "伊那市", "赤磐市"):
        assert M.market_warning(city) is None, f"{city} should not be warned"


def test_thin_market_warns():
    """賃貸需要も観光も無く1万人未満の自治体だけ警告。"""
    assert M.market_warning("東吉野村") is not None      # 1,281人・両フラグなし
    assert M.market_warning("伊根町") is None            # 1,691人だが観光あり
    assert M.market_warning("奈義町") is None            # 5,100人だが駐屯地(賃貸需要)


def test_unknown_municipality_passes():
    """未登録の自治体は警告を出さない (デフォルト通過)。"""
    assert M.market_warning("登録されていない町") is None


# ---- AI 判定 ----

def test_parse_response_valid():
    r = resale_ai.parse_response(
        'ゴミ {"toilet":"和式","bath":"要修繕","lifeline":"浄化槽","parking":"あり",'
        '"vacancy_hint":"長期","verdict":"警告","reasons":"和式と浴室修繕"} 余計'
    )
    assert r["toilet"] == "和式" and r["verdict"] == "警告"
    assert r["reasons"] == "和式と浴室修繕"


def test_parse_response_clamps_unknown_values():
    """許容外の値は「不明」/「検討可」に丸める。"""
    r = resale_ai.parse_response('{"toilet":"へんな値","verdict":"あやしい"}')
    assert r["toilet"] == "不明"
    assert r["verdict"] == "検討可"


def test_parse_response_no_json():
    with pytest.raises(ValueError):
        resale_ai.parse_response("JSONが含まれていません")


def test_prompt_hash_stable():
    assert resale_ai.prompt_hash() == resale_ai.prompt_hash()
    assert len(resale_ai.prompt_hash()) == 16
