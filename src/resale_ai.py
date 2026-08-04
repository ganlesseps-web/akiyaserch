"""再販目線の AI 構造化判定 (Claude Haiku)。

掲載本文は設備を書かないことが多く (「和式」明記は実測0件)、キーワード判定
だけでは拾えない。そこで本文を Claude に読ませ、設備・ライフライン・空き家
期間の手がかりを構造化して推定させる。

重要な設計方針 (プロ壁打ちセッション15の合意):
- verdict はハード除外に使わない。あくまで⚠️警告/参考表示で、最終判断は人間。
- 分からないものは「不明」を返させる (推測で埋めない)。
- 「和式トイレでも、風呂だけ直せば住めそうなら検討可」の例外ルールを明記。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """あなたは日本の地方の中古住宅を「再販・賃貸・民泊」の出口で仕入れる
プロのバイヤーの助手です。物件情報を読み、事実として書かれていることだけを構造化します。

【最重要】書かれていないことは推測せず "不明" にしてください。憶測で埋めない。

【判定項目】
- toilet: "和式" / "洋式" / "不明"
- bath: "要修繕"(浴室が壊れている・古い・要交換と読み取れる) / "使用可" / "不明"
- lifeline: "公共下水" / "浄化槽" / "汲み取り" / "井戸" / "不明"
   ※上水道と井戸の併用は "不明" ではなく実際の下水処理方式を優先
- parking: "あり" / "なし" / "不明"  ※記載がなければ "なし" ではなく "不明"
- vacancy_hint: "長期"(空き家5年超と読み取れる) / "短期" / "不明"
- verdict: 次の3択
   - "検討可": 大きな地雷が読み取れない。多少の修繕(トイレ洋式化・内装)は許容。
   - "警告": 気になる減点(汲み取り/傾き/調整区域/駐車場なし明記 等)がある。
   - "見送り": 再建築不可・借地・共有持分・井戸のみ・重大構造欠陥など、
              どの出口でも救いにくい要素が明記されている。
- reasons: 60字以内の日本語。判断の根拠を簡潔に。

【例外ルール】
和式トイレであっても、浴室など他が使える状態で「風呂だけ直せば住めそう」なら
"検討可" にしてよい (洋式化は10〜25万円で、この価格帯では致命傷ではない)。

出力は次の JSON のみ。他のテキストは一切出力しないこと。
{"toilet":"...","bath":"...","lifeline":"...","parking":"...","vacancy_hint":"...","verdict":"...","reasons":"..."}
"""

_ALLOWED = {
    "toilet": {"和式", "洋式", "不明"},
    "bath": {"要修繕", "使用可", "不明"},
    "lifeline": {"公共下水", "浄化槽", "汲み取り", "井戸", "不明"},
    "parking": {"あり", "なし", "不明"},
    "vacancy_hint": {"長期", "短期", "不明"},
    "verdict": {"検討可", "警告", "見送り"},
}


def prompt_hash() -> str:
    """判定仕様のハッシュ。SYSTEM_PROMPT を変えたら全件再判定される。"""
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:16]


def format_property(row: Any) -> str:
    """物件行を Claude に渡すテキストに整形 (scorer._format_property と同じ発想)。"""
    def get(key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default

    parts = [f"タイトル: {get('title')}"]
    price = get("price")
    parts.append(f"価格: {price}円" if price is not None else "価格: 不明")
    parts.append(f"所在地: {get('address') or get('prefecture') or '不明'}")
    if get("area_land"):
        parts.append(f"土地: {get('area_land')}㎡")
    if get("area_building"):
        parts.append(f"建物: {get('area_building')}㎡")
    body = get("body")
    if body:
        parts.append(f"概要:\n{str(body)[:1500]}")
    return "\n".join(parts)


def parse_response(text: str) -> dict[str, str]:
    """Claude の応答から JSON を取り出し、値を許容集合に丸める。"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON in response: {text[:200]}")
    data = json.loads(text[start:end + 1])

    out: dict[str, str] = {}
    for key, allowed in _ALLOWED.items():
        v = str(data.get(key) or "").strip()
        out[key] = v if v in allowed else ("検討可" if key == "verdict" else "不明")
    out["reasons"] = str(data.get("reasons") or "").strip()[:200]
    return out


def assess_property(row: Any, model: str = DEFAULT_MODEL) -> dict[str, str]:
    """1物件を Claude で構造化判定する。"""
    import anthropic  # late import (未使用時に依存を要求しない)

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を使用
    msg = client.messages.create(
        model=model,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": format_property(row)}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    return parse_response(text)


def assess_unassessed(conn: Any, *, limit: int = 50, model: str = DEFAULT_MODEL) -> dict[str, int]:
    """未判定 or 仕様が変わった物件を順に判定して resale_ai に保存する。"""
    from . import db

    phash = prompt_hash()
    rows = conn.execute(
        """
        SELECT p.* FROM properties p
        LEFT JOIN resale_ai a ON a.property_id = p.id
        WHERE p.status = 'active'
          AND (p.resale_ng IS NULL OR p.resale_ng = 0)
          AND (a.prompt_hash IS NULL OR a.prompt_hash != ?)
        ORDER BY p.first_seen_at DESC
        LIMIT ?
        """,
        (phash, limit),
    ).fetchall()

    stats = {"target": len(rows), "assessed": 0, "failed": 0}
    if not rows:
        return stats
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    now = db.now_iso()
    for row in rows:
        try:
            r = assess_property(row, model=model)
        except Exception as e:  # noqa: BLE001 - 1件の失敗で全体を止めない
            logger.warning("assess failed for property %s: %s", row["id"], e)
            stats["failed"] += 1
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO resale_ai
              (property_id, verdict, toilet, bath, lifeline, parking,
               vacancy_hint, reasons, prompt_hash, model, assessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], r["verdict"], r["toilet"], r["bath"], r["lifeline"],
             r["parking"], r["vacancy_hint"], r["reasons"], phash, model, now),
        )
        stats["assessed"] += 1
        logger.info("assessed %s → %s (%s)", row["id"], r["verdict"], r["reasons"][:30])
    return stats
