"""LLM 共通層 (Gemini 無料枠 + モデルフォールバック) の単体テスト。ネットワーク不要。"""
import json
from pathlib import Path

import pytest

from src import llm, resale_ai


@pytest.fixture
def cfg():
    return llm.LLMConfig(
        provider="gemini",
        models=["model-a", "model-b", "model-c"],
        request_interval_seconds=0.0,   # テストでは待たない
    )


class _Resp:
    """httpx.Response の最小モック。"""
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _ok(obj):
    return _Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]})


# ---- 設定 ----

def test_config_loads_shipped_yaml():
    """同梱の config/ai.yaml が読めて、Gemini の無料枠モデルが並んでいること。"""
    c = llm.LLMConfig.load(Path("config/ai.yaml"))
    assert c.provider == "gemini"
    assert "gemini-3.5-flash-lite" in c.models     # ユーザー指定の第一候補
    assert "gemini-3.1-flash-lite" in c.models     # ユーザー指定の2番手
    assert c.models[0] == "gemini-3.5-flash-lite"  # 最安・最速を先に試す


def test_config_requires_models(tmp_path):
    p = tmp_path / "ai.yaml"
    p.write_text("provider: gemini\nmodels: []\n", encoding="utf-8")
    with pytest.raises(llm.LLMError):
        llm.LLMConfig.load(p)


def test_api_key_present(monkeypatch, cfg):
    for v in llm.GEMINI_KEY_ENVS:
        monkeypatch.delenv(v, raising=False)
    assert llm.api_key_present(cfg) is False
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    assert llm.api_key_present(cfg) is True


def test_api_key_accepts_google_api_key(monkeypatch, cfg):
    for v in llm.GEMINI_KEY_ENVS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")     # 別名でも拾う
    assert llm.api_key_present(cfg) is True


# ---- 呼び出し / フォールバック ----

def test_generate_json_success(monkeypatch, cfg):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _ok({"verdict": "検討可"}))
    data, model = llm.generate_json("sys", "user", cfg=cfg)
    assert data == {"verdict": "検討可"}
    assert model == "model-a"          # 1番目のモデルで成功


def test_falls_back_to_next_model_on_quota(monkeypatch, cfg):
    """無料枠切れ(429)なら次のモデルへ自動で切り替わる。"""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return _Resp(429, text="quota") if len(calls) == 1 else _ok({"ok": True})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    data, model = llm.generate_json("sys", "user", cfg=cfg)
    assert data == {"ok": True}
    assert model == "model-b"          # 2番目に切り替わった
    assert "model-a" in calls[0] and "model-b" in calls[1]


def test_all_models_exhausted_raises_quota(monkeypatch, cfg):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _Resp(429, text="quota"))
    with pytest.raises(llm.QuotaExceeded):
        llm.generate_json("sys", "user", cfg=cfg)


def test_404_model_falls_through(monkeypatch, cfg):
    """モデルIDが無効(404)でも次のモデルで救う。"""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return _Resp(404, text="not found") if len(calls) == 1 else _ok({"ok": True})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    data, model = llm.generate_json("sys", "user", cfg=cfg)
    assert model == "model-b"


def test_missing_api_key_raises(monkeypatch, cfg):
    for v in llm.GEMINI_KEY_ENVS:
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(llm.NoAPIKey):
        llm.generate_json("sys", "user", cfg=cfg)


def test_schema_is_sent_in_payload(monkeypatch, cfg):
    """構造化出力 (responseSchema) がリクエストに載ること。"""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        captured["headers"] = headers
        return _ok({"ok": True})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.generate_json("SYS", "USER", schema={"type": "OBJECT"}, cfg=cfg)
    gen = captured["body"]["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert gen["responseSchema"] == {"type": "OBJECT"}
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert captured["headers"]["x-goog-api-key"] == "dummy"   # キーはヘッダで渡す


def test_extracts_json_with_surrounding_text(monkeypatch, cfg):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    resp = _Resp(200, {"candidates": [{"content": {"parts": [
        {"text": 'ゴミ {"verdict":"警告"} 余計'}]}}]})
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: resp)
    data, _ = llm.generate_json("sys", "user", cfg=cfg)
    assert data == {"verdict": "警告"}


def test_empty_candidates_is_error(monkeypatch, cfg):
    """safety block 等で candidates が空でも落ちずに LLMError にする。"""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _Resp(200, {"candidates": []}))
    with pytest.raises(llm.LLMError):
        llm.generate_json("sys", "user", cfg=cfg)


# ---- resale_ai との結合 ----

def test_assess_property_uses_llm(monkeypatch, cfg):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _ok({
        "toilet": "和式", "bath": "使用可", "lifeline": "浄化槽", "parking": "あり",
        "vacancy_hint": "不明", "verdict": "検討可", "reasons": "風呂は使える",
    }))
    row = {"title": "テスト", "price": 1000000, "address": "岡山県高梁市",
           "area_land": None, "area_building": None, "body": "和式トイレ"}
    result, model = resale_ai.assess_property(row, cfg=cfg)
    assert result["toilet"] == "和式" and result["verdict"] == "検討可"
    assert model == "model-a"


def test_response_schema_has_enums():
    """Gemini の構造化出力スキーマが enum で値を強制していること。"""
    schema = resale_ai.RESPONSE_SCHEMA
    assert schema["type"] == "OBJECT"
    assert set(schema["properties"]["verdict"]["enum"]) == {"検討可", "警告", "見送り"}
    assert "reasons" in schema["required"]
