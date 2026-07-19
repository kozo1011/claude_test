"""AgentBridge（§3.1）: 接続先 Agent への転送と受信。

- 素通し保証（§2.1・受け入れ基準1）: Agent の回答テキストを一切加工しない
- 人格の注入は Agent のシステムプロンプトへ行う（§2.1 の唯一の例外）
- 1 PersonaInstance = 1 Agent の 1:1（§11.1）
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .agent import Agent
from .composers import compose_prompt
from .memory import PersonaMemory
from .models import Persona, PersonaBinding
from .state import StateEngine


class AgentError(Exception):
    """Agent 呼び出しの失敗。"""


@dataclass
class BridgeResult:
    text: str            # Agent の回答そのもの（無加工）
    requested_at: float
    received_at: float
    system_prompt: str


class AgentBridge:
    def __init__(
        self,
        persona: Persona,
        binding: PersonaBinding,
        agent: Agent,
        engine: StateEngine,
        memory: PersonaMemory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if binding.agent_id != agent.agent_id:
            raise ValueError(
                f"Binding の agentId ({binding.agent_id}) と Agent ({agent.agent_id}) が一致しません"
            )
        self.persona = persona
        self.binding = binding
        self.agent = agent
        self.engine = engine
        self.memory = memory
        self._clock = clock

    def system_prompt(self) -> str:
        memory_lines = None
        if self.memory is not None:
            memory_lines = self.memory.read_lines(
                self.persona.id, self.engine.user_id
            )
        return compose_prompt(
            self.persona,
            binding=self.binding,
            state=self.engine.state,
            familiarity_effective=self.engine.familiarity_effective(),
            memory_lines=memory_lines,
        )

    async def ask(self, context_prompt: str) -> BridgeResult:
        """Agent へ転送し、回答を素通しで返す。"""
        requested_at = self._clock()
        self.engine.set_context("thinking", requested_at)
        system = self.system_prompt()
        try:
            text = await self.agent.respond(system, context_prompt)
        except Exception as exc:
            self.engine.observe("task_error")
            raise AgentError(str(exc)) from exc
        received_at = self._clock()
        return BridgeResult(
            text=text,
            requested_at=requested_at,
            received_at=received_at,
            system_prompt=system,
        )
