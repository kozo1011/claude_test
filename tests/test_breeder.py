"""§12 Breed: 再現性（基準8）・多様性（基準9）・anchor 演算・系譜。"""

import statistics

import pytest

from persona_layer.breeder import PersonaBreeder, RefusalOverflowError
from persona_layer.models import AXES

from .conftest import make_persona


@pytest.fixture
def breeder():
    return PersonaBreeder()


def low_high_parents():
    a = make_persona(
        id="low", name="低", tics=["〜です", "〜ます"],
        distance=0, density=0, assertion=0, initiative=0, affect=0, playfulness=0,
    )
    b = make_persona(
        id="high", name="高", first_person="俺", second_person="あんた",
        tics=["〜だぜ", "〜じゃん"],
        distance=4, density=4, assertion=4, initiative=4, affect=4, playfulness=4,
    )
    return a, b


def test_breed_reproducibility_criterion_8(breeder):
    """受け入れ基準8: 同一の親 × 同一 seed → 常に同一の子。"""
    a, b = low_high_parents()
    child1 = breeder.breed(a, b, seed=42).child
    child2 = breeder.breed(a, b, seed=42).child
    assert child1 == child2


def test_breed_diversity_criterion_9(breeder):
    """受け入れ基準9: seed を変えて50体。各軸の分散が親の分散と同等以上。
    単純平均で実装すると必ずここで落ちる（§12.2）。"""
    a, b = low_high_parents()
    children = breeder.population(a, b, 50, base_seed=0)
    for axis in AXES:
        parent_values = [getattr(a.style, axis), getattr(b.style, axis)]
        parent_var = statistics.pvariance(parent_values)  # {0,4} → 4.0
        child_values = [getattr(c.style, axis) for c in children]
        assert statistics.pvariance(child_values) >= parent_var * 0.8, axis
        # 中央値(2)への収束が起きていないこと
        assert any(v <= 1 for v in child_values), axis
        assert any(v >= 3 for v in child_values), axis


def test_child_axes_come_from_parents_or_one_step_mutation(breeder):
    a, b = low_high_parents()
    for child in breeder.population(a, b, 30, base_seed=100):
        for axis in AXES:
            v = getattr(child.style, axis)
            assert v in {0, 1, 3, 4}, f"{axis}={v} は交叉±1変異では出ない値"


def test_first_second_person_inherited_as_set(breeder):
    """§12.3: 一人称・二人称はセットで片親から。「わたくし×お前」を作らない。"""
    a, b = low_high_parents()
    for child in breeder.population(a, b, 30, base_seed=200):
        pair = (child.anchor.first_person, child.anchor.second_person)
        assert pair in {("私", "あなた"), ("俺", "あんた")}


def test_verbal_tics_mixed_from_both_parents(breeder):
    a, b = low_high_parents()
    children = breeder.population(a, b, 30, base_seed=300)
    pool_a = set(a.anchor.verbal_tics)
    pool_b = set(b.anchor.verbal_tics)
    for child in children:
        tics = set(child.anchor.verbal_tics)
        assert 2 <= len(tics) <= 3
        assert tics <= pool_a | pool_b
    # 混成（両親由来の混在）が実際に起きること
    assert any(
        set(c.anchor.verbal_tics) & pool_a and set(c.anchor.verbal_tics) & pool_b
        for c in children
    )


def test_refusal_lines_union(breeder):
    a = make_persona(id="a", refusals=["r1", "r2"])
    b = make_persona(id="b", refusals=["r2", "r3"])
    child = breeder.breed(a, b, seed=1).child
    assert child.anchor.refusal_lines == ["r1", "r2", "r3"]


def test_refusal_overflow_stops_generation(breeder):
    """§12.6: 和集合が上限10件を超えたら生成を止めて管理者に選別を求める。"""
    a = make_persona(id="a", refusals=[f"a{i}" for i in range(6)])
    b = make_persona(id="b", refusals=[f"b{i}" for i in range(6)])
    with pytest.raises(RefusalOverflowError):
        breeder.breed(a, b, seed=1)


def test_lineage_recorded_with_seed(breeder):
    a, b = low_high_parents()
    child = breeder.breed(a, b, seed=777).child
    assert child.lineage is not None
    assert child.lineage.parents == ("low", "high")
    assert child.lineage.seed == 777
    assert child.lineage.generation == 1
    grandchild = breeder.breed(child, a, seed=778).child
    assert grandchild.lineage.generation == 2


def test_auto_seed_recorded(breeder):
    a, b = low_high_parents()
    child = breeder.breed(a, b).child  # seed 省略時も必ず記録される（§12.1）
    assert child.lineage.seed is not None
    assert breeder.breed(a, b, seed=child.lineage.seed).child == child


def test_extreme_combo_warns_but_not_forbidden(breeder):
    """§12.7: 極端な組み合わせは警告のみ。禁止しない。"""
    a = make_persona(id="a", distance=0, playfulness=4)
    b = make_persona(id="b", first_person="僕", second_person="君",
                     distance=0, playfulness=4)
    result = breeder.breed(a, b, seed=5, mutation_rate=0.0)
    assert result.warnings
    assert result.child is not None


def test_memory_familiarity_binding_not_inherited(breeder):
    """§12.4: 子は未接続・メモリーなし・familiarity 0 で生まれる。"""
    a, b = low_high_parents()
    child = breeder.breed(a, b, seed=9).child
    data = child.model_dump()
    assert "memory" not in data and "familiarity" not in data
    assert "expertise" not in data  # Binding は Persona に含まれない
