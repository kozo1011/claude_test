"""接続先 Agent の抽象（§1.3: タスク回答の生成はすべて Agent 側の責務）。

人格レイヤーから見た Agent は「システムプロンプトと会話文脈を受け取り、
タスク回答テキストを返すもの」以上ではない。実 Agent（LLM・既存エージェント
基盤など）はこのプロトコルを満たすアダプタを書いて接続する。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Protocol, runtime_checkable

import httpx

from .config import AppConfig, ConfigError, LLMConfig, load_config


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
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY が設定されていません")
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._transport = transport

    async def respond(self, system: str | None, prompt: str) -> str:
        body: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport
        ) as client:
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


class OpenAICompatibleAgent:
    """OpenAI 互換の Chat Completions API を使うアダプタ。

    OpenAI 本家と OpenRouter（https://openrouter.ai）の両方をこれで賄う。
    差分は base_url と API キーだけで、リクエスト/レスポンス形式は共通。
    OpenRouter が推奨する識別ヘッダ等は extra["headers"] で渡せる。
    """

    def __init__(
        self,
        agent_id: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 60.0,
        extra: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.extra = extra or {}
        self._transport = transport

    async def respond(self, system: str | None, prompt: str) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        headers = {"Authorization": f"Bearer {self.api_key}"}
        headers.update(self.extra.get("headers", {}))
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport
        ) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content") or ""


class GeminiAgent:
    """Google Gemini（Generative Language API）を使うアダプタ。

    system は systemInstruction に、ユーザー発話は contents に載せる。
    API キーは x-goog-api-key ヘッダで渡す（URL に載せない）。
    """

    def __init__(
        self,
        agent_id: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._transport = transport

    async def respond(self, system: str | None, prompt: str) -> str:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport
        ) as client:
            resp = await client.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""  # セーフティ等で候補が無い場合は空（呼び出し側でメタ発話に流れる）
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)


def _provider_from_agent_id(agent_id: str | None) -> str | None:
    """agentId からプロバイダを推定する。None は「設定の既定に従う」。"""
    aid = (agent_id or "").lower()
    if aid in ("", "default"):
        return None
    if aid in ("echo", "mock", "scripted"):
        return "mock"
    for provider in ("anthropic", "openrouter", "openai", "gemini"):
        if aid.startswith(provider):
            return provider
    return None  # 未知の agentId は設定の既定プロバイダに従う


def build_agent(agent_id: str = "default", config: AppConfig | None = None) -> Agent:
    """設定に基づいて Agent を構成する。

    agentId が "echo"/"mock" や特定プロバイダ名で始まる場合はそれを優先し、
    それ以外（"default" や未知）は設定ファイルの provider を使う。キーが無い
    プロバイダを指すときは、デモが止まらないよう EchoAgent にフォールバックする。
    返す Agent の agent_id は要求された agentId に一致させる（Binding 整合のため）。
    """
    config = config or load_config()
    llm: LLMConfig = config.resolve(_provider_from_agent_id(agent_id))
    if llm.provider == "mock" or not llm.has_key:
        return EchoAgent(agent_id=agent_id or "echo")
    common = dict(
        agent_id=agent_id,
        model=llm.model,
        api_key=llm.api_key,
        base_url=llm.base_url,
        max_tokens=llm.max_tokens,
        temperature=llm.temperature,
        timeout=llm.timeout,
    )
    if llm.provider == "anthropic":
        return AnthropicAgent(**common)
    if llm.provider in ("openai", "openrouter"):
        return OpenAICompatibleAgent(extra=llm.extra, **common)
    if llm.provider == "gemini":
        return GeminiAgent(**common)
    raise ConfigError(f"未対応のプロバイダです: {llm.provider}")


def make_agent(agent_id: str | None = None, config: AppConfig | None = None) -> Agent:
    """設定ファイル + 環境変数から Agent を構成する（後方互換のためのエイリアス）。"""
    return build_agent(agent_id or "default", config)
