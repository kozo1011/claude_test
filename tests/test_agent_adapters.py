"""既存 AI Agent 接続アダプタ（HTTP / Python / 設定駆動）のテスト。

ネットワークには出ず、httpx.MockTransport でリクエスト形式を検証する。
"""

import json

import httpx
import pytest

from persona_layer.agent import (
    AgentRequest,
    AgentTurn,
    EchoAgent,
    GeminiAgent,
    HTTPAgent,
    OpenAICompatibleAgent,
    build_agent,
    load_python_agent,
)
from persona_layer.config import AppConfig, ConfigError, expand_env
from persona_layer.room import Room
from persona_layer.models import PersonaBinding

from .conftest import make_persona
from .test_room import TIMESCALE, task_speeches


def sample_request() -> AgentRequest:
    return AgentRequest(
        system="あなたは楓です",
        prompt="これまでの会話:\n利用者（人間の参加者）: 見積もりは？",
        instruction="直前の発話に応答してください",
        turns=[
            AgentTurn(role="user", content="見積もりは？", speaker_name="利用者",
                      speaker_kind="human"),
            AgentTurn(role="assistant", content="確認します", speaker_name="楓",
                      speaker_kind="persona", is_self=True),
            AgentTurn(role="user", content="お願い", speaker_name="利用者",
                      speaker_kind="human"),
        ],
        persona={"id": "kaede", "style": {"distance": 2}},
        session_id="kaede@hermes:user1",
    )


# ---- HTTPAgent（既存 Agent 接続の本命） ----

async def test_http_agent_default_contract():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": "見積もりは120万円です"})

    agent = HTTPAgent(
        agent_id="hermes",
        url="http://localhost:9000/chat",
        transport=httpx.MockTransport(handler),
    )
    out = await agent.respond_request(sample_request())
    assert out == "見積もりは120万円です"
    assert captured["url"] == "http://localhost:9000/chat"
    assert captured["method"] == "POST"
    body = captured["body"]
    assert body["system"] == "あなたは楓です"
    assert body["sessionId"] == "kaede@hermes:user1"
    assert body["text"] == "お願い"                     # 直前の user 発話
    assert body["persona"]["id"] == "kaede"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][1]["isSelf"] is True        # 自分の過去発話（§11.5）
    assert body["messages"][0]["speakerName"] == "利用者"


