"""Anthropic Messages API バックエンド。"""

from __future__ import annotations

import os

import httpx

from .base import AgentBackend, GenerationRequest

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicBackend(AgentBackend):
    name = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 60.0,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY が設定されていません")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def generate(self, request: GenerationRequest) -> str:
        body = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        return "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
