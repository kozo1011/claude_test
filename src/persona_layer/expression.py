"""表情ステートマシン（§8）。

状態 → 表情ID の決定的マッピング。LLM は関与しない（§2.2）。
マッピングは tables/expressions.yaml のテーブル駆動（§8.1）。
"""

from __future__ import annotations

import time
from typing import Callable

from . import tables
from .state import StateEngine

EXPRESSION_IDS = ("neutral", "listening", "thinking", "speaking", "puzzled", "pleased")


class ExpressionMachine:
    def __init__(
        self, engine: StateEngine, clock: Callable[[], float] = time.time
    ) -> None:
        table = tables.expressions()
        self._base: dict[str, str] = table["base"]
        self._override: dict[str, str] = table["event_override"]["map"]
        self._override_duration: float = float(table["event_override"]["duration_sec"])
        self._engine = engine
        self._clock = clock

    def expression(self, now: float | None = None) -> str:
        """現在の表情ID。同一の状態列に対し常に同一の表情列を返す（受け入れ基準6）。"""
        now = self._clock() if now is None else now
        state = self._engine.state
        if (
            state.last_event is not None
            and state.last_event_at is not None
            and now - state.last_event_at <= self._override_duration
        ):
            return self._override[state.last_event]
        return self._base[self._engine.context(now)]
