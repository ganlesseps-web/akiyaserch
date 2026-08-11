"""LLM 呼び出しの共通層。

既定は **Gemini の無料枠** を使う (Claude API の課金を避けるため)。
複数モデルを順に試し、無料枠を使い切った (429) ら次のモデルへフォールバックする
ので、「Flash-Lite の無料枠を複数モデル分たし算して使う」運用ができる。

- 依存追加なし: 素の REST を httpx で叩く (httpx は既にコア依存)。
- provider="claude" にすれば従来の Anthropic API も使える (任意・課金される)。

設定は config/ai.yaml (無ければ既定値)。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/ai.yaml")

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
# Gemini のAPIキーはこの順で環境変数を探す
GEMINI_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")


class LLMError(RuntimeError):
    """LLM 呼び出しの一般エラー。"""


class QuotaExceeded(LLMError):
    """無料枠 / レート上限に達した (429)。次のモデルへフォールバックする合図。"""


class NoAPIKey(LLMError):
    """APIキーが未設定。呼び出し側で「スキップ」判断に使う。"""


@dataclass
class LLMConfig:
    provider: str = "gemini"
    # フォールバック順。前のモデルが無料枠切れなら次を試す。
    models: list[str] = field(default_factory=list)
    max_output_tokens: int = 512
    temperature: float = 0.0
    # 1リクエストごとの待機秒 (無料枠は RPM 制限が厳しいので既定で少し待つ)
    request_interval_seconds: float = 4.0
    timeout_seconds: float = 60.0

    @classmethod
    def load(cls, path: Path | None = None) -> "LLMConfig":
        p = path or DEFAULT_CONFIG_PATH
        data: dict[str, Any] = {}
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg = cls()
        cfg.provider = str(data.get("provider") or cfg.provider)
        models = data.get("models")
        if models:
            cfg.models = [str(m) for m in models]
        cfg.max_output_tokens = int(data.get("max_output_tokens", cfg.max_output_tokens))
        cfg.temperature = float(data.get("temperature", cfg.temperature))
        cfg.request_interval_seconds = float(
            data.get("request_interval_seconds", cfg.request_interval_seconds)
        )
        cfg.timeout_seconds = float(data.get("timeout_seconds", cfg.timeout_seconds))
        if not cfg.models:
            raise LLMError(
                "利用するモデルが設定されていません。config/ai.yaml の models を設定してください。"
            )
        return cfg


def api_key_present(cfg: LLMConfig | None = None) -> bool:
    """APIキーが設定されているか (未設定ならジョブを skip する用途)。"""
    provider = (cfg.provider if cfg else "gemini").lower()
    if provider == "claude":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return any(os.environ.get(v) for v in GEMINI_KEY_ENVS)


def _gemini_api_key() -> str:
    for v in GEMINI_KEY_ENVS:
        key = os.environ.get(v)
        if key:
            return key
    raise NoAPIKey(
        "Gemini の APIキーが未設定です (GEMINI_API_KEY)。"
        " https://aistudio.google.com/apikey で取得できます。"
    )


def _extract_json(text: str) -> dict[str, Any]:
    """応答から JSON を取り出す。前後にゴミがあっても {...} を拾う。

    出力トークン上限などで応答が途中で切れた場合 ('{"a":"x","b' で終わる等) は、
    そこまでに完成しているキーだけを救出する (1件まるごと失敗させない)。
    """
    start = text.find("{")
    if start == -1:
        raise LLMError(f"応答に JSON がありません: {text[:200]}")
    end = text.rfind("}")
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass  # 閉じ括弧はあるが壊れている → 下の救出処理へ

    # 尻切れの救出: 完成している "key": "value" ペアだけ拾って組み立てる
    salvaged = dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', text[start:]))
    if salvaged:
        logger.warning("応答が途中で切れたため部分的に復元しました (%d項目)", len(salvaged))
        return salvaged
    raise LLMError(f"応答の JSON が壊れています: {text[:200]}")


def _call_gemini(
    model: str, system: str, user: str, schema: dict[str, Any] | None, cfg: LLMConfig
) -> dict[str, Any]:
    """Gemini REST (generateContent) を叩いて JSON を返す。429 は QuotaExceeded に変換。

    一時的な失敗 (5xx/タイムアウト) のみ指数バックオフで再試行する。
    429 は再試行せず即座に次のモデルへ回す (1日あたり上限なら待っても回復しないため)。
    """
    generation: dict[str, Any] = {
        "responseMimeType": "application/json",
        "maxOutputTokens": cfg.max_output_tokens,
        "temperature": cfg.temperature,
    }
    if schema:
        generation["responseSchema"] = schema

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation,
    }

    url = GEMINI_ENDPOINT.format(model=model)
    headers = {"x-goog-api-key": _gemini_api_key(), "Content-Type": "application/json"}

    resp = None
    for attempt in range(3):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=cfg.timeout_seconds)
        except httpx.HTTPError as e:
            if attempt == 2:
                raise LLMError(f"Gemini 接続失敗 ({model}): {e}") from e
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 429:
            raise QuotaExceeded(f"{model}: 無料枠/レート上限 (429)")
        if resp.status_code >= 500:  # 一時障害のみ再試行
            if attempt == 2:
                raise LLMError(f"{model}: HTTP {resp.status_code} {resp.text[:200]}")
            time.sleep(2 ** attempt)
            continue
        break

    if resp is None:
        raise LLMError(f"{model}: 応答がありません")
    if resp.status_code == 404:
        raise LLMError(f"{model}: モデルが見つかりません (404)。モデルIDを確認してください。")
    if resp.status_code >= 400:
        raise LLMError(f"{model}: HTTP {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError) as e:
        # safety block 等で candidates が空になることがある
        raise LLMError(f"{model}: 応答を解釈できません: {str(data)[:200]}") from e
    if not text:
        raise LLMError(f"{model}: 応答が空です")
    return _extract_json(text)


def _call_claude(
    model: str, system: str, user: str, _schema: dict[str, Any] | None, cfg: LLMConfig
) -> dict[str, Any]:
    """Anthropic API (任意・課金あり)。"""
    import anthropic  # late import

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NoAPIKey("ANTHROPIC_API_KEY が未設定です")
    client = anthropic.Anthropic()
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=cfg.max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # noqa: BLE001 - SDK 例外を種別に寄せる
        if "rate_limit" in str(e).lower() or "429" in str(e):
            raise QuotaExceeded(f"{model}: レート上限") from e
        raise LLMError(f"{model}: {e}") from e
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    return _extract_json(text)


def generate_json(
    system: str,
    user: str,
    *,
    schema: dict[str, Any] | None = None,
    cfg: LLMConfig | None = None,
) -> tuple[dict[str, Any], str]:
    """JSON を返させる。使えるモデルを順に試す。

    Returns: (パース済み JSON, 実際に使ったモデル名)
    Raises:
        QuotaExceeded — 全モデルが無料枠切れ
        NoAPIKey      — APIキー未設定
        LLMError      — その他
    """
    cfg = cfg or LLMConfig.load()
    call = _call_claude if cfg.provider.lower() == "claude" else _call_gemini

    last_error: Exception | None = None
    quota_hits = 0
    for model in cfg.models:
        try:
            data = call(model, system, user, schema, cfg)
            if cfg.request_interval_seconds > 0:
                time.sleep(cfg.request_interval_seconds)
            return data, model
        except QuotaExceeded as e:
            quota_hits += 1
            last_error = e
            logger.info("%s は無料枠切れ。次のモデルを試します。", model)
            continue
        except NoAPIKey:
            raise
        except LLMError as e:
            # モデル固有の失敗 (404 等) も次のモデルで救えることがある
            last_error = e
            logger.warning("%s で失敗: %s", model, e)
            continue

    if quota_hits and quota_hits == len(cfg.models):
        raise QuotaExceeded("すべてのモデルが無料枠/レート上限に達しました")
    raise LLMError(f"全モデルで失敗しました: {last_error}")
