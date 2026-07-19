import json
from pathlib import Path

import pytest
import yaml

from persona_layer.exporters import export, formats
from persona_layer.loader import load_persona
from persona_layer.schema import Persona

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


@pytest.fixture
def persona():
    return load_persona(PERSONAS_DIR / "tutor_haru.yaml")


def test_available_formats(persona):
    assert {"system-prompt", "json", "yaml", "anthropic", "openai", "markdown"} <= set(
        formats()
    )


def test_unknown_format_raises(persona):
    with pytest.raises(ValueError, match="未知のエクスポート形式"):
        export(persona, "nope")


def test_system_prompt_export(persona):
    result = export(persona, "system-prompt")
    assert "春野ハル" in result.text
    assert result.suggested_filename == "tutor-haru.system.txt"


def test_canonical_json_roundtrip(persona):
    result = export(persona, "json")
    restored = Persona.model_validate(json.loads(result.text))
    assert restored == persona


def test_canonical_yaml_roundtrip(persona):
    result = export(persona, "yaml")
    restored = Persona.model_validate(yaml.safe_load(result.text))
    assert restored == persona


def test_anthropic_export_is_valid_request_body(persona):
    body = json.loads(export(persona, "anthropic").text)
    assert body["model"].startswith("claude-")
    assert "春野ハル" in body["system"]
    assert body["messages"] == []


def test_openai_export_has_system_message(persona):
    body = json.loads(export(persona, "openai").text)
    assert body["messages"][0]["role"] == "system"
    assert "春野ハル" in body["messages"][0]["content"]


def test_markdown_sheet(persona):
    text = export(persona, "markdown").text
    assert "# ペルソナ: 春野ハル" in text
    assert "## システムプロンプト" in text
    assert "## 初回挨拶" in text
