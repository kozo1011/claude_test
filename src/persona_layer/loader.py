"""ペルソナ定義ファイル（YAML/JSON）の読み書き。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import Persona


class PersonaLoadError(Exception):
    """定義ファイルが読めない・検証に失敗したときに送出される。"""


def loads(text: str, fmt: str = "yaml") -> Persona:
    try:
        if fmt == "json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise PersonaLoadError(f"パースに失敗しました: {exc}") from exc
    if not isinstance(data, dict):
        raise PersonaLoadError("ペルソナ定義はマッピング（キーと値の組）である必要があります")
    try:
        return Persona.model_validate(data)
    except ValidationError as exc:
        lines = [
            f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        raise PersonaLoadError("スキーマ検証に失敗しました:\n" + "\n".join(lines)) from exc


def load_persona(path: str | Path) -> Persona:
    path = Path(path)
    if not path.exists():
        raise PersonaLoadError(f"ファイルが見つかりません: {path}")
    fmt = "json" if path.suffix.lower() == ".json" else "yaml"
    return loads(path.read_text(encoding="utf-8"), fmt=fmt)


def save_persona(persona: Persona, path: str | Path) -> None:
    path = Path(path)
    data = persona.model_dump(mode="json")
    if path.suffix.lower() == ".json":
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    else:
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def load_personas_dir(directory: str | Path) -> dict[str, Persona]:
    """ディレクトリ内の *.yaml / *.yml / *.json をすべて読み込み、id で引ける辞書を返す。"""
    directory = Path(directory)
    personas: dict[str, Persona] = {}
    for path in sorted(directory.glob("*")):
        if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        persona = load_persona(path)
        if persona.id in personas:
            raise PersonaLoadError(f"ペルソナ id が重複しています: {persona.id} ({path})")
        personas[persona.id] = persona
    return personas
