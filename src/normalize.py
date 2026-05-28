"""RawListing -> db.Listing 正規化。価格・面積・住所の文字列をパース。"""
from __future__ import annotations

import re

from .db import Listing
from .scrapers.base import RawListing

# 全47都道府県
PREFECTURES = [
    "北海道",
    "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
    "沖縄県",
]
_PREF_RE = re.compile("|".join(re.escape(p) for p in PREFECTURES))

# 市区町村抽出。3 パターン:
#   (A) 郡+町村:           幌泉郡えりも町
#   (B) 市 (+政令指定区):    大阪市北区, 桶川市
#   (C) 23区:               千代田区
# non-greedy にして 市/町/村 の最初の出現で止める (字レベルを誤って吸わないため)。
_CITY_RE = re.compile(
    r"(?:"
    r"(?:[一-龥々ヵヶ]+郡)?[一-龥々ヵヶぁ-んァ-ヶー]+?[市町村](?:[一-龥々ヵヶぁ-んァ-ヶー]+区)?"
    r"|[一-龥々ヵヶぁ-んァ-ヶー]+?区"
    r")"
)

# 数値抽出（小数あり）
_NUM_RE = re.compile(r"[\d,]+\.?\d*")


def normalize(raw: RawListing) -> Listing:
    address = (raw.address_text or "").strip()
    # "①住所A / ②住所B" のような複数表記は最初の住所のみ取る
    first_addr = _take_first_address(address)

    prefecture = _extract_prefecture(first_addr)
    city = _extract_city(first_addr, prefecture)
    # スクレイパが構造化データから判定したヒントがあれば優先 (zero.estate の 物件分類 等)。
    # 無ければ title+body からキーワード分類にフォールバック。
    property_type = raw.property_type_hint or classify_property_type(raw.title, raw.body)
    is_bad, reason = is_dilapidated(raw.title, raw.body)
    has_settlement, settlement_reason = detect_settlement_offer(raw.title, raw.body)

    return Listing(
        source=raw.source,
        listing_id=raw.listing_id,
        url=raw.url,
        title=raw.title or "(タイトルなし)",
        price=_parse_price(raw.price_text),
        prefecture=prefecture,
        city=city,
        address=first_addr or None,
        area_land=_parse_area(raw.area_land_text),
        area_building=_parse_area(raw.area_building_text),
        thumbnail_url=raw.thumbnail_url,
        body=raw.body,
        posted_at=raw.posted_at,
        property_type=property_type,
        dilapidated=1 if is_bad else 0,
        dilapidation_reason=reason or None,
        settlement_offer=1 if has_settlement else 0,
        settlement_offer_reason=settlement_reason or None,
    )


# 物件タイプ判定キーワード
_HOUSE_DEFINITIVE = (
    "戸建", "一戸建", "一軒家", "古民家", "邸宅",
    "家屋", "平屋", "中古住宅", "中古一戸", "中古一戸建", "新築一戸建",
)
_HOUSE_BUILDING_HINTS = (
    "LDK", "DK", "間取り", "築", "階建", "木造", "鉄骨", "RC造", "鉄筋",
    "二階建", "2階建", "リフォーム済", "リノベ済",
)
_APARTMENT = ("マンション", "アパート", "ワンルーム", "コーポ", "メゾネット", "ハイツ")
_COMMERCIAL = ("オフィスビル", "事業用ビル", "商業ビル", "テナント募集", "店舗のみ")
_LAND_ONLY = (
    "山林", "農地", "田畑", "更地", "原野", "林地", "空き地", "空地",
    "宅地分譲", "分譲地", "別荘地のみ", "土地のみ",
)


