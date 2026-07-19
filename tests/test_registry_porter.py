"""§11.1 Registry（バージョン管理・tombstone）と §10 Porter（移植・基準7）。"""

import json
import zipfile
from io import BytesIO

import pytest

from persona_layer.breeder import PersonaBreeder
from persona_layer.composers import compose_prompt, compose_prosody
from persona_layer.models import PersonaBinding
from persona_layer.porter import MANIFEST_MAX_BYTES, PersonaPorter, PortError
from persona_layer.registry import PersonaRegistry, RegistryError

from .conftest import make_persona


@pytest.fixture
def registry():
    return PersonaRegistry()


def test_edit_creates_new_version_old_kept(registry):
    """§11.1: 編集は新バージョンを作る。稼働中インスタンスは旧版を保持できる。"""
    v1 = make_persona(density=1)
    registry.create(v1)
    v2 = v1.model_copy(update={"style": v1.style.model_copy(update={"density": 3})})
    _, version = registry.update(v1.id, v2)
    assert version == 2
    assert registry.get(v1.id).style.density == 3
    assert registry.get(v1.id, version=1).style.density == 1  # 旧版は残る


def test_prebake_runs_on_create_and_update(registry):
    persona = make_persona()
    registry.create(persona)
    baked = registry.baked_templates(persona.id)
    assert baked["filler"]


def test_delete_is_tombstone(registry):
    """§12.5: 物理削除しない。レコードは残り、家系図が壊れない。"""
    a = make_persona(id="a")
    b = make_persona(id="b", first_person="僕", second_person="君")
    registry.create(a)
    registry.create(b)
    child = PersonaBreeder().breed(a, b, seed=1).child
    registry.create(child)
    registry.delete("a")
    with pytest.raises(RegistryError):
        registry.get("a")  # 通常取得は不可
    listed = registry.list(include_deleted=True)  # 家系図用に列挙は可能
    assert any(p.id == "a" and deleted for p, deleted in listed)
    assert registry.get(child.id).lineage.parents == ("a", "b")  # 参照は生きている
    assert registry.children_of("a") == [child.id]  # 逆引きインデックス（§12.5）


def test_lineage_cannot_be_edited(registry):
    a = make_persona(id="a")
    b = make_persona(id="b", first_person="僕", second_person="君")
    registry.create(a)
    registry.create(b)
    child = PersonaBreeder().breed(a, b, seed=1).child
    registry.create(child)
    tampered = child.model_copy(update={"lineage": None})
    with pytest.raises(RegistryError, match="lineage"):
        registry.update(child.id, tampered)


def test_binding_crud(registry):
    persona = make_persona()
    registry.create(persona)
    binding = PersonaBinding(
        persona_id=persona.id, agent_id="agent-1", expertise=["投資"]
    )
    registry.bind(binding)
    assert registry.binding(persona.id, "agent-1").expertise == ["投資"]
    with pytest.raises(RegistryError):
        registry.binding(persona.id, "agent-x")


# ---- Porter（§10） ----

def test_package_structure(tmp_path, sage):
    sprites = tmp_path / "sprites"
    sprites.mkdir()
    for name in ("neutral_0.webp", "pleased_2.webp"):
        (sprites / name).write_bytes(b"webp-dummy")
    data = PersonaPorter().export_bytes(sage, sprites_dir=sprites)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "voice.json" in names
        assert "sprites/neutral_0.webp" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["schemaVersion"] == "1.0"
        assert len(zf.read("manifest.json")) < MANIFEST_MAX_BYTES  # §14
        voice = json.loads(zf.read("voice.json"))
        assert "vendorNeutral" in voice  # ベンダー非依存の記述（§10.3）


def test_port_identity_criterion_7(sage):
    """受け入れ基準7: export → import した人格が同一の文体・prosody を出す。"""
    data = PersonaPorter().export_bytes(sage)
    registry = PersonaRegistry()
    imported, _ = PersonaPorter(registry).import_bytes(data)
    assert imported == sage
    assert compose_prompt(imported) == compose_prompt(sage)
    assert compose_prosody(imported, 0.3) == compose_prosody(sage, 0.3)


def test_import_rejects_schema_mismatch(sage):
    data = PersonaPorter().export_bytes(sage)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    manifest["schemaVersion"] = "9.9"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    with pytest.raises(PortError, match="互換性"):
        PersonaPorter().import_bytes(buffer.getvalue())


def test_package_excludes_memory_and_binding(sage):
    """§10.1: メモリー・Binding は含まれない。"""
    data = PersonaPorter().export_bytes(sage)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        manifest = zf.read("manifest.json").decode("utf-8")
    assert "expertise" not in manifest
    assert "memory" not in manifest.lower()
    assert "familiarity" not in manifest.lower()


def test_import_after_bind_gives_same_voice_expressions(sage):
    """§10.2: インポート直後は口調・声・表情が同一で、得意分野とメモリーだけ空。"""
    registry = PersonaRegistry()
    imported, voice = PersonaPorter(registry).import_bytes(
        PersonaPorter().export_bytes(sage)
    )
    assert imported.assets == sage.assets
    assert voice["voiceId"] == sage.assets.voice_id
    assert registry.bindings(imported.id) == []  # 未接続で生まれる
    assert registry.baked_templates(imported.id)  # プリベイク済み（§10.2 手順5）


def test_import_without_parents_drops_lineage(sage, clown):
    child = PersonaBreeder().breed(sage, clown, seed=3).child
    data = PersonaPorter().export_bytes(child)
    registry = PersonaRegistry()  # 親のいない移植先
    imported, _ = PersonaPorter(registry).import_bytes(data)
    assert imported.lineage is None  # 参照切れの系譜は持ち込まない
