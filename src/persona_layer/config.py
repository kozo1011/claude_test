"""LLM プロバイダ設定（§1.3: Agent の実体選択）。

使う LLM プロバイダとモデルを設定ファイル（YAML）で選ぶ。対応プロバイダ:
anthropic / openai / openrouter / gemini / mock。

API キーは**設定ファイルに書かず環境変数から**読む（鍵をリポジトリに
コミットしないため）。プロバイダごとの既定の環境変数名は API_KEY_ENVS 参照。
設定ファイルの各プロバイダで ``api_key_env`` を指定すれば別名の環境変数も使える。

設定ファイルの探索順:
    1. 明示パス（引数 / CLI --config）
    2. 環境変数 PERSONA_LAYER_CONFIG
    3. カレントディレクトリの persona-layer.config.yaml
いずれも無ければ空設定（provider=auto）で動く。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KNOWN_PROVIDERS = ("anthropic", "openai", "openrouter", "gemini")

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}
DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
API_KEY_ENVS = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class LLMConfig:
    """解決済みの単一プロバイダ設定。build_agent がこれを受けて Agent を作る。"""

    provider: str          # anthropic|openai|openrouter|gemini|mock
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def _read_key(provider: str, pconf: dict) -> str:
    names = pconf.get("api_key_env")
    if isinstance(names, str):
        names = [names]
    if not names:
        names = API_KEY_ENVS.get(provider, [])
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


class AppConfig:
    def __init__(self, raw: dict | None = None) -> None:
        raw = raw or {}
        self.raw = raw
        self.default_provider = str(raw.get("provider", "auto") or "auto")
        self.max_tokens = int(raw.get("max_tokens", 1024))
        self.temperature = float(raw.get("temperature", 0.7))
        self.timeout = float(raw.get("timeout", 60.0))
        self._providers: dict[str, dict] = raw.get("providers", {}) or {}

    def autodetect(self) -> str:
        """キーが設定されているプロバイダを既定順で1つ選ぶ。無ければ mock。"""
        for provider in KNOWN_PROVIDERS:
            if _read_key(provider, self._providers.get(provider, {}) or {}):
                return provider
        return "mock"

    def resolve(self, provider: str | None = None) -> LLMConfig:
        """指定（省略時は設定の provider）を解決して LLMConfig を返す。"""
        provider = (provider or self.default_provider or "auto").lower()
        if provider in ("auto", ""):
            provider = self.autodetect()
        if provider in ("mock", "echo", "none"):
            return LLMConfig(provider="mock")
        if provider not in KNOWN_PROVIDERS:
            raise ConfigError(
                f"未知のプロバイダです: {provider}"
                f"（利用可能: {', '.join(KNOWN_PROVIDERS)}, mock）"
            )
        pconf = self._providers.get(provider, {}) or {}
        return LLMConfig(
            provider=provider,
            model=str(pconf.get("model") or DEFAULT_MODELS[provider]),
            base_url=str(pconf.get("base_url") or DEFAULT_BASE_URLS[provider]),
            api_key=_read_key(provider, pconf),
            max_tokens=int(pconf.get("max_tokens", self.max_tokens)),
            temperature=float(pconf.get("temperature", self.temperature)),
            timeout=float(pconf.get("timeout", self.timeout)),
            extra=pconf.get("extra", {}) or {},
        )


def _find_config_path(path: str | Path | None) -> Path | None:
    if path:
        return Path(path)
    env = os.environ.get("PERSONA_LAYER_CONFIG")
    if env:
        return Path(env)
    default = Path.cwd() / "persona-layer.config.yaml"
    return default if default.exists() else None


def load_config(path: str | Path | None = None) -> AppConfig:
    resolved = _find_config_path(path)
    if resolved is None:
        return AppConfig({})
    if not resolved.exists():
        raise ConfigError(f"設定ファイルが見つかりません: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"設定ファイルの読み込みに失敗しました: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("設定ファイルはマッピング形式である必要があります")
    return AppConfig(raw)
