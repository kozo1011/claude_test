"""上流エージェント中継バックエンド。

eラーニングのように「教材エージェントが内容を決め、ペルソナ層が話者になる」
構成で使う。上流エージェントは HTTP で以下の契約を満たせばよい:

    POST <url>
    リクエスト:  {"system": str, "messages": [{"role": "user"|"assistant", "content": str}, ...]}
    レスポンス: {"content": str}

上流が返した内容は Runtime 側でペルソナの話し方に書き換えられる（restyler 指定時）。
"""

from __future__ import annotations

import httpx

from .base import AgentBackend, GenerationRequest


class RelayBackend(AgentBackend):
    name = "relay"

    def __init__(self, url: str, timeout: float = 60.0):
        self.url = url
        self.timeout = timeout

    async def generate(self, request: GenerationRequest) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.url,
                json={
                    "system": request.system,
                    "messages": [
                        {"role": m.role, "content": m.content}
                        for m in request.messages
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
        content = data.get("content")
        if not isinstance(content, str):
            raise ValueError(
                f"上流エージェントの応答に content (str) がありません: {data!r}"
            )
        return content
