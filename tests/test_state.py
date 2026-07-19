"""§6 状態エンジン: arousal 減衰・familiarity 遅延減衰・context。"""

import math

import pytest

from persona_layer.state import FamiliarityStore, StateEngine


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def make_engine(clock, store=None):
    return StateEngine("p1", user_id="u1", store=store, clock=clock)


def test_arousal_bumps_per_spec(clock):
    engine = make_engine(clock)
    engine.observe("user_utterance")
    assert engine.arousal() == pytest.approx(0.15)
    engine.observe("task_success")
    assert engine.arousal() == pytest.approx(0.40)
    engine.observe("user_correction")
    assert engine.arousal() == pytest.approx(0.50)
    engine.observe("task_error")
    assert engine.arousal() == pytest.approx(0.70)


def test_arousal_exponential_decay_tau_180(clock):
    engine = make_engine(clock)
    engine.observe("task_success")  # 0.25
    clock.advance(180.0)
    assert engine.arousal() == pytest.approx(0.25 * math.exp(-1.0), rel=1e-6)


def test_arousal_clipped_at_1(clock):
    engine = make_engine(clock)
    for _ in range(10):
        engine.observe("task_success")
    assert engine.arousal() == 1.0


def test_meta_length_factor(clock):
    engine = make_engine(clock)
    assert engine.meta_length_factor() == pytest.approx(0.7)
    engine.observe("task_success")
    assert engine.meta_length_factor() == pytest.approx(0.7 + 0.6 * 0.25)


def test_familiarity_weekly_equilibrium_is_about_043(clock):
    """§6.2 の均衡点表: 週1利用 → 約 0.43 に収束。"""
    engine = make_engine(clock)
    for _ in range(300):
        clock.advance(7 * 86400)
        engine.familiarity_effective()  # 読み出し時の遅延減衰
        engine.end_session()            # セッション終了で +0.03
    assert engine.familiarity_effective() == pytest.approx(0.43, abs=0.02)


def test_familiarity_daily_saturates_to_1(clock):
    engine = make_engine(clock)
    for _ in range(300):
        clock.advance(86400)
        engine.familiarity_effective()
        engine.end_session()
    assert engine.familiarity_effective() > 0.95


def test_familiarity_monthly_almost_resets(clock):
    engine = make_engine(clock)
    for _ in range(300):
        clock.advance(30 * 86400)
        engine.familiarity_effective()
        engine.end_session()
    assert engine.familiarity_effective() == pytest.approx(0.12, abs=0.02)


def test_familiarity_persists_per_persona_user(clock):
    store = FamiliarityStore()
    engine = make_engine(clock, store)
    engine.end_session()
    engine2 = make_engine(clock, store)
    assert engine2.state.familiarity == pytest.approx(0.03)
    # 別人格への親密度は別（§4.4）
    other = StateEngine("p2", user_id="u1", store=store, clock=clock)
    assert other.state.familiarity == 0.0


def test_context_idle_after_3_seconds(clock):
    engine = make_engine(clock)
    engine.set_context("listening")
    assert engine.context() == "listening"
    clock.advance(3.1)
    assert engine.context() == "idle"


def test_thinking_persists_regardless_of_time(clock):
    """thinking は Agent 応答待ちなので時間経過で idle に落ちない（§6.3）。"""
    engine = make_engine(clock)
    engine.set_context("thinking")
    clock.advance(60)
    assert engine.context() == "thinking"
