"""接続先 Agent の抽象（§1.3: タスク回答の生成はすべて Agent 側の責務）。

人格レイヤーから見た Agent は「人格記述と会話文脈を受け取り、タスク回答テキストを
返すもの」以上ではない。ここには次の2系統のアダプタが同梱されている。

1. **既存 AI Agent への接続**（本来の想定・§1.3）
   - ``HTTPAgent``   … 任意の HTTP JSON API。送受信のフィールド名を設定で寄せられる
   - ``PythonAgent`` … 同一プロセス内の Python 実装（module:Class）
   - ``OpenAICompatibleAgent`` … /chat/completions 互換のエンドポイント
2. **LLM 直結**（配線確認・単体デモ用）
   - ``AnthropicAgent`` / ``OpenAICompatibleAgent`` / ``GeminiAgent``

Agent は最低限 ``respond(system, prompt) -> str`` を実装すればよい。会話の役割構造や
セッションIDを活かしたい場合は ``respond_request(AgentRequest) -> str`` を実装する。
AgentBridge は後者があればそちらを優先して呼ぶ。
"""

from __future__ import annotations

import asyncio
import importlib
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from .config import AgentSpec, AppConfig, ConfigError, LLMConfig, load_config


# ---- Agent へ渡す要求（構造化） ----

@dataclass
class AgentTurn:
    """会話1発話ぶん（§11.5: 話者名と「自分」の区別を保持する）。"""

    role: str                  # "user"（相手）| "assistant"（自分）
    content: str
    speaker_name: str = ""     # 「楓」「利用者」など
    speaker_kind: str = ""     # "human" | "persona"
    is_self: bool = False      # このインスタンス自身の過去発話か

    def labeled_content(self) -> str:
        """複数人が居る場に備え、自分以外の発話には話者名を前置する。"""
        if self.is_self or not self.speaker_name:
            return self.content
        return f"{self.speaker_name}: {self.content}"


@dataclass
class AgentRequest:
    system: str | None = None          # 人格記述（§2.1 の例外規定で許される注入）
    prompt: str = ""                   # 平文フォールバック（turns 非対応の Agent 用）
    instruction: str = ""              # 今回の依頼（「直前の発話に応答してください」等）
    turns: list[AgentTurn] = field(default_factory=list)
    persona: dict[str, Any] = field(default_factory=dict)  # 構造化した人格情報
    session_id: str = ""               # Agent 側が履歴を持つ場合の識別子


@runtime_checkable
class Agent(Protocol):
    agent_id: str

    async def respond(self, system: str | None, prompt: str) -> str:
        """タスク回答を返す。人格レイヤーはこの戻り値を一切書き換えない（§2.1）。"""
        ...


def _as_request(system: str | None, prompt: str) -> AgentRequest:
    return AgentRequest(
        system=system,
        prompt=prompt,
        turns=[AgentTurn(role="user", content=prompt)],
    )


def _merge_consecutive(turns: list[AgentTurn]) -> list[dict[str, str]]:
    """role が連続する発話をまとめ、user/assistant が交互になる形にする。

    Anthropic / Gemini は交互を要求するため。先頭が assistant の場合は落とす。
    """
    merged: list[dict[str, str]] = []
    for turn in turns:
        text = turn.labeled_content()
        if not text:
            continue
        if merged and merged[-1]["role"] == turn.role:
            merged[-1]["content"] += "\n" + text
        else:
            merged.append({"role": turn.role, "content": text})
    while merged and merged[0]["role"] == "assistant":
        merged.pop(0)
    return merged


def _llm_messages(request: AgentRequest) -> list[dict[str, str]]:
    """LLM API へ渡す messages を組む。turns が空なら prompt にフォールバック。"""
    messages = _merge_consecutive(request.turns)
    if not messages:
        messages = [{"role": "user", "content": request.prompt}]
    return messages


def _llm_system(request: AgentRequest) -> str:
    """人格記述に今回の依頼を足したもの（回答内容には干渉しない枠組みのみ）。"""
    parts = [p for p in (request.system, request.instruction) if p]
    return "\n\n".join(parts)


