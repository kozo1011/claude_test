"""LLM 設定（config.py）とプロバイダアダプタ（agent.py）のテスト。

ネットワークには出ず、httpx.MockTransport でリクエスト形式を検証する。
"""

import json

import httpx
import pytest

from persona_layer.agent import (
    EchoAgent,
    GeminiAgent,
    OpenAICompatibleAgent,
    build_agent,
)
from persona_layer.config import AppConfig, ConfigError, load_config


# ---- config.py ----

def test_default_config_is_auto_mock_without_keys(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    cfg = AppConfig({})
    assert cfg.resolve().provider == "mock"


def test_autodetect_prefers_available_key(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-xxx")
    llm = AppConfig({"provider": "auto"}).resolve()
    assert llm.provider == "openrouter"
    assert llm.api_key == "sk-or-xxx"
    assert llm.base_url == "https://openrouter.ai/api/v1"
    assert llm.model == "openai/gpt-4o-mini"  # 既定モデル


def test_provider_and_model_from_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    cfg = AppConfig(
        {"provider": "gemini", "providers": {"gemini": {"model": "gemini-2.5-flash"}}}
    )
    llm = cfg.resolve()
    assert llm.provider == "gemini"
    assert llm.model == "gemini-2.5-flash"
    assert llm.api_key == "g-key"


def test_gemini_key_falls_back_to_google_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")
    llm = AppConfig({"provider": "gemini"}).resolve()
    assert llm.api_key == "goog-key"


def test_custom_api_key_env_name(monkeypatch):
    monkeypatch.setenv("MY_ROUTER_KEY", "custom")
    cfg = AppConfig(
        {"provider": "openrouter",
         "providers": {"openrouter": {"api_key_env": "MY_ROUTER_KEY"}}}
    )
    assert cfg.resolve().api_key == "custom"


def test_common_max_tokens_overridable_per_provider():
    cfg = AppConfig(
        {"provider": "openrouter", "max_tokens": 512,
         "providers": {"openrouter": {"max_tokens": 2048}}}
    )
    assert cfg.resolve().max_tokens == 2048
    cfg2 = AppConfig({"provider": "openrouter", "max_tokens": 512})
    assert cfg2.resolve().max_tokens == 512


def test_unknown_provider_raises():
    with pytest.raises(ConfigError, match="未知のプロバイダ"):
        AppConfig({"provider": "llama-cpp"}).resolve()


def test_load_config_from_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    path = tmp_path / "cfg.yaml"
    path.write_text(
        "provider: openrouter\nproviders:\n  openrouter:\n    model: anthropic/claude-3.5-sonnet\n",
        encoding="utf-8",
    )
    llm = load_config(path).resolve()
    assert llm.model == "anthropic/claude-3.5-sonnet"


def test_load_config_missing_explicit_path_errors(tmp_path):
    with pytest.raises(ConfigError, match="見つかりません"):
        load_config(tmp_path / "nope.yaml")


# ---- build_agent のプロバイダ選択 ----

def test_build_agent_mock_without_key(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    agent = build_agent("default", AppConfig({"provider": "openrouter"}))
    assert isinstance(agent, EchoAgent)  # キー未設定 → ダミーへフォールバック


def test_build_agent_selects_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    agent = build_agent("default", AppConfig({"provider": "openrouter"}))
    assert isinstance(agent, OpenAICompatibleAgent)
    assert agent.agent_id == "default"


def test_build_agent_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    agent = build_agent("default", AppConfig({"provider": "gemini"}))
    assert isinstance(agent, GeminiAgent)


def test_agent_id_prefix_overrides_default_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    cfg = AppConfig({"provider": "gemini"})
    # agentId が "openrouter" 始まりなら設定の既定(gemini)より優先される
    agent = build_agent("openrouter-1", cfg)
    assert isinstance(agent, OpenAICompatibleAgent)


def test_echo_agent_id_forces_mock(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    agent = build_agent("echo", AppConfig({"provider": "openrouter"}))
    assert isinstance(agent, EchoAgent)


# ---- OpenRouter（OpenAI 互換）アダプタ ----

async def test_openrouter_request_and_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["referer"] = request.headers.get("http-referer")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "了解しました"}}]},
        )

    agent = OpenAICompatibleAgent(
        agent_id="openrouter",
        model="openai/gpt-4o-mini",
        api_key="sk-or-test",
        base_url="https://openrouter.ai/api/v1",
        extra={"headers": {"HTTP-Referer": "http://localhost:8000"}},
        transport=httpx.MockTransport(handler),
    )
    out = await agent.respond("あなたは楓です", "こんにちは")
    assert out == "了解しました"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-or-test"
    assert captured["referer"] == "http://localhost:8000"
    assert captured["body"]["model"] == "openai/gpt-4o-mini"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "あなたは楓です"}
    assert captured["body"]["messages"][1] == {"role": "user", "content": "こんにちは"}


async def test_openai_compatible_handles_empty_choices():
    agent = OpenAICompatibleAgent(
        "openai", "gpt-4o-mini", "k", "https://api.openai.com/v1",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []})),
    )
    assert await agent.respond(None, "x") == ""


# ---- Gemini アダプタ ----

async def test_gemini_request_and_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-goog-api-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "はい、"}, {"text": "承知しました"}]}}]},
        )

    agent = GeminiAgent(
        agent_id="gemini",
        model="gemini-2.0-flash",
        api_key="g-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        transport=httpx.MockTransport(handler),
    )
    out = await agent.respond("あなたは源です", "調子はどう？")
    assert out == "はい、承知しました"  # parts が結合される
    assert captured["url"].endswith("/v1beta/models/gemini-2.0-flash:generateContent")
    assert captured["key"] == "g-test"  # キーはヘッダ（URLに載せない）
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "あなたは源です"
    assert captured["body"]["contents"][0]["parts"][0]["text"] == "調子はどう？"
    # 既定 max_tokens は 2048（1024 では思考トークンを含むモデルで切れるため）
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 2048


async def test_gemini_no_candidates_returns_empty():
    agent = GeminiAgent(
        "gemini", "gemini-2.0-flash", "k",
        "https://generativelanguage.googleapis.com/v1beta",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []})),
    )
    assert await agent.respond(None, "x") == ""


async def test_llm_error_propagates_as_exception():
    """HTTP エラーは例外になり、AgentBridge 側で apology メタ発話に流れる。"""
    agent = OpenAICompatibleAgent(
        "openrouter", "m", "k", "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad key"})),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await agent.respond(None, "x")
