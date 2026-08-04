from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.audit import build_rows, hhmmss, parse_oob, parse_pln, read_scnx
from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.plan import PlanStep
from vtmak.scnx.spec import build_spec
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
    spec = build_spec(events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"),
                      DisCatalog.load(cfg / "dis_catalog.csv"),
                      WeaponRanges.load(cfg / "weapon_ranges.csv"), "battle")
    scnx = get_writer("template", str(GOLDEN)).write(
        spec, tmp_path_factory.mktemp("scnx"))
    return spec, read_scnx(scnx), events


def test_round_trip_matches_the_spec_task_for_task(built):
    """저작된 .pln을 되읽으면 스펙의 PlanStep과 개수가 정확히 맞는다."""
    spec, contents, events = built
    _, _, warnings = build_rows(spec, contents, events)
    assert warnings == []


def test_rows_cover_every_entity_and_every_step(built):
    spec, contents, events = built
    tasks, objects, _ = build_rows(spec, contents, events)
    assert len(objects) == len(spec.entities)
    assert len(tasks) == sum(len(v) for v in spec.entity_plans.values())
    assert sum(o.n_tasks for o in objects) == sum(
        1 for v in spec.entity_plans.values() for s in v if s.pln)


def test_dropped_events_are_visible_not_silent(built):
    """저작 못 한 이벤트는 표에 사유와 함께 남는다 — 조용히 사라지지 않는다.

    VR-Forces가 실행을 거부하는 것이 실측된 조합은 .pln에 안 나가지만, 표에는
    사유를 달고 남아야 한다. 그래야 '왜 이 객체가 안 움직이지'를 표에서 찾는다.
    """
    spec, contents, events = built
    tasks, objects, _ = build_rows(spec, contents, events)
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
        tasks, objects, _ = build_rows(spec, contents, events)
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
    """좌표로 저작된 태스크도 '어디로/누구를'이 비면 안 된다."""
    spec, contents, events = built
    tasks, _, _ = build_rows(spec, contents, events)
    live = [t for t in tasks if t.in_scnx and t.task_kind != "set_speed"]
    assert live and all(t.ref_id for t in live)
    moves = [t for t in live if t.task_kind == "move"]
    assert moves and all(t.ref_id.startswith("LOC_") for t in moves)
    cover = [t for t in live if t.task_kind == "take_cover"]
    assert cover and all(t.ref_kind == "ENTITY" for t in cover)


def test_coordinate_tasks_need_the_events_to_name_their_target(built):
    """events 없이 부르면 uuid가 없는 태스크의 ref는 비어 있다(대비 확인)."""
    spec, contents, _ = built
    tasks, _, _ = build_rows(spec, contents)
    assert any(t.in_scnx and not t.ref_id for t in tasks)
