"""§11 ルーム・入退室・発話権の統合テスト（受け入れ基準 1・5・11・12）。

timescale を縮めて実時間の backoff（200ms〜1200ms）を数ms〜数十msで再現する。
"""

import asyncio
import random

import pytest

from persona_layer.agent import ScriptedAgent
from persona_layer.models import PersonaBinding
from persona_layer.room import Room, match_invocation, suggest_alternative
from persona_layer.room.bus import RoomBus

from .conftest import make_persona

TIMESCALE = 0.02  # backoff 1200ms → 24ms


def binding_for(persona, agent_id, expertise=None, aliases=None):
    return PersonaBinding(
        persona_id=persona.id,
        agent_id=agent_id,
        expertise=expertise or [],
        invocation_aliases=aliases or [persona.display_name],
    )


async def enter(room, persona, replies, expertise=None, delay=0.0, seed=0):
    agent = ScriptedAgent(replies, agent_id=f"agent-{persona.id}", delay_sec=delay)
    await room.enter(
        persona,
        binding_for(persona, agent.agent_id, expertise),
        agent,
        rng=random.Random(seed),
    )
    return agent


def task_speeches(room):
    return [e for e in room.bus.log if e.type == "speech" and e.kind == "task"]


# ---- RoomBus（§11.4） ----

def test_bus_requires_speaker_id():
    bus = RoomBus()
    with pytest.raises(ValueError, match="speakerId"):
        bus.publish("speech", speaker_id="", speaker_kind="human")


def test_bus_records_all_events_with_time():
    bus = RoomBus()
    bus.publish("speech", speaker_id="u1", speaker_kind="human", text="a", kind="human")
    bus.publish("bid", speaker_id="p1", speaker_kind="persona")
    assert [e.type for e in bus.log] == ["speech", "bid"]
    assert all(e.at > 0 and e.seq > 0 for e in bus.log)


# ---- 単体運用 = N=1 のルーム（§2.6, Phase 7） ----

async def test_single_instance_responds_with_passthrough_criterion_1():
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    persona = make_persona(id="p1", name="楓")
    raw = "結論: 移行は7月が最適です。理由は3点あります。"
    agent = await enter(room, persona, [raw])
    room.human_speech("u1", "移行時期はいつがいい？")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)
    speeches = task_speeches(room)
    assert len(speeches) == 1
    assert speeches[0].text == raw          # 素通し（受け入れ基準1）
    assert speeches[0].speaker_id == "p1@agent-p1"
    assert speeches[0].ssml.startswith("<prosody")
    assert len(agent.calls) == 1
    await room.close()


async def test_filler_precedes_agent_response_criterion_5():
    """受け入れ基準5: filler の発話開始が Agent 応答の受信より必ず早い。"""
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    persona = make_persona(id="p1", name="楓")
    await enter(room, persona, ["回答です"], delay=0.05)
    room.human_speech("u1", "調べて")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)
    log = room.bus.log
    filler = next(e for e in log if e.type == "speech" and e.meta_kind == "filler")
    answer = next(e for e in log if e.type == "speech" and e.kind == "task")
    assert filler.seq < answer.seq
    assert filler.at < answer.at
    await room.close()


async def test_switch_is_leave_then_enter():
    """§11.3: 「切り替え」は退室+入室の組み合わせ。専用コードはない。"""
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    a = make_persona(id="pa", name="A")
    b = make_persona(id="pb", name="B")
    await enter(room, a, ["Aの回答"])
    await room.leave("pa@agent-pa")
    await enter(room, b, ["Bの回答"])
    room.human_speech("u1", "お願い")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)
    speeches = task_speeches(room)
    assert {e.speaker_id for e in speeches} == {"pb@agent-pb"}
    types = [e.type for e in room.bus.log]
    assert "enter" in types and "leave" in types
    await room.close()


async def test_duplicate_persona_agent_pair_rejected():
    """§11.1: 同一人格×同一 Agent は1ルームに1つまで。"""
    room = Room(timescale=TIMESCALE)
    persona = make_persona(id="p1")
    agent = ScriptedAgent([], agent_id="a1")
    await room.enter(persona, binding_for(persona, "a1"), agent)
    with pytest.raises(ValueError, match="既に"):
        await room.enter(persona, binding_for(persona, "a1"), agent)
    await room.close()


# ---- 複数体（§11.6, Phase 10） ----

async def test_no_self_reaction_criterion_11():
    """受け入れ基準11: speakerId を根拠に、自分自身の発話に反応しない。"""
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    a = make_persona(id="pa", name="阿部", initiative=4)
    b = make_persona(id="pb", name="別役", initiative=2)
    agent_a = await enter(room, a, ["Aの回答です"], seed=1)
    agent_b = await enter(room, b, ["Bの回答です"], seed=2)
    room.human_speech("u1", "意見を聞かせて")
    await room.wait_quiet(idle_sec=0.3, timeout_sec=5)
    # 高々1回ずつしか Agent は呼ばれない（自己発話への反応があれば増殖する）
    assert len(agent_a.calls) <= 2 and len(agent_b.calls) <= 2
    # 同一話者のタスク回答が連続しない（独演の禁止）
    speakers = [e.speaker_id for e in task_speeches(room)]
    assert all(x != y for x, y in zip(speakers, speakers[1:]))
    await room.close()


