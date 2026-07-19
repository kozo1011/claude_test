"""PersonaBreeder（§12): 人格の交配。

- ランダム性は生成時に1回だけ効く（§2.5）。同じ親 × 同じ seed → 同じ子（§12.1）
- style は一様交叉 + 突然変異（§12.2）。単純平均は禁止（子が中央値に収束する）
- anchor は要素ごとに演算が異なる（§12.3）
- メモリー・familiarity・Binding・assets の新規生成は継承しない（§12.4）
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .models import AXES, MAX_REFUSAL_LINES, Anchor, Lineage, Persona, Style


class BreedError(Exception):
    pass


class RefusalOverflowError(BreedError):
    """refusalLines の和集合が上限10件を超えた（§12.6）。管理者の選別が必要。"""


@dataclass
class BreedResult:
    child: Persona
    warnings: list[str] = field(default_factory=list)


# 破綻ではないが極端な組み合わせ（§12.7: 警告のみ。禁止しない）
_EXTREME_COMBOS = [
    (
        lambda s: s.distance == 0 and s.playfulness >= 3,
        "distance=0（最敬体）と playfulness>=3（強い遊び）の組み合わせです",
    ),
    (
        lambda s: s.affect == 0 and s.playfulness >= 3,
        "affect=0（平板）と playfulness>=3（強い遊び）の組み合わせです",
    ),
]


class PersonaBreeder:
    def breed(
        self,
        parent_a: Persona,
        parent_b: Persona,
        seed: int | None = None,
        mutation_rate: float = 0.15,
    ) -> BreedResult:
        if parent_a.id == parent_b.id:
            raise BreedError("同一人格同士は交配できません")
        if seed is None:
            seed = time.time_ns() % (2**31)  # 自動生成。必ず lineage に記録される
        rng = random.Random(seed)

        style = self._breed_style(parent_a.style, parent_b.style, rng, mutation_rate)
        anchor = self._breed_anchor(parent_a.anchor, parent_b.anchor, rng)

        # assets は自動生成できない。片親から継承する（§12.4）
        assets_parent = parent_a if rng.random() < 0.5 else parent_b
        name_first = parent_a if rng.random() < 0.5 else parent_b
        name_second = parent_b if name_first is parent_a else parent_a
        display_name = (
            name_first.display_name[: max(1, (len(name_first.display_name) + 1) // 2)]
            + name_second.display_name[len(name_second.display_name) // 2 :]
        )

        child = Persona(
            id=f"{parent_a.id}-x-{parent_b.id}-s{seed}",
            display_name=display_name,
            anchor=anchor,
            style=style,
            assets=assets_parent.assets.model_copy(deep=True),
            lineage=Lineage(
                parents=(parent_a.id, parent_b.id),
                generation=max(parent_a.generation(), parent_b.generation()) + 1,
                seed=seed,
            ),
        )
        warnings = [
            message for check, message in _EXTREME_COMBOS if check(child.style)
        ]
        self._validate(child)
        return BreedResult(child=child, warnings=warnings)

    # ---- style: 一様交叉 + 突然変異（§12.2） ----

    @staticmethod
    def _breed_style(
        a: Style, b: Style, rng: random.Random, mutation_rate: float
    ) -> Style:
        values: dict[str, int] = {}
        for axis in AXES:
            v = getattr(a, axis) if rng.random() < 0.5 else getattr(b, axis)
            if rng.random() < mutation_rate:
                v += -1 if rng.random() < 0.5 else 1
            values[axis] = max(0, min(4, v))
        return Style(**values)

    # ---- anchor: 要素ごとの演算（§12.3） ----

    @staticmethod
    def _breed_anchor(a: Anchor, b: Anchor, rng: random.Random) -> Anchor:
        # 一人称・二人称はセットで片親から丸ごと（破綻した組み合わせの防止）
        person_parent = a if rng.random() < 0.5 else b
        # verbalTics は各親から 1〜2個をサンプリングし、計2〜3個に
        tics: list[str] = []
        for parent in (a, b):
            pool = list(parent.verbal_tics)
            if not pool:
                continue
            take = min(len(pool), rng.randint(1, 2))
            tics.extend(rng.sample(pool, take))
        seen: set[str] = set()
        tics = [t for t in tics if not (t in seen or seen.add(t))][:3]
        # refusalLines は和集合（重複除去）。上限超過は生成を止める（§12.6）
        refusals = list(dict.fromkeys([*a.refusal_lines, *b.refusal_lines]))
        if len(refusals) > MAX_REFUSAL_LINES:
            raise RefusalOverflowError(
                f"refusalLines の和集合が {len(refusals)} 件で上限 "
                f"{MAX_REFUSAL_LINES} 件を超えました。管理者による選別が必要です"
            )
        note_parent = a if rng.random() < 0.5 else b
        return Anchor(
            first_person=person_parent.first_person,
            second_person=person_parent.second_person,
            verbal_tics=tics,
            refusal_lines=refusals,
            free_note=note_parent.free_note,
        )

    # ---- 生成後の検証（§12.7 の構造検査部分） ----

    @staticmethod
    def _validate(child: Persona) -> None:
        if not child.anchor.first_person or not child.anchor.second_person:
            raise BreedError("生成された子の一人称/二人称が空です。seed を変えて再生成してください")

    def population(
        self,
        parent_a: Persona,
        parent_b: Persona,
        count: int,
        base_seed: int = 0,
        mutation_rate: float = 0.15,
    ) -> list[Persona]:
        """seed を変えた子を count 体生成する。
        受け入れ基準3・4・9 のテストデータ生成器として使う（§12.8）。"""
        return [
            self.breed(parent_a, parent_b, seed=base_seed + i, mutation_rate=mutation_rate).child
            for i in range(count)
        ]