# ---- 動作確認・テスト用 ----

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


# ---- 既存 AI Agent への接続 ----

DEFAULT_SEND_MAP = {
    "system": "system",
    "messages": "messages",
    "text": "text",
    "instruction": "instruction",
    "persona": "persona",
    "session_id": "sessionId",
}


def _dig(data: Any, path: str) -> Any:
    """"a.b.c" のドット記法で入れ子の値を取り出す。"""
    current = data
    for key in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(key)]
                continue
            except (ValueError, IndexError):
                return None
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


class HTTPAgent:
    """任意の HTTP JSON API を Agent として使う汎用アダプタ。

    HermesAgent のような既存エージェントに、コードを書かずに接続するための口。
    送信フィールド名（``send``）と回答の取り出し位置（``receive``）を設定で寄せられる。

    既定の契約:
        POST <url>
        → {"system": str, "messages": [{"role","content","speakerName"}...],
           "text": str, "instruction": str, "persona": {...}, "sessionId": str}
        ← {"content": str}
    """

    def __init__(
        self,
        agent_id: str,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        send: dict[str, str | None] | None = None,
        receive: str = "content",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url:
            raise ConfigError("HTTP Agent には url の指定が必要です")
        self.agent_id = agent_id
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.send = {**DEFAULT_SEND_MAP, **(send or {})}
        self.receive = receive
        self.timeout = timeout
        self._transport = transport

    def _payload(self, request: AgentRequest) -> dict[str, Any]:
        last_user = next(
            (t.content for t in reversed(request.turns) if t.role == "user"), ""
        )
        values: dict[str, Any] = {
            "system": request.system,
            "messages": [
                {
                    "role": t.role,
                    "content": t.content,
                    "speakerName": t.speaker_name,
                    "speakerKind": t.speaker_kind,
                    "isSelf": t.is_self,
                }
                for t in request.turns
            ],
            "text": last_user or request.prompt,
            "instruction": request.instruction,
            "persona": request.persona,
            "session_id": request.session_id,
        }
        payload: dict[str, Any] = {}
        for key, field_name in self.send.items():
            if field_name is None or key not in values:
                continue  # None を指定したフィールドは送らない
            payload[field_name] = values[key]
        return payload

    async def respond_request(self, request: AgentRequest) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport
        ) as client:
            resp = await client.request(
                self.method, self.url, headers=self.headers, json=self._payload(request)
            )
            resp.raise_for_status()
            data = resp.json()
        content = _dig(data, self.receive)
        if not isinstance(content, str):
            raise ValueError(
                f"Agent の応答から文字列を取り出せません"
                f"（receive='{self.receive}' / 実際の応答: {data!r}）"
            )
        return content

    async def respond(self, system: str | None, prompt: str) -> str:
        return await self.respond_request(_as_request(system, prompt))


def load_python_agent(
    target: str, agent_id: str, options: dict[str, Any] | None = None
) -> Agent:
    """``module:Class`` 形式で Python 実装の Agent を読み込む。

    同一プロセスで動く既存エージェント（HermesAgent が Python 製の場合など）向け。
    生成したオブジェクトは ``respond`` を持つ必要がある。
    """
    if ":" not in target:
        raise ConfigError(
            f"python Agent の target は 'module:Class' 形式で指定してください: {target!r}"
        )
    module_name, attr_name = target.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigError(f"モジュールを読み込めません: {module_name}（{exc}）") from exc
    try:
        factory = getattr(module, attr_name)
    except AttributeError as exc:
        raise ConfigError(
            f"{module_name} に {attr_name} が見つかりません"
        ) from exc
    instance = factory(**(options or {}))
    if not hasattr(instance, "respond"):
        raise ConfigError(
            f"{target} は Agent プロトコル（async respond(system, prompt)）を満たしていません"
        )
    if not getattr(instance, "agent_id", ""):
        instance.agent_id = agent_id
    return instance


# ---- LLM 直結アダプタ ----

