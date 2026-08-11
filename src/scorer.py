"""AI スコアリング: 物件を好み基準で 0-10 採点させる.

config/preferences.yaml の `description` を system prompt に、物件情報を user message に。
出力は JSON {"score": int, "reason": str} を構造化出力で強制。
モデルは config/ai.yaml (既定: Gemini の無料枠)。

スコア + reason + preferences_hash を `ai_scores` テーブルにキャッシュ。
preferences が変わった (hash 違い) 物件は再採点される。
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import llm

logger = logging.getLogger(__name__)

DEFAULT_PREFERENCES_PATH = Path("config/preferences.yaml")
# モデルは config/ai.yaml (src/llm.py) 側で決まる。ここは後方互換のための表示用。
DEFAULT_MODEL = "(config/ai.yaml)"


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


SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "score": {"type": "INTEGER"},
        "reason": {"type": "STRING"},
    },
    "required": ["score", "reason"],
}


def score_property(row: sqlite3.Row, cfg: PreferenceConfig) -> tuple[int, str]:
    """1物件を採点。(score, reason) を返す。

    既定では Gemini の無料枠を使う (src/llm.py, config/ai.yaml)。
    """
    data, _model = llm.generate_json(
        SYSTEM_PROMPT.format(preferences=cfg.description),
        _format_property(row),
        schema=SCORE_SCHEMA,
    )
    try:
        score = int(data["score"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"score が取得できません: {str(data)[:200]}") from e
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

    if not llm.api_key_present():
        raise llm.NoAPIKey(
            "AI のAPIキーが未設定です (既定は GEMINI_API_KEY)。"
            " https://aistudio.google.com/apikey で取得できます。"
        )

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
