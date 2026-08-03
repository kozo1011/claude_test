"""リファレンス API サーバ。

会議UI（WebRTC・画面共有・音声入出力）は別コンポーネント（§1.3）。
ここでは外部UIが人格レイヤーへ接続するための HTTP/WebSocket I/F と、
動作確認用の簡易ブラウザコンソール（/）だけを提供する。
"""

from __future__ import annotations

import base64
import dataclasses
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .agent import Agent, build_agent
from .config import AppConfig, ConfigError, load_config
from .breeder import BreedError, PersonaBreeder
from .composers import compose_prompt
from .models import Persona, PersonaBinding
from .porter import PersonaPorter, PortError
from .presets import PRESETS, from_preset, preset_names
from .registry import PersonaRegistry, RegistryError
from .room import Room
from .room.bus import RoomEvent

_WEB_DIR = Path(__file__).resolve().parent / "web"


class CreatePersonaRequest(BaseModel):
    preset: str | None = None
    id: str | None = None
    displayName: str | None = None
    persona: dict | None = None  # 完全な Persona JSON（camelCase）


class BreedRequest(BaseModel):
    parentA: str
    parentB: str
    seed: int | None = None
    mutationRate: float = 0.15


class ImportRequest(BaseModel):
    packageBase64: str


class BindingRequest(BaseModel):
    personaId: str
    agentId: str
    expertise: list[str] = []
    outOfScopeStance: str = ""
    invocationAliases: list[str] = []


class EnterRequest(BaseModel):
    personaId: str
    agentId: str | None = None  # 省略時は登録済み Binding（設定の bindings:）に従う
    userId: str = "default"


class LeaveRequest(BaseModel):
    instanceId: str


class SpeechRequest(BaseModel):
    userId: str = "user"
    name: str = "利用者"
    text: str


def _event_json(event: RoomEvent) -> dict:
    data = dataclasses.asdict(event)
    return {k: v for k, v in data.items() if v not in ("", None, {})}


