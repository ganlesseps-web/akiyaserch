"""AI スコアリング: Claude (Haiku) に物件を好み基準で 0-10 採点させる.

config/preferences.yaml の `description` を system prompt に、物件情報を user message に。
出力は JSON {"score": int, "reason": str} を厳密に強制 (tool_use 形式)。

スコア + reason + preferences_hash を `ai_scores` テーブルにキャッシュ。
preferences が変わった (hash 違い) 物件は再採点される。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PREFERENCES_PATH = Path("config/preferences.yaml")
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class PreferenceConfig:
    description: str
    score_threshold: int
    model: str

    @classmethod
    def load(cls, path: Path | None = None) -> "PreferenceConfig":
        p = path or DEFAULT_PREFERENCES_PATH
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(
            description=str(data.get("description") or "").strip(),
            score_threshold=int(data.get("score_threshold", 6)),
            model=str(data.get("model") or DEFAULT_MODEL),
        )

    @property
    def hash(self) -> str:
        """description 内容のハッシュ。preferences 変更時に再スコアの目印。"""
        return hashlib.sha256(self.description.encode("utf-8")).hexdigest()[:16]


SYSTEM_PROMPT = """あなたは中古物件選定の専門アシスタント。
ユーザーの好みを踏まえて物件を 0-10 でスコアリングします。

【スコアリング基準】
- 0-2: 完全に好みに合わない / 致命的な欠点あり
- 3-4: 好みから外れる
- 5-6: 普通、好みの一部に合致
- 7-8: 好みに良く合う、おすすめできる
- 9-10: 理想的、絶対見るべき

【ユーザーの好み】
{preferences}

物件情報を読み、JSON で {{"score": <0-10の整数>, "reason": "<30字以内の根拠>"}} を出力。
それ以外のテキスト出力禁止。
"""


def _format_property(row: sqlite3.Row) -> str:
    parts = [
        f"タイトル: {row['title']}",
        f"価格: {row['price']}円" if row['price'] is not None else "価格: 不明",
        f"所在地: {row['address'] or row['prefecture'] or '不明'}",
    ]
    if row['area_land']:
        parts.append(f"土地: {row['area_land']:.0f}㎡")
    if row['area_building']:
        parts.append(f"建物: {row['area_building']:.0f}㎡")
    if row['body']:
        body = row['body'][:800]
        parts.append(f"概要:\n{body}")
    return "\n".join(parts)


def score_property(row: sqlite3.Row, cfg: PreferenceConfig) -> tuple[int, str]:
    """Claude API で 1物件を採点。(score, reason) を返す。"""
    import anthropic  # late import to keep base install light when not used

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    msg = client.messages.create(
        model=cfg.model,
        max_tokens=200,
        system=SYSTEM_PROMPT.format(preferences=cfg.description),
        messages=[{"role": "user", "content": _format_property(row)}],
    )

    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()

    # JSON 部分のみ抽出 (前後にゴミがあっても拾えるよう {...} を探す)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON in response: {text[:200]}")
    data = json.loads(text[start: end + 1])
    score = int(data["score"])
    reason = str(data.get("reason") or "").strip()[:120]
    return max(0, min(10, score)), reason


def score_unscored(
    conn: sqlite3.Connection,
    cfg: PreferenceConfig | None = None,
    *,
    limit: int = 100,
) -> dict[str, int]:
    """preferences_hash が現状と違う or 未スコアの物件を順に採点。"""
    cfg = cfg or PreferenceConfig.load()
    pref_hash = cfg.hash

    rows = conn.execute(
        """
        SELECT p.* FROM properties p
        LEFT JOIN ai_scores s ON s.property_id = p.id
        WHERE p.status = 'active'
          AND (s.preferences_hash IS NULL OR s.preferences_hash != ?)
        ORDER BY p.first_seen_at DESC
        LIMIT ?
        """,
        (pref_hash, limit),
    ).fetchall()

    stats = {"target": len(rows), "scored": 0, "failed": 0}
    if not rows:
        return stats

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    now = __import__("src.db", fromlist=["now_iso"]).now_iso()
    for row in rows:
        try:
            score, reason = score_property(row, cfg)
        except Exception as e:
            logger.warning("score failed for property %d: %s", row["id"], e)
            stats["failed"] += 1
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO ai_scores
              (property_id, score, reason, preferences_hash, model, scored_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row["id"], score, reason, pref_hash, cfg.model, now),
        )
        stats["scored"] += 1
        logger.info("scored %d → %d/10 (%s)", row["id"], score, reason[:30])

    return stats
