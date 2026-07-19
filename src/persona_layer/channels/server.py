"""FastAPI サーバ: REST + WebSocket チャネル。

- ``GET  /``                          … ブラウザクライアント（チャット+音声）
- ``GET  /api/personas``              … ペルソナ一覧
- ``GET  /api/personas/{id}``         … ペルソナ詳細（音声パラメータ含む）
- ``POST /api/personas/{id}/export``  … 移植用エクスポート
- ``POST /api/chat/{id}``             … 1発話ぶんの応答（RESTクライアント向け）
- ``WS   /ws/chat/{id}``              … ストリーミング会話（ブラウザ/音声向け）
- ``POST /api/tts/{id}``              … サーバサイドTTS（プロバイダ設定時のみ）

WebSocket プロトコル（JSON テキストフレーム）:
    接続直後  サーバ→ {"type": "session_start", "session_id", "persona", "voice", "greeting"}
    発話      クライアント→ {"type": "user_message", "text": "..."}
    応答      サーバ→ {"type": "assistant_chunk", "text": "..."} を0回以上
              サーバ→ {"type": "assistant_message", "text": "<全文>"}
    エラー    サーバ→ {"type": "error", "message": "..."}
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..backends.base import AgentBackend
from ..exporters import export, formats
from ..loader import load_personas_dir
from ..runtime import PersonaRuntime, Session
from ..schema import Persona
from ..voice.base import TTSProvider, web_speech_params

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ChatRequest(BaseModel):
    text: str
    session_id: str | None = None


class ExportRequest(BaseModel):
    format: str = "system-prompt"


def _persona_summary(p: Persona) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "version": p.version,
        "description": p.description,
        "language": p.language,
        "voice_enabled": p.voice.enabled,
    }


def create_app(
    personas: dict[str, Persona],
    backend_factory,
    restyler_factory=None,
    tts_provider: TTSProvider | None = None,
) -> FastAPI:
    """アプリを構築する。

    Args:
        personas: id -> Persona。
        backend_factory: ``() -> AgentBackend``。ペルソナ非依存の共有バックエンド。
        restyler_factory: ``() -> AgentBackend | None``。中継モードの文体変換用。
        tts_provider: サーバサイド TTS（無指定なら /api/tts は 501 を返す）。
    """
    app = FastAPI(title="Persona Layer", version="0.1.0")

    runtimes: dict[str, PersonaRuntime] = {}
    sessions: dict[str, Session] = {}

    def runtime_for(persona_id: str) -> PersonaRuntime:
        if persona_id not in personas:
            raise HTTPException(status_code=404, detail=f"unknown persona: {persona_id}")
        if persona_id not in runtimes:
            backend: AgentBackend = backend_factory()
            restyler = restyler_factory() if restyler_factory else None
            runtimes[persona_id] = PersonaRuntime(
                personas[persona_id], backend, restyler=restyler
            )
        return runtimes[persona_id]

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")

    @app.get("/api/personas")
    async def list_personas() -> list[dict]:
        return [_persona_summary(p) for p in personas.values()]

    @app.get("/api/personas/{persona_id}")
    async def get_persona(persona_id: str) -> dict:
        if persona_id not in personas:
            raise HTTPException(status_code=404, detail=f"unknown persona: {persona_id}")
        p = personas[persona_id]
        return {
            **_persona_summary(p),
            "greeting": p.greeting,
            "voice": web_speech_params(p),
        }

    @app.get("/api/export-formats")
    async def export_formats() -> list[str]:
        return formats()

    @app.post("/api/personas/{persona_id}/export")
    async def export_persona(persona_id: str, req: ExportRequest) -> dict:
        if persona_id not in personas:
            raise HTTPException(status_code=404, detail=f"unknown persona: {persona_id}")
        try:
            result = export(personas[persona_id], req.format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "format": result.format,
            "filename": result.suggested_filename,
            "mime": result.mime,
            "content": result.text,
        }

    @app.post("/api/chat/{persona_id}")
    async def chat(persona_id: str, req: ChatRequest) -> dict:
        runtime = runtime_for(persona_id)
        session = sessions.get(req.session_id or "")
        if session is None or session.persona_id != persona_id:
            session = runtime.new_session()
            sessions[session.id] = session
        reply = await runtime.respond(session, req.text)
        return {"session_id": session.id, "reply": reply}

    @app.post("/api/tts/{persona_id}")
    async def tts(persona_id: str, req: ChatRequest) -> Response:
        if tts_provider is None:
            raise HTTPException(
                status_code=501,
                detail="サーバサイドTTSは未設定です（VOICEVOX_URL 等を設定してください）",
            )
        if persona_id not in personas:
            raise HTTPException(status_code=404, detail=f"unknown persona: {persona_id}")
        clip = await tts_provider.synthesize(req.text, personas[persona_id])
        return Response(content=clip.data, media_type=clip.mime)

    @app.websocket("/ws/chat/{persona_id}")
    async def ws_chat(websocket: WebSocket, persona_id: str) -> None:
        await websocket.accept()
        if persona_id not in personas:
            await websocket.send_json(
                {"type": "error", "message": f"unknown persona: {persona_id}"}
            )
            await websocket.close()
            return
        runtime = runtime_for(persona_id)
        persona = personas[persona_id]
        session = runtime.new_session()
        sessions[session.id] = session
        await websocket.send_json(
            {
                "type": "session_start",
                "session_id": session.id,
                "persona": _persona_summary(persona),
                "voice": web_speech_params(persona),
                "greeting": persona.greeting,
            }
        )
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") != "user_message":
                    continue
                text = str(data.get("text", "")).strip()
                if not text:
                    continue
                try:
                    parts: list[str] = []
                    async for chunk in runtime.stream_respond(session, text):
                        parts.append(chunk)
                        await websocket.send_json(
                            {"type": "assistant_chunk", "text": chunk}
                        )
                    await websocket.send_json(
                        {"type": "assistant_message", "text": "".join(parts)}
                    )
                except Exception as exc:  # バックエンド障害は接続を切らずに通知する
                    await websocket.send_json(
                        {"type": "error", "message": f"応答生成に失敗しました: {exc}"}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            sessions.pop(session.id, None)

    return app


def create_default_app() -> FastAPI:
    """環境変数から構成する既定アプリ（uvicorn から直接起動する場合用）。

    - PERSONA_DIR    … ペルソナ定義ディレクトリ（既定: ./personas）
    - PERSONA_BACKEND, ANTHROPIC_API_KEY / OPENAI_API_KEY / RELAY_URL … cli.make_backend 参照
    - VOICEVOX_URL   … 設定時のみサーバサイドTTS有効
    """
    from ..cli import make_backend, make_restyler

    personas = load_personas_dir(os.environ.get("PERSONA_DIR", "personas"))
    tts = None
    voicevox_url = os.environ.get("VOICEVOX_URL", "")
    if voicevox_url:
        from ..voice.voicevox import VoicevoxTTS

        tts = VoicevoxTTS(voicevox_url)
    return create_app(
        personas,
        backend_factory=make_backend,
        restyler_factory=make_restyler,
        tts_provider=tts,
    )
