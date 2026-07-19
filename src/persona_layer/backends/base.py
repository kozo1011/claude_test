"""応答を生成する「バックエンド」の共通インターフェース。

バックエンドは LLM API・別の AI エージェント・スクリプトなど何でもよく、
ペルソナ層はこの抽象を通じてのみ応答生成器と会話する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

Role = Literal["user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class GenerationRequest:
    system: str
    messages: list[ChatMessage] = field(default_factory=list)
    max_tokens: int = 1024
    temperature: float = 0.7


class AgentBackend(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> str:
        """会話履歴に対する応答テキストを返す。"""

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        """応答をチャンクで返す。既定では generate() の結果を一括で返す。"""
        yield await self.generate(request)
