"""PersonaPorter（§10）: 人格パッケージのエクスポート／インポート。

パッケージ形式（§10.1）:
    <persona-id>.persona (zip)
      manifest.json   … Persona（§4.2）そのもの（camelCase・4KB未満）
      sprites/        … 表情スプライト18枚（あれば）
      voice.json      … voiceId とベンダー非依存の記述

- メモリー・Binding は含まれない（§10.1）
- §5.1 文言表・§5.3 prosody 表は受け入れ側ランタイムが持つ（§10.3）
- schemaVersion 不一致はインポート時に拒否（§10.3）
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .models import SCHEMA_VERSION, Persona
from .registry import PersonaRegistry

MANIFEST_MAX_BYTES = 4096  # §14


class PortError(Exception):
    pass


DEFAULT_VOICE_NEUTRAL = {
    "genderTendency": "neutral",   # 性別傾向
    "baseRate": "medium",          # 話速基準
    "register": "mid",             # 音域
}


class PersonaPorter:
    def __init__(self, registry: PersonaRegistry | None = None) -> None:
        self.registry = registry

    # ---- export ----

    def export_bytes(
        self,
        persona: Persona,
        sprites_dir: str | Path | None = None,
        voice_neutral: dict | None = None,
    ) -> bytes:
        manifest = json.dumps(
            persona.model_dump(by_alias=True, exclude_none=True),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        if len(manifest) >= MANIFEST_MAX_BYTES:
            raise PortError(
                f"manifest.json が {MANIFEST_MAX_BYTES} バイトを超えています"
                f"（{len(manifest)} バイト）"
            )
        voice = {
            "voiceId": persona.assets.voice_id,
            "vendorNeutral": voice_neutral or DEFAULT_VOICE_NEUTRAL,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest)
            zf.writestr(
                "voice.json",
                json.dumps(voice, ensure_ascii=False, indent=2),
            )
            if sprites_dir is not None:
                sprites = sorted(Path(sprites_dir).glob("*.webp"))
                for sprite in sprites:
                    zf.write(sprite, f"sprites/{sprite.name}")
        return buffer.getvalue()

    def export(
        self,
        persona: Persona,
        out_dir: str | Path = ".",
        sprites_dir: str | Path | None = None,
        voice_neutral: dict | None = None,
    ) -> Path:
        out = Path(out_dir) / f"{persona.id}.persona"
        out.write_bytes(self.export_bytes(persona, sprites_dir, voice_neutral))
        return out

    # ---- import ----

    def import_bytes(
        self, data: bytes, sprites_out: str | Path | None = None
    ) -> tuple[Persona, dict]:
        """パッケージを検証して (Persona, voice.json) を返す。
        registry があれば登録とプリベイク（§10.2 手順3・5）まで行う。
        Binding は含まれないため、管理者が別途 bind する（§10.2 手順4）。"""
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise PortError(f"パッケージを開けません: {exc}") from exc
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise PortError("manifest.json がありません")
        raw = json.loads(zf.read("manifest.json").decode("utf-8"))
        if raw.get("schemaVersion") != SCHEMA_VERSION:
            raise PortError(
                f"schemaVersion {raw.get('schemaVersion')!r} は"
                f"このランタイム（{SCHEMA_VERSION}）と互換性がありません"
            )
        # インポート先に lineage の親が居ない場合は系譜を外して受け入れる
        # （親のいない環境への移植は正当なユースケース）
        if self.registry is not None and raw.get("lineage"):
            parents = raw["lineage"].get("parents", [])
            known = {p.id for p, _ in self.registry.list(include_deleted=True)}
            if not all(parent in known for parent in parents):
                raw = {k: v for k, v in raw.items() if k != "lineage"}
        persona = Persona.model_validate(raw)
        voice = (
            json.loads(zf.read("voice.json").decode("utf-8"))
            if "voice.json" in names
            else {}
        )
        if sprites_out is not None:
            out = Path(sprites_out)
            out.mkdir(parents=True, exist_ok=True)
            for name in names:
                if name.startswith("sprites/") and name.endswith(".webp"):
                    (out / Path(name).name).write_bytes(zf.read(name))
        if self.registry is not None:
            self.registry.create(persona)  # 登録と同時にプリベイク実行
        return persona, voice

    def import_file(
        self, path: str | Path, sprites_out: str | Path | None = None
    ) -> tuple[Persona, dict]:
        return self.import_bytes(Path(path).read_bytes(), sprites_out)
