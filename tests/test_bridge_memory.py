"""§2.1 素通し保証（AgentBridge）と §9 メモリー。"""

import pytest

from persona_layer.agent import ScriptedAgent
from persona_layer.bridge import AgentBridge, AgentError
from persona_layer.memory import PersonaMemory, classify_utterance
from persona_layer.models import PersonaBinding
from persona_layer.state import StateEngine

from .conftest import make_persona
from .test_state import FakeClock


def make_bridge(reply: str, clock=None, memory=None):
    persona = make_persona()
    clock = clock or FakeClock()
    agent = ScriptedAgent([reply], agent_id="a1")
    binding = PersonaBinding(persona_id=persona.id, agent_id="a1")
    engine = StateEngine(persona.id, clock=clock)
    return AgentBridge(persona, binding, agent, engine, memory, clock), agent, engine


async def test_pass_through_criterion_1():
    """受け入れ基準1: Agent 出力とユーザー到達テキストが完全一致。"""
    raw = "売上は 1,234,567 円です。<注意>記号も改行も\nそのまま。"
    bridge, _, _ = make_bridge(raw)
    result = await bridge.ask("質問")
    assert result.text == raw  # 一切の書き換えなし


async def test_persona_injected_into_agent_system_prompt():
    """§2.1 例外規定: 文体は Agent 側システムプロンプトへの注入のみ。"""
    bridge, agent, _ = make_bridge("回答")
    await bridge.ask("質問")
    system, prompt = agent.calls[0]
    assert "テスト" in system  # 人格記述が system に入る
    assert "一人称は「私」" in system
    assert prompt == "質問"


async def test_agent_error_bumps_arousal_and_raises():
    persona = make_persona()
    clock = FakeClock()

    class FailingAgent:
        agent_id = "a1"

        async def respond(self, system, prompt):
            raise RuntimeError("boom")

    binding = PersonaBinding(persona_id=persona.id, agent_id="a1")
    engine = StateEngine(persona.id, clock=clock)
    bridge = AgentBridge(persona, binding, FailingAgent(), engine, clock=clock)
    with pytest.raises(AgentError):
        await bridge.ask("質問")
    assert engine.state.last_event == "error"


async def test_binding_agent_mismatch_rejected():
    """1 PersonaInstance = 1 Agent の 1:1 制約（§11.1）の基礎検証。"""
    persona = make_persona()
    binding = PersonaBinding(persona_id=persona.id, agent_id="other")
    engine = StateEngine(persona.id)
    with pytest.raises(ValueError):
        AgentBridge(persona, binding, ScriptedAgent([], agent_id="a1"), engine)


# ---- §9 メモリー ----

def test_classify_explicit_request():
    assert classify_utterance("この形式で覚えておいて") == ("preference", 1.0)


def test_classify_preference_expression():
    assert classify_utterance("箇条書きは嫌いです") == ("preference", 0.6)
    assert classify_utterance("メールより口頭の方がいい") == ("preference", 0.6)


def test_classify_ordinary_utterance_not_stored():
    assert classify_utterance("今日の売上を教えて") is None


def test_memory_read_only_preference_and_episode():
    """§9.2: 人格レイヤーが読むのは preference と episode のみ。"""
    memory = PersonaMemory()
    memory.consider_utterance("p1", "u1", "長い説明は嫌い")
    memory.record_correction("p1", "u1", "その数字は間違い、正しくは200")
    memory.record_episode("p1", "u1", "月次レポートを完了した")
    lines = memory.read_lines("p1", "u1")
    assert "長い説明は嫌い" in lines
    assert "月次レポートを完了した" in lines
    assert all("正しくは200" not in line for line in lines)


def test_memory_scoped_by_persona_and_user():
    memory = PersonaMemory()
    memory.consider_utterance("p1", "u1", "箇条書きは嫌い")
    assert memory.read_lines("p2", "u1") == []
    assert memory.read_lines("p1", "u2") == []


def test_memory_read_limits():
    """直近10件 + weight 上位5件（§9.2）。"""
    memory = PersonaMemory(clock=iter(range(100)).__next__)
    for i in range(30):
        memory.record_episode("p1", "u1", f"エピソード{i}")
    memory.consider_utterance("p1", "u1", "覚えておいて: 敬称は不要")
    lines = memory.read_lines("p1", "u1")
    assert len(lines) <= 15
    assert "覚えておいて: 敬称は不要" in lines  # weight 1.0 は必ず入る