def is_dilapidated(title: str | None, body: str | None) -> tuple[bool, str]:
    """オンボロ (大幅修繕しないと住めない) 判定。

    確実なシグナル (例: "解体前提", "住める状態ではありません") は即 True。
    "雨漏り" / "腐食" / "シロアリ" 等は否定文脈 (なし/無し/ありません/修繕済 等) を
    確認してから判定する。これにより「雨漏り対策済み」「雨漏りはありません」を
    弾かない。
    """
    text = ((title or "") + " " + (body or "")).strip()
    if not text:
        return False, ""

    # 確実なオンボロ指標
    DEFINITIVE = (
        "住める状態ではあり",   # "ではありません" を catch (substring match)
        "住居としては使用",     # "住居としては使用不可" 等
        "居住不可", "住居不可",
        "解体前提", "解体推奨", "取り壊し前提", "取り壊しを前提",
        "廃屋", "廃墟", "倒壊", "全壊", "半壊",
        "残置物のみ", "ご自身で解体",
    )
    for kw in DEFINITIVE:
        if kw in text:
            return True, kw

    # 文脈依存: keyword が否定文脈なら OK と判定
    # (key: 不利キーワード, value: 否定 / 修繕済 を示すパターン list)
    CONTEXTUAL = {
        "雨漏り": [
            "雨漏りはありません", "雨漏りはござ", "雨漏りはなく",
            "雨漏りはない", "雨漏りなし", "雨漏り無し",
            "雨漏り対策", "雨漏り修繕済", "雨漏り修理済",
            "雨漏り等の損傷はあり",   # "...はありません" を catch
            "雨漏り等の損傷はござ",
            "雨漏り等の形跡はあり",
            "雨漏り等の形跡はござ",
            "重大な瑕疵は見受け",     # 「雨漏り・...・シロアリ被害等の重大な瑕疵は見受けられません」
            "屋根葺き替え",
            "雨漏りや構造に関わる大規模修繕は想定しておらず",
            "雨漏りリスクや築年数を考慮",
        ],
        "腐食": [
            "腐食はあり",     # ありません 用
            "腐食はござ",
            "腐食なし", "腐食無し", "腐食はない", "腐食はなく",
            "腐食しておりません",
            "腐食に強い",     # 「腐食に強いポリエチレン製」等 (アンチコロージョン素材言及)
            "腐食対策", "腐食防止", "腐食しにくい", "防腐",
            "腐食しないよう",
        ],
        "シロアリ被害": [
            "シロアリ被害なし", "シロアリ被害は見受けられ",
            "シロアリ被害はあり",   # ありません 用
            "シロアリ被害等の重大な瑕疵は",
        ],
        "シロアリ食害": [
            "シロアリ食害なし", "シロアリ食害無し", "シロアリ食害はあり",
        ],
    }
    for bad_kw, ok_patterns in CONTEXTUAL.items():
        if bad_kw in text:
            if not any(p in text for p in ok_patterns):
                return True, bad_kw

    # 大規模修繕系: "必要" / "前提" の文脈で
    if "大規模" in text:
        for need_pat in ("大規模なリフォームが必要", "大規模リフォームが必要",
                         "大規模なリフォーム必要", "大規模な修繕が必要",
                         "大規模修繕が必要", "大規模な修繕を要", "大規模なリノベを要",
                         "フルリノベ前提", "フルリノベが必要", "フルリノベーション必要"):
            if need_pat in text:
                return True, need_pat

    return False, ""


def classify_property_type(title: str | None, body: str | None) -> str:
    """物件タイプ分類. Returns one of:
       'house'      — 一軒家・戸建て・古民家・農家の家など
       'apartment'  — マンション・アパート
       'commercial' — オフィスビル・テナント・店舗専用
       'land'       — 山林・農地・更地など建物なし
       'unknown'    — 判定不能 (title/body が薄い場合)
    """
    text = ((title or "") + " " + (body or "")).strip()
    if not text:
        return "unknown"

    if any(k in text for k in _APARTMENT):
        return "apartment"
    if any(k in text for k in _COMMERCIAL):
        return "commercial"
    if any(k in text for k in _HOUSE_DEFINITIVE):
        return "house"
    # 建物ヒントあり、かつ明らかな land 文言が無い → 家とみなす
    if any(k in text for k in _HOUSE_BUILDING_HINTS):
        if not any(k in text for k in _LAND_ONLY):
            return "house"
    # 明確な land 系
    if any(k in text for k in _LAND_ONLY):
        return "land"
    return "unknown"


