"""移住者コミュニティの有無 (config/communities.yaml) を物件に当てる。

2026-10-25 ユーザー指示「移住者コミュニティがあるエリアと分かるように・その順に並べたい」。
ダッシュボードのカードに印 (◎/○/△) を出し、並び替え「移住者の集まりが活発な順」に使う。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .negotiation import _q, _split_area

MARKS = {3: "◎", 2: "○", 1: "△"}
LABELS = {3: "移住者の交流が活発", 2: "移住体験・支援拠点あり", 1: "相談窓口のみ"}

_cache: list[tuple[str, str, int, str]] | None = None   # (市, 区, level, note)

# 実行場所 (Vercel など) に左右されないよう、このファイルの位置から探す
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "communities.yaml"


def load(path: Path | None = None) -> list[tuple[str, str, int, str]]:
    global _cache
    if _cache is not None and path is None:
        return _cache
    p = path or DEFAULT_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    out = []
    for name, v in ((data or {}).get("communities") or {}).items():
        city, ward = _split_area(str(name))
        out.append((city, ward, int(v.get("level", 0)), str(v.get("note", ""))))
    # 区まで指定したものを先に見る (新潟市西蒲区 → 新潟市 より優先)
    out.sort(key=lambda t: t[1] == "")
    if path is None:
        _cache = out
    return out


def _city_matches(city: str, c: str) -> bool:
    """DB の city は「久米郡美咲町」「丹波篠山市西紀南地区」のように郡名・地区名が付くことがある。"""
    base = city.split("郡", 1)[1] if "郡" in city else city
    return base == c or base.startswith(c)


def lookup(city: str | None, address: str | None) -> tuple[int, str]:
    """(level, note)。未調査なら (0, "")。"""
    if not city:
        return 0, ""
    for c, ward, level, note in load():
        if _city_matches(city, c) and (not ward or ward in (address or "")):
            return level, note
    return 0, ""


def badge(row) -> dict | None:
    """カード表示用。未調査なら None。"""
    def get(key):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError, ValueError):  # 本番DBの行は無い列で ValueError
            return None
    level, note = lookup(get("city"), get("address"))
    if not level:
        return None
    return {"level": level, "mark": MARKS[level], "label": LABELS[level], "note": note}


def level_sql() -> str:
    """並び替え用の SQL 式 (3〜1、未調査は 0)。CASE は WHEN を並べるだけなので式は深くならない。"""
    whens = []
    for c, ward, level, _note in load():
        # _city_matches と同じ: 完全一致 / 後ろに地区名 / 前に郡名
        cond = (f"(p.city = {_q(c)} OR p.city LIKE {_q(c + '%')}"
                f" OR p.city LIKE {_q('%郡' + c + '%')})")
        if ward:
            cond += f" AND p.address LIKE {_q('%' + ward + '%')}"
        whens.append(f"WHEN {cond} THEN {level}")
    if not whens:
        return "0"
    return "(CASE " + " ".join(whens) + " ELSE 0 END)"
