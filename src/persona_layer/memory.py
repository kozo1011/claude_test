"""PersonaMemory（§9）: 選好・関係史の記憶。

- 書き込みトリガーは機械的に固定（§9.1）。LLM に「重要さ」を判定させない
- 人格レイヤーが読むのは preference と episode のみ（§9.2）。
  タスク知識は Agent 側のメモリの責務
- 移植・継承されない（§9.3）
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Callable

from .models import MemoryRecord, MemoryType

READ_RECENT = 10
READ_TOP_WEIGHT = 5
READABLE_TYPES: tuple[MemoryType, ...] = ("preference", "episode")

_EXPLICIT = re.compile(r"覚えて(おいて|て|ください)|記憶して")
_PREFERENCE = re.compile(r"(嫌い|苦手|好き|好み|の方がいい|のほうがいい|にしてほしい|でお願い)")


def classify_utterance(text: str) -> tuple[MemoryType, float] | None:
    """§9.1 の書き込みトリガー判定（軽量・ルールベース）。

    該当しなければ None（書き込まない）。訂正・タスク完了/失敗は発話ではなく
    イベントとして record_correction / record_episode で書き込む。
    """
    if _EXPLICIT.search(text):
        return ("preference", 1.0)
    if _PREFERENCE.search(text):
        return ("preference", 0.6)
    return None


class PersonaMemory:
    """既定はインメモリ。records を差し替えれば永続化バックエンドに載る。"""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self.records: list[MemoryRecord] = []

    def _write(
        self, persona_id: str, user_id: str, type_: MemoryType, content: str, weight: float
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=uuid.uuid4().hex,
            persona_id=persona_id,
            user_id=user_id,
            type=type_,
            content=content.strip(),
            created_at=self._clock(),
            weight=weight,
        )
        self.records.append(record)
        return record

    def consider_utterance(
        self, persona_id: str, user_id: str, text: str
    ) -> MemoryRecord | None:
        """人間の発話を §9.1 で判定し、該当すれば書き込む。"""
        result = classify_utterance(text)
        if result is None:
            return None
        type_, weight = result
        return self._write(persona_id, user_id, type_, text, weight)

    def record_correction(
        self, persona_id: str, user_id: str, content: str
    ) -> MemoryRecord:
        """ユーザーが Agent の誤りを訂正した（weight 0.8）。"""
        return self._write(persona_id, user_id, "correction", content, 0.8)

    def record_episode(
        self, persona_id: str, user_id: str, content: str
    ) -> MemoryRecord:
        """タスクの完了/失敗（weight 0.4）。"""
        return self._write(persona_id, user_id, "episode", content, 0.4)

    def read_lines(self, persona_id: str, user_id: str) -> list[str]:
        """システムプロンプト注入用: 直近10件 + weight 上位5件（§9.2）。
        preference / episode のみを読む。correction はタスク側の関心事。"""
        readable = [
            r
            for r in self.records
            if r.persona_id == persona_id
            and r.user_id == user_id
            and r.type in READABLE_TYPES
        ]
        recent = sorted(readable, key=lambda r: r.created_at)[-READ_RECENT:]
        top = sorted(readable, key=lambda r: r.weight, reverse=True)[:READ_TOP_WEIGHT]
        seen: set[str] = set()
        lines: list[str] = []
        for record in recent + top:
            if record.id not in seen:
                seen.add(record.id)
                lines.append(record.content)
        return lines
