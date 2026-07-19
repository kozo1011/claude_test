"""ペルソナ定義スキーマ（Portable Persona Definition; PPD）。

このモジュールが定義する ``Persona`` が本システムの中核データであり、
YAML/JSON として保存・交換され、任意の AI エージェントへ移植できる。
スキーマは後方互換を保ちながら ``SCHEMA_VERSION`` で版管理する。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class Formality(str, Enum):
    casual = "casual"
    polite = "polite"
    formal = "formal"


class ResponseLength(str, Enum):
    short = "short"
    medium = "medium"
    long = "long"


class Formatting(str, Enum):
    plain = "plain"
    markdown = "markdown"


class StrictModel(BaseModel):
    # 未知キーは定義ファイルの typo である可能性が高いため、読み込み時に弾く
    model_config = ConfigDict(extra="forbid")


class Identity(StrictModel):
    role: str = "アシスタント"
    background: str = ""
    first_person: str = ""
    audience: str = ""


class Personality(StrictModel):
    traits: list[str] = Field(default_factory=list)
    tone: str = ""
    formality: Formality = Formality.polite
    humor: str = ""


class SpeechStyle(StrictModel):
    sentence_endings: list[str] = Field(default_factory=list)
    favorite_phrases: list[str] = Field(default_factory=list)
    avoid_words: list[str] = Field(default_factory=list)
    quirks: list[str] = Field(default_factory=list)
    response_length: ResponseLength = ResponseLength.medium
    formatting: Formatting = Formatting.plain


class Behavior(StrictModel):
    goals: list[str] = Field(default_factory=list)
    guidelines: list[str] = Field(default_factory=list)
    prohibited: list[str] = Field(default_factory=list)
    on_unknown: str = "知らないことは正直に「わからない」と伝える"


class Knowledge(StrictModel):
    domains: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class VoiceProfile(StrictModel):
    """音声合成/認識のためのヒント。

    ``pitch``/``rate``/``volume`` は Web Speech API 互換の倍率表現とし、
    各 TTS プロバイダ固有の設定は ``providers`` に名前空間を切って持つ。
    """

    enabled: bool = True
    language: str = ""  # 空なら Persona.language から導出（例: ja -> ja-JP）
    gender_hint: str = ""
    style: str = ""
    pitch: float = Field(default=1.0, ge=0.5, le=2.0)
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Example(StrictModel):
    user: str
    assistant: str


class Safety(StrictModel):
    ai_disclosure: bool = True  # AIかと問われたら認める
    restrictions: list[str] = Field(default_factory=list)


class Meta(StrictModel):
    author: str = ""
    created: str = ""
    license: str = ""
    tags: list[str] = Field(default_factory=list)


class Persona(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    version: str = "1.0.0"
    description: str = ""
    language: str = "ja"
    greeting: str = ""
    identity: Identity = Field(default_factory=Identity)
    personality: Personality = Field(default_factory=Personality)
    speech_style: SpeechStyle = Field(default_factory=SpeechStyle)
    behavior: Behavior = Field(default_factory=Behavior)
    knowledge: Knowledge = Field(default_factory=Knowledge)
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    examples: list[Example] = Field(default_factory=list)
    safety: Safety = Field(default_factory=Safety)
    meta: Meta = Field(default_factory=Meta)

    def voice_language(self) -> str:
        """音声用の BCP47 言語タグを返す。"""
        if self.voice.language:
            return self.voice.language
        base = self.language.split("-")[0].lower()
        defaults = {"ja": "ja-JP", "en": "en-US", "zh": "zh-CN", "ko": "ko-KR"}
        return defaults.get(base, self.language or "ja-JP")


def json_schema() -> dict[str, Any]:
    """PPD の JSON Schema を返す（他言語実装との相互運用用）。"""
    return Persona.model_json_schema()
