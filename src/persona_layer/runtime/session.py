"""会話セッション（履歴）の保持。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from ..backends.base import ChatMessage, Role


@dataclass
class Session:
    persona_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    messages: list[ChatMessage] = field(default_factory=list)

    def append(self, role: Role, content: str) -> None:
        self.messages.append(ChatMessage(role=role, content=content))

    def window(self, max_turns: int) -> list[ChatMessage]:
        """直近 max_turns 往復ぶんの履歴を返す（コンテキスト長対策）。"""
        if max_turns <= 0:
            return list(self.messages)
        return self.messages[-max_turns * 2 :]

    def to_transcript(self) -> str:
        return "\n".join(f"{m.role}: {m.content}" for m in self.messages)