async def test_initiative_orders_first_speech_criterion_12():
    """受け入れ基準12: 沈黙後の初手は主導性の高い方が取る。"""
    for seed in range(5):
        room = Room(timescale=TIMESCALE)
        room.join_human("u1", "利用者")
        eager = make_persona(id="eager", name="先手", initiative=4)
        shy = make_persona(id="shy", name="後手", initiative=0)
        await enter(room, eager, ["先手の回答"], seed=seed)
        await enter(room, shy, ["後手の回答"], seed=seed + 100)
        room.human_speech("u1", "誰か答えて")
        await room.wait_quiet(idle_sec=0.3, timeout_sec=5)
        speeches = task_speeches(room)
        assert speeches, "誰も答えていない"
        # backoff: eager 200-320ms / shy 1200-1320ms → eager が必ず先
        assert speeches[0].speaker_id == "eager@agent-eager"
        await room.close()


async def test_addressed_persona_answers():
    """名指しされた人格が高優先で応答する（§11.6 bid条件）。"""
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    a = make_persona(id="pa", name="阿部", initiative=0)   # 名指しされる側は低主導
    b = make_persona(id="pb", name="別役", initiative=4)
    await enter(room, a, ["阿部の回答"], seed=1)
    await enter(room, b, ["別役の回答"], seed=2)
    room.human_speech("u1", "阿部さん、これどう思う？")
    await room.wait_quiet(idle_sec=0.3, timeout_sec=5)
    speeches = task_speeches(room)
    # 高優先 bid の backoff（50-170ms）は通常 bid の最短（200ms）より必ず短い
    # → 主導性が低くても、名指しされた阿部が先に発話権を取る
    assert speeches
    assert speeches[0].speaker_id == "pa@agent-pa"
    await room.close()


async def test_expertise_triggers_ai_to_ai_response():
    """他 AI の発話でも expertise に触れれば bid する（§11.6）。"""
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    first = make_persona(id="first", name="一朗", initiative=4)
    expert = make_persona(id="expert", name="専門家", initiative=2)
    await enter(room, first, ["これは投資の判断が要りますね"], seed=1)
    agent_expert = await enter(
        room, expert, ["投資の観点では分散が重要です"], ["投資"], seed=2
    )
    room.human_speech("u1", "この計画どう思う？")
    await room.wait_quiet(idle_sec=0.4, timeout_sec=5)
    speeches = task_speeches(room)
    assert speeches[0].speaker_id == "first@agent-first"
    assert any(e.speaker_id == "expert@agent-expert" for e in speeches)
    # expert の Agent には話者名付きの文脈が渡っている（§11.5）
    _, prompt = agent_expert.calls[0]
    assert "一朗" in prompt and "利用者" in prompt
    assert "人間" in prompt
    await room.close()


async def test_context_marks_own_past_speech():
    """§11.5: 自分の過去発話に「（自分）」の印をつける。"""
    room = Room(timescale=TIMESCALE)
    room.join_human("u1", "利用者")
    persona = make_persona(id="p1", name="楓")
    agent = await enter(room, persona, ["1回目の回答", "2回目の回答"])
    room.human_speech("u1", "最初の質問")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)
    room.human_speech("u1", "続きの質問")
    await room.wait_quiet(idle_sec=0.2, timeout_sec=5)
    _, prompt2 = agent.calls[1]
    assert "楓（自分・AI）: 1回目の回答" in prompt2
    await room.close()


async def test_turn_limit_stops_ai_chatter_until_human_speaks():
    """§11.7: ターン上限の安全弁。人間の発話で再開する。"""
    room = Room(timescale=TIMESCALE, max_persona_turns=2)
    room.join_human("u1", "利用者")
    # 互いの expertise に触れ続ける2体 → 放置すると無限に続く構成
    a = make_persona(id="pa", name="阿部", initiative=3)
    b = make_persona(id="pb", name="別役", initiative=3)
    await enter(room, a, ["経営の話を続けます"] * 10, ["経営"], seed=1)
    await enter(room, b, ["経営について補足します"] * 10, ["経営"], seed=2)
    room.human_speech("u1", "経営について議論して")
    await room.wait_quiet(idle_sec=0.4, timeout_sec=5)
    assert any(e.type == "turn_limit" for e in room.bus.log)
    count_after_stop = len(task_speeches(room))
    assert count_after_stop <= 4  # 上限2 + 進行中だった発話ぶんの余裕
    # 人間（司会）が喋ると再開する
    room.human_speech("u1", "続けて")
    await room.wait_quiet(idle_sec=0.4, timeout_sec=5)
    assert len(task_speeches(room)) > count_after_stop
    await room.close()


# ---- §11.2 入室の照合・提案（LLMなし） ----

def test_match_invocation_by_alias():
    b1 = PersonaBinding(
        persona_id="p1", agent_id="a1", invocation_aliases=["楓", "かえで"]
    )
    b2 = PersonaBinding(persona_id="p2", agent_id="a2", invocation_aliases=["源"])
    assert match_invocation("楓さんを出して", [b1, b2]) is b1
    assert match_invocation("源さんに聞きたい", [b1, b2]) is b2
    assert match_invocation("誰か出して", [b1, b2]) is None  # 自動ルーティングしない


def test_suggest_alternative_by_expertise_only():
    current = PersonaBinding(persona_id="p1", agent_id="a1", expertise=["開発"])
    other = PersonaBinding(persona_id="p2", agent_id="a2", expertise=["投資"])
    assert suggest_alternative("投資信託を選びたい", current, [other]) is other
    assert suggest_alternative("コードレビューして", current, [other]) is None
