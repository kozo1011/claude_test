"""データモデル（仕様書 §4）。

Persona / PersonaBinding / PersonaMemory の3分割（§4.1）が本システムの土台。
- Persona は移植・継承の単位（§10, §12）
- expertise は Binding に置く（Persona に置くと移植が成立しない・§17）
- gender / age フィールドは意図的に存在しない（§17）

JSON 表現は仕様書の TypeScript 定義に合わせて camelCase とする。
"""

from __future__ import annotations

import time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"

MAX_REFUSAL_LINES = 10  # §12.6

AxisName = Literal[
    "distance", "density", "assertion", "initiative", "affect", "playfulness"
]
AXES: tuple[AxisName, ...] = (
    "distance", "density", "assertion", "initiative", "affect", "playfulness"
)

Context = Literal["idle", "listening", "thinking", "speaking", "reporting"]
StateEvent = Literal["success", "error", "correction"]
MemoryType = Literal["preference", "correction", "episode"]


def _to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


class SpecModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        validate_assignment=True,
    )


class Anchor(SpecModel):
    """層1: 同一性アンカー（§4.2）。"""

    first_person: str
    second_person: str
    verbal_tics: list[str] = Field(default_factory=list)  # 語尾・口癖 2〜3個
    refusal_lines: list[str] = Field(default_factory=list, max_length=MAX_REFUSAL_LINES)
    free_note: Optional[str] = None


Axis = Field(ge=0, le=4)


class Style(SpecModel):
    """層2: 表出スタイル。各 0〜4 の整数6軸（§4.2, §5）。"""

    distance: int = Axis
    density: int = Axis
    assertion: int = Axis
    initiative: int = Axis
    affect: int = Axis
    playfulness: int = Axis

    def as_dict(self) -> dict[str, int]:
        return {axis: getattr(self, axis) for axis in AXES}


class Assets(SpecModel):
    sprite_set: str = "default"
    voice_id: str = "default"


class Lineage(SpecModel):
    """Breed で生成された場合のみ（§4.2, §12.5）。親→子の一方向。"""

    parents: tuple[str, str]
    generation: int = Field(ge=1)
    seed: int


class Persona(SpecModel):
    """移植・継承の単位（§4.2）。約1KB の JSON に収まることが移植性の根拠（§10.4）。"""

    schema_version: str = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str
    anchor: Anchor
    style: Style
    assets: Assets = Field(default_factory=Assets)
    lineage: Optional[Lineage] = None

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"schemaVersion {v!r} はこのランタイム（{SCHEMA_VERSION}）と互換性がありません"
            )
        return v

    def generation(self) -> int:
        return self.lineage.generation if self.lineage else 0


class PersonaBinding(SpecModel):
    """Agent への接続（§4.3）。移植・継承の対象外。"""

    persona_id: str
    agent_id: str
    expertise: list[str] = Field(default_factory=list)
    out_of_scope_stance: str = ""
    invocation_aliases: list[str] = Field(default_factory=list)


class PersonaState(SpecModel):
    """実行時状態（§4.4）。人格ごと・セッションごとに独立して保持する。"""

    persona_id: str
    arousal: float = Field(default=0.0, ge=0.0, le=1.0)
    familiarity: float = Field(default=0.0, ge=0.0, le=1.0)
    last_contact_at: float = Field(default_factory=time.time)
    context: Context = "idle"
    last_event: Optional[StateEvent] = None
    last_event_at: Optional[float] = None


class MemoryRecord(SpecModel):
    """選好・関係史の1レコード（§4.5）。1行1事実。"""

    id: str
    persona_id: str
    user_id: str
    type: MemoryType
    content: str
    created_at: float
    weight: float = Field(ge=0.0, le=1.0)
