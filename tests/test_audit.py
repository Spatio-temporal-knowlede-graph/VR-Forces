from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout, Coord
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.audit import build_rows, hhmmss, parse_oob, parse_pln, read_scnx
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.engagements import EngagementSlot, EnrichmentConfig
from vtmak.scnx.gates import validate_interaction_plan
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.plan import PlanStep
from vtmak.scnx.spec import EntitySpec, ScnxSpec, build_spec
from vtmak.scnx.writer import get_writer

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ensure_golden(ROOT / "yewon_test")

_PLN = '''(
   (Plan-File (version "2.0"))
(Plan
      (plan-name  "VRF_UUID:aaa")
      (Block
         (Task (task-type "move-to") (control-point "VRF_UUID:cafe-0001"))
         (Set (set-data-request-type "set-speed") (speed 8.000000) )
         (Task (task-type "find_cover") (script-id "find_cover") (variables (DtRwObjectName (Threat "VRF_UUID:beef-0002") ) ) )
      )
      (plan-execution-stack
      )
   )
)
'''

_OOB = '''(order-of-battle
  (local-vrf-object
      (object-identifier  "1:3001:3001")
      (object-type  1 (1 1 222 2 8 1 0))
      (marking-text "ENBTR60001")
      (object-label "병력수송 장갑차 1")
      (uuid  "VRF_UUID:aaa")
  )
)
'''


def test_parse_pln_keeps_task_and_set_in_file_order():
    plans = parse_pln(_PLN)
    assert list(plans) == ["aaa"]
    assert [t.task_type for t in plans["aaa"]] == [
        "move-to", "set-speed", "find_cover"]
    assert [t.seq for t in plans["aaa"]] == [1, 2, 3]


def test_parse_pln_collects_task_references():
    tasks = parse_pln(_PLN)["aaa"]
    assert tasks[0].refs == ("cafe-0001",)
    assert tasks[1].refs == ()
    assert tasks[2].refs == ("beef-0002",)
    assert tasks[2].script_id == "find_cover"


def test_parse_oob_reads_identity_fields():
    (o,) = parse_oob(_OOB)
    assert o.uuid == "aaa"
    assert o.marking == "ENBTR60001"
    assert o.label == "병력수송 장갑차 1"
    assert o.dis == (1, 1, 222, 2, 8, 1, 0)
    assert o.kind == "1"


def test_hhmmss():
    assert hhmmss(0) == "00:00"
    assert hhmmss(162) == "02:42"
    assert hhmmss(None) == ""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"))
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    kinds = TaskKinds.load(cfg / "task_kinds.csv")
    spec = build_spec(events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"),
                      kinds,
                      DisCatalog.load(cfg / "dis_catalog.csv"),
                      WeaponRanges.load(cfg / "weapon_ranges.csv"), "battle")
    scnx = get_writer("template", str(GOLDEN)).write(
        spec, tmp_path_factory.mktemp("scnx"))
    return spec, read_scnx(scnx), events, kinds


def test_round_trip_matches_the_spec_task_for_task(built):
    """저작된 .pln을 되읽으면 스펙의 PlanStep과 개수가 정확히 맞는다."""
    spec, contents, events, kinds = built
    _, _, warnings = build_rows(spec, contents, kinds, events)
    assert warnings == []


def test_rows_cover_every_entity_and_every_step(built):
    spec, contents, events, kinds = built
    tasks, objects, _ = build_rows(spec, contents, kinds, events)
    assert len(objects) == len(spec.entities)
    assert len(tasks) == sum(len(v) for v in spec.entity_plans.values())
    assert sum(o.n_tasks for o in objects) == sum(
        1 for v in spec.entity_plans.values() for s in v if s.pln)


def test_dropped_events_are_visible_not_silent(built):
    """저작 못 한 이벤트는 표에 사유와 함께 남는다 — 조용히 사라지지 않는다.

    VR-Forces가 실행을 거부하는 것이 실측된 조합은 .pln에 안 나가지만, 표에는
    사유를 달고 남아야 한다. 그래야 '왜 이 객체가 안 움직이지'를 표에서 찾는다.
    """
    spec, contents, events, kinds = built
    tasks, objects, _ = build_rows(spec, contents, kinds, events)
    dropped = [t for t in tasks if not t.in_scnx]
    assert dropped, "실측으로 걸러내는 조합이 하나도 없다 — 필터가 죽었다"
    assert all(t.note for t in dropped), \
        [t.event_id for t in dropped if not t.note]

    oid = spec.entities[0].object_id
    broken = PlanStep(event_id="ETEST", time_s=0, template="moveTo",
                      task_kind="move", action_label=None, pln=None,
                      issues=["템플릿 없음"])
    saved = spec.entity_plans.get(oid, [])
    before = {o.object_id: o.n_dropped for o in objects}
    spec.entity_plans[oid] = list(saved) + [broken]
    try:
        tasks, objects, _ = build_rows(spec, contents, kinds, events)
        dropped = [t for t in tasks if not t.in_scnx]
        assert "ETEST" in [t.event_id for t in dropped]
        assert all(t.note for t in dropped)
        now = {o.object_id: o.n_dropped for o in objects}
        assert now[oid] == before[oid] + 1
        assert {k: v for k, v in now.items() if k != oid} == \
            {k: v for k, v in before.items() if k != oid}
    finally:
        spec.entity_plans[oid] = saved