class AnthropicAgent:
    """Anthropic Messages API を Agent として使う参考アダプタ。"""

    def __init__(
        self,
        agent_id: str = "anthropic",
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        max_tokens: int = 2048,
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

    async def respond_request(self, request: AgentRequest) -> str:
        body: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": _llm_messages(request),
        }
        system = _llm_system(request)
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

    async def respond(self, system: str | None, prompt: str) -> str:
        return await self.respond_request(_as_request(system, prompt))


class OpenAICompatibleAgent:
    """OpenAI 互換の Chat Completions API を使うアダプタ。

    OpenAI 本家・OpenRouter に加え、/chat/completions 互換を出している既存
    エージェントにも base_url を向けるだけで接続できる。
    """

    def __init__(
        self,
        agent_id: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int = 2048,
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

    async def respond_request(self, request: AgentRequest) -> str:
        messages: list[dict] = []
        system = _llm_system(request)
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(_llm_messages(request))
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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

    async def respond(self, system: str | None, prompt: str) -> str:
        return await self.respond_request(_as_request(system, prompt))


class GeminiAgent:
    """Google Gemini（Generative Language API）を使うアダプタ。"""

    def __init__(
        self,
        agent_id: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int = 2048,
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

    async def respond_request(self, request: AgentRequest) -> str:
        contents = [
            {
                # Gemini の role は user / model
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in _llm_messages(request)
        ]
        body: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }
        system = _llm_system(request)
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

    async def respond(self, system: str | None, prompt: str) -> str:
        return await self.respond_request(_as_request(system, prompt))


# ---- 構成（設定 → Agent） ----

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


def _build_llm_agent(agent_id: str, llm: LLMConfig) -> Agent:
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


def _build_from_spec(spec: AgentSpec, config: AppConfig) -> Agent:
    """設定ファイルの agents: 定義から Agent を作る。"""
    conf = spec.config
    if spec.type == "http":
        return HTTPAgent(
            agent_id=spec.name,
            url=str(conf.get("url", "")),
            method=str(conf.get("method", "POST")),
            headers=conf.get("headers") or {},
            send=conf.get("send"),
            receive=str(conf.get("receive", "content")),
            timeout=float(conf.get("timeout", 120.0)),
        )
    if spec.type == "python":
        return load_python_agent(
            str(conf.get("target", "")), spec.name, conf.get("options") or {}
        )
    if spec.type == "openai_compatible":
        return OpenAICompatibleAgent(
            agent_id=spec.name,
            model=str(conf.get("model", "default")),
            api_key=str(conf.get("api_key", "")),
            base_url=str(conf.get("base_url", "")),
            max_tokens=int(conf.get("max_tokens", config.max_tokens)),
            temperature=float(conf.get("temperature", config.temperature)),
            timeout=float(conf.get("timeout", config.timeout)),
            extra={"headers": conf.get("headers") or {}},
        )
    if spec.type == "mock":
        return EchoAgent(agent_id=spec.name)
    if spec.type == "llm":
        return _build_llm_agent(spec.name, config.resolve(conf.get("provider")))
    raise ConfigError(
        f"未知の Agent type です: {spec.type}"
        "（http | openai_compatible | python | llm | mock）"
    )


def build_agent(agent_id: str = "default", config: AppConfig | None = None) -> Agent:
    """設定に基づいて Agent を構成する。

    解決順:
      1. 設定ファイルの ``agents.<agent_id>`` 定義（既存 Agent への接続はここ）
      2. agentId のプレフィックスによる LLM プロバイダ推定（"gemini-1" など）
      3. 設定の既定プロバイダ。キーが無ければ EchoAgent にフォールバック
    """
    config = config or load_config()
    spec = config.resolve_agent(agent_id)
    if spec is not None:
        return _build_from_spec(spec, config)
    return _build_llm_agent(
        agent_id, config.resolve(_provider_from_agent_id(agent_id))
    )


def make_agent(agent_id: str | None = None, config: AppConfig | None = None) -> Agent:
    """設定ファイル + 環境変数から Agent を構成する（後方互換のためのエイリアス）。"""
    return build_agent(agent_id or "default", config)
