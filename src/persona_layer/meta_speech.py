"""メタ発話（§7）。

- テンプレートは起動時（および人格の編集・生成時）にプリベイクする（§2.3, §7.2）
- 実行時はキャッシュから選ぶだけ。LLM を呼ばない
- 選択は決定的なローテーションで行い、直近2件を除外する（§7.2）
- filler / backchannel は読み上げ 1.5 秒以内に収まる長さに制限する（§7.3）
"""

from __future__ import annotations

import zlib
from collections import deque
from typing import Protocol

from . import tables
from .models import Persona

META_KINDS = ("backchannel", "filler", "progress", "handoff", "apology", "handover")
SHORT_KINDS = ("backchannel", "filler")

# 読み上げ速度の想定: 約9文字/秒（日本語TTSの標準速度相当）→ 1.5秒 ≒ 13文字
CHARS_PER_SECOND = 9
MAX_SHORT_CHARS = int(1.5 * CHARS_PER_SECOND)


class TemplateBaker(Protocol):
    """プリベイク器のインターフェース。LLM ベイカーを差し込む場合もこの形。
    生成は人格の決定的な関数であること（§7.2 注記）。"""

    def bake(self, persona: Persona) -> dict[str, list[str]]: ...


class RuleBasedBaker:
    """LLM を使わない既定のベイカー。

    素材テーブル（tables/meta_templates.yaml）から、人格の distance に応じた
    レジスタ（敬体/常体）を選び、verbalTics を長さの許すかぎり織り込む。
    同一人格からは常に同一のテンプレート集が生まれる（決定的）。
    """

    def bake(self, persona: Persona) -> dict[str, list[str]]:
        source = tables.meta_templates()
        register = "casual" if persona.style.distance >= 3 else "polite"
        baked: dict[str, list[str]] = {}
        for kind in META_KINDS:
            variants = list(source[kind][register])
            # 口癖を織り込んだバリエーションを追加（5〜8件の範囲に収める）
            for i, tic in enumerate(persona.anchor.verbal_tics):
                base = variants[i % len(variants)]
                candidate = f"{base}、{tic}"
                if kind in SHORT_KINDS and len(candidate) > MAX_SHORT_CHARS:
                    continue
                if candidate not in variants and len(variants) < 8:
                    variants.append(candidate)
            if kind in SHORT_KINDS:
                variants = [v for v in variants if len(v) <= MAX_SHORT_CHARS]
            baked[kind] = variants
        return baked


class MetaSpeech:
    """プリベイク済みテンプレートの保持と選択（1 PersonaInstance に1つ）。"""

    def __init__(self, persona: Persona, baker: TemplateBaker | None = None) -> None:
        self.persona = persona
        self._templates = (baker or RuleBasedBaker()).bake(persona)
        for kind in META_KINDS:
            if not self._templates.get(kind):
                raise ValueError(f"メタ発話テンプレートが空です: {kind}")
        # 人格ごとに開始位置をずらす（複数体が同じ相槌を揃って打つのを避ける）。
        # Python の hash() はプロセスごとに変わるため、安定ハッシュを使う（決定性）
        stable = zlib.crc32(persona.id.encode("utf-8"))
        self._cursor = {
            kind: stable % len(self._templates[kind]) for kind in META_KINDS
        }
        self._recent: dict[str, deque[str]] = {
            kind: deque(maxlen=2) for kind in META_KINDS
        }

    def templates(self, kind: str) -> list[str]:
        return list(self._templates[kind])

    def pick(self, kind: str, **fmt: str) -> str:
        """次のテンプレートを選ぶ。直近2件は選ばない（§7.2）。決定的。"""
        variants = self._templates[kind]
        recent = self._recent[kind]
        for _ in range(len(variants)):
            index = self._cursor[kind] % len(variants)
            self._cursor[kind] += 1
            candidate = variants[index]
            if candidate not in recent or len(variants) <= 2:
                break
        recent.append(candidate)
        return candidate.format(**fmt) if fmt else candidate