class AgentPool:
    """agentId → Agent。設定ファイルの provider に従って Agent を構成する。

    agentId "default" は設定の既定プロバイダ、"echo"/"mock" はダミー、
    "gemini"/"openrouter"/"anthropic"/"openai" 始まりは各プロバイダを指す。
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._agents: dict[str, Agent] = {}

    def get(self, agent_id: str) -> Agent:
        if agent_id not in self._agents:
            try:
                self._agents[agent_id] = build_agent(agent_id, self._config)
            except (ValueError, ConfigError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self._agents[agent_id]


def create_app(
    persona_files: list[str] | None = None,
    config_path: str | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    app = FastAPI(title="Persona Layer", version="0.4.0")
    registry = PersonaRegistry()
    porter = PersonaPorter(registry)
    breeder = PersonaBreeder()
    app_config = config or load_config(config_path)
    agents = AgentPool(app_config)
    rooms: dict[str, Room] = {}

    configured_bindings = {b["persona_id"]: b for b in app_config.bindings()}
    for path in persona_files or []:
        persona = Persona.model_validate(
            json.loads(Path(path).read_text(encoding="utf-8"))
        )
        registry.create(persona)
        # 設定ファイルの bindings: があればそれを使う（人格ごとに接続先 Agent と
        # 得意分野を割り当てられる・§4.3）。無ければ既定 Agent に繋ぐ。
        entry = configured_bindings.get(persona.id)
        if entry is not None:
            registry.bind(
                PersonaBinding(
                    persona_id=persona.id,
                    agent_id=entry["agent_id"],
                    expertise=entry["expertise"],
                    out_of_scope_stance=entry["out_of_scope_stance"],
                    invocation_aliases=entry["invocation_aliases"]
                    or [persona.display_name],
                )
            )
        else:
            registry.bind(
                PersonaBinding(
                    persona_id=persona.id,
                    agent_id="default",  # 設定の provider（既定は環境変数から自動）
                    invocation_aliases=[persona.display_name],
                )
            )

    def _registry_call(fn, *args):
        try:
            return fn(*args)
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ---- 管理（§11.1: 人格管理者ロール想定の管理I/F） ----

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")

    @app.get("/api/presets")
    async def presets() -> dict:
        return {
            name: {"style": entry["style"].as_dict()} for name, entry in PRESETS.items()
        }

    @app.get("/api/config")
    async def active_config() -> dict:
        """現在有効な接続先（キーは返さない）。ブラウザの表示・確認用。"""
        llm = app_config.resolve()
        agent_names = app_config.agent_names()
        return {
            "provider": llm.provider,
            "model": llm.model,
            "hasApiKey": llm.has_key,
            "agents": agent_names,  # 設定された既存 Agent の接続先名
            "usingMock": not agent_names
            and (llm.provider == "mock" or not llm.has_key),
        }

    @app.get("/api/personas")
    async def list_personas(include_deleted: bool = False) -> list[dict]:
        return [
            {
                **persona.model_dump(by_alias=True, exclude_none=True),
                "deleted": deleted,  # 家系図でのグレー表示用（§12.5）
                "version": registry.version_of(persona.id),
            }
            for persona, deleted in registry.list(include_deleted=include_deleted)
        ]

    @app.post("/api/personas")
    async def create_persona(req: CreatePersonaRequest) -> dict:
        if req.persona is not None:
            persona = Persona.model_validate(req.persona)
        elif req.preset and req.id and req.displayName:
            if req.preset not in preset_names():
                raise HTTPException(status_code=400, detail=f"未知のプリセット: {req.preset}")
            persona = from_preset(req.preset, req.id, req.displayName)
        else:
            raise HTTPException(
                status_code=400, detail="persona か (preset, id, displayName) を指定してください"
            )
        try:
            registry.create(persona)
        except RegistryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return persona.model_dump(by_alias=True, exclude_none=True)

    @app.get("/api/personas/{persona_id}")
    async def get_persona(persona_id: str) -> dict:
        persona = _registry_call(registry.get, persona_id)
        return persona.model_dump(by_alias=True, exclude_none=True)

    @app.put("/api/personas/{persona_id}")
    async def update_persona(persona_id: str, body: dict) -> dict:
        persona = Persona.model_validate(body)
        updated, version = _registry_call(registry.update, persona_id, persona)
        return {
            **updated.model_dump(by_alias=True, exclude_none=True),
            "version": version,
        }

    @app.delete("/api/personas/{persona_id}")
    async def delete_persona(persona_id: str) -> dict:
        _registry_call(registry.delete, persona_id)  # 論理削除（§12.5）
        return {"deleted": True, "tombstone": True}

    @app.get("/api/personas/{persona_id}/prompt")
    async def persona_prompt(persona_id: str) -> dict:
        persona = _registry_call(registry.get, persona_id)
        return {"prompt": compose_prompt(persona)}

    @app.get("/api/personas/{persona_id}/children")
    async def persona_children(persona_id: str) -> list[str]:
        return registry.children_of(persona_id)

    # ---- Breed（§12） ----

    @app.post("/api/breed")
    async def breed(req: BreedRequest) -> dict:
        parent_a = _registry_call(registry.get, req.parentA)
        parent_b = _registry_call(registry.get, req.parentB)
        try:
            result = breeder.breed(
                parent_a, parent_b, seed=req.seed, mutation_rate=req.mutationRate
            )
        except BreedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        registry.create(result.child)
        return {
            "child": result.child.model_dump(by_alias=True, exclude_none=True),
            "warnings": result.warnings,
        }

    # ---- 移植（§10） ----

    @app.get("/api/personas/{persona_id}/export")
    async def export_persona(persona_id: str) -> Response:
        persona = _registry_call(registry.get, persona_id)
        try:
            data = porter.export_bytes(persona)
        except PortError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{persona_id}.persona"'
            },
        )

    @app.post("/api/import")
    async def import_persona(req: ImportRequest) -> dict:
        try:
            persona, voice = porter.import_bytes(base64.b64decode(req.packageBase64))
        except (PortError, RegistryError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "persona": persona.model_dump(by_alias=True, exclude_none=True),
            "voice": voice,
            "note": "Binding とメモリーは含まれません。管理者が別途設定してください（§10.2）",
        }

    # ---- Binding（§4.3） ----

    @app.post("/api/bindings")
    async def create_binding(req: BindingRequest) -> dict:
        binding = PersonaBinding(
            persona_id=req.personaId,
            agent_id=req.agentId,
            expertise=req.expertise,
            out_of_scope_stance=req.outOfScopeStance,
            invocation_aliases=req.invocationAliases,
        )
        _registry_call(registry.bind, binding)
        return binding.model_dump(by_alias=True)

    @app.get("/api/bindings")
    async def list_bindings(persona_id: str | None = None) -> list[dict]:
        return [b.model_dump(by_alias=True) for b in registry.bindings(persona_id)]

    # ---- ルーム（§11） ----

    @app.post("/api/rooms")
    async def create_room() -> dict:
        room = Room()
        rooms[room.room_id] = room
        return {"roomId": room.room_id}

    def _room(room_id: str) -> Room:
        if room_id not in rooms:
            raise HTTPException(status_code=404, detail=f"unknown room: {room_id}")
        return rooms[room_id]

    @app.post("/api/rooms/{room_id}/enter")
    async def enter_room(room_id: str, req: EnterRequest) -> dict:
        room = _room(room_id)
        persona = _registry_call(registry.get, req.personaId)
        agent_id = req.agentId
        if not agent_id or agent_id == "default":
            # 登録済み Binding（設定ファイル由来を含む）があればその接続先を使う
            registered = registry.bindings(req.personaId)
            agent_id = registered[0].agent_id if registered else "default"
        try:
            binding = registry.binding(req.personaId, agent_id)
        except RegistryError:
            binding = PersonaBinding(
                persona_id=req.personaId,
                agent_id=agent_id,
                invocation_aliases=[persona.display_name],
            )
        agent = agents.get(agent_id)
        try:
            instance = await room.enter(
                persona, binding, agent, user_id=req.userId
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"instanceId": instance.instance_id}

    @app.post("/api/rooms/{room_id}/leave")
    async def leave_room(room_id: str, req: LeaveRequest) -> dict:
        room = _room(room_id)
        try:
            await room.leave(req.instanceId)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"left": req.instanceId}

    @app.post("/api/rooms/{room_id}/speech")
    async def human_speech(room_id: str, req: SpeechRequest) -> dict:
        room = _room(room_id)
        room.join_human(req.userId, req.name)
        event = room.human_speech(req.userId, req.text)
        return {"seq": event.seq}

    @app.get("/api/rooms/{room_id}/log")
    async def room_log(room_id: str) -> list[dict]:
        return [_event_json(e) for e in _room(room_id).bus.log]

    @app.websocket("/ws/rooms/{room_id}")
    async def room_ws(websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        if room_id not in rooms:
            await websocket.send_json({"type": "error", "message": "unknown room"})
            await websocket.close()
            return
        room = rooms[room_id]
        queue = room.bus.subscribe()
        try:
            for event in room.bus.log:  # 履歴を再送してから購読
                await websocket.send_json(_event_json(event))
            while True:
                event = await queue.get()
                await websocket.send_json(_event_json(event))
        except WebSocketDisconnect:
            pass
        finally:
            room.bus.unsubscribe(queue)

    return app


def create_default_app() -> FastAPI:
    return create_app()
