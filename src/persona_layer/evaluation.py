"""評価用ユーティリティ（§12.8, §15）。

- 受け入れ基準3・4（軸の有効性・直交性）は人間の盲検が必要な基準。
  ここではその素材（軸スイープした人格群・プロンプト群）を生成する
- 受け入れ基準2（同一性の一貫性）の機械計測部分（一人称・語尾の出現率）を提供する
"""

from __future__ import annotations

from .breeder import PersonaBreeder
from .composers import compose_prompt
from .models import AXES, AxisName, Persona


def axis_sweep(base: Persona, axis: AxisName) -> list[Persona]:
    """指定軸のみを 0→4 に振った5体を返す（他軸は固定）。盲検素材（基準3・4）。"""
    personas = []
    for value in range(5):
        style = base.style.model_copy(update={axis: value})
        personas.append(
            base.model_copy(update={"id": f"{base.id}-{axis}{value}", "style": style})
        )
    return personas


def sweep_prompts(base: Persona, axis: AxisName) -> list[str]:
    """軸スイープ人格それぞれのシステムプロンプト。これを同一質問に適用した
    出力を盲検提示し、人間が順序を当てられるかを検査する（基準3）。"""
    return [compose_prompt(p) for p in axis_sweep(base, axis)]


def all_sweeps(base: Persona) -> dict[str, list[str]]:
    return {axis: sweep_prompts(base, axis) for axis in AXES}


def breed_test_population(
    parent_a: Persona, parent_b: Persona, count: int = 50, base_seed: int = 0
) -> list[Persona]:
    """基準9（Breed の多様性）などの検査母集団（§12.8）。"""
    return PersonaBreeder().population(parent_a, parent_b, count, base_seed)


def identity_consistency(persona: Persona, utterances: list[str]) -> float:
    """基準2の機械計測部分: 一人称・語尾のいずれかを含む発話の割合。

    注意: 「誤った一人称を使っていないか」も併せて確認する。他の一人称が
    出現した発話は不一致としてカウントする。
    """
    if not utterances:
        return 1.0
    others = {"私", "僕", "俺", "わたくし", "あたし"} - {persona.anchor.first_person}
    consistent = 0
    for utterance in utterances:
        if any(other in utterance for other in others):
            continue
        markers = [persona.anchor.first_person, *persona.anchor.verbal_tics]
        if any(marker and marker in utterance for marker in markers):
            consistent += 1
    return consistent / len(utterances)
