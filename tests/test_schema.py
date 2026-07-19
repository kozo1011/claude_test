from pathlib import Path

import pytest

from persona_layer.loader import (
    PersonaLoadError,
    load_persona,
    load_personas_dir,
    loads,
    save_persona,
)
from persona_layer.schema import Persona, json_schema

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def test_load_sample_personas():
    personas = load_personas_dir(PERSONAS_DIR)
    assert set(personas) == {"tutor-haru", "assistant-rei"}
    haru = personas["tutor-haru"]
    assert haru.name == "春野ハル"
    assert haru.voice.enabled
    assert haru.voice.providers["voicevox"]["speaker_id"] == 8


def test_minimal_persona_uses_defaults():
    p = loads("id: mini\nname: ミニ\n")
    assert p.language == "ja"
    assert p.personality.formality.value == "polite"
    assert p.voice.pitch == 1.0
    assert p.voice_language() == "ja-JP"


def test_voice_language_derivation():
    p = loads("id: en1\nname: En\nlanguage: en\n")
    assert p.voice_language() == "en-US"
    p2 = loads("id: en2\nname: En\nlanguage: en\nvoice:\n  language: en-GB\n")
    assert p2.voice_language() == "en-GB"


def test_unknown_key_rejected():
    with pytest.raises(PersonaLoadError, match="スキーマ検証"):
        loads("id: x\nname: X\ntypo_key: 1\n")


def test_invalid_id_rejected():
    with pytest.raises(PersonaLoadError):
        loads("id: 'Bad ID!'\nname: X\n")


def test_pitch_range_validated():
    with pytest.raises(PersonaLoadError):
        loads("id: x\nname: X\nvoice:\n  pitch: 9.0\n")


def test_yaml_json_roundtrip(tmp_path):
    original = load_persona(PERSONAS_DIR / "tutor_haru.yaml")
    json_path = tmp_path / "haru.json"
    yaml_path = tmp_path / "haru.yaml"
    save_persona(original, json_path)
    save_persona(original, yaml_path)
    assert load_persona(json_path) == original
    assert load_persona(yaml_path) == original


def test_duplicate_id_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text("id: dup\nname: A\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("id: dup\nname: B\n", encoding="utf-8")
    with pytest.raises(PersonaLoadError, match="重複"):
        load_personas_dir(tmp_path)


def test_json_schema_exportable():
    schema = json_schema()
    assert schema["title"] == "Persona"
    assert "id" in schema["required"]