def test_references_resolve_to_readable_names(built):
    """좌표로 저작된 태스크도 '어디로/누구를'이 비면 안 된다.

    wait는 예외다 — 정지·잔류 표현은 참조_필드가 아예 없는 kind라
    (task_kinds.csv) '누구를/어디로'에 해당하는 게 없다. 동반 행동
    (`기반kind:행동`, 예: `move_slow:속도 지정`)도 예외다 — 참조는 바로 앞뒤의
    본 태스크 줄이 이미 보여준다.

    take_cover는 Task 5(2026-08-27)에서 move_cover로 바뀌었다 — find_cover
    (컨트롤러 비활성 실측)를 좌표 이동으로 대체한다. max_cover_move_m을
    400.0으로 올리고 이격을 지점 공유 배치 규칙으로 바꾼 뒤(리뷰 라운드 1)
    hitBy 77건 중 52건이 저작된다 — 실제로 저작되는 move_cover로 확인한다.

    suppress를 더 이상 예외로 두지 않는다(Task 6) — build_rows가 이제
    step.slot_id로 슬롯을 직접 찾아 target_ref(제압사격의 좌표 목표)를
    되살린다. 예외를 남겨 두면 이 수리가 실제로 됐는지 아무도 모른다.
    """
    spec, contents, events, kinds = built
    tasks, _, _ = build_rows(spec, contents, kinds, events)
    live = [t for t in tasks
            if t.in_scnx and t.task_kind != "wait"
            and ":" not in t.task_kind]
    assert live and all(t.ref_id for t in live)
    moves = [t for t in live if t.task_kind == "move"]
    assert moves and all(t.ref_id.startswith("LOC_") for t in moves)
    cover = [t for t in live if t.task_kind == "move_cover"]
    assert cover, "move_cover 중 저작된 것이 하나도 없다"
    assert all(t.ref_kind == "COORD" for t in cover), (
        "좌표 이동은 통제점·엔티티 uuid가 아니라 intent_object로 참조를 남긴다")
    # 제압사격도 이제 슬롯에서 참조를 되살린다(Task 6 리페어) — 좌표
    # task라 .pln에 uuid가 없으므로 ref_kind는 COORD여야 한다.
    suppress = [t for t in live if t.task_kind == "suppress"]
    assert len(suppress) == 77, len(suppress)
    assert all(t.ref_kind == "COORD" for t in suppress)


def test_coordinate_tasks_need_the_events_to_name_their_target(built):
    """events 없이 부르면 uuid가 없는 태스크의 ref는 비어 있다(대비 확인)."""
    spec, contents, _, kinds = built
    tasks, _, _ = build_rows(spec, contents, kinds)
    assert any(t.in_scnx and not t.ref_id for t in tasks)


# ---------------------------------------------------------------------------
# G4(validate_interaction_plan) — 합성 spec으로 각 차단 위반을 개별 재현한다.
# 전체 파이프라인을 돌리지 않는다. 필요한 필드만 채운 ScnxSpec을 손으로
# 만든다(Task 6 브리프).
# ---------------------------------------------------------------------------

def _slot(slot_id, shooter="FR-A", target="EN-B", origin="enrichment",
         shooter_faction="BLUE", target_faction="RED"):
    """EngagementSlot 하나와 그 두 진영을 함께 돌려준다."""
    slot = EngagementSlot(slot_id, origin, (), 100, shooter, target,
                          Coord(21.0, 105.0, 0.0), Coord(21.001, 105.0, 0.0),
                          "LOC_B", "", None, 111.0, 0, 1, 5, 10, 10, "")
    return slot, {shooter: shooter_faction, target: target_faction}


def _follow_step(oid, event_id):
    return PlanStep(event_id, 0, "moveTo", "follow", "대형 추종 이동",
                    '(Task (task-type "follow-entity") (offset 0 0 0) )')


def _fire_step(oid, event_id, slot_id="SRC-E2"):
    step = PlanStep(event_id, 10, "directFireAt", "fire_direct",
                    "대상 직접사격",
                    '(Task (task-type "fire-at-target") '
                    '(max-rounds-to-fire 1))')
    step.slot_id = slot_id
    return step


def _synthetic_spec(steps=(), slots=()):
    """steps는 객체 O1의 계획, slots는 (slot, factions) 쌍의 목록."""
    spec = ScnxSpec(scenario_id="t", terrain="t")
    if steps:
        spec.entity_plans["O1"] = list(steps)
    factions = {}
    for slot, f in slots:
        spec.engagement_slots.append(slot)
        factions.update(f)
    spec.entities = [EntitySpec(object_id=o, name=o, uuid=o, entity_class="c",
                                type_group="g", faction=fac, dis=None,
                                coord=Coord(21.0, 105.0, 0.0), heading=0.0,
                                initial_state="")
                     for o, fac in sorted(factions.items())]
    return spec


def test_follow_before_fire_is_blocked():
    spec = _synthetic_spec(steps=[_follow_step("O1", "E1"),
                                  _fire_step("O1", "E2")])
    v = validate_interaction_plan(spec, EnrichmentConfig.defaults())
    assert any(x.code == "C4.2" and "O1" in x.detail and "E1" in x.detail
               and "E2" in x.detail for x in v)


def test_duplicate_slot_id_is_blocked():
    spec = _synthetic_spec(slots=[_slot("ENR-000"), _slot("ENR-000")])
    assert any(x.code == "C4.1"
               for x in validate_interaction_plan(
                   spec, EnrichmentConfig.defaults()))


def test_same_faction_slot_is_blocked():
    spec = _synthetic_spec(slots=[_slot("ENR-000", shooter_faction="RED",
                                        target_faction="RED")])
    assert any(x.code == "C4.5"
               for x in validate_interaction_plan(
                   spec, EnrichmentConfig.defaults()))
