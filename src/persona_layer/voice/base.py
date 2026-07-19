"""音声入出力のプラガブルなインターフェース。

方針:
- 標準構成ではブラウザ側の Web Speech API で STT/TTS を行う（サーバ追加依存なし）。
  サーバはペルソナの VoiceProfile をパラメータとしてクライアントへ渡すだけでよい。
- サーバサイド合成が必要な場合（品質重視・キャラクターボイス等）は
  TTSProvider 実装（例: VOICEVOX）を差し込む。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..schema import Persona


@dataclass
class AudioClip:
    data: bytes
    mime: str


class TTSProvider(ABC):
    name: str = "tts"

    @abstractmethod
    async def synthesize(self, text: str, persona: Persona) -> AudioClip:
        """テキストをペルソナの声で音声化する。"""


class STTProvider(ABC):
    name: str = "stt"

    @abstractmethod
    async def transcribe(self, audio: AudioClip, language: str) -> str:
        """音声をテキストに書き起こす。"""


def web_speech_params(persona: Persona) -> dict[str, Any]:
    """ブラウザの Web Speech API に渡す発話/認識パラメータ。"""
    v = persona.voice
    return {
        "enabled": v.enabled,
        "lang": persona.voice_language(),
        "pitch": v.pitch,
        "rate": v.rate,
        "volume": v.volume,
        "voice_hint": v.providers.get("web_speech", {}).get("voice_name", ""),
    }
