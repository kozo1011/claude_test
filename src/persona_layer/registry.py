"""PersonaRegistry（§3.1, §11.1）: 人格定義の CRUD・検証・プリベイク・バージョン管理。

- 編集は新バージョンを作る。稼働中のインスタンスは自分が掴んだ版を保持し続ける
- 削除は論理削除（tombstone）。物理削除すると lineage の参照が切れ家系図が壊れる（§12.5）
- lineage.parents の逆引きインデックスを持つ（§12.5）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .meta_speech import MetaSpeech, TemplateBaker
from .models import Persona, PersonaBinding


class RegistryError(Exception):
    pass


@dataclass
class PersonaRecord:
    versions: list[Persona] = field(default_factory=list)  # index 0 が v1
    deleted: bool = False
    updated_at: float = 0.0

    @property
    def latest(self) -> Persona:
        return self.versions[-1]

    @property
    def version(self) -> int:
        return len(self.versions)


class PersonaRegistry:
    def __init__(self, baker: TemplateBaker | None = None) -> None:
        self._records: dict[str, PersonaRecord] = {}
        self._bindings: dict[tuple[str, str], PersonaBinding] = {}
        self._children: dict[str, set[str]] = {}  # 親id → 子idの集合（逆引き）
        self._baked: dict[str, dict[str, list[str]]] = {}
        self._baker = baker

    # ---- Persona CRUD ----

    def create(self, persona: Persona) -> Persona:
        if persona.id in self._records:
            raise RegistryError(f"人格 id が重複しています: {persona.id}")
        if persona.lineage is not None:
            for parent_id in persona.lineage.parents:
                if parent_id not in self._records:
                    raise RegistryError(
                        f"lineage の親が登録されていません: {parent_id}"
                    )
        record = PersonaRecord(versions=[persona], updated_at=time.time())
        self._records[persona.id] = record
        if persona.lineage is not None:
            for parent_id in persona.lineage.parents:
                self._children.setdefault(parent_id, set()).add(persona.id)
        self._prebake(persona)
        return persona

    def get(self, persona_id: str, version: int | None = None) -> Persona:
        record = self._require(persona_id)
        if record.deleted and version is None:
            raise RegistryError(f"人格は削除済みです: {persona_id}")
        if version is None:
            return record.latest
        if not 1 <= version <= record.version:
            raise RegistryError(f"バージョンが存在しません: {persona_id} v{version}")
        return record.versions[version - 1]

    def update(self, persona_id: str, persona: Persona) -> tuple[Persona, int]:
        """編集は新バージョンを作る（§11.1）。旧版は残り、稼働中インスタンスに影響しない。"""
        record = self._require(persona_id)
        if record.deleted:
            raise RegistryError(f"削除済みの人格は編集できません: {persona_id}")
        if persona.id != persona_id:
            raise RegistryError("id は変更できません")
        if persona.lineage != record.latest.lineage:
            raise RegistryError("lineage は編集できません（系譜の改変防止・§12.5）")
        record.versions.append(persona)
        record.updated_at = time.time()
        self._prebake(persona)  # 編集後はプリベイクを再実行（§11.1）
        return persona, record.version

    def delete(self, persona_id: str) -> None:
        """論理削除（tombstone・§12.5）。レコードと全バージョンは残る。"""
        self._require(persona_id).deleted = True

    def restore(self, persona_id: str) -> None:
        self._require(persona_id).deleted = False

    def list(self, include_deleted: bool = False) -> list[tuple[Persona, bool]]:
        """(最新版, deleted) の一覧。削除済みは家系図でグレー表示するため含められる。"""
        return [
            (record.latest, record.deleted)
            for record in self._records.values()
            if include_deleted or not record.deleted
        ]

    def is_deleted(self, persona_id: str) -> bool:
        return self._require(persona_id).deleted

    def version_of(self, persona_id: str) -> int:
        return self._require(persona_id).version

    def children_of(self, persona_id: str) -> list[str]:
        """逆引きインデックスによる子の列挙（§12.5）。"""
        return sorted(self._children.get(persona_id, set()))

    def _require(self, persona_id: str) -> PersonaRecord:
        record = self._records.get(persona_id)
        if record is None:
            raise RegistryError(f"人格が見つかりません: {persona_id}")
        return record

    # ---- プリベイク（§7.2） ----

    def _prebake(self, persona: Persona) -> None:
        meta = MetaSpeech(persona, self._baker)
        self._baked[persona.id] = {
            kind: meta.templates(kind)
            for kind in ("backchannel", "filler", "progress", "handoff", "apology", "handover")
        }

    def baked_templates(self, persona_id: str) -> dict[str, list[str]]:
        return self._baked[persona_id]

    # ---- Binding CRUD（§4.3） ----

    def bind(self, binding: PersonaBinding) -> PersonaBinding:
        self._require(binding.persona_id)
        self._bindings[(binding.persona_id, binding.agent_id)] = binding
        return binding

    def binding(self, persona_id: str, agent_id: str) -> PersonaBinding:
        try:
            return self._bindings[(persona_id, agent_id)]
        except KeyError:
            raise RegistryError(
                f"Binding が見つかりません: {persona_id} × {agent_id}"
            ) from None

    def bindings(self, persona_id: str | None = None) -> list[PersonaBinding]:
        return [
            b
            for b in self._bindings.values()
            if persona_id is None or b.persona_id == persona_id
        ]
