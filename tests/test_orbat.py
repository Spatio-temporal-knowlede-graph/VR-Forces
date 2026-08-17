"""편제 도출 — 원문에 편제 언급이 0건이라 (진영 × 역할 × 초기배치)에서 만든다.

실측 기대치는 2026-08-17 build/events/battle.jsonl(객체 335, task 가능 328)
기준이다. 숫자가 틀어지면 편제가 아니라 입력이 바뀐 것이니 둘 다 본다.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.parser import Event
from vtmak.registry import ClassMap, build_registry

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"


@pytest.fixture(scope="module")
def registry():
    evs = [Event(**{k: v for k, v in json.loads(l).items()
                    if k != "source_line"})
           for l in open(ROOT / "build" / "events" / "battle.jsonl",
                         encoding="utf-8")]
    cm = ClassMap.load(CFG / "entity_class_map.csv")
    layout = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    return build_registry(evs, cm, layout.static_ids())


@pytest.fixture(scope="module")
def orbat(registry):
    return build_orbat(registry, OrbatConfig.load(CFG / "orbat.json"))


def test_echelon_counts(orbat):
    """대대 2 · 중대 13 · 소대 52 = 부대 67. 설계가 약속한 수다."""
    got = Counter(u.echelon for u in orbat.units())
    assert got == {"소대": 52, "중대": 13, "대대": 2}


def test_every_taskable_entity_has_a_platoon(orbat, registry):
    """고아가 하나라도 있으면 .oob 조직 트리가 안 닫힌다."""
    taskable = [o for o, d in registry.items() if d.taskable]
    missing = [o for o in taskable if orbat.platoon_of(o) is None]
    assert missing == []


def test_chain_closes_at_battalion(orbat):
    """소대 → (중대) → 대대. 깊이는 2단과 3단이 섞인다."""
    for u in orbat.units():
        if u.echelon != "소대":
            continue
        chain = orbat.chain(u.unit_id)
        assert orbat.get(chain[-1]).echelon == "대대", u.unit_id
        assert len(chain) in (2, 3), (u.unit_id, chain)


def test_markings_fit_dis(orbat):
    marks = [u.marking for u in orbat.units()]
    assert len(marks) == len(set(marks))
    for m in marks:
        assert m.isascii() and 0 < len(m.encode("ascii")) <= 11, m


def test_deterministic(registry):
    cfg = OrbatConfig.load(CFG / "orbat.json")
    a = [(u.unit_id, u.members) for u in build_orbat(registry, cfg).units()]
    b = [(u.unit_id, u.members) for u in build_orbat(registry, cfg).units()]
    assert a == b


def test_unknown_role_is_loud(registry):
    """역할이 표에 없으면 조용히 빠지면 안 된다 — 그 객체가 고아가 된다."""
    cfg = OrbatConfig.load(CFG / "orbat.json")
    cfg.function_of_role.pop("방어 보병")
    with pytest.raises(KeyError):
        build_orbat(registry, cfg)


def test_task_organization_targets_exist(orbat):
    ids = {u.unit_id for u in orbat.units()}
    for a, b in orbat.supports() + orbat.reinforces():
        assert a in ids, a
        assert b in ids, b
