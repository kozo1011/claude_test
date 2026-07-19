"""§7 メタ発話（プリベイク）と §8 表情ステートマシン。"""

from persona_layer.expression import ExpressionMachine
from persona_layer.meta_speech import (
    MAX_SHORT_CHARS,
    META_KINDS,
    MetaSpeech,
    RuleBasedBaker,
)
from persona_layer.state import StateEngine

from .conftest import make_persona
from .test_state import FakeClock


def test_prebake_produces_5_to_8_variants_per_kind(sage):
    baked = RuleBasedBaker().bake(sage)
    for kind in META_KINDS:
        assert 5 <= len(baked[kind]) <= 8, kind


def test_prebake_is_deterministic_function_of_persona(sage):
    """§7.2: テンプレート集は人格の決定的な関数。"""
    assert RuleBasedBaker().bake(sage) == RuleBasedBaker().bake(sage)


def test_filler_and_backchannel_within_1_5_seconds(sage, clown):
    """§7.3: filler / backchannel は読み上げ1.5秒以内に収まる長さ。"""
    for persona in (sage, clown):
        baked = RuleBasedBaker().bake(persona)
        for kind in ("filler", "backchannel"):
            for text in baked[kind]:
                assert len(text) <= MAX_SHORT_CHARS, text


def test_register_follows_distance(sage, clown):
    """distance が高い人格は常体、低い人格は敬体のテンプレートになる。"""
    polite = RuleBasedBaker().bake(sage)     # distance=1
    casual = RuleBasedBaker().bake(clown)    # distance=4
    assert "少々お待ちください" in polite["filler"]
    assert "ちょっと待ってて" in casual["filler"]


def test_pick_avoids_recent_two(sage):
    meta = MetaSpeech(sage)
    picks = [meta.pick("filler") for _ in range(20)]
    for i in range(2, len(picks)):
        assert picks[i] != picks[i - 1]
        assert picks[i] != picks[i - 2]


def test_pick_never_calls_llm_and_is_fast(sage):
    """§2.3: 実行時はキャッシュから選ぶだけ（実質ゼロレイテンシ）。"""
    import time

    meta = MetaSpeech(sage)
    start = time.perf_counter()
    for _ in range(1000):
        meta.pick("backchannel")
    assert time.perf_counter() - start < 0.1  # 1000回で100ms未満 → 1回0.1ms未満


def test_handover_formats_name(sage):
    meta = MetaSpeech(sage)
    text = meta.pick("handover", name="楓")
    assert "楓さん" in text


def test_expression_mapping_and_event_override():
    clock = FakeClock()
    engine = StateEngine("p1", clock=clock)
    machine = ExpressionMachine(engine, clock)
    assert machine.expression() == "neutral"
    engine.set_context("thinking")
    assert machine.expression() == "thinking"
    # 一時上書き: success → pleased（2.0秒間・§8.1）
    engine.observe("task_success")
    assert machine.expression() == "pleased"
    clock.advance(1.9)
    assert machine.expression() == "pleased"
    clock.advance(0.2)
    assert machine.expression() == "thinking"
    engine.set_context("reporting")
    assert machine.expression() == "speaking"  # v1 は流用


def test_expression_determinism_criterion_6():
    """受け入れ基準6: 同一の状態列 → 常に同一の表情列。"""

    def run() -> list[str]:
        clock = FakeClock()
        engine = StateEngine("p1", clock=clock)
        machine = ExpressionMachine(engine, clock)
        result = []
        script = [
            ("ctx", "listening"), ("tick", 1.0), ("obs", "user_utterance"),
            ("ctx", "thinking"), ("tick", 2.0), ("obs", "task_error"),
            ("tick", 1.0), ("ctx", "speaking"), ("tick", 2.5), ("obs", "task_success"),
        ]
        for op, value in script:
            if op == "ctx":
                engine.set_context(value)
            elif op == "obs":
                engine.observe(value)
            else:
                clock.advance(value)
            result.append(machine.expression())
        return result

    assert run() == run()
