from pathlib import Path

from persona_layer.compiler import compile_style_prompt, compile_system_prompt
from persona_layer.loader import load_persona, loads

PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def test_japanese_prompt_contains_key_sections():
    persona = load_persona(PERSONAS_DIR / "tutor_haru.yaml")
    prompt = compile_system_prompt(persona)
    assert "あなたは「春野ハル」です。" in prompt
    assert "## 人格" in prompt
    assert "## 話し方" in prompt
    assert "いい質問ですね" in prompt
    assert "## してはいけないこと" in prompt
    assert "AIであると認める" in prompt
    assert "## 応答例" in prompt


def test_prompt_is_deterministic():
    persona = load_persona(PERSONAS_DIR / "tutor_haru.yaml")
    assert compile_system_prompt(persona) == compile_system_prompt(persona)


def test_examples_can_be_excluded():
    persona = load_persona(PERSONAS_DIR / "tutor_haru.yaml")
    prompt = compile_system_prompt(persona, include_examples=False)
    assert "## 応答例" not in prompt


def test_english_template():
    persona = loads(
        "id: en-bot\nname: Sage\nlanguage: en\n"
        "personality:\n  traits: [calm]\n"
    )
    prompt = compile_system_prompt(persona)
    assert 'You are "Sage".' in prompt
    assert "## Personality" in prompt
    assert "calm" in prompt


def test_plain_formatting_adds_voice_note():
    persona = loads("id: x\nname: X\n")
    assert "音声で読み上げられる" in compile_system_prompt(persona)
    persona_md = loads("id: y\nname: Y\nspeech_style:\n  formatting: markdown\n")
    assert "音声で読み上げられる" not in compile_system_prompt(persona_md)


def test_style_prompt_for_relay_mode():
    persona = load_persona(PERSONAS_DIR / "tutor_haru.yaml")
    prompt = compile_style_prompt(persona)
    assert "書き換えてください" in prompt
    assert "春野ハル" in prompt
