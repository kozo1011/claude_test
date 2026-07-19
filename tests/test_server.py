import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from persona_layer.backends.mock import EchoBackend
from persona_layer.channels.server import create_app
from persona_layer.loader import load_personas_dir

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


@pytest.fixture
def client():
    personas = load_personas_dir(PERSONAS_DIR)
    app = create_app(personas, backend_factory=EchoBackend)
    return TestClient(app)


def test_index_serves_web_client(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Persona Layer" in resp.text


def test_list_personas(client):
    resp = client.get("/api/personas")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert ids == {"tutor-haru", "assistant-rei"}


def test_get_persona_includes_voice_params(client):
    resp = client.get("/api/personas/tutor-haru")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "春野ハル"
    assert data["voice"]["lang"] == "ja-JP"
    assert data["voice"]["pitch"] == 1.15
    assert data["greeting"]


def test_unknown_persona_404(client):
    assert client.get("/api/personas/nope").status_code == 404


def test_export_endpoint(client):
    resp = client.post(
        "/api/personas/tutor-haru/export", json={"format": "anthropic"}
    )
    assert resp.status_code == 200
    body = json.loads(resp.json()["content"])
    assert "春野ハル" in body["system"]


def test_export_bad_format_400(client):
    resp = client.post("/api/personas/tutor-haru/export", json={"format": "bad"})
    assert resp.status_code == 400


def test_rest_chat_keeps_session(client):
    resp1 = client.post("/api/chat/tutor-haru", json={"text": "こんにちは"})
    assert resp1.status_code == 200
    session_id = resp1.json()["session_id"]
    assert "こんにちは" in resp1.json()["reply"]
    resp2 = client.post(
        "/api/chat/tutor-haru", json={"text": "続きです", "session_id": session_id}
    )
    assert resp2.json()["session_id"] == session_id


def test_websocket_chat_flow(client):
    with client.websocket_connect("/ws/chat/tutor-haru") as ws:
        start = ws.receive_json()
        assert start["type"] == "session_start"
        assert start["persona"]["name"] == "春野ハル"
        assert start["voice"]["enabled"] is True
        assert start["greeting"]

        ws.send_json({"type": "user_message", "text": "テストです"})
        chunks = []
        while True:
            msg = ws.receive_json()
            if msg["type"] == "assistant_chunk":
                chunks.append(msg["text"])
            elif msg["type"] == "assistant_message":
                assert msg["text"] == "".join(chunks)
                assert "テストです" in msg["text"]
                break
            else:
                pytest.fail(f"unexpected message: {msg}")


def test_websocket_unknown_persona(client):
    with client.websocket_connect("/ws/chat/nope") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_tts_unconfigured_returns_501(client):
    resp = client.post("/api/tts/tutor-haru", json={"text": "こんにちは"})
    assert resp.status_code == 501
