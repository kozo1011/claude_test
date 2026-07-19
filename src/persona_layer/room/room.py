"""Room（§3.0, §11）: 参加者の入退室管理と RoomBus の保持。

- 「人格の切り替え」は独立した操作ではなく enter/leave の組み合わせ（§11.3）
- 1体運用は N=1 のルーム（§2.6）。専用コードは存在しない
- 発話ターン数の上限は §11.7 の安全弁。調停ではなく無限ループの最終防波堤
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from ..agent import Agent
from ..memory import PersonaMemory
from ..meta_speech import TemplateBaker
from ..models import Persona, PersonaBinding
from ..state import FamiliarityStore
from .. import tables
from .bus import RoomBus, RoomEvent
from .instance import PersonaInstance


@dataclass
class HumanParticipant:
    user_id: str
    name: str


class Room:
    def __init__(
        self,
        room_id: str | None = None,
        clock: Callable[[], float] = time.time,
        timescale: float = 1.0,
        max_persona_turns: int | None = None,
        familiarity_store: FamiliarityStore | None = None,
    ) -> None:
        self.room_id = room_id or f"room-{uuid.uuid4().hex[:8]}"
        self.bus = RoomBus(clock)
        self._clock = clock
        self.timescale = timescale
        self.instances: dict[str, PersonaInstance] = {}
        self.humans: dict[str, HumanParticipant] = {}
        self._familiarity_store = familiarity_store
        cfg = tables.arbiter()
        self._max_persona_turns = (
            max_persona_turns
            if max_persona_turns is not None
            else int(cfg["max_persona_turns"])
        )
        self._persona_turns = 0
        self._limit_notified = False
        self.bus.add_listener(self._count_turns)

    # ---- §11.7 の安全弁（調停ではない。人間の発話で常にリセットされる） ----

    def _count_turns(self, event: RoomEvent) -> None:
        if event.type != "speech":
            return
        if event.kind == "human":
            self._persona_turns = 0
            self._limit_notified = False
        elif event.kind == "task":
            self._persona_turns += 1
            if self._persona_turns >= self._max_persona_turns and not self._limit_notified:
                self._limit_notified = True
                self.bus.publish(
                    "turn_limit",
                    speaker_id=f"room:{self.room_id}",
                    speaker_kind="room",
                    payload={"turns": self._persona_turns},
                )

    # ---- 入退室（§11.2, §11.3） ----

    async def enter(
        self,
        persona: Persona,
        binding: PersonaBinding,
        agent: Agent,
        user_id: str = "default",
        baker: TemplateBaker | None = None,
        memory: PersonaMemory | None = None,
        rng: random.Random | None = None,
    ) -> PersonaInstance:
        # 同一人格の同一 Agent へのインスタンスは1ルームに1つまで（§11.1）
        for instance in self.instances.values():
            if (
                instance.persona.id == persona.id
                and instance.binding.agent_id == agent.agent_id
            ):
                raise ValueError(
                    f"({persona.id}, {agent.agent_id}) は既にこのルームに入室しています"
                )
        instance = PersonaInstance(
            persona,
            binding,
            agent,
            self.bus,
            user_id=user_id,
            baker=baker,
            memory=memory,
            familiarity_store=self._familiarity_store,
            clock=self._clock,
            timescale=self.timescale,
            rng=rng,
        )
        await instance.start()
        self.instances[instance.instance_id] = instance
        self.bus.publish(
            "enter",
            speaker_id=instance.instance_id,
            speaker_kind="persona",
            speaker_name=persona.display_name,
        )
        return instance

    async def leave(self, instance_id: str) -> None:
        instance = self.instances.pop(instance_id, None)
        if instance is None:
            raise KeyError(f"インスタンスが見つかりません: {instance_id}")
        self.bus.publish(
            "leave",
            speaker_id=instance_id,
            speaker_kind="persona",
            speaker_name=instance.persona.display_name,
        )
        await instance.stop()

    async def close(self) -> None:
        for instance_id in list(self.instances):
            await self.leave(instance_id)

    # ---- 人間参加者 ----

    def join_human(self, user_id: str, name: str) -> HumanParticipant:
        participant = HumanParticipant(user_id=user_id, name=name)
        self.humans[user_id] = participant
        return participant

    def human_speech(self, user_id: str, text: str) -> RoomEvent:
        participant = self.humans.get(user_id) or HumanParticipant(user_id, user_id)
        return self.bus.publish(
            "speech",
            speaker_id=user_id,
            speaker_kind="human",
            speaker_name=participant.name,
            text=text,
            kind="human",
        )

    async def wait_quiet(self, idle_sec: float = 0.3, timeout_sec: float = 30.0) -> None:
        """バスが静まるまで待つ（デモ・テスト用の補助）。"""
        import asyncio

        deadline = time.monotonic() + timeout_sec
        last_len = -1
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            if self.bus.is_busy or len(self.bus.log) != last_len:
                last_len = len(self.bus.log)
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= idle_sec:
                return
            await asyncio.sleep(0.02)


# ---- §11.2 入室の照合と提案（LLM を呼ばない） ----

def match_invocation(
    text: str, bindings: list[PersonaBinding]
) -> PersonaBinding | None:
    """「〇〇さんを出して」の照合。invocationAliases の部分一致のみ。
    トピックによる自動ルーティングは実装しない（§11.2, §17）。"""
    for binding in bindings:
        if any(alias and alias in text for alias in binding.invocation_aliases):
            return binding
    return None


def suggest_alternative(
    text: str,
    current: PersonaBinding,
    others: list[PersonaBinding],
) -> PersonaBinding | None:
    """専門外の質問を受けたとき、expertise 照合だけで別人格を提案する（§11.2）。"""
    if any(topic and topic in text for topic in current.expertise):
        return None  # 専門内なので提案不要
    for binding in others:
        if binding.persona_id == current.persona_id:
            continue
        if any(topic and topic in text for topic in binding.expertise):
            return binding
    return None