def _take_first_address(address: str) -> str:
    """"①xxx / ②yyy" のような複数住所表記は先頭だけ採用。"""
    # 丸数字や区切り文字 / 改行 で分割
    parts = re.split(r"[/／\n]|[①-⑳]|[（(]\s*", address)
    for p in parts:
        s = p.strip().lstrip("：:、,").strip()
        if _PREF_RE.search(s):
            return s
    return address


def _extract_prefecture(address: str) -> str | None:
    m = _PREF_RE.search(address)
    return m.group(0) if m else None


def _extract_city(address: str, prefecture: str | None) -> str | None:
    if prefecture:
        idx = address.find(prefecture)
        if idx >= 0:
            address = address[idx + len(prefecture):]
    m = _CITY_RE.search(address)
    return m.group(0) if m else None


def _parse_price(text: str | None) -> int | None:
    if not text:
        return None
    s = text.replace(",", "").replace(" ", "").replace("　", "")
    if "0円" in s or s.startswith("0") and "円" in s:
        return 0
    m = re.search(r"(\d+)\s*億", s)
    oku = int(m.group(1)) * 100_000_000 if m else 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", s)
    man = int(float(m.group(1)) * 10_000) if m else 0
    m = re.search(r"(\d+)\s*円", s)
    yen = int(m.group(1)) if m else 0
    total = oku + man + yen
    if total > 0:
        return total
    # フォールバック: 純粋な数字
    m = _NUM_RE.search(s)
    return int(float(m.group(0).replace(",", ""))) if m else None


def _parse_area(text: str | None) -> float | None:
    if not text:
        return None
    m = _NUM_RE.search(text.replace(",", ""))
    return float(m.group(0)) if m else None


def detect_settlement_offer(title: str | None, body: str | None) -> tuple[bool, str]:
    """「定住条件付き譲渡」「試住制度」「改修費返済不要」等を検出.

    検出対象パターン:
    - 「○年定住で譲渡/所有権移転」型 (北海道沼田町・島根津和野などで実例)
    - 「試住制度」「お試し移住」型 (神河町・養父市・伊根町など)
    - 「改修費自治体負担・○年定住で返済不要」型 (与謝野町・朝来市など)
    - 「無償譲渡」「無料譲渡」「贈与」型
    - 「賃貸後譲渡」「リース後購入」型

    Returns (True, "ヒットした語句") or (False, "")
    """
    text = ((title or "") + " " + (body or "")).strip()
    if not text:
        return False, ""

    # 確実なシグナル
    SIGNALS = (
        "無償譲渡", "無料譲渡", "ゼロ円譲渡", "0円譲渡",
        "無償でお譲り", "無料でお譲り",
        "定住条件付", "定住要件付", "定住条件を満たせば",
        "定住で譲渡", "定住で所有権", "居住で譲渡",
        "試住制度", "お試し移住", "お試し居住", "お試し滞在", "お試し住宅",
        "賃貸後譲渡", "賃貸期間後譲渡", "リース後譲渡", "賃貸後購入",
        "改修費 返済不要", "改修費返済不要", "返済免除",
        "○年定住", "年定住で", "年定住すれば",
        "贈与可", "譲渡可",  # ※「譲渡」単独はノイズ多いので「譲渡可」のみ
    )
    for kw in SIGNALS:
        if kw in text:
            return True, kw

    # 価格コンテキスト: "賃料 ○円 → 譲渡可" のようなパターン
    if "譲渡" in text and ("年後" in text or "年間" in text or "後に" in text):
        return True, "譲渡(条件付)"

    return False, ""
