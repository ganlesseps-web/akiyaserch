"""自治体マスタ (人口 / 賃貸需要 / 観光フラグ) の参照。

再販目線のフィルタで「人口の絶対値で足切りしない」代わりに使う。
プロ壁打ち(セッション15)の合意:
  人口3万カットは高梁(2.5万)・韮崎・甲州などユーザーが自ら追加した供給源を
  全滅させるため廃止。代わりに『賃貸需要の核(工場/大学/病院/通勤圏)も
  観光資源も無く、かつ人口1万未満』の自治体のみ⚠️警告にする。

city 表記は normalize._extract_city の出力に揺れがある
  (例: "多可郡多可町加美区" / "吉野郡下市" / "神崎郡神河町")
ため、_normalize_city() で郡・区を落としてから突き合わせる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path("config/municipalities.yaml")

# 人口がこの値未満で、賃貸需要も観光も無ければ警告
SMALL_POPULATION_THRESHOLD = 10_000

_GUN_RE = re.compile(r"^[一-龥々ヵヶぁ-んァ-ヶー]+郡")   # 先頭の "○○郡" を落とす
_WARD_SUFFIX_RE = re.compile(r"(町|村)[一-龥々ヵヶぁ-んァ-ヶー]+区$")  # "多可町加美区" → "多可町"


@dataclass(frozen=True)
class Municipality:
    name: str
    prefecture: str | None
    population: int | None
    rental_demand: bool
    tourism: bool

    @property
    def is_thin_market(self) -> bool:
        """賃貸需要も観光も無く、人口も小さい = 出口が見えにくい自治体。"""
        if self.rental_demand or self.tourism:
            return False
        if self.population is None:
            return False
        return self.population < SMALL_POPULATION_THRESHOLD


def _normalize_city(city: str) -> str:
    """city 表記の揺れを吸収する。

    "多可郡多可町加美区" -> "多可町"
    "吉野郡下市"        -> "下市"   (マスタ側も "下市町" と "下市" を両方持たせる)
    "神崎郡神河町"      -> "神河町"
    """
    s = (city or "").strip()
    if not s:
        return ""
    s = _GUN_RE.sub("", s)          # 郡を落とす
    s = _WARD_SUFFIX_RE.sub(r"\1", s)  # 町/村の下の区を落とす
    return s


@lru_cache(maxsize=1)
def _load(path_str: str) -> dict[str, Municipality]:
    p = Path(path_str)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, Municipality] = {}
    for name, v in (data.get("municipalities") or {}).items():
        v = v or {}
        m = Municipality(
            name=name,
            prefecture=v.get("prefecture"),
            population=v.get("population"),
            rental_demand=bool(v.get("rental_demand", False)),
            tourism=bool(v.get("tourism", False)),
        )
        out[_normalize_city(name)] = m
        # "下市町" と "下市" のような別名も引けるようにする
        for alias in (v.get("aliases") or []):
            out[_normalize_city(str(alias))] = m
    return out


def lookup(city: str | None, path: Path | None = None) -> Municipality | None:
    """city 名から自治体マスタを引く。未登録なら None。"""
    if not city:
        return None
    table = _load(str(path or DEFAULT_PATH))
    key = _normalize_city(city)
    if key in table:
        return table[key]
    # 「下市」「下市町」のような 町/村/市 の有無ゆれを救う
    for suffix in ("町", "村", "市"):
        if key + suffix in table:
            return table[key + suffix]
    if key and key[-1] in "町村市" and key[:-1] in table:
        return table[key[:-1]]
    return None


def market_warning(city: str | None, path: Path | None = None) -> str | None:
    """出口が見えにくい自治体なら警告文字列を返す。該当しなければ None。

    マスタ未登録の自治体は「情報なし」として通す (デフォルト通過の設計原則)。
    """
    m = lookup(city, path)
    if m is None or not m.is_thin_market:
        return None
    pop = f"{m.population:,}人" if m.population is not None else "人口不明"
    return f"小規模({pop}・賃貸/観光需要の核なし)"
