"""PersonaInstance（§2.6, §3.0）: 1体の人格の実行時実体。

自分の PersonaState・AgentBridge・MetaSpeech・SpeechArbiter・表情だけを持ち、
他の人格を知らない。「現在の人格」というグローバル状態は存在しない。

1発話の流れ（§3.0）:
  RoomBus購読 → 発話権判定(§11.6) → filler(即時・§7.3) → AgentBridge転送
    → タスク回答受信 → 素通し+声・表情(§2.1/§2.2) → RoomBusへ発話(話者ID付き)
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Callable

from ..agent import Agent, AgentRequest, AgentTurn
from ..bridge import AgentBridge, AgentError
from ..composers import compose_prosody
from ..expression import ExpressionMachine
from ..memory import PersonaMemory
from ..meta_speech import MetaSpeech, TemplateBaker
from ..models import Persona, PersonaBinding
from ..state import FamiliarityStore, StateEngine
from .. import tables
from .arbiter import SpeechArbiter
from .bus import RoomBus, RoomEvent

_CORRECTION_MARKERS = ("違うよ", "違います", "間違って", "そうじゃなくて", "訂正")

# Agent へ渡す依頼文。回答の「内容」は指示せず、枠組みだけを与える（§2.1）。
# 相槌・つなぎはメタ発話が担うため、回答側で重複させないよう明示する。
INSTRUCTION = (
    "上記の会話の流れを踏まえ、直前の発話に応答してください。"
    "あなたの役割と得意分野に沿って、具体的な内容を述べてください。"
    "挨拶や相槌だけで終わらせないでください（相槌は別のしくみが担当します）。"
)


class PersonaInstance:
    def __init__(
        self,
        persona: Persona,
        binding: PersonaBinding,
        agent: Agent,
        bus: RoomBus,
        user_id: str = "default",
        baker: TemplateBaker | None = None,
        memory: PersonaMemory | None = None,
        familiarity_store: FamiliarityStore | None = None,
        clock: Callable[[], float] = time.time,
        timescale: float = 1.0,
        rng: random.Random | None = None,
    ) -> None:
        if binding.persona_id != persona.id:
            raise ValueError("Binding の personaId が一致しません")
        self.persona = persona
        self.binding = binding
        self.instance_id = f"{persona.id}@{agent.agent_id}"
        # Agent 側が会話履歴を保持する構成のための識別子（人格×利用者で一意）
        self.session_id = f"{self.instance_id}:{user_id}"
        self.bus = bus
        self.timescale = timescale
        self._clock = clock
        self.engine = StateEngine(
            persona.id, user_id=user_id, store=familiarity_store, clock=clock
        )
        self.memory = memory
        self.meta = MetaSpeech(persona, baker)
        self.bridge = AgentBridge(persona, binding, agent, self.engine, memory, clock)
        self.expressions = ExpressionMachine(self.engine, clock)
        self.arbiter = SpeechArbiter(self.instance_id, persona, binding, rng)
        self._progress_after = float(tables.arbiter()["progress_after_sec"])
        self._queue: asyncio.Queue[RoomEvent] | None = None
        self._task: asyncio.Task | None = None
        self._last_trigger_seq = 0

    # ---- ライフサイクル ----

    async def start(self) -> None:
        self._queue = self.bus.subscribe()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._queue is not None:
            self.bus.unsubscribe(self._queue)
            self._queue = None
        self.engine.end_session()

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.timescale)

    # ---- イベント処理 ----

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                await self._handle(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 1イベントの失敗でインスタンスを殺さない（バスのログが記録を持つ）
                continue

    async def _handle(self, event: RoomEvent) -> None:
        # 自分自身のイベントには一切反応しない（§11.4・受け入れ基準11）
        if event.speaker_id == self.instance_id:
            return
        if event.type == "turn_limit":
            self.arbiter.suspended = True
            return
        if event.type != "speech":
            return
        if event.kind == "human":
            self.engine.observe("user_utterance")
            self.engine.set_context("listening")
            self._observe_memory(event)
            # 相槌（§7.1）: 即時・テンプレートのみ
            self._publish_meta("backchannel")
        await self._try_speak(event)

    def _observe_memory(self, event: RoomEvent) -> None:
        if any(marker in event.text for marker in _CORRECTION_MARKERS):
            self.engine.observe("user_correction")
            if self.memory is not None:
                self.memory.record_correction(
                    self.persona.id, self.engine.user_id, event.text
                )
        elif self.memory is not None:
            self.memory.consider_utterance(
                self.persona.id, self.engine.user_id, event.text
            )

    # ---- 発話権ループ（§11.6 の 1〜5） ----

    async def _try_speak(self, trigger: RoomEvent) -> None:
        for _ in range(3):
            # 1-2. carrier sense: 発話中なら空くまで待つ
            while self.bus.is_busy:
                await self._sleep(0.05)
            current = self.bus.last_speech() or trigger
            if current.seq <= self._last_trigger_seq:
                return  # この発話には判定済み
            # 3. 喋るべきか判定
            bid = self.arbiter.decide(current, self.bus)
            self._last_trigger_seq = current.seq
            if bid is None:
                return
            bid_event = self.bus.publish(
                "bid",
                speaker_id=self.instance_id,
                speaker_kind="persona",
                speaker_name=self.persona.display_name,
                payload={"priority": bid.priority, "backoffSec": bid.backoff_sec},
            )
            # 4. backoff だけ待つ
            await self._sleep(bid.backoff_sec)
            # 5. まだ空いていれば発話開始。先を越されたら諦めて 1 へ
            if self.bus.is_busy or self.bus.speech_started_after(bid_event.seq):
                self._last_trigger_seq = 0  # 新しい発話に対して再判定できるように戻す
                continue
            await self._speak(current)
            return

    # ---- 発話（filler → Agent 転送 → 素通し） ----

    def _publish_meta(self, meta_kind: str, **fmt: str) -> RoomEvent:
        text = self.meta.pick(meta_kind, **fmt)
        prosody = compose_prosody(self.persona, self.engine.arousal())
        return self.bus.publish(
            "speech",
            speaker_id=self.instance_id,
            speaker_kind="persona",
            speaker_name=self.persona.display_name,
            text=text,
            kind="meta",
            meta_kind=meta_kind,
            ssml=prosody.to_ssml(text),
            expression=self.expressions.expression(),
        )

    def _context_prompt(self) -> str:
        """§11.5: 直近発話に話者名を付け、自分の過去発話に印をつけて Agent へ渡す。

        構造化メッセージ（turns）に対応しない Agent 向けの平文フォールバック。
        """
        lines: list[str] = ["これまでの会話:"]
        for event in self.bus.recent_speeches():
            name = event.speaker_name or event.speaker_id
            if event.speaker_id == self.instance_id:
                label = f"{name}（自分・AI）"
            elif event.speaker_kind == "human":
                label = f"{name}（人間の参加者）"
            else:
                label = f"{name}（他のAI）"
            lines.append(f"{label}: {event.text}")
        lines.append("")
        lines.append(INSTRUCTION)
        return "\n".join(lines)

    def _build_request(self) -> AgentRequest:
        """§11.5: 会話文脈を役割構造（user/assistant）付きで組み立てる。"""
        turns: list[AgentTurn] = []
        for event in self.bus.recent_speeches():
            is_self = event.speaker_id == self.instance_id
            turns.append(
                AgentTurn(
                    role="assistant" if is_self else "user",
                    content=event.text,
                    speaker_name=event.speaker_name or event.speaker_id,
                    speaker_kind=event.speaker_kind,
                    is_self=is_self,
                )
            )
        return AgentRequest(
            prompt=self._context_prompt(),
            instruction=INSTRUCTION,
            turns=turns,
            session_id=self.session_id,
        )

    async def _speak(self, trigger: RoomEvent) -> None:
        self.bus.publish(
            "speech_start",
            speaker_id=self.instance_id,
            speaker_kind="persona",
            speaker_name=self.persona.display_name,
        )
        try:
            # filler は Agent への転送と同時に出す（§7.3: 応答を待たない）
            self._publish_meta("filler")
            ask = asyncio.ensure_future(self.bridge.ask(self._build_request()))
            progressed = False
            try:
                while True:
                    done, _ = await asyncio.wait(
                        [ask], timeout=self._progress_after * self.timescale
                    )
                    if done:
                        break
                    if not progressed:
                        self._publish_meta("progress")  # 処理が3秒を超過（§7.1）
                        progressed = True
            except asyncio.CancelledError:
                ask.cancel()
                raise
            try:
                result = ask.result()
            except AgentError:
                self._publish_meta("apology")
                return
            if progressed:
                self._publish_meta("handoff")
            self.engine.observe("task_success")
            self.engine.set_context("speaking")
            prosody = compose_prosody(self.persona, self.engine.arousal())
            # タスク回答は素通し（§2.1）。text は Agent の出力と完全一致すること
            self.bus.publish(
                "speech",
                speaker_id=self.instance_id,
                speaker_kind="persona",
                speaker_name=self.persona.display_name,
                text=result.text,
                kind="task",
                ssml=prosody.to_ssml(result.text),
                expression=self.expressions.expression(),
            )
            if self.memory is not None:
                self.memory.record_episode(
                    self.persona.id,
                    self.engine.user_id,
                    f"応答したタスク: {trigger.text[:40]}",
                )
        finally:
            self.bus.publish(
                "speech_end",
                speaker_id=self.instance_id,
                speaker_kind="persona",
                speaker_name=self.persona.display_name,
            )
            self.engine.set_context("idle")
