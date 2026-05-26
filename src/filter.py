"""通知フィルタ。yaml を読んで、Listing/Row が通知対象かを判定する。"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import db

DEFAULT_FILTERS_PATH = Path("config/filters.yaml")


@dataclass
class FilterConfig:
    price_max: int
    prefectures: set[str]
    borderline_prefectures: set[str]
    drive_origin: str
    drive_max_seconds: int
    ng_keywords: list[str]
    min_ai_score: int  # 0 なら AI スコア無視。>0 なら scored & score >= min_ai_score を要求。
    property_types: set[str]  # 通す物件タイプ. 空 set なら全許可。

    @classmethod
    def load(cls, path: Path | None = None) -> "FilterConfig":
        p = path or DEFAULT_FILTERS_PATH
        data = yaml.safe_load(p.read_text(encoding="utf-8"))

        # preferences.yaml の score_threshold を取り込み (存在する時のみ)
        min_ai_score = 0
        pref_path = Path("config/preferences.yaml")
        if pref_path.exists():
            try:
                pref_data = yaml.safe_load(pref_path.read_text(encoding="utf-8")) or {}
                min_ai_score = int(pref_data.get("score_threshold", 0))
            except (yaml.YAMLError, ValueError):
                pass

        return cls(
            price_max=int(data.get("price_max", 3_000_000)),
            prefectures=set(data.get("prefectures") or []),
            borderline_prefectures=set(data.get("borderline_prefectures") or []),
            drive_origin=data.get("drive_origin", ""),
            drive_max_seconds=int(data.get("drive_max_seconds", 7200)),
            ng_keywords=list(data.get("ng_keywords") or []),
            min_ai_score=min_ai_score,
            property_types=set(data.get("property_types") or []),
        )


def passes(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    cfg: FilterConfig,
    *,
    use_distance_matrix: bool = False,
) -> tuple[bool, str]:
    """Returns (pass, reason). reason は通すor落とす理由（ログ用）。"""
    price = row["price"]
    if price is not None and price > cfg.price_max:
        return False, f"price {price} > {cfg.price_max}"

    body = (row["title"] or "") + " " + (row["body"] or "")
    for ng in cfg.ng_keywords:
        if ng in body:
            return False, f"NG keyword: {ng}"

    # 物件タイプフィルタ (一軒家のみにしたい場合 ['house'] を設定)
    if cfg.property_types:
        ptype = row["property_type"] if "property_type" in row.keys() else None
        # row が _LibsqlRow のとき keys() メソッドは list[str] を返す
        try:
            ptype = row["property_type"]
        except (KeyError, IndexError):
            ptype = None
        if ptype not in cfg.property_types:
            return False, f"property_type {ptype} not in {cfg.property_types}"

    pref = row["prefecture"]
    if pref is None:
        return False, "prefecture unknown"

    if pref not in cfg.prefectures:
        return False, f"prefecture {pref} not in allowlist"

    # 境界府県は Distance Matrix で詰める（任意・キー設定時のみ）
    if use_distance_matrix and pref in cfg.borderline_prefectures and row["address"]:
        ok, reason = _check_drive_time(conn, row["address"], cfg)
        if not ok:
            return False, reason

    # AI スコアゲート (preferences.yaml で score_threshold > 0 のとき)
    if cfg.min_ai_score > 0:
        score_row = conn.execute(
            "SELECT score FROM ai_scores WHERE property_id = ?", (row["id"],)
        ).fetchone()
        if score_row is None:
            return False, "ai score pending"
        if score_row["score"] < cfg.min_ai_score:
            return False, f"ai score {score_row['score']} < {cfg.min_ai_score}"

    return True, "ok"


def _check_drive_time(
    conn: sqlite3.Connection, address: str, cfg: FilterConfig
) -> tuple[bool, str]:
    cached = db.cached_drive_seconds(conn, address, cfg.drive_origin)
    if cached is db.MISS:
        secs = _query_distance_matrix(address, cfg.drive_origin)
        db.cache_drive(conn, address, cfg.drive_origin, secs)
    else:
        secs = cached  # may be None (no route)

    if secs is None:
        return False, "no driving route from origin"
    if secs > cfg.drive_max_seconds:
        return False, f"drive {secs}s > {cfg.drive_max_seconds}s"
    return True, f"drive {secs}s ok"


def _query_distance_matrix(address: str, origin: str) -> int | None:
    """Google Maps Distance Matrix API を呼ぶ。GOOGLE_MAPS_API_KEY 未設定なら None。"""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None
    try:
        import googlemaps  # optional dep
    except ImportError:
        return None
    gm = googlemaps.Client(key=api_key)
    res = gm.distance_matrix(
        origins=[origin], destinations=[address], mode="driving", language="ja",
    )
    try:
        elem = res["rows"][0]["elements"][0]
        if elem.get("status") != "OK":
            return None
        return int(elem["duration"]["value"])
    except (KeyError, IndexError):
        return None
