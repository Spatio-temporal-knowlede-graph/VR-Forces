from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.plan import balanced
from vtmak.scnx.spec import build_spec

ROOT = Path(__file__).resolve().parents[1]


def _build():
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(
        (ROOT / "scenario_original" / "scenario_v3.txt").read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    return build_spec(res.events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"),
                      DisCatalog.load(cfg / "dis_catalog.csv"),
                      WeaponRanges.load(cfg / "weapon_ranges.csv"),
                      scenario_id="battle")


@pytest.fixture(scope="module")
def spec():
    return _build()


def test_entities_exclude_static_objects(spec):
    ids = {e.object_id for e in spec.entities}
    assert len(ids) == 328
    assert "EN-FP-001" not in ids
    assert "OBJ-009" not in ids


def test_every_entity_has_dis_and_nonzero_coord(spec):
    for e in spec.entities:
        assert e.dis is not None, e.object_id
        assert not e.coord.is_zero(), e.object_id


def test_entities_sharing_a_location_are_jittered(spec):
    at = [e for e in spec.entities if e.object_id.startswith("FR-INF-")][:20]
    assert len({e.coord.as_tuple() for e in at}) == len(at)


def test_only_unclassified_models_lack_a_pln(spec):
    """설계 스펙 §8.3 — 무기체계 미확정 2종만 태스크가 없어야 한다."""
    empty = sorted(oid for oid, steps in spec.entity_plans.items()
                   if not any(s.pln for s in steps))
    assert empty == ["EN-MIM-001", "FR-M901-001"]


def test_no_synthesised_plan_steps(spec):
    # 플랜 보강을 제거했으므로 원문 이벤트가 아닌 스텝이 있으면 안 된다.
    for steps in spec.entity_plans.values():
        for s in steps:
            assert s.event_id.startswith("E"), s


def test_all_pln_blocks_are_balanced(spec):
    for oid, steps in spec.entity_plans.items():
        for s in steps:
            if s.pln:
                assert balanced(s.pln), f"{oid} {s.event_id}"


def test_artillery_fires_at_a_location_not_an_entity(spec):
    steps = [s for s in spec.entity_plans["FR-M109-001"] if s.pln]
    ffe = [s for s in steps if "ffe-on-location" in s.pln]
    assert ffe, [s.pln for s in steps]
    # 정적 목표는 좌표로 처리한다(설계 스펙 §5.3) — uuid 참조가 없어야 한다.
    assert all(not s.refs for s in ffe)
    assert "VRF_UUID" not in ffe[0].pln


def test_artillery_can_move(spec):
    """포병도 진지변환 이동을 한다. task_catalog에 이동 템플릿을 추가했다."""
    steps = [s for s in spec.entity_plans["FR-AHS-001"] if s.pln]
    assert any("move-to-location-task" in s.pln for s in steps)


def test_infantry_direct_fire_targets_an_entity(spec):
    steps = [s for s in spec.entity_plans["FR-INF-001"] if s.pln]
    fire = [s for s in steps if "fire-at-target" in s.pln]
    assert fire
    assert fire[0].refs
    assert f'"VRF_UUID:{fire[0].refs[0]}"' in fire[0].pln


def test_aim_produces_no_task(spec):
    # 포신 정렬은 config에서 noop으로 선언했다(ffe가 조준까지 처리).
    for steps in spec.entity_plans.values():
        for s in steps:
            assert s.template != "aimAt" or s.pln is None


def test_control_objects_have_real_coords(spec):
    refs = {c.ref_id for c in spec.control_objects}
    assert "LOC_남측제1방어선" in refs
    assert all(c.coord is not None and not c.coord.is_zero()
               for c in spec.control_objects)


def test_uuids_are_unique(spec):
    uids = [e.uuid for e in spec.entities] + [c.uuid for c in spec.control_objects]
    assert len(uids) == len(set(uids))


def test_spec_is_deterministic(spec):
    other = _build()
    assert [(e.object_id, e.uuid, e.coord.as_tuple()) for e in spec.entities] == \
           [(e.object_id, e.uuid, e.coord.as_tuple()) for e in other.entities]
    assert [(c.ref_id, c.uuid) for c in spec.control_objects] == \
           [(c.ref_id, c.uuid) for c in other.control_objects]
