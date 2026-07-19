"""SpeechArbiter（§11.6）: 発話権のローカル判定。

CSMA/CD と同型の分散プロトコル。中央の司会コンポーネントは存在しない。
- backoff は initiative 軸の関数（主導性の高い人格ほど先に喋る）
- jitter は衝突を割るためだけの微小ランダム（§2.5 の唯一の例外。
  発話の内容は一切変えず、いつ喋るかしか動かさない）
- bid 判定は LLM を呼ばない軽量判定のみ
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import tables
from ..models import Persona, PersonaBinding
from .bus import RoomBus, RoomEvent


@dataclass(frozen=True)
class Bid:
    priority: str        # "high" | "normal"
    backoff_sec: float   # jitter 込み


class SpeechArbiter:
    def __init__(
        self,
        instance_id: str,
        persona: Persona,
        binding: PersonaBinding,
        rng: random.Random | None = None,
    ) -> None:
        cfg = tables.arbiter()
        self.instance_id = instance_id
        self.persona = persona
        self.binding = binding
        self._base = float(cfg["backoff_base_sec"][persona.style.initiative])
        self._jitter_max = float(cfg["jitter_max_sec"])
        self._addressed_base = float(cfg["addressed_backoff_base_sec"])
        self._silent_boost_turns = int(cfg["silent_boost_turns"])
        self._silent_boost_factor = float(cfg["silent_boost_factor"])
        self._rng = rng or random.Random()
        self.suspended = False  # §11.7 ターン上限超過で立ち、人間の発話で解除

    # ---- 判定材料（すべて軽量・LLMなし） ----

    def _addressed(self, text: str) -> bool:
        names = [self.persona.display_name, *self.binding.invocation_aliases]
        return any(name and name in text for name in names)

    def _expertise_hit(self, text: str) -> bool:
        return any(topic and topic in text for topic in self.binding.expertise)

    def _silent_recently(self, bus: RoomBus) -> bool:
        recent = bus.recent_speeches(self._silent_boost_turns)
        return bool(recent) and all(e.speaker_id != self.instance_id for e in recent)

    # ---- bid 判定（§11.6） ----

    def decide(self, event: RoomEvent, bus: RoomBus) -> Bid | None:
        # 自分自身の発話には決して反応しない（受け入れ基準11）
        if event.speaker_id == self.instance_id:
            return None
        if event.type != "speech" or event.kind not in ("human", "task"):
            return None
        # 人間の発話は安全弁の suspend を解除する（§11.7 司会＝人間）
        if event.speaker_kind == "human":
            self.suspended = False
        if self.suspended:
            return None
        # 直前の実質発話が自分 → 連続発話を避けるため bid しない
        last = bus.last_speech()
        if last is not None and last.speaker_id == self.instance_id:
            return None

        addressed = self._addressed(event.text)
        if event.speaker_kind == "human":
            # 人間の発話には誰かが応えるべきなので常に bid（誰が先かは backoff が決める）
            priority = "high" if addressed else "normal"
        elif addressed:
            priority = "high"
        elif self._expertise_hit(event.text):
            priority = "normal"
        else:
            return None

        if priority == "high":
            # 名指しは initiative 非依存の短い backoff（jitter 上限を足しても
            # 通常 bid の最短 200ms より短い）→ 名指しされた人格が必ず先に取る
            backoff = self._addressed_base
        elif self._silent_recently(bus):
            backoff = self._base * self._silent_boost_factor
        else:
            backoff = self._base
        backoff += self._rng.uniform(0.0, self._jitter_max)
        return Bid(priority=priority, backoff_sec=backoff)
