import re
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.plan import balanced
from vtmak.scnx.spec import build_spec

ROOT = Path(__file__).resolve().parents[1]


def _build():
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    # 파이프라인과 같게 명부를 감축한다(02_parse_events.py와 동일).
    task_ids = {e.event_id for e in res.events
                if pm.task_kind(e.template, e.action_label) not in ("", "noop")}
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"),
                         task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    return build_spec(events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"),
                      DisCatalog.load(cfg / "dis_catalog.csv"),
                      WeaponRanges.load(cfg / "weapon_ranges.csv"),
                      scenario_id="battle")


@pytest.fixture(scope="module")
def spec():
    return _build()


def test_entities_exclude_static_objects(spec):
    ids = {e.object_id for e in spec.entities}
    assert ids
    assert "EN-FP-001" not in ids
    assert "OBJ-009" not in ids


def test_every_entity_has_dis_and_nonzero_coord(spec):
    for e in spec.entities:
        assert e.dis is not None, e.object_id
        assert not e.coord.is_zero(), e.object_id


def test_entities_sharing_a_location_are_jittered(spec):
    at = [e for e in spec.entities if e.object_id.startswith("FR-INF-")][:20]
    assert len({e.coord.as_tuple() for e in at}) == len(at)


def test_every_entity_gets_a_pln(spec):
    """플랜이 빈 엔티티는 '실행할 수 없는 태스크만 받은' 객체뿐이어야 한다.

    플랜이 비면 VR-Forces에서 그 객체는 초기 배치 자리에 가만히 서 있는다.
    원문이 이동·사격을 시켰는데 저작이 안 된 것이면 조용히 넘기지 않는다.
    반대로 VR-Forces가 실행을 거부하는 것이 실측된 조합(skip_reason)만 남아
    비었다면 그건 의도한 결과다 — 견인 대공포처럼 이 시나리오에서 할 수 있는
    일이 하나도 없는 모델이 있다.
    """
    for oid, steps in sorted(spec.entity_plans.items()):
        if any(s.pln for s in steps):
            continue
        assert steps, oid
        assert all(s.skip_reason for s in steps), \
            (oid, [s.issues for s in steps if not s.skip_reason])


def test_empty_plans_are_only_towed_equipment(spec):
    """플랜이 빈 객체가 실제로 어느 모델인지 못 박아 둔다.

    unsupported_tasks가 넓어지면 여기서 먼저 걸린다 — 조용히 객체가
    늘어나면 시나리오가 소리 없이 비어 간다.
    """
    cls = {e.object_id: e.entity_class for e in spec.entities}
    empty = {cls[oid] for oid, steps in spec.entity_plans.items()
             if not any(s.pln for s in steps)}
    assert empty == {"ZPU-4 AA Gun", "M901 Patriot Launcher"}, empty


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
    gun = next(e.object_id for e in spec.entities
               if e.entity_class == "M109 Howitzer")
    steps = [s for s in spec.entity_plans[gun] if s.pln]
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
    """제압으로 끝나지 않는 직접사격은 fire-at-target으로 남는다."""
    fire = [s for steps in spec.entity_plans.values() for s in steps
            if s.pln and "fire-at-target" in s.pln]
    assert fire
    assert fire[0].refs
    assert f'"VRF_UUID:{fire[0].refs[0]}"' in fire[0].pln


def test_suppressive_fire_replaces_plain_fire_when_target_is_suppressed(spec):
    """원문의 사격→피격→제압 3문장을 이어붙여 제압사격으로 저작한다."""
    sup = [s for steps in spec.entity_plans.values() for s in steps
           if s.pln and "provide_suppressive_fire_loc" in s.pln]
    assert sup
    # 좌표 기반 스크립트 태스크 — uuid 참조가 없어야 한다
    assert all(not s.refs for s in sup)
    assert all("targetLocation" in s.pln for s in sup)


def test_being_hit_produces_a_take_cover_task(spec):
    cover = [s for steps in spec.entity_plans.values() for s in steps
             if s.pln and "find_cover" in s.pln]
    assert cover
    for s in cover:
        assert s.template == "hitBy"
        assert s.refs, "Threat = 피격 원천 객체의 uuid"
        assert "StartingLocation" in s.pln


def test_assault_formation_move_follows_the_unit_leader(spec):
    follow = [(oid, s) for oid, steps in spec.entity_plans.items()
              for s in steps if s.pln and "follow-entity" in s.pln]
    assert follow
    leaders = {s.refs[0] for _, s in follow}
    uuids = {e.uuid: e.object_id for e in spec.entities}
    assert leaders <= set(uuids), "추종 대상이 실제 엔티티여야 한다"
    for oid, s in follow:
        assert uuids[s.refs[0]] != oid, "자기 자신을 추종하면 안 된다"


def test_supply_move_sets_speed_first(spec):
    for steps in spec.entity_plans.values():
        for i, s in enumerate(steps):
            if s.task_kind == "move_slow":
                assert i > 0 and steps[i - 1].task_kind == "set_speed"
                assert "(speed 8.000000)" in steps[i - 1].pln


def test_task_type_variety(spec):
    import re
    kinds = set()
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.pln:
                m = re.search(r'task-type "([^"]+)"|'
                              r'set-data-request-type "([^"]+)"', s.pln)
                kinds.add(m.group(1) or m.group(2))
    # 확장 전에는 4종뿐이었다. move-to(통제점)를 좌표 이동으로 바꾸면서
    # move-to-location-task로 합쳐져 7종이 되었다.
    assert len(kinds) >= 7, sorted(kinds)
    assert "move-to" not in kinds, "통제점 이동은 더 이상 저작하지 않는다"


def test_aim_produces_no_task(spec):
    # 포신 정렬은 config에서 noop으로 선언했다(ffe가 조준까지 처리).
    for steps in spec.entity_plans.values():
        for s in steps:
            assert s.template != "aimAt" or s.pln is None


def test_no_tactical_graphics_are_created(spec):
    """통제점(= VR-Forces 전술 그래픽)을 하나도 만들지 않는다.

    전술 그래픽이 시나리오 로딩을 느리게 해서, 모든 태스크가 통제점 uuid 대신
    좌표를 직접 적는다(사용자 결정 2026-08-03). 통제점은 태스크가 참조할 때만
    생기므로, 참조가 사라지면 개수도 0이 된다.
    """
    assert spec.control_objects == []
    for oid, steps in spec.entity_plans.items():
        for s in steps:
            assert "control-point" not in (s.pln or ""), f"{oid} {s.event_id}"


def test_move_tasks_carry_real_coordinates(spec):
    """좌표 이동 태스크에 자리표시자가 남아 있으면 안 된다."""
    moves = [s for steps in spec.entity_plans.values() for s in steps
             if s.pln and "move-to-location-task" in s.pln]
    assert moves
    for s in moves:
        assert "X Y Z" not in s.pln, s.event_id
        assert re.search(r"\(aiming-point\s+-?\d+\.\d+\s+-?\d+\.\d+\s+"
                         r"-?\d+\.\d+\)", s.pln), s.event_id


def test_uuids_are_unique(spec):
    uids = [e.uuid for e in spec.entities] + [c.uuid for c in spec.control_objects]
    assert len(uids) == len(set(uids))


def test_spec_is_deterministic(spec):
    other = _build()
    assert [(e.object_id, e.uuid, e.coord.as_tuple()) for e in spec.entities] == \
           [(e.object_id, e.uuid, e.coord.as_tuple()) for e in other.entities]
    assert [(c.ref_id, c.uuid) for c in spec.control_objects] == \
           [(c.ref_id, c.uuid) for c in other.control_objects]
