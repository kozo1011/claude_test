"""ターミナル対話チャネル。"""

from __future__ import annotations

import asyncio
import sys

from ..runtime import PersonaRuntime


async def chat_loop(runtime: PersonaRuntime) -> None:
    persona = runtime.persona
    print(f"=== {persona.name} と会話します（終了: /quit）===")
    if persona.greeting:
        print(f"{persona.name}: {persona.greeting}")
    session = runtime.new_session()
    while True:
        try:
            user_text = await asyncio.to_thread(input, "あなた: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        user_text = user_text.strip()
        if not user_text:
            continue
        if user_text in {"/quit", "/exit", "quit", "exit"}:
            break
        print(f"{persona.name}: ", end="", flush=True)
        try:
            async for chunk in runtime.stream_respond(session, user_text):
                print(chunk, end="", flush=True)
            print()
        except Exception as exc:
            print(f"\n[エラー] 応答生成に失敗しました: {exc}", file=sys.stderr)
