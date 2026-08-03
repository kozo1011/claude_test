"""`persona-layer` コマンド: 人格の作成・確認・交配・移植と、デモルームの実行。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .agent import make_agent
from .breeder import PersonaBreeder, BreedError
from .composers import compose_prompt, compose_prosody
from .config import AppConfig, ConfigError, load_config
from .models import Persona, PersonaBinding
from .porter import PersonaPorter, PortError
from .presets import from_preset, preset_names
from .registry import PersonaRegistry
from .room import Room


def _load_persona(path: str) -> Persona:
    try:
        return Persona.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception as exc:
        print(f"エラー: {path} を読めません: {exc}", file=sys.stderr)
        sys.exit(1)


def _dump_persona(persona: Persona, path: str | None) -> None:
    text = json.dumps(
        persona.model_dump(by_alias=True, exclude_none=True),
        ensure_ascii=False,
        indent=2,
    )
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
        print(f"書き出しました: {path}")
    else:
        print(text)


def cmd_presets(args: argparse.Namespace) -> None:
    for name in preset_names():
        print(name)


def cmd_create(args: argparse.Namespace) -> None:
    try:
        persona = from_preset(args.preset, args.id, args.name)
    except KeyError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    _dump_persona(persona, args.output)


def cmd_show(args: argparse.Namespace) -> None:
    p = _load_persona(args.file)
    print(f"id:        {p.id}  (schema {p.schema_version})")
    print(f"名前:      {p.display_name}")
    print(f"一人称:    {p.anchor.first_person} / 二人称: {p.anchor.second_person}")
    print(f"口癖:      {'、'.join(p.anchor.verbal_tics)}")
    print(f"6軸:       {p.style.as_dict()}")
    prosody = compose_prosody(p)
    print(f"prosody:   rate={prosody.rate}% pitch={prosody.pitch}")
    if p.lineage:
        print(f"系譜:      親={p.lineage.parents} 世代={p.lineage.generation} seed={p.lineage.seed}")


def cmd_prompt(args: argparse.Namespace) -> None:
    print(compose_prompt(_load_persona(args.file)))


def cmd_breed(args: argparse.Namespace) -> None:
    a = _load_persona(args.parent_a)
    b = _load_persona(args.parent_b)
    try:
        result = PersonaBreeder().breed(
            a, b, seed=args.seed, mutation_rate=args.mutation_rate
        )
    except BreedError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    for warning in result.warnings:
        print(f"警告: {warning}", file=sys.stderr)
    _dump_persona(result.child, args.output)


def cmd_export(args: argparse.Namespace) -> None:
    persona = _load_persona(args.file)
    try:
        out = PersonaPorter().export(persona, args.out_dir, sprites_dir=args.sprites)
    except PortError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"エクスポートしました: {out}")


def cmd_import(args: argparse.Namespace) -> None:
    registry = PersonaRegistry()
    try:
        persona, voice = PersonaPorter(registry).import_file(args.package)
    except PortError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"インポートしました: {persona.display_name} ({persona.id})")
    print(f"voice.json: {json.dumps(voice, ensure_ascii=False)}")
    print("※ Binding（得意分野）とメモリーは含まれません。管理者が別途設定してください（§10.2）")
    if args.output:
        _dump_persona(persona, args.output)


async def _demo(
    persona_paths: list[str], config: AppConfig, agent_id: str | None = None
) -> None:
    room = Room(timescale=1.0)
    room.join_human("user", "利用者")
    configured = {b["persona_id"]: b for b in config.bindings()}
    for i, path in enumerate(persona_paths):
        persona = _load_persona(path)
        entry = configured.get(persona.id)
        target = agent_id or (entry or {}).get("agent_id") or f"agent-{i}"
        agent = make_agent(target, config)
        binding = PersonaBinding(
            persona_id=persona.id,
            agent_id=agent.agent_id,
            expertise=list((entry or {}).get("expertise") or []),
            out_of_scope_stance=str((entry or {}).get("out_of_scope_stance") or ""),
            invocation_aliases=list((entry or {}).get("invocation_aliases") or [])
            or [persona.display_name],
        )
        await room.enter(persona, binding, agent)
        print(f"[入室] {persona.display_name} ({persona.id}) → {agent.agent_id}")

    queue = room.bus.subscribe()

    async def printer() -> None:
        while True:
            event = await queue.get()
            if event.type == "speech" and event.speaker_kind == "persona":
                tag = f"[{event.meta_kind}]" if event.kind == "meta" else "[回答]"
                print(f"{event.speaker_name} {tag} {event.text}")
                if event.expression:
                    print(f"  (表情: {event.expression} / {event.ssml.split('>')[0]}>)")

    printer_task = asyncio.create_task(printer())
    print("=== デモルーム（終了: /quit）===")
    try:
        while True:
            text = (await asyncio.to_thread(input, "あなた: ")).strip()
            if text in {"/quit", "/exit"}:
                break
            if not text:
                continue
            room.human_speech("user", text)
            await room.wait_quiet(idle_sec=0.5)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        printer_task.cancel()
        await room.close()


def _load_config_or_exit(path: str | None) -> AppConfig:
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_config(args: argparse.Namespace) -> None:
    config = _load_config_or_exit(args.config)
    llm = config.resolve()
    print("[既定の LLM（agents: 未定義の接続先に使われる）]")
    print(f"  provider: {llm.provider}")
    print(f"  model:    {llm.model or '(なし)'}")
    print(f"  base_url: {llm.base_url or '(なし)'}")
    print(f"  APIキー:  {'設定済み' if llm.has_key else '未設定（→ ダミーで動作）'}")
    if llm.provider == "mock" or not llm.has_key:
        print("  → 実際の LLM ではなくダミー（EchoAgent）で応答します")

    names = config.agent_names()
    print()
    print("[接続先 Agent（agents:）]")
    if not names:
        print("  (未定義) 既存 AI Agent に繋ぐには agents: を設定してください")
    for name in names:
        try:
            spec = config.resolve_agent(name)
        except ConfigError as exc:
            print(f"  - {name}: 設定エラー: {exc}")
            continue
        detail = spec.config.get("url") or spec.config.get("target") or spec.config.get(
            "base_url"
        ) or spec.config.get("provider") or ""
        print(f"  - {name}  type={spec.type}  {detail}")

    bindings = config.bindings()
    if bindings:
        print()
        print("[人格 → Agent の割り当て（bindings:）]")
        for b in bindings:
            expertise = "、".join(b["expertise"]) or "(なし)"
            print(f"  - {b['persona_id']} → {b['agent_id']}  得意分野: {expertise}")


def _connection_info(config: AppConfig, agent_id: str | None = None) -> str:
    """起動時に表示する接続先の説明。"""
    if agent_id:
        return f"接続先 Agent: {agent_id}"
    if config.agent_names():
        return f"接続先 Agent: {'、'.join(config.agent_names())}（bindings: に従って割り当て）"
    llm = config.resolve()
    if llm.provider == "mock" or not llm.has_key:
        return (
            "接続先が未設定のためダミー応答で動作します"
            "（既存 Agent に繋ぐには設定の agents: を、LLM 直結なら provider: を設定）"
        )
    return f"LLM 直結: {llm.provider} / {llm.model}"


def cmd_demo(args: argparse.Namespace) -> None:
    config = _load_config_or_exit(args.config)
    print(f"[info] {_connection_info(config, args.agent)}", file=sys.stderr)
    try:
        asyncio.run(_demo(args.files, config, args.agent))
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .server import create_app

    config = _load_config_or_exit(args.config)
    app = create_app(persona_files=args.files, config=config)
    print(f"[info] {_connection_info(config)}")
    print(f"http://{args.host}:{args.port}/ をブラウザで開いてください")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="persona-layer",
        description="AI Agent インターフェース用 人格レイヤー",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("presets", help="プリセット一覧（§13）")
    p.set_defaults(func=cmd_presets)

    p = sub.add_parser("create", help="プリセットから人格を作成する")
    p.add_argument("--preset", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--output", "-o", default=None)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("show", help="人格の概要を表示する")
    p.add_argument("file")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("prompt", help="システムプロンプトを表示する（PromptComposer）")
    p.add_argument("file")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("breed", help="2体を交配して新人格を生成する（§12）")
    p.add_argument("parent_a")
    p.add_argument("parent_b")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--mutation-rate", type=float, default=0.15)
    p.add_argument("--output", "-o", default=None)
    p.set_defaults(func=cmd_breed)

    p = sub.add_parser("export", help=".persona パッケージへエクスポートする（§10）")
    p.add_argument("file")
    p.add_argument("--out-dir", default=".")
    p.add_argument("--sprites", default=None, help="表情スプライトのディレクトリ")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help=".persona パッケージを検証して取り込む（§10）")
    p.add_argument("package")
    p.add_argument("--output", "-o", default=None, help="Persona JSON の書き出し先")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("config", help="現在有効な LLM 設定を表示する")
    p.add_argument("--config", "-c", default=None, help="設定ファイル（YAML）のパス")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("demo", help="ターミナルでデモルームを実行する")
    p.add_argument("files", nargs="+", help="人格 JSON（複数可＝複数体同時稼働）")
    p.add_argument("--config", "-c", default=None, help="設定ファイル（YAML）のパス")
    p.add_argument(
        "--agent", "-a", default=None,
        help="接続先 Agent 名（設定の agents: で定義したもの。例: hermes）",
    )
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("serve", help="リファレンスAPIサーバ + ブラウザデモを起動する")
    p.add_argument("files", nargs="*", help="起動時に登録する人格 JSON")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--config", "-c", default=None, help="設定ファイル（YAML）のパス")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
