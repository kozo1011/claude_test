"""§5 PromptComposer / ProsodyComposer と、§6.2 の distance オフセット。"""

from persona_layer import tables
from persona_layer.composers import (
    compose_prompt,
    compose_prosody,
    effective_distance,
)
from persona_layer.models import AXES, PersonaBinding

from .conftest import make_persona


def test_prompt_contains_anchor_and_all_axis_lines(sage):
    prompt = compose_prompt(sage)
    assert "紫苑" in prompt
    assert "一人称は「私」" in prompt
    assert "「〜でしょう」" in prompt
    assert "決して言わない: 根拠のない断定" in prompt
    table = tables.style_prompts()
    for axis in AXES:
        assert table[axis][getattr(sage.style, axis)] in prompt


def test_prompt_is_deterministic(sage):
    """受け入れ基準10: 同一人格・同一状態 → 同一のプロンプト（文体一定）。"""
    assert compose_prompt(sage) == compose_prompt(sage)


def test_axis_value_changes_only_its_own_line():
    """§5.1 の表引きが軸ごとに独立していること（基準4の構造的前提）。"""
    base = make_persona(density=0)
    varied = make_persona(density=4)
    diff = set(compose_prompt(base).splitlines()) ^ set(compose_prompt(varied).splitlines())
    table = tables.style_prompts()
    assert diff == {f"- {table['density'][0]}", f"- {table['density'][4]}"}


def test_binding_expertise_included(sage):
    binding = PersonaBinding(
        persona_id="sage",
        agent_id="a1",
        expertise=["投資", "税務"],
        out_of_scope_stance="専門外は正直に伝え、詳しい人格を紹介する",
    )
    prompt = compose_prompt(sage, binding=binding)
    assert "投資" in prompt and "税務" in prompt
    assert "専門外" in prompt


def test_memory_lines_injected(sage):
    prompt = compose_prompt(sage, memory_lines=["利用者は箇条書きを好まない"])
    assert "利用者は箇条書きを好まない" in prompt


def test_effective_distance_offsets_with_familiarity():
    """§6.2: 初対面は丁寧、慣れると砕ける。"""
    assert effective_distance(1, 0.0) == 1
    assert effective_distance(1, 1.0) == 3   # round(1.5) = 2
    assert effective_distance(4, 1.0) == 4   # クリップ
    assert effective_distance(0, 0.2) == 0


def test_familiarity_changes_distance_line_in_prompt():
    persona = make_persona(distance=1)
    formal = compose_prompt(persona, familiarity_effective=0.0)
    familiar = compose_prompt(persona, familiarity_effective=1.0)
    table = tables.style_prompts()
    assert f"- {table['distance'][1]}" in formal
    assert f"- {table['distance'][3]}" in familiar


def test_prosody_table_per_spec():
    """§5.3 の静的テーブル。affect がテキストと音声の両方を駆動する。"""
    expected = {0: (95, "-1st"), 1: (100, "+0st"), 2: (105, "+1st"),
                3: (110, "+2st"), 4: (115, "+3st")}
    for affect, (rate, pitch) in expected.items():
        p = make_persona(affect=affect)
        prosody = compose_prosody(p, arousal=0.0)
        assert (prosody.rate, prosody.pitch) == (rate, pitch)


def test_prosody_arousal_correction():
    """rate_final = rate_base + round(arousal * 5)。§5.3 の出力例を再現。"""
    p = make_persona(affect=2)  # base 105%
    prosody = compose_prosody(p, arousal=0.4)
    assert prosody.rate == 107
    assert prosody.to_ssml("できました、共有しますね") == (
        '<prosody rate="107%" pitch="+1st">できました、共有しますね</prosody>'
    )


def test_prosody_is_deterministic(sage):
    assert compose_prosody(sage, 0.5) == compose_prosody(sage, 0.5)
