"""TTS ラッパーのインターフェース（§7.3 注記）。

v1 で割り込みは実装しないが、将来対応のため stop() を持つ形にしておく。
実際の音声出力は会議UI側（別コンポーネント・§1.3）の責務であり、
ここには差し込み口だけを定義する。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSAdapter(Protocol):
    async def speak(self, ssml: str) -> None:
        """SSML（prosody 付き）を発話する。"""
        ...

    def stop(self) -> None:
        """発話を即時中断する（将来の割り込み対応用）。"""
        ...


class NullTTS:
    """既定の何もしない実装（テキストチャネルのみの構成用）。"""

    async def speak(self, ssml: str) -> None:
        return None

    def stop(self) -> None:
        return None