async def test_http_agent_custom_field_mapping():
    """HermesAgent 側の既存 API に合わせてフィールド名を寄せられること。"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"result": {"reply": "了解"}})

    agent = HTTPAgent(
        agent_id="hermes",
        url="http://localhost:9000/ask",
        headers={"Authorization": "Bearer tok"},
        send={"text": "question", "session_id": "conversation_id",
              "system": None, "messages": None, "persona": None, "instruction": None},
        receive="result.reply",           # ドット記法で入れ子から取り出す
        transport=httpx.MockTransport(handler),
    )
    assert await agent.respond_request(sample_request()) == "了解"
    assert captured["auth"] == "Bearer tok"
    # None を指定したフィールドは送らない
    assert set(captured["body"]) == {"question", "conversation_id"}
    assert captured["body"]["question"] == "お願い"


async def test_http_agent_bad_response_raises():
    agent = HTTPAgent(
        agent_id="hermes",
        url="http://x/chat",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"foo": 1})),
    )
    with pytest.raises(ValueError, match="receive"):
        await agent.respond_request(sample_request())


async def test_http_agent_plain_respond_still_works():
    """respond(system, prompt) 経由でも使える（後方互換）。"""
    agent = HTTPAgent(
        agent_id="hermes",
        url="http://x/chat",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"content": "ok"})
        ),
    )
    assert await agent.respond("sys", "hello") == "ok"


def test_http_agent_requires_url():
    with pytest.raises(ConfigError, match="url"):
        HTTPAgent(agent_id="x", url="")


# ---- PythonAgent ----

class _DummyAgent:
    """load_python_agent のテスト用（module:Class 解決の確認）。"""

    def __init__(self, prefix: str = "") -> None:
        self.agent_id = ""
        self.prefix = prefix

    async def respond(self, system, prompt):
        return f"{self.prefix}{prompt}"


async def test_load_python_agent():
    agent = load_python_agent(
        "tests.test_agent_adapters:_DummyAgent", "hermes-local", {"prefix": "> "}
    )
    assert agent.agent_id == "hermes-local"
    assert await agent.respond(None, "hi") == "> hi"


def test_load_python_agent_bad_target():
    with pytest.raises(ConfigError, match="module:Class"):
        load_python_agent("no_colon", "x")
    with pytest.raises(ConfigError, match="読み込めません"):
        load_python_agent("nonexistent_module_xyz:Klass", "x")
    with pytest.raises(ConfigError, match="見つかりません"):
        load_python_agent("tests.test_agent_adapters:NoSuchClass", "x")


# ---- 設定駆動（agents: / bindings:） ----

def test_config_agents_take_priority_over_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    config = AppConfig({
        "provider": "gemini",
        "agents": {"hermes": {"type": "http", "url": "http://localhost:9000/chat"}},
    })
    agent = build_agent("hermes", config)
    assert isinstance(agent, HTTPAgent)   # 既定 provider(gemini) より agents: が優先
    assert agent.url == "http://localhost:9000/chat"
    # 未定義の agentId は従来どおりプロバイダ推定にフォールバック
    assert isinstance(build_agent("default", config), GeminiAgent)


def test_config_agent_openai_compatible():
    config = AppConfig({
        "agents": {
            "hermes": {
                "type": "openai_compatible",
                "base_url": "http://localhost:9000/v1",
                "model": "hermes-1",
            }
        }
    })
    agent = build_agent("hermes", config)
    assert isinstance(agent, OpenAICompatibleAgent)
    assert agent.base_url == "http://localhost:9000/v1"
    assert agent.model == "hermes-1"


def test_config_agent_mock_and_llm(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    config = AppConfig({
        "agents": {
            "dummy": {"type": "mock"},
            "router": {"type": "llm", "provider": "openrouter"},
        }
    })
    assert isinstance(build_agent("dummy", config), EchoAgent)
    assert isinstance(build_agent("router", config), OpenAICompatibleAgent)


def test_config_agent_env_expansion(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    config = AppConfig({
        "agents": {
            "hermes": {
                "type": "http",
                "url": "http://localhost:9000/chat",
                "headers": {"Authorization": "Bearer ${HERMES_API_KEY}"},
            }
        }
    })
    agent = build_agent("hermes", config)
    assert agent.headers["Authorization"] == "Bearer secret-123"


def test_expand_env_leaves_unknown_empty(monkeypatch):
    monkeypatch.delenv("NOT_SET_XYZ", raising=False)
    assert expand_env("a${NOT_SET_XYZ}b") == "ab"
    assert expand_env({"k": ["${NOT_SET_XYZ}x"]}) == {"k": ["x"]}


def test_config_agent_validation():
    with pytest.raises(ConfigError, match="type がありません"):
        AppConfig({"agents": {"a": {"url": "x"}}}).resolve_agent("a")
    with pytest.raises(ConfigError, match="type が不正"):
        AppConfig({"agents": {"a": {"type": "grpc"}}}).resolve_agent("a")


def test_config_bindings():
    config = AppConfig({
        "bindings": [
            {"persona": "kaede", "agent": "hermes", "expertise": ["経費"],
             "invocationAliases": ["楓"]},
        ]
    })
    binding = config.bindings()[0]
    assert binding["persona_id"] == "kaede"
    assert binding["agent_id"] == "hermes"
    assert binding["expertise"] == ["経費"]
    # PersonaBinding にそのまま渡せる形であること（§4.3）
    assert PersonaBinding(**binding).agent_id == "hermes"


def test_config_binding_requires_persona():
    with pytest.raises(ConfigError, match="persona がありません"):
        AppConfig({"bindings": [{"agent": "hermes"}]}).bindings()


# ---- 構造化メッセージ（品質改善） ----

async def test_llm_receives_multi_turn_roles():
    """会話が1本の平文ではなく role 付き多ターンで渡ること。"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    agent = OpenAICompatibleAgent(
        "openrouter", "m", "k", "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(handler),
    )
    await agent.respond_request(sample_request())
    messages = captured["body"]["messages"]
    assert messages[0]["role"] == "system"
    assert "あなたは楓です" in messages[0]["content"]
    assert "直前の発話に応答" in messages[0]["content"]   # instruction も system 側へ
    assert [m["role"] for m in messages[1:]] == ["user", "assistant", "user"]
    # 自分以外の発話には話者名が付く（§11.5）
    assert messages[1]["content"] == "利用者: 見積もりは？"
    assert messages[2]["content"] == "確認します"          # 自分の発話は名前なし


