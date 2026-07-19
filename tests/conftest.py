import pytest

from persona_layer.models import Anchor, Persona, Style
from persona_layer.presets import from_preset


@pytest.fixture
def sage() -> Persona:
    return from_preset("賢者", "sage", "紫苑")


@pytest.fixture
def clown() -> Persona:
    return from_preset("道化", "clown", "トト")


@pytest.fixture
def caretaker() -> Persona:
    return from_preset("世話役", "caretaker", "楓")


@pytest.fixture
def artisan() -> Persona:
    return from_preset("職人", "artisan", "源")


def make_persona(
    id: str = "p1",
    name: str = "テスト",
    first_person: str = "私",
    second_person: str = "あなた",
    tics: list[str] | None = None,
    refusals: list[str] | None = None,
    **style,
) -> Persona:
    axes = dict(distance=1, density=2, assertion=2, initiative=2, affect=1, playfulness=1)
    axes.update(style)
    return Persona(
        id=id,
        display_name=name,
        anchor=Anchor(
            first_person=first_person,
            second_person=second_person,
            verbal_tics=tics if tics is not None else ["〜ですね"],
            refusal_lines=refusals or [],
        ),
        style=Style(**axes),
    )
