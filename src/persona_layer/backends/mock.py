"""API キーなしで動作確認・テストを行うためのモックバックエンド。"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import AgentBackend, GenerationRequest


class EchoBackend(AgentBackend):
    """受け取った発話を復唱する。配線確認用。"""

    name = "mock"

    def __init__(self, chunk_delay: float = 0.0):
        self._chunk_delay = chunk_delay

    async def generate(self, request: GenerationRequest) -> str:
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        return (
            f"（モック応答）「{last_user}」と受け取りました。"
            "APIキーを設定するとLLMが応答します。"
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        text = await self.generate(request)
        # ストリーミング表示の動作確認のため少しずつ返す
        for i in range(0, len(text), 8):
            if self._chunk_delay:
                await asyncio.sleep(self._chunk_delay)
            yield text[i : i + 8]


class ScriptedBackend(AgentBackend):
    """あらかじめ渡した応答を順番に返す。テスト・デモ用。"""

    name = "scripted"

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self._index = 0
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> str:
        self.requests.append(request)
        if not self._replies:
            return ""
        reply = self._replies[min(self._index, len(self._replies) - 1)]
        self._index += 1
        return reply
