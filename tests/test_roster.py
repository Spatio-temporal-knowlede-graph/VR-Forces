from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import PatternMap, parse_scenario
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import (RosterPlan, engagement_pairs_of, filter_events,
                          select_roster, unit_of)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(
        (ROOT / "scenario_original" / "scenario_v3.txt").read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    cm = ClassMap.load(ROOT / "config" / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    plan = RosterPlan.load(ROOT / "config" / "roster.json")
    return res.events, reg, plan


def test_unit_of():
    assert unit_of("FR-INF-001") == "FR-INF"
    assert unit_of("EN-CAESAR-003") == "EN-CAESAR"
    assert unit_of("OBJ-009") == "OBJ"


def test_hits_the_target_count(env):
    events, reg, plan = env
    assert len(select_roster(events, reg, plan)) == plan.target


def test_keeps_every_static_object(env):
    events, reg, plan = env
    keep = select_roster(events, reg, plan)
    static = {oid for oid, d in reg.items() if not d.taskable}
    assert static <= keep


def test_preserves_every_engagement_kind(env):
    """STKG의 관계 종류가 통째로 사라지면 안 된다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan)
    kept = filter_events(events, keep)
    kinds = lambda evs: {(unit_of(a), unit_of(t))
                         for a, t in engagement_pairs_of(evs)}
    assert kinds(kept) == kinds(events)


def test_no_orphan_events(env):
    """남은 이벤트가 명부에 없는 객체를 가리키면 안 된다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan)
    for e in filter_events(events, keep):
        for ref in (e.actor, e.target, e.source_obj):
            assert not ref or ref in keep, e.event_id


def test_no_unit_is_wiped_out(env):
    events, reg, plan = env
    keep = select_roster(events, reg, plan)
    before = {unit_of(o) for o in reg}
    after = {unit_of(o) for o in keep}
    assert before == after


def test_is_deterministic(env):
    events, reg, plan = env
    assert select_roster(events, reg, plan) == select_roster(events, reg, plan)


def test_raising_the_target_keeps_a_superset(env):
    events, reg, _ = env
    small = select_roster(events, reg, RosterPlan(120, 0.4))
    big = select_roster(events, reg, RosterPlan(200, 0.4))
    assert len(small) == 120 and len(big) == 200
    # 교전 쌍 선택이 같으므로 작은 명부의 교전 참여자는 큰 쪽에도 있어야 한다
    fighters = {o for p in engagement_pairs_of(events) for o in p}
    assert (small & fighters) <= big
