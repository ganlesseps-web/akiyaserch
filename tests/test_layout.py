"""間取り (3部屋以上のみ) のテスト (2026-11-17)。"""
from src import layout


def test_parse_basic():
    assert layout.parse("間取り 4DK | 築年月 1980年") == ("4DK", 4)
    assert layout.parse("ペース付きのコンパクトな物件(1K)") == ("1K", 1)
    assert layout.parse("田畑や山林付きの物件(2SLDK)") == ("2SLDK", 2)
    assert layout.parse("３ＬＤＫ＋Ｓ") == ("3LDK+S", 3)
    assert layout.parse("10LDK | 木造") == ("10LDK", 10)
    assert layout.parse("ワンルーム") == ("1R", 1)


def test_parse_ignores_km_and_none():
    assert layout.parse("駅まで約37km 車で40分") is None
    assert layout.parse("125KMを誇る一級河川") is None
    assert layout.parse(None) is None


def test_parse_prefers_near_madori():
    # 「間取り」の後ろの値を優先 (他の物件の紹介より)
    assert layout.parse("おすすめ 2DK の家 … 間取り：5DK") == ("5DK", 5)


def test_enough():
    assert layout.enough(None)
    assert layout.enough(3)
    assert not layout.enough(2)
