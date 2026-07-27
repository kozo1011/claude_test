"""Persona Layer: AI Agent インターフェース用 人格レイヤー（開発指示書 v0.4 準拠）。

Agent 出力に声・文体・表情を付与する中間レイヤー。タスク回答の内容は
生成も書き換えもしない（§1.3, §2.1）。
"""

from .agent import (
    Agent,
    AnthropicAgent,
    EchoAgent,
    GeminiAgent,
    OpenAICompatibleAgent,
    ScriptedAgent,
    build_agent,
    make_agent,
)
from .breeder import BreedResult, PersonaBreeder, RefusalOverflowError
from .config import AppConfig, ConfigError, LLMConfig, load_config
from .bridge import AgentBridge, BridgeResult
from .composers import Prosody, compose_prompt, compose_prosody, effective_distance
from .expression import ExpressionMachine
from .memory import PersonaMemory
from .meta_speech import MetaSpeech, RuleBasedBaker
from .models import (
    SCHEMA_VERSION,
    Anchor,
    Assets,
    Lineage,
    MemoryRecord,
    Persona,
    PersonaBinding,
    PersonaState,
    Style,
)
from .porter import PersonaPorter, PortError
from .presets import PRESETS, from_preset, preset_names
from .registry import PersonaRegistry, RegistryError
from .room import Room, RoomBus, RoomEvent, PersonaInstance, SpeechArbiter
from .state import FamiliarityStore, StateEngine
from .tts import NullTTS, TTSAdapter

__version__ = "0.4.0"

__all__ = [
    "SCHEMA_VERSION",
    "Agent",
    "AgentBridge",
    "Anchor",
    "AnthropicAgent",
    "AppConfig",
    "Assets",
    "BreedResult",
    "BridgeResult",
    "ConfigError",
    "EchoAgent",
    "ExpressionMachine",
    "FamiliarityStore",
    "GeminiAgent",
    "LLMConfig",
    "OpenAICompatibleAgent",
    "Lineage",
    "MemoryRecord",
    "MetaSpeech",
    "NullTTS",
    "PRESETS",
    "Persona",
    "PersonaBinding",
    "PersonaBreeder",
    "PersonaInstance",
    "PersonaMemory",
    "PersonaPorter",
    "PersonaRegistry",
    "PersonaState",
    "PortError",
    "Prosody",
    "RefusalOverflowError",
    "RegistryError",
    "Room",
    "RoomBus",
    "RoomEvent",
    "RuleBasedBaker",
    "ScriptedAgent",
    "SpeechArbiter",
    "StateEngine",
    "Style",
    "TTSAdapter",
    "build_agent",
    "compose_prompt",
    "compose_prosody",
    "effective_distance",
    "from_preset",
    "load_config",
    "make_agent",
    "preset_names",
]
