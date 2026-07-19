"""`persona` コマンド: 検証・コンパイル・エクスポート・会話・サーバ起動。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .backends.base import AgentBackend
from .backends.mock import EchoBackend
from .compiler import compile_system_prompt
from .exporters import export, formats
from .loader import PersonaLoadError, load_persona, load_personas_dir
from .runtime import PersonaRuntime
from .schema import json_schema


def make_backend(name: str | None = None) -> AgentBackend:
    """環境変数から応答バックエンドを構成する。

    PERSONA_BACKEND=mock|anthropic|openai|relay|auto（既定: auto）
    auto は ANTHROPIC_API_KEY → OPENAI_API_KEY → mock の順で選ぶ。
    relay は RELAY_URL（上流エージェントのURL）が必要。
    """
    name = name or os.environ.get("PERSONA_BACKEND", "auto")
    if name == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            name = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            name = "openai"
        else:
            name = "mock"
    if name == "mock":
        return EchoBackend()
    if name == "anthropic":
        from .backends.anthropic_backend import AnthropicBackend

        return AnthropicBackend(
            model=os.environ.get("PERSONA_MODEL", "claude-sonnet-5")
        )
    if name == "openai":
        from .backends.openai_backend import OpenAIBackend

        return OpenAIBackend(model=os.environ.get("PERSONA_MODEL", "gpt-4o-mini"))
    if name == "relay":
        from .backends.relay import RelayBackend

        url = os.environ.get("RELAY_URL", "")
        if not url:
            raise ValueError("relay バックエンドには RELAY_URL の設定が必要です")
        return RelayBackend(url)
    raise ValueError(f"未知のバックエンドです: {name}")


def make_restyler() -> AgentBackend | None:
    """中継モードの文体変換に使う LLM を構成する。

    relay バックエンド使用時に API キーがあれば LLM を返し、なければ None
    （= 上流の応答をそのまま返す）。それ以外のバックエンドでは、応答生成側の
    LLM がペルソナのシステムプロンプトを直接受け取るため不要。
    """
    if os.environ.get("PERSONA_BACKEND") != "relay":
        return None
    if os.environ.get("ANTHROPIC_API_KEY"):
        from .backends.anthropic_backend import AnthropicBackend

        return AnthropicBackend()
    if os.environ.get("OPENAI_API_KEY"):
        from .backends.openai_backend import OpenAIBackend

        return OpenAIBackend()
    return None


def _load_or_exit(path: str):
    try:
        return load_persona(path)
    except PersonaLoadError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_validate(args: argparse.Namespace) -> None:
    persona = _load_or_exit(args.file)
    print(f"OK: {persona.name} ({persona.id} v{persona.version})")


def cmd_show(args: argparse.Namespace) -> None:
    p = _load_or_exit(args.file)
    print(f"id:          {p.id}")
    print(f"name:        {p.name}")
    print(f"version:     {p.version}")
    print(f"language:    {p.language}")
    print(f"description: {p.description}")
    print(f"role:        {p.identity.role}")
    print(f"traits:      {'、'.join(p.personality.traits)}")
    print(f"voice:       {'有効' if p.voice.enabled else '無効'} ({p.voice_language()})")
    print(f"examples:    {len(p.examples)}件")


def cmd_compile(args: argparse.Namespace) -> None:
    persona = _load_or_exit(args.file)
    print(compile_system_prompt(persona))


def cmd_export(args: argparse.Namespace) -> None:
    persona = _load_or_exit(args.file)
    try:
        result = export(persona, args.format)
    except ValueError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.output:
        out = Path(args.output)
        if out.is_dir():
            out = out / result.suggested_filename
        out.write_text(result.text, encoding="utf-8")
        print(f"書き出しました: {out}")
    else:
        print(result.text)


def cmd_schema(args: argparse.Namespace) -> None:
    print(json.dumps(json_schema(), ensure_ascii=False, indent=2))


def cmd_chat(args: argparse.Namespace) -> None:
    from .channels.cli import chat_loop

    persona = _load_or_exit(args.file)
    try:
        backend = make_backend(args.backend)
    except ValueError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    restyler = make_restyler()
    runtime = PersonaRuntime(persona, backend, restyler=restyler)
    if backend.name == "mock":
        print("[info] APIキー未設定のためモックバックエンドで動作しています", file=sys.stderr)
    asyncio.run(chat_loop(runtime))


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .channels.server import create_app

    try:
        personas = load_personas_dir(args.personas)
    except PersonaLoadError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    if not personas:
        print(f"エラー: {args.personas} にペルソナ定義がありません", file=sys.stderr)
        sys.exit(1)

    tts = None
    voicevox_url = os.environ.get("VOICEVOX_URL", "")
    if voicevox_url:
        from .voice.voicevox import VoicevoxTTS

        tts = VoicevoxTTS(voicevox_url)

    app = create_app(
        personas,
        backend_factory=lambda: make_backend(args.backend),
        restyler_factory=make_restyler,
        tts_provider=tts,
    )
    names = ", ".join(p.name for p in personas.values())
    print(f"ペルソナ: {names}")
    print(f"http://{args.host}:{args.port}/ をブラウザで開いてください")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="persona",
        description="Persona Layer: AIエージェントと人間のあいだの移植可能な人格インターフェース",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="ペルソナ定義を検証する")
    p.add_argument("file")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("show", help="ペルソナの概要を表示する")
    p.add_argument("file")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("compile", help="システムプロンプトを生成して表示する")
    p.add_argument("file")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("export", help="他エージェントへの移植用にエクスポートする")
    p.add_argument("file")
    p.add_argument(
        "--format", "-f", default="system-prompt",
        help=f"形式: {', '.join(formats())}",
    )
    p.add_argument("--output", "-o", default="", help="出力ファイル/ディレクトリ")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("schema", help="ペルソナ定義の JSON Schema を表示する")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("chat", help="ターミナルで会話する")
    p.add_argument("file")
    p.add_argument("--backend", "-b", default=None, help="mock|anthropic|openai|relay")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("serve", help="Web/音声チャネルのサーバを起動する")
    p.add_argument("--personas", "-p", default="personas", help="ペルソナ定義ディレクトリ")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--backend", "-b", default=None, help="mock|anthropic|openai|relay")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
