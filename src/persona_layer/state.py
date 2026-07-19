"""層3: 状態エンジン（§6）。

- arousal: 指数減衰（τ=180秒）+ イベント加算。読み出し時に減衰計算する
- familiarity: 上昇はセッション終了時、減衰は読み出し時の遅延計算のみ
  （バッチジョブは使わない・§6.2）
- context: すべて Agent の応答を待たずに確定できる（§2.2 の前提）
"""

from __future__ import annotations

import math
import time
from typing import Callable, Literal

from .models import Context, PersonaState

AROUSAL_TAU_SEC = 180.0
AROUSAL_BUMPS = {
    "user_utterance": 0.15,
    "task_success": 0.25,
    "user_correction": 0.10,
    "task_error": 0.20,
}
FAMILIARITY_SESSION_GAIN = 0.03
FAMILIARITY_DAILY_DECAY = 0.99
IDLE_AFTER_SEC = 3.0

ObservableEvent = Literal[
    "user_utterance", "task_success", "user_correction", "task_error"
]

_EVENT_MARK = {
    "task_success": "success",
    "task_error": "error",
    "user_correction": "correction",
}


class FamiliarityStore:
    """(personaId, userId) → familiarity の永続化。既定はインメモリ。"""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], tuple[float, float]] = {}

    def load(self, persona_id: str, user_id: str) -> tuple[float, float] | None:
        return self._data.get((persona_id, user_id))

    def save(
        self, persona_id: str, user_id: str, familiarity: float, last_contact_at: float
    ) -> None:
        self._data[(persona_id, user_id)] = (familiarity, last_contact_at)


class StateEngine:
    """1つの PersonaInstance が保持する実行時状態（§4.4）。"""

    def __init__(
        self,
        persona_id: str,
        user_id: str = "default",
        store: FamiliarityStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._store = store
        self.user_id = user_id
        now = clock()
        familiarity, last_contact = 0.0, now
        if store is not None:
            saved = store.load(persona_id, user_id)
            if saved is not None:
                familiarity, last_contact = saved
        self.state = PersonaState(
            persona_id=persona_id,
            familiarity=familiarity,
            last_contact_at=last_contact,
        )
        self._arousal_at = now
        self._last_io_at = now

    # ---- arousal（§6.1） ----

    def arousal(self, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        dt = max(0.0, now - self._arousal_at)
        return self.state.arousal * math.exp(-dt / AROUSAL_TAU_SEC)

    def observe(self, event: ObservableEvent, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        value = self.arousal(now) + AROUSAL_BUMPS[event]
        self.state.arousal = max(0.0, min(1.0, value))
        self._arousal_at = now
        self._last_io_at = now
        mark = _EVENT_MARK.get(event)
        if mark is not None:
            self.state.last_event = mark
            self.state.last_event_at = now

    def meta_length_factor(self, now: float | None = None) -> float:
        """§6.1: メタ発話長さ係数 = 0.7 + 0.6 * arousal。"""
        return 0.7 + 0.6 * self.arousal(now)

    # ---- familiarity（§6.2） ----

    def familiarity_effective(self, now: float | None = None) -> float:
        """遅延減衰を適用して返す。読み出し時に stored も更新する（仕様通り）。"""
        now = self._clock() if now is None else now
        days = max(0.0, (now - self.state.last_contact_at) / 86400.0)
        effective = self.state.familiarity * (FAMILIARITY_DAILY_DECAY ** days)
        self.state.familiarity = effective
        self.state.last_contact_at = now
        self._persist()
        return effective

    def end_session(self, now: float | None = None) -> None:
        """セッション終了時: familiarity += 0.03（クリップ上限 1.0）。"""
        now = self._clock() if now is None else now
        self.state.familiarity = min(1.0, self.state.familiarity + FAMILIARITY_SESSION_GAIN)
        self.state.last_contact_at = now
        self._persist()

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save(
                self.state.persona_id,
                self.user_id,
                self.state.familiarity,
                self.state.last_contact_at,
            )

    # ---- context（§6.3） ----

    def set_context(self, context: Context, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        self.state.context = context
        self._last_io_at = now

    def context(self, now: float | None = None) -> Context:
        """現在の文脈。listening/speaking は入出力が3秒途絶えると idle に戻る。
        thinking（Agent 応答待ち）と reporting は明示遷移まで維持する。"""
        now = self._clock() if now is None else now
        current = self.state.context
        if current in ("listening", "speaking") and now - self._last_io_at > IDLE_AFTER_SEC:
            return "idle"
        return current
