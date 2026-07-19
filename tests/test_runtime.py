from pathlib import Path

from persona_layer.backends.mock import EchoBackend, ScriptedBackend
from persona_layer.loader import load_persona
from persona_layer.runtime import PersonaRuntime

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def make_runtime(**kwargs):
    persona = load_persona(PERSONAS_DIR / "tutor_haru.yaml")
    return PersonaRuntime(persona, kwargs.pop("backend", EchoBackend()), **kwargs)


async def test_respond_updates_history():
    runtime = make_runtime()
    session = runtime.new_session()
    reply = await runtime.respond(session, "こんにちは")
    assert "こんにちは" in reply
    assert [m.role for m in session.messages] == ["user", "assistant"]
    assert session.messages[1].content == reply


async def test_backend_receives_persona_system_prompt():
    backend = ScriptedBackend(["はい、ここがポイントです。"])
    runtime = make_runtime(backend=backend)
    session = runtime.new_session()
    await runtime.respond(session, "二次方程式がわかりません")
    request = backend.requests[0]
    assert "春野ハル" in request.system
    assert request.messages[-1].content == "二次方程式がわかりません"


async def test_multi_turn_history_is_passed():
    backend = ScriptedBackend(["1つ目", "2つ目"])
    runtime = make_runtime(backend=backend)
    session = runtime.new_session()
    await runtime.respond(session, "最初の質問")
    await runtime.respond(session, "次の質問")
    second_request = backend.requests[1]
    contents = [m.content for m in second_request.messages]
    assert contents == ["最初の質問", "1つ目", "次の質問"]


async def test_history_window_trims_old_turns():
    backend = ScriptedBackend(["応答"])
    runtime = make_runtime(backend=backend, max_history_turns=2)
    session = runtime.new_session()
    for i in range(5):
        await runtime.respond(session, f"発話{i}")
    last_request = backend.requests[-1]
    # 2往復ぶん（4メッセージ、末尾は今回の user 発話）に切り詰められる
    assert len(last_request.messages) == 4
    assert last_request.messages[-1].content == "発話4"
    # セッション自体は全履歴を保持する
    assert len(session.messages) == 10


async def test_stream_respond_accumulates_history():
    runtime = make_runtime()
    session = runtime.new_session()
    chunks = [c async for c in runtime.stream_respond(session, "テスト")]
    assert len(chunks) > 1  # EchoBackend は分割して返す
    assert session.messages[-1].content == "".join(chunks)


async def test_relay_mode_restyles_upstream_content():
    upstream = ScriptedBackend(["第3章では二次方程式の解の公式を扱います。"])
    restyler = ScriptedBackend(["第3章では、二次方程式の解の公式を一緒に見ていきましょう！"])
    runtime = make_runtime(backend=upstream, restyler=restyler)
    session = runtime.new_session()
    reply = await runtime.respond(session, "次は何を勉強しますか？")
    assert reply == "第3章では、二次方程式の解の公式を一緒に見ていきましょう！"
    # 文体変換には style prompt が使われ、原文が user メッセージとして渡る
    style_request = restyler.requests[0]
    assert "書き換えてください" in style_request.system
    assert style_request.messages[0].content == "第3章では二次方程式の解の公式を扱います。"
    # 履歴には変換後の応答が残る
    assert session.messages[-1].content == reply


async def test_relay_mode_stream_returns_single_chunk():
    upstream = ScriptedBackend(["原文"])
    restyler = ScriptedBackend(["変換後"])
    runtime = make_runtime(backend=upstream, restyler=restyler)
    session = runtime.new_session()
    chunks = [c async for c in runtime.stream_respond(session, "q")]
    assert chunks == ["変換後"]


async def test_restyler_failure_returns_raw_text():
    upstream = ScriptedBackend(["原文のまま"])
    restyler = ScriptedBackend([""])  # 空応答 = 変換失敗相当
    runtime = make_runtime(backend=upstream, restyler=restyler)
    session = runtime.new_session()
    reply = await runtime.respond(session, "q")
    assert reply == "原文のまま"


async def test_greeting_comes_from_persona():
    runtime = make_runtime()
    assert "春野ハル" in runtime.greeting()
