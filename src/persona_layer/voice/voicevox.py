"""VOICEVOX エンジンによるサーバサイド TTS プロバイダ（任意）。

ローカル等で VOICEVOX エンジン（https://voicevox.hiroshiba.jp/）を起動し、
環境変数 VOICEVOX_URL（例: http://127.0.0.1:50021）を設定すると有効になる。
話者はペルソナの voice.providers.voicevox.speaker_id で指定する。
"""

from __future__ import annotations

import httpx

from ..schema import Persona
from .base import AudioClip, TTSProvider


class VoicevoxTTS(TTSProvider):
    name = "voicevox"

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def synthesize(self, text: str, persona: Persona) -> AudioClip:
        conf = persona.voice.providers.get("voicevox", {})
        speaker = int(conf.get("speaker_id", 1))
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            query_resp = await client.post(
                f"{self.base_url}/audio_query",
                params={"text": text, "speaker": speaker},
            )
            query_resp.raise_for_status()
            query = query_resp.json()
            # Web Speech 互換の倍率を VOICEVOX のスケールへ写像する
            query["speedScale"] = persona.voice.rate
            query["pitchScale"] = max(-0.15, min(0.15, (persona.voice.pitch - 1.0) * 0.15))
            query["volumeScale"] = persona.voice.volume
            synth_resp = await client.post(
                f"{self.base_url}/synthesis",
                params={"speaker": speaker},
                json=query,
            )
            synth_resp.raise_for_status()
        return AudioClip(data=synth_resp.content, mime="audio/wav")
