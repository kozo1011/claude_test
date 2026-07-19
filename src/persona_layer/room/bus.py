"""RoomBus（§11.4）: イベントバスであって、調停者ではない。

- 発話イベントの配信と記録のみを行う。「誰が喋るか」は決めない
- speakerId は全イベント必須（無いと AI が自分の発言に反応して無限ループ）
- 全発話・全 bid を時刻付きで記録する（分散モデルのデバッグの命綱）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

EventType = Literal[
    "enter", "leave", "speech_start", "speech", "speech_end", "bid", "turn_limit"
]
SpeakerKind = Literal["human", "persona", "room"]
# speech の kind: human=人間の発話 / task=Agent のタスク回答（素通し） / meta=メタ発話
SpeechKind = Literal["human", "task", "meta", ""]

SUBSTANTIVE_KINDS = ("human", "task")


@dataclass(frozen=True)
class RoomEvent:
    type: EventType
    speaker_id: str
    speaker_kind: SpeakerKind
    seq: int
    at: float
    speaker_name: str = ""
    text: str = ""
    kind: SpeechKind = ""
    meta_kind: str = ""       # backchannel | filler | progress | handoff | apology | handover
    ssml: str = ""
    expression: str = ""
    payload: dict = field(default_factory=dict)


class RoomBus:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._seq = 0
        self.log: list[RoomEvent] = []
        self._queues: list[asyncio.Queue[RoomEvent]] = []
        self._listeners: list[Callable[[RoomEvent], None]] = []
        self._active_speakers: set[str] = set()

    # ---- 購読 ----

    def subscribe(self) -> asyncio.Queue[RoomEvent]:
        queue: asyncio.Queue[RoomEvent] = asyncio.Queue()
        self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RoomEvent]) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    def add_listener(self, listener: Callable[[RoomEvent], None]) -> None:
        """同期リスナー（Room の安全弁カウンタ等・記録用途）。調停には使わないこと。"""
        self._listeners.append(listener)

    # ---- 発行 ----

    def publish(
        self,
        type: EventType,
        speaker_id: str,
        speaker_kind: SpeakerKind,
        **fields,
    ) -> RoomEvent:
        if not speaker_id:
            raise ValueError("speakerId は全イベントで必須です（§11.4）")
        self._seq += 1
        event = RoomEvent(
            type=type,
            speaker_id=speaker_id,
            speaker_kind=speaker_kind,
            seq=self._seq,
            at=self._clock(),
            **fields,
        )
        self.log.append(event)
        if type == "speech_start":
            self._active_speakers.add(speaker_id)
        elif type == "speech_end":
            self._active_speakers.discard(speaker_id)
        for listener in self._listeners:
            listener(event)
        for queue in self._queues:
            queue.put_nowait(event)
        return event

    # ---- carrier sense 用の観測（判断はしない） ----

    @property
    def is_busy(self) -> bool:
        return bool(self._active_speakers)

    def last_speech(self) -> RoomEvent | None:
        """直近の実質的な発話（人間の発話 or タスク回答）。メタ発話は含まない。"""
        for event in reversed(self.log):
            if event.type == "speech" and event.kind in SUBSTANTIVE_KINDS:
                return event
        return None

    def speech_started_after(self, seq: int) -> bool:
        return any(
            e.seq > seq and e.type == "speech_start" for e in reversed(self.log)
        )

    def recent_speeches(self, limit: int = 12) -> list[RoomEvent]:
        speeches = [
            e
            for e in self.log
            if e.type == "speech" and e.kind in SUBSTANTIVE_KINDS
        ]
        return speeches[-limit:]
