"""Persona Layer: AIエージェントと人間のあいだの移植可能な人格インターフェース層。"""

from .compiler import compile_style_prompt, compile_system_prompt
from .loader import PersonaLoadError, load_persona, load_personas_dir, save_persona
from .runtime import PersonaRuntime, Session
from .schema import SCHEMA_VERSION, Persona

__version__ = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "Persona",
    "PersonaLoadError",
    "PersonaRuntime",
    "Session",
    "compile_style_prompt",
    "compile_system_prompt",
    "load_persona",
    "load_personas_dir",
    "save_persona",
]
