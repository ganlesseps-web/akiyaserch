"""値引き交渉の候補 (2026-10-23 ユーザー指示)。

「市場で200万円で出ていても、数年空き家なら交渉で下がるのでは」という考えに沿い、
48市町村の調査対象地域 (config/filters.yaml の negotiation.areas) に限って
300万円以上〜price_max未満の物件も DB に残し、ダッシュボードの「🤝交渉候補」タブに出す。

- 収集 (purge.should_skip) と削除 (purge._target_sql) で同じ判定を使う
  (ズレると「消したのに翌朝また入る」事故になる)
- 通常の一覧と Discord 通知は今まで通り300万円未満のみ
- 印: 掲載が長い (掲載開始日から1年以上 / 不明なら当システムで半年以上) /
  値下げ歴あり / 本文に「価格相談」等
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

NORMAL_PRICE_MAX = 3_000_000  # 通常の一覧の上限 (purge.PRICE_CUTOFF_YEN と同じ)
BAND_MIN = 2_000_000          # 交渉候補タブに出す下限 (これ以下は通常の一覧で十分)


@dataclass(frozen=True)
class Config:
    price_max: int
    long_listed_days: int
    long_seen_days: int
    areas: tuple[tuple[str, str], ...]   # (市町村名, 区名 or "")


_cache: Config | None = None


def _split_area(name: str) -> tuple[str, str]:
    """「新潟市西蒲区」→ ("新潟市", "西蒲区")。区が無ければ ("五島市", "")。"""
    m = re.match(r"^(.+?市)(.+区)$", name)
    return (m.group(1), m.group(2)) if m else (name, "")


def load(path: Path | None = None) -> Config:
    global _cache
    if _cache is not None and path is None:
        return _cache
    p = path or Path("config/filters.yaml")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    neg = (data or {}).get("negotiation") or {}
    cfg = Config(
        price_max=int(neg.get("price_max", 0) or 0),
        long_listed_days=int(neg.get("long_listed_days", 365)),
        long_seen_days=int(neg.get("long_seen_days", 180)),
        areas=tuple(_split_area(str(a)) for a in (neg.get("areas") or [])),
    )
    if path is None:
        _cache = cfg
    return cfg


def in_area(city: str | None, address: str | None, cfg: Config | None = None) -> bool:
    cfg = cfg or load()
    if not city:
        return False
    for c, ward in cfg.areas:
        if city == c and (not ward or ward in (address or "")):
            return True
    return False


def keep_pricey(price: int | None, city: str | None, address: str | None,
                cfg: Config | None = None) -> bool:
    """300万円以上でも交渉候補として残す物件なら True。"""
    cfg = cfg or load()
    return (price is not None and NORMAL_PRICE_MAX <= price < cfg.price_max
            and in_area(city, address, cfg))


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def area_sql(cfg: Config | None = None) -> str:
    """対象地域の SQL 条件 (p.city / p.address)。値は設定ファイル由来で、引用符はエスケープ済み。"""
    cfg = cfg or load()
    parts = []
    for c, ward in cfg.areas:
        if ward:
            parts.append(f"(p.city = {_q(c)} AND p.address LIKE {_q('%' + ward + '%')})")
        else:
            parts.append(f"p.city = {_q(c)}")
    return "(" + (" OR ".join(parts) or "0") + ")"


def keep_pricey_sql(cfg: Config | None = None) -> str:
    """keep_pricey と同じ条件の SQL 版 (purge の削除対象から外すため)。"""
    cfg = cfg or load()
    return f"(p.price < {int(cfg.price_max)} AND {area_sql(cfg)})"


def band_sql(cfg: Config | None = None) -> str:
    """「🤝交渉候補」タブの条件: 対象地域の 200万円超〜price_max未満。"""
    cfg = cfg or load()
    return (f" AND p.price > {BAND_MIN} AND p.price < {int(cfg.price_max)}"
            f" AND {area_sql(cfg)}")


_TALK_RE = re.compile(r"価格(は)?(応相談|相談可|交渉可|要相談)|値引き(相談|交渉)?可|応相談")


def _days_since(text: str | None, today: date) -> int | None:
    if not text:
        return None
    try:
        d = datetime.fromisoformat(str(text)[:10]).date()
    except ValueError:
        return None
    return (today - d).days


def marks(row: Any, *, today: date | None = None, cfg: Config | None = None) -> list[str]:
    """交渉の材料になる印。カードに表示する短い日本語のリスト。"""
    cfg = cfg or load()
    today = today or date.today()

    def get(key: str) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return None

    out: list[str] = []
    listed = _days_since(get("listed_at"), today)
    seen = _days_since(get("first_seen_at"), today)
    if listed is not None and listed >= cfg.long_listed_days:
        out.append(f"📅 掲載{listed / 365:.1f}年")
    elif listed is None and seen is not None and seen >= cfg.long_seen_days:
        out.append(f"📅 {seen // 30}か月以上掲載")
    old, new = get("drop_old_price"), get("drop_new_price")
    if old is not None and new is not None and new < old:
        out.append("🔻 値下げ歴あり")
    if _TALK_RE.search(f"{get('title') or ''} {get('body') or ''}"):
        out.append("💬 価格相談の記載")
    return out
