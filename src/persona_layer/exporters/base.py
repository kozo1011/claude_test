"""エクスポート形式のレジストリ。

新しい移植先を増やすときは、``Persona -> ExportResult`` の関数を書いて
``register()`` するだけでよい。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import yaml

from ..compiler import compile_system_prompt
from ..schema import Persona


@dataclass
class ExportResult:
    format: str
    text: str
    suggested_filename: str
    mime: str = "text/plain"


Exporter = Callable[[Persona], ExportResult]

_REGISTRY: dict[str, Exporter] = {}


def register(name: str) -> Callable[[Exporter], Exporter]:
    def deco(fn: Exporter) -> Exporter:
        _REGISTRY[name] = fn
        return fn

    return deco


def formats() -> list[str]:
    return sorted(_REGISTRY)


def export(persona: Persona, fmt: str) -> ExportResult:
    try:
        exporter = _REGISTRY[fmt]
    except KeyError:
        raise ValueError(
            f"未知のエクスポート形式です: {fmt}（利用可能: {', '.join(formats())}）"
        ) from None
    return exporter(persona)


@register("system-prompt")
def _export_system_prompt(persona: Persona) -> ExportResult:
    """任意の LLM エージェントに貼り付けられるシステムプロンプト。"""
    return ExportResult(
        format="system-prompt",
        text=compile_system_prompt(persona),
        suggested_filename=f"{persona.id}.system.txt",
    )


@register("json")
def _export_canonical_json(persona: Persona) -> ExportResult:
    """正規形式（PPD）の JSON。persona-layer 実装同士の交換用。"""
    return ExportResult(
        format="json",
        text=json.dumps(persona.model_dump(mode="json"), ensure_ascii=False, indent=2),
        suggested_filename=f"{persona.id}.persona.json",
        mime="application/json",
    )


@register("yaml")
def _export_canonical_yaml(persona: Persona) -> ExportResult:
    """正規形式（PPD）の YAML。"""
    return ExportResult(
        format="yaml",
        text=yaml.safe_dump(
            persona.model_dump(mode="json"), allow_unicode=True, sort_keys=False
        ),
        suggested_filename=f"{persona.id}.persona.yaml",
        mime="application/yaml",
    )


@register("anthropic")
def _export_anthropic(persona: Persona) -> ExportResult:
    """Anthropic Messages API のリクエスト雛形。"""
    body = {
        "model": "claude-sonnet-5",
        "max_tokens": 1024,
        "system": compile_system_prompt(persona),
        "messages": [],
    }
    return ExportResult(
        format="anthropic",
        text=json.dumps(body, ensure_ascii=False, indent=2),
        suggested_filename=f"{persona.id}.anthropic.json",
        mime="application/json",
    )


@register("openai")
def _export_openai(persona: Persona) -> ExportResult:
    """OpenAI Chat Completions API のリクエスト雛形。"""
    body = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": compile_system_prompt(persona)},
        ],
    }
    return ExportResult(
        format="openai",
        text=json.dumps(body, ensure_ascii=False, indent=2),
        suggested_filename=f"{persona.id}.openai.json",
        mime="application/json",
    )


@register("markdown")
def _export_markdown(persona: Persona) -> ExportResult:
    """人間可読なキャラクターシート。

    GPTs の Instructions、Claude Projects、Dify などプロンプト欄を持つ
    任意のサービスへ貼り付けて移植できる。
    """
    p = persona
    lines = [
        f"# ペルソナ: {p.name} (`{p.id}` v{p.version})",
        "",
        p.description or "",
        "",
        "| 項目 | 値 |",
        "| --- | --- |",
        f"| 言語 | {p.language} |",
        f"| 役割 | {p.identity.role} |",
        f"| 一人称 | {p.identity.first_person or '-'} |",
        f"| 性格 | {'、'.join(p.personality.traits) or '-'} |",
        f"| 口調 | {p.personality.tone or '-'} |",
        f"| 音声 | {'有効' if p.voice.enabled else '無効'}"
        f" (pitch={p.voice.pitch}, rate={p.voice.rate}) |",
        "",
        "## システムプロンプト",
        "",
        "以下をそのまま移植先エージェントのシステムプロンプト/指示欄に貼り付けてください。",
        "",
        "```",
        compile_system_prompt(p),
        "```",
        "",
    ]
    if p.greeting:
        lines += ["## 初回挨拶", "", p.greeting, ""]
    return ExportResult(
        format="markdown",
        text="\n".join(lines),
        suggested_filename=f"{persona.id}.md",
        mime="text/markdown",
    )
