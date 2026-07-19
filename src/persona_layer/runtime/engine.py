"""ペルソナランタイム。

人間側チャネル（CLI/WebSocket/音声）と応答バックエンド（LLM/上流エージェント）の
あいだに立ち、ペルソナの適用・履歴管理・中継時の文体変換を行う中核。
"""

from __future__ import annotations

from typing import AsyncIterator

from ..backends.base import AgentBackend, ChatMessage, GenerationRequest
from ..compiler import compile_style_prompt, compile_system_prompt
from ..schema import Persona, ResponseLength
from .session import Session

_MAX_TOKENS = {
    ResponseLength.short: 512,
    ResponseLength.medium: 1024,
    ResponseLength.long: 2048,
}


class PersonaRuntime:
    def __init__(
        self,
        persona: Persona,
        backend: AgentBackend,
        restyler: AgentBackend | None = None,
        max_history_turns: int = 30,
    ):
        """
        Args:
            persona: 適用するペルソナ定義。
            backend: 応答を生成するバックエンド。
            restyler: 指定すると、backend の応答をペルソナの話し方に書き換える
                LLM バックエンド。中継モード（RelayBackend 等、ペルソナを知らない
                上流エージェント）で使う。
            max_history_turns: バックエンドへ渡す履歴の最大往復数。
        """
        self.persona = persona
        self.backend = backend
        self.restyler = restyler
        self.max_history_turns = max_history_turns
        self.system_prompt = compile_system_prompt(persona)
        self._style_prompt = compile_style_prompt(persona)

    def new_session(self) -> Session:
        return Session(persona_id=self.persona.id)

    def greeting(self) -> str:
        return self.persona.greeting

    def _request(self, session: Session) -> GenerationRequest:
        return GenerationRequest(
            system=self.system_prompt,
            messages=session.window(self.max_history_turns),
            max_tokens=_MAX_TOKENS[self.persona.speech_style.response_length],
        )

    async def _restyle(self, text: str) -> str:
        if self.restyler is None or not text.strip():
            return text
        restyled = await self.restyler.generate(
            GenerationRequest(
                system=self._style_prompt,
                messages=[ChatMessage(role="user", content=text)],
                max_tokens=2048,
                temperature=0.5,
            )
        )
        return restyled or text

    async def respond(self, session: Session, user_text: str) -> str:
        """ユーザー発話に応答し、履歴を更新して応答テキストを返す。"""
        session.append("user", user_text)
        raw = await self.backend.generate(self._request(session))
        reply = await self._restyle(raw)
        session.append("assistant", reply)
        return reply

    async def stream_respond(
        self, session: Session, user_text: str
    ) -> AsyncIterator[str]:
        """応答をチャンクで逐次返す。restyler があるときは全文確定後に一括で返す。"""
        session.append("user", user_text)
        if self.restyler is not None:
            raw = await self.backend.generate(self._request(session))
            reply = await self._restyle(raw)
            session.append("assistant", reply)
            yield reply
            return
        parts: list[str] = []
        async for chunk in self.backend.stream(self._request(session)):
            parts.append(chunk)
            yield chunk
        session.append("assistant", "".join(parts))
