"""OpenAI Chat Completions API バックエンド（互換APIにも利用可）。"""

from __future__ import annotations

import os

import httpx

from .base import AgentBackend, GenerationRequest

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIBackend(AgentBackend):
    name = "openai"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY が設定されていません")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def generate(self, request: GenerationRequest) -> str:
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "messages": messages,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"] or ""
