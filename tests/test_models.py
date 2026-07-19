"""§4 データモデル: 3分割・camelCase 互換・検証。"""

import json

import pytest
from pydantic import ValidationError

from persona_layer.models import (
    MAX_REFUSAL_LINES,
    Anchor,
    Lineage,
    Persona,
    PersonaBinding,
    Style,
)

from .conftest import make_persona


def test_persona_json_is_camel_case_per_spec(sage):
    data = sage.model_dump(by_alias=True, exclude_none=True)
    assert data["schemaVersion"] == "1.0"
    assert data["displayName"] == "紫苑"
    assert data["anchor"]["firstPerson"] == "私"
    assert data["anchor"]["verbalTics"]
    assert data["assets"]["voiceId"] == "default"
    # snake_case のキーが漏れていないこと
    text = json.dumps(data)
    assert "display_name" not in text and "first_person" not in text


def test_camel_case_roundtrip(sage):
    data = sage.model_dump(by_alias=True, exclude_none=True)
    assert Persona.model_validate(data) == sage


def test_persona_has_no_gender_age_expertise_fields():
    """§17: gender / age は存在しない。expertise は Binding に属する（§4.1）。"""
    fields = set(Persona.model_fields)
    assert "gender" not in fields and "age" not in fields
    assert "expertise" not in fields
    assert "expertise" in PersonaBinding.model_fields


def test_style_axes_are_0_to_4():
    with pytest.raises(ValidationError):
        Style(distance=5, density=0, assertion=0, initiative=0, affect=0, playfulness=0)
    with pytest.raises(ValidationError):
        Style(distance=-1, density=0, assertion=0, initiative=0, affect=0, playfulness=0)


def test_refusal_lines_capped_at_10():
    with pytest.raises(ValidationError):
        Anchor(
            first_person="私",
            second_person="あなた",
            refusal_lines=[f"r{i}" for i in range(MAX_REFUSAL_LINES + 1)],
        )


def test_schema_version_mismatch_rejected():
    persona = make_persona()
    data = persona.model_dump(by_alias=True, exclude_none=True)
    data["schemaVersion"] = "2.0"
    with pytest.raises(ValidationError, match="互換性"):
        Persona.model_validate(data)


def test_unknown_field_rejected():
    data = make_persona().model_dump(by_alias=True, exclude_none=True)
    data["gender"] = "female"  # §17 のフィールドを混入させても弾かれる
    with pytest.raises(ValidationError):
        Persona.model_validate(data)


def test_lineage_records_parents_generation_seed():
    lineage = Lineage(parents=("a", "b"), generation=1, seed=42)
    persona = make_persona(id="child")
    child = persona.model_copy(update={"lineage": lineage})
    assert child.generation() == 1
    assert persona.generation() == 0