async def test_gemini_uses_model_role_and_alternates():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        )

    agent = GeminiAgent(
        "gemini", "gemini-2.0-flash", "k",
        "https://generativelanguage.googleapis.com/v1beta",
        transport=httpx.MockTransport(handler),
    )
    await agent.respond_request(sample_request())
    contents = captured["body"]["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]


async def test_consecutive_same_role_merged_and_leading_assistant_dropped():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    agent = OpenAICompatibleAgent(
        "openai", "m", "k", "https://api.openai.com/v1",
        transport=httpx.MockTransport(handler),
    )
    request = AgentRequest(
        turns=[
            AgentTurn(role="assistant", content="先頭の自分発話", is_self=True),
            AgentTurn(role="user", content="A", speaker_name="甲"),
            AgentTurn(role="user", content="B", speaker_name="乙"),
        ]
    )
    await agent.respond_request(request)
    messages = [m for m in captured["body"]["messages"] if m["role"] != "system"]
    # 先頭の assistant は落ち、連続する user はまとめられる
    assert messages == [{"role": "user", "content": "甲: A\n乙: B"}]


async def test_empty_turns_falls_back_to_prompt():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    agent = OpenAICompatibleAgent(
        "openai", "m", "k", "https://api.openai.com/v1",
        transport=httpx.MockTransport(handler),
    )
    await agent.respond_request(AgentRequest(prompt="平文だけ", turns=[]))
    assert captured["body"]["messages"][-1] == {"role": "user", "content": "平文だけ"}


# ---- ルーム経由の結合（受け入れ基準1を新経路で再検証） ----

async def test_external_agent_answer_passes_through_room():
    """HTTP 接続した既存 Agent の回答が、そのままルームに出ること（§2.1）。"""
    raw = "第3四半期の売上は 1,234,567 円です。<注記>記号もそのまま。"
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": raw})

    agent = HTTPAgent(
        agent_id="hermes",
        url="http://localhost:9000/chat",
        transport=httpx.MockTransport(handler),
    )
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    persona = make_persona(id="kaede", name="楓")
    binding = PersonaBinding(
        persona_id="kaede", agent_id="hermes", expertise=["売上"],
        invocation_aliases=["楓"],
    )
    await room.enter(persona, binding, agent)
    room.human_speech("u1", "第3四半期の売上を教えて")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)

    speeches = task_speeches(room)
    assert len(speeches) == 1
    assert speeches[0].text == raw          # 素通し（受け入れ基準1）
    assert speeches[0].speaker_id == "kaede@hermes"
    # Agent には人格記述とセッションID、話者付き履歴が渡っている
    assert "楓" in captured["body"]["system"]
    assert captured["body"]["sessionId"] == "kaede@hermes:default"
    assert captured["body"]["messages"][-1]["content"] == "第3四半期の売上を教えて"
    await room.close()


async def test_external_agent_failure_falls_back_to_apology():
    """接続先が落ちていても apology メタ発話に流れ、ルームは壊れないこと。"""
    agent = HTTPAgent(
        agent_id="hermes",
        url="http://localhost:9000/chat",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(500, json={"error": "down"})
        ),
    )
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    persona = make_persona(id="kaede", name="楓")
    binding = PersonaBinding(persona_id="kaede", agent_id="hermes")
    await room.enter(persona, binding, agent)
    room.human_speech("u1", "調子はどう？")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)

    assert task_speeches(room) == []       # タスク回答は出ない
    metas = [e.meta_kind for e in room.bus.log if e.kind == "meta"]
    assert "apology" in metas
    await room.close()
