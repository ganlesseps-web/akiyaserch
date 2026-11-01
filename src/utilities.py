"""上下水道の判別 (2026-11-01 ユーザー指示「上下水道があるところのみに絞りたい・判別をしっかり」)。

物件の本文には水道・下水の情報がほとんど無い (609件中 50件程度) ので、
各物件の詳細ページを1回だけ見に行き、「水道」「下水道」「トイレ」の欄から判定する。

- 水道 (water): public=公営の水道 / well=井戸・地下水・共同飲料水など / none=未接続・無し / unknown
- 下水 (sewage): public=公共下水・集落排水 / septic=浄化槽 / flush=水洗(方式は不明) /
                 kumitori=汲み取り / simple=簡易水洗 / none=下水無し / unknown
- 下水は「良いほう」を採る (公共下水 > 浄化槽 > 水洗 > 汲み取り > 簡易水洗 > 無し)。
  例:「公共下水接続済トイレ有り、使っていない汲取りトイレ有り」→ 公共下水
- 否定 (未接続・無し・されておらず 等) が直後に付く語は数えない。
  直後の範囲は次の欄の名前 (ガス・電気・トイレ…) で区切る (「上水道 公営 ガス なし」を誤読しないため)
- 海の名前 (豊後水道)・料金の話 (水道代)・郡名 (下水内郡)・検索用の飾り (高梁市の絞り込み欄) は除く
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

WATER_LABELS = {"public": "公営水道", "well": "井戸など", "none": "なし", "unknown": "未確認"}
SEWAGE_LABELS = {
    "public": "公共下水", "septic": "浄化槽", "flush": "水洗(方式不明)",
    "kumitori": "汲み取り", "simple": "簡易水洗", "none": "なし", "unknown": "未確認",
}

# 「水道」「下水道」と書いてあっても設備の話ではないもの
_NOISE = re.compile(
    r"(豊後|紀伊|豊予|鳴門)水道"
    r"|(?<!下)水道(光熱費?|代|料金?|加入金|負担金|分担金|申込費?|利用料|局|課|事業|メーター|工事費)"
    r"|下水道?(料金?|代|使用料|負担金|受益者負担金|課|局|事業)"
    r"|下水内郡|浄化槽(設置|整備)?(エリア|区域|地域)|浄化槽(設置)?補助"
)

# 直後の範囲を区切る「次の欄の名前」
_NEXT_LABEL = re.compile(r"ガス|電気|トイレ|風呂|浴室|駐車|(?<!上)下水|排水|台所|キッチン|給湯|(?<![上下])水道|プロパン|設備")
_NEGATION = re.compile(r"未接続|未整備|未設置|未加入|未引込|無し|なし|無い|ない|ません|おらず|不可|撤去|閉栓")

_WATER_PUBLIC = re.compile(
    r"(公営|市営|町営|村営|公共|簡易|市|町|村)上?水道|上水道|上下水道"
    r"|(?<!下)水道\s*[:：]?\s*(有り?|あり|完備|公営|市|町|村|上水|水道|接続済|引込済|本管|公共)"
)
_WATER_WELL = re.compile(r"井戸|地下水|私設水道|自家水道|共同飲料水|共同水道|山水|沢水|湧水|簡易給水")
_WATER_NONE = re.compile(
    r"(?<!下)水道\s*[:：]?\s*(未接続|無し|なし|未整備|未引込|未加入)"
    r"|上下?水道(が|は)?(接続されておらず|未接続|無し|なし|ありません|通っていない)"
)

_SEWER_PUBLIC = re.compile(
    r"公共下水|上下水道|集落排水|コミュニティ・?プラント|水洗\s*[（(]\s*(公共)?下水"
    r"|下水道?(本管)?\s*[:：]?\s*[（(]?\s*(接続済|接続あり|接続有|完備|整備済|引込済|あり|有り?(?!無)"
    r"|下水道|公共|利用可|使用可|水洗|本管|市|町|村)"
)
_SEPTIC = re.compile(r"浄化槽")
_FLUSH = re.compile(r"(?<!簡易)(?<!非)水洗")
_KUMITORI = re.compile(r"汲み?取り?|くみ取り|ポットン|非水洗")
_KUMITORI_NOT = re.compile(
    r"浄化槽[^。\n]{0,6}の?(汲み?取り?|くみ取り)"     # 浄化槽の汲み取り (清掃のこと)
    r"|(汲み?取り?|くみ取り)(式)?で?は(ありません|ない|なく)"
    r"|(汲み?取り?|くみ取り)[^。\n]{0,12}(から|より)[^。\n]{0,10}(水洗|下水|浄化槽)"
)
_SIMPLE = re.compile(r"簡易水洗")
_SEWER_NONE = re.compile(
    r"下水道?\s*[:：]?\s*(無し|なし|未接続|未整備|接続不可|不可)|下水(道)?(接続|引込)不可"
    r"|上下水道(が|は)?(接続されておらず|未接続|無し|なし|ありません)"
)


@dataclass(frozen=True)
class Utilities:
    water: str
    sewage: str
    note: str   # 判定の根拠 (前後の文章の抜き出し)


def page_text(html: bytes | str) -> str:
    """詳細ページから本文の文字だけを取り出す (検索欄・メニューは除く)。"""
    soup = BeautifulSoup(html, "lxml")
    for el in soup.select("script, style, form, select, nav, header, footer, noscript"):
        el.decompose()
    # 高梁市: 物件の設備は --active の付いた印だけ。付いていない印は「その設備は無い」の意味
    for el in soup.select(".detail__meta-facility"):
        if "detail__meta-facility--active" not in (el.get("class") or []):
            el.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _window(text: str, end: int, size: int = 14) -> str:
    w = text[end:end + size]
    m = _NEXT_LABEL.search(w)
    return w[:m.start()] if m else w


def _hits(rx: re.Pattern[str], text: str, *, check_neg: bool = True) -> list[re.Match[str]]:
    return [m for m in rx.finditer(text)
            if not (check_neg and _NEGATION.search(_window(text, m.end())))]


def _snip(text: str, m: re.Match[str]) -> str:
    return text[max(0, m.start() - 8):m.end() + 12].strip()


def judge(text: str) -> Utilities:
    text = _NOISE.sub(" ", re.sub(r"\s+", " ", text or ""))
    notes: list[str] = []

    water = "unknown"
    for kind, rx, neg in (("public", _WATER_PUBLIC, True), ("well", _WATER_WELL, False),
                          ("none", _WATER_NONE, False)):
        hits = _hits(rx, text, check_neg=neg)
        if hits:
            water = kind
            notes.append("水道: " + _snip(text, hits[0]))
            break

    sewage = "unknown"
    kumitori_hits = [m for m in _KUMITORI.finditer(text)
                     if not _KUMITORI_NOT.search(text[max(0, m.start() - 12):m.end() + 30])]
    candidates = (
        ("public", _hits(_SEWER_PUBLIC, text)),
        ("septic", _hits(_SEPTIC, text)),
        ("flush", _hits(_FLUSH, text)),
        ("kumitori", kumitori_hits),
        ("simple", _hits(_SIMPLE, text, check_neg=False)),
        ("none", _hits(_SEWER_NONE, text, check_neg=False)),
    )
    for kind, hits in candidates:
        if hits:
            sewage = kind
            notes.append("下水: " + _snip(text, hits[0]))
            break
    return Utilities(water, sewage, " / ".join(notes)[:300])


def judge_listing(title: str | None, body: str | None, detail_html: bytes | str | None) -> Utilities:
    parts = [title or "", body or ""]
    if detail_html:
        parts.append(page_text(detail_html))
    return judge(" ".join(parts))


# --- ダッシュボード用 -------------------------------------------------------
# 「上下水道あり」: 公営水道 + 公共下水(集落排水を含む)
# 「水道+下水か浄化槽」: 公営水道 + (公共下水 / 浄化槽)  ※田舎は浄化槽が普通なので別に用意
WS_FILTERS = {
    "public": " AND p.water_supply = 'public' AND p.sewage = 'public'",
    "septic": " AND p.water_supply = 'public' AND p.sewage IN ('public', 'septic')",
    "unknown": (" AND (p.utilities_checked_at IS NULL"
                " OR p.water_supply = 'unknown' OR p.sewage = 'unknown')"),
}

# 汲み取りと分かった家は一覧に出さない (2026-10-25 ユーザー指示「汲み取り式は除外」)
KUMITORI_EXCLUSION = " AND (p.sewage IS NULL OR p.sewage != 'kumitori')"


def badge(row) -> dict | None:
    """カード表示用。未確認なら {"checked": False}。"""
    def get(key):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError, ValueError):  # 本番DBの行は無い列で ValueError
            return None
    if not get("utilities_checked_at"):
        return {"checked": False, "text": "上下水道 未確認", "good": False}
    w, s = get("water_supply") or "unknown", get("sewage") or "unknown"
    good = w == "public" and s in ("public", "septic")
    return {"checked": True, "good": good, "note": get("utilities_note") or "",
            "text": f"水道:{WATER_LABELS.get(w, '未確認')} / 下水:{SEWAGE_LABELS.get(s, '未確認')}"}


# --- 詳細ページを見に行って判定する (trade utilities) ---------------------------
def check_missing(conn, *, limit: int = 200, sources: set[str] | None = None,
                  exclude: set[str] | None = None) -> dict[str, int]:
    """まだ上下水道を調べていない物件の詳細ページを1回だけ見に行く。

    ページが開けなかった物件 (アットホームのメンテナンス中など) は「未確認」のまま残し、
    次の回にもう一度見に行く。
    """
    import time

    import httpx
    import urllib3

    from . import db
    from .enrich import INTER_REQUEST_SECONDS, _client
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    sql = ("SELECT p.id, p.source, p.url, p.title, p.body FROM properties p"
           " WHERE p.status = 'active' AND p.utilities_checked_at IS NULL")
    params: list = []
    if sources:
        sql += f" AND p.source IN ({', '.join('?' * len(sources))})"
        params += sorted(sources)
    if exclude:
        sql += f" AND p.source NOT IN ({', '.join('?' * len(exclude))})"
        params += sorted(exclude)
    sql += " ORDER BY p.first_seen_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    stats = {"target": len(rows), "checked": 0, "failed": 0, "good": 0, "kumitori": 0}
    with _client() as client:
        for i, r in enumerate(rows):
            if i:
                time.sleep(INTER_REQUEST_SECONDS)
            try:
                resp = client.get(r["url"])
            except httpx.HTTPError:
                stats["failed"] += 1
                continue
            if resp.status_code != 200:
                stats["failed"] += 1
                continue
            u = judge_listing(r["title"], r["body"], resp.content)
            conn.execute(
                "UPDATE properties SET water_supply = ?, sewage = ?, utilities_note = ?,"
                " utilities_checked_at = ? WHERE id = ?",
                (u.water, u.sewage, u.note, db.now_iso(), r["id"]),
            )
            stats["checked"] += 1
            stats["good"] += u.water == "public" and u.sewage in ("public", "septic")
            stats["kumitori"] += u.sewage == "kumitori"
    return stats
