"""設定テーブルのローダ。

§5.1 の文言表・§5.3 の prosody 表・§8.1 の表情マップ・§11.6 の調停パラメータは
コードではなく YAML テーブルとして持つ（§8.1・§17「テーブル駆動」要件）。
これらはランタイムの一部であり、移植パッケージには含めない（§10.3）。
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

import yaml


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    text = (resources.files(__package__) / f"{name}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def style_prompts() -> dict[str, dict[int, str]]:
    return load("style_prompts")


def prosody() -> dict[str, Any]:
    return load("prosody")


def expressions() -> dict[str, Any]:
    return load("expressions")


def arbiter() -> dict[str, Any]:
    return load("arbiter")


def meta_templates() -> dict[str, dict[str, list[str]]]:
    return load("meta_templates")
