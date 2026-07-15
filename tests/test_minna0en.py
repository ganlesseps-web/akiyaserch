"""みんなの0円物件 (tRPC API 版) のパーサ／フィルタ単体テスト。ネットワーク不要。"""
from src.scrapers.minna_0en import MinnaZeroEnScraper


def _item(**over):
    base = dict(
        id=1, title="テスト0円物件", prefecture="岡山県", city="高梁市",
        address="岡山県高梁市", propertyType="土地・建物", publicStatus="募集中",
        builtYear="1970年", specialNotes='["残置物あり","長期空き家"]',
        images=[{"imageUrl": "https://x/a.jpg", "sortOrder": 1},
                {"imageUrl": "https://x/b.jpg", "sortOrder": 0}],
        approvedAt="2026-07-01T00:00:00.000Z", createdAt="2026-06-01T00:00:00.000Z",
    )
    base.update(over)
    return base


def test_item_to_raw_house():
    r = MinnaZeroEnScraper._item_to_raw(_item())
    assert r is not None
    assert r.listing_id == "1"
    assert r.price_text == "0円"
    assert r.url == "https://zero.estate/properties/1"
    assert r.property_type_hint == "house"
    assert r.address_text == "岡山県高梁市"
    assert r.thumbnail_url == "https://x/b.jpg"     # sortOrder 0 を先頭に採用
    assert "残置物あり" in (r.body or "") and "長期空き家" in (r.body or "")
    assert r.posted_at == "2026-07-01T00:00:00.000Z"


def test_item_to_raw_type_mapping():
    assert MinnaZeroEnScraper._item_to_raw(_item(propertyType="マンション")).property_type_hint == "apartment"
    assert MinnaZeroEnScraper._item_to_raw(_item(propertyType="土地のみ")).property_type_hint == "land"
    assert MinnaZeroEnScraper._item_to_raw(_item(propertyType="建物のみ")).property_type_hint == "house"


def test_item_to_raw_broken_notes_ok():
    r = MinnaZeroEnScraper._item_to_raw(_item(specialNotes="壊れたJSON"))
    assert r is not None                            # 壊れた specialNotes でも落ちない


def test_item_to_raw_missing_id():
    assert MinnaZeroEnScraper._item_to_raw(_item(id=None)) is None


def test_fetch_filters_sold_and_land(monkeypatch):
    payload = {"items": [
        _item(id=1, propertyType="土地・建物", publicStatus="募集中"),
        _item(id=2, propertyType="土地のみ", publicStatus="募集中"),      # 更地 → 除外
        _item(id=3, propertyType="土地・建物", publicStatus="成約済み"),   # 売却済 → 除外
        _item(id=4, propertyType="マンション", publicStatus="募集中"),
        _item(id=5, propertyType="土地・建物", publicStatus="受付停止"),   # 停止中 → 除外
    ], "totalPages": 1, "page": 1}
    s = MinnaZeroEnScraper()
    monkeypatch.setattr(s, "_fetch_page", lambda client, page: payload)
    got = list(s.fetch(None))
    assert {r.listing_id for r in got} == {"1", "4"}    # 更地・売却済・停止中は除外


def test_fetch_stops_at_last_page(monkeypatch):
    pages = {
        1: {"items": [_item(id=10)], "totalPages": 2, "page": 1},
        2: {"items": [_item(id=11)], "totalPages": 2, "page": 2},
    }
    s = MinnaZeroEnScraper()
    monkeypatch.setattr(s, "_fetch_page", lambda client, page: pages[page])
    got = list(s.fetch(None))
    assert {r.listing_id for r in got} == {"10", "11"}
