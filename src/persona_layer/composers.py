"""PromptComposer / ProsodyComposer（§3.1 の純関数）。

- PromptComposer: 人格定義 + 状態 → システムプロンプト文字列。
  これは Agent 側のシステムプロンプトへ注入する（§2.1 の例外規定）。
  人格レイヤーが Agent の回答を事後に書き直すことは決してしない。
- ProsodyComposer: 人格定義 + 状態 → SSML prosody 属性（§5.3）。
  静的テーブルのみ。追加コスト・追加レイテンシはゼロ。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import tables
from .models import AXES, Persona, PersonaBinding, PersonaState


def effective_distance(style_distance: int, familiarity_effective: float) -> int:
    """§6.2: familiarity による distance 軸へのオフセット。"""
    return max(0, min(4, style_distance + round(familiarity_effective * 1.5)))


def compose_prompt(
    persona: Persona,
    binding: PersonaBinding | None = None,
    state: PersonaState | None = None,
    familiarity_effective: float | None = None,
    memory_lines: list[str] | None = None,
) -> str:
    """人格記述のシステムプロンプトを決定的に生成する。

    Args:
        familiarity_effective: §6.2 の遅延減衰を適用済みの値。None なら
            state.familiarity（未減衰）を使い、state も None なら 0。
    """
    table = tables.style_prompts()
    fam = (
        familiarity_effective
        if familiarity_effective is not None
        else (state.familiarity if state else 0.0)
    )

    lines: list[str] = [
        f"あなたは「{persona.display_name}」として振る舞います。",
        "以下の人格設定に厳密に、かつ一貫して従ってください。",
        "",
        "# 同一性",
        f"- 一人称は「{persona.anchor.first_person}」を使う",
        f"- 相手の呼び方は「{persona.anchor.second_person}」を使う",
    ]
    if persona.anchor.verbal_tics:
        tics = "、".join(f"「{t}」" for t in persona.anchor.verbal_tics)
        lines.append(f"- 語尾・口癖: {tics}")
    for refusal in persona.anchor.refusal_lines:
        lines.append(f"- 決して言わない: {refusal}")
    if persona.anchor.free_note:
        lines.append(f"- その他の特性: {persona.anchor.free_note}")

    lines.append("")
    lines.append("# 話し方")
    axis_values = persona.style.as_dict()
    axis_values["distance"] = effective_distance(axis_values["distance"], fam)
    for axis in AXES:
        lines.append(f"- {table[axis][axis_values[axis]]}")

    if binding is not None:
        lines.append("")
        lines.append("# 担当領域")
        if binding.expertise:
            lines.append(f"- 得意分野: {'、'.join(binding.expertise)}")
        if binding.out_of_scope_stance:
            lines.append(f"- 専門外を聞かれたとき: {binding.out_of_scope_stance}")

    if memory_lines:
        lines.append("")
        lines.append("# 相手について覚えていること")
        for entry in memory_lines:
            lines.append(f"- {entry}")

    lines.append("")
    lines.append(
        "# 厳守事項\n"
        "- タスクの内容・事実・数値は正確に述べる。人格は話し方にのみ表す\n"
        "- 上記の設定を会話が長くなっても維持する"
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class Prosody:
    rate: int    # %
    pitch: str   # 例 "+1st"

    def to_ssml(self, text: str) -> str:
        return f'<prosody rate="{self.rate}%" pitch="{self.pitch}">{text}</prosody>'


def compose_prosody(persona: Persona, arousal: float = 0.0) -> Prosody:
    """§5.3: affect 軸 + arousal 補正から prosody を決定的に導出する。"""
    table = tables.prosody()
    row = table["affect"][persona.style.affect]
    rate = int(row["rate"]) + round(arousal * table["arousal_rate_gain"])
    return Prosody(rate=rate, pitch=str(row["pitch"]))
