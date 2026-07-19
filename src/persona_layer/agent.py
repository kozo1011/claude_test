"""接続先 Agent の抽象（§1.3: タスク回答の生成はすべて Agent 側の責務）。

人格レイヤーから見た Agent は「システムプロンプトと会話文脈を受け取り、
タスク回答テキストを返すもの」以上ではない。実 Agent（LLM・既存エージェント
基盤など）はこのプロトコルを満たすアダプタを書いて接続する。
"""

from __future__ import annotations

import asyncio
import os
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class Agent(Protocol):
    agent_id: str

    async def respond(self, system: str | None, prompt: str) -> str:
        """タスク回答を返す。人格レイヤーはこの戻り値を一切書き換えない（§2.1）。"""
        ...


class EchoAgent:
    """配線確認用。受け取った発話をそのまま返す。"""

    def __init__(self, agent_id: str = "echo") -> None:
        self.agent_id = agent_id

    async def respond(self, system: str | None, prompt: str) -> str:
        # コンテキスト（§11.5 形式）から直前の発話行を拾って復唱する
        utterances = [
            line.split("）: ", 1)[1]
            for line in prompt.splitlines()
            if "）: " in line
        ]
        last = utterances[-1] if utterances else prompt.strip()
        return f"（EchoAgent）「{last}」について承知しました。"


class ScriptedAgent:
    """テスト・デモ用。あらかじめ渡した回答を順に返す。呼び出しを記録する。"""

    def __init__(
        self, replies: list[str], agent_id: str = "scripted", delay_sec: float = 0.0
    ) -> None:
        self.agent_id = agent_id
        self._replies = list(replies)
        self._index = 0
        self.delay_sec = delay_sec
        self.calls: list[tuple[str | None, str]] = []

    async def respond(self, system: str | None, prompt: str) -> str:
        self.calls.append((system, prompt))
        if self.delay_sec:
            await asyncio.sleep(self.delay_sec)
        if not self._replies:
            return ""
        reply = self._replies[min(self._index, len(self._replies) - 1)]
        self._index += 1
        return reply


class AnthropicAgent:
    """Anthropic Messages API を Agent として使う参考アダプタ。"""

    def __init__(
        self,
        agent_id: str = "anthropic",
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 60.0,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY が設定されていません")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def respond(self, system: str | None, prompt: str) -> str:
        body: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
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


def make_agent(agent_id: str | None = None) -> Agent:
    """環境変数から Agent を構成する（ANTHROPIC_API_KEY があれば LLM、なければ Echo）。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicAgent(agent_id=agent_id or "anthropic")
    return EchoAgent(agent_id=agent_id or "echo")
