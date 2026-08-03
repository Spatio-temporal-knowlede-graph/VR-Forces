from pathlib import Path

import pytest

from collections import Counter

from vtmak.geometry import BattlefieldLayout
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import (RosterPlan, engagement_pairs_of, filter_events,
                          select_roster, unit_of)

ROOT = Path(__file__).resolve().parents[1]


def _task_ids(events):
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    return {e.event_id for e in events
            if pm.task_kind(e.template, e.action_label) not in ("", "noop")}


@pytest.fixture(scope="module")
def env():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
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


def test_hits_the_entity_target_without_exceeding_any_quota(env):
    """엔티티 수는 정확히 맞추고, 부대별 정원은 상한으로 지킨다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    got = Counter(unit_of(o) for o in keep)
    available = sum(1 for e in reg.values() if e.taskable)
    # 원문이 정원보다 작으면 있는 만큼만 남는다.
    assert (sum(1 for o in keep if reg[o].taskable)
            == min(plan.target_entities, available))
    over = {u: (got[u], cap) for u, cap in plan.quota.items() if got[u] > cap}
    assert over == {}


def test_no_unit_is_emptied(env):
    """부대 바닥이 없으면 이벤트가 적은 부대(지휘소 경계 보병 등)가 통째로
    사라진다. 실측으로 80개에서 3개 부대가 비었다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    got = Counter(unit_of(o) for o in keep)
    units = {unit_of(o) for o, d in reg.items() if d.taskable}
    assert plan.min_per_unit >= 1
    assert [u for u in sorted(units) if got[u] < plan.min_per_unit] == []


def test_task_yield_beats_a_flat_cut(env):
    """수확량 선택이 정원 균등 축소보다 task를 더 많이 남기는가.

    이게 뒤집히면 복잡한 선택을 유지할 이유가 없다.
    """
    events, reg, plan = env
    tids = _task_ids(events)

    def surviving_tasks(keep):
        return sum(1 for e in filter_events(events, keep)
                   if e.event_id in tids)

    smart = select_roster(events, reg, plan, tids)
    flat = {u: max(1, round(n * 0.8)) for u, n in plan.quota.items()}
    while sum(flat.values()) > plan.target_entities:
        u = max(flat, key=lambda k: (flat[k], k))
        flat[u] -= 1
    dumb = select_roster(events, reg, RosterPlan(0, 0.0, flat))
    assert sum(1 for o in dumb if reg[o].taskable) <= plan.target_entities
    assert surviving_tasks(smart) > surviving_tasks(dumb)


def test_quota_covers_every_taskable_unit(env):
    """정원표에 빠진 부대가 있으면 그 부대만 통째로 살아남는다 — 조용한 사고다."""
    _, reg, plan = env
    units = {unit_of(o) for o, d in reg.items() if d.taskable}
    assert units - set(plan.quota) == set()


def test_quota_keeps_every_entity_type(env):
    """축소 원칙 1 — 원문에 나온 엔티티 타입은 하나도 잃지 않는다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    every = {d.entity_class for d in reg.values() if d.taskable}
    kept = {reg[o].entity_class for o in keep if reg[o].taskable}
    assert kept == every, sorted(every - kept)


def test_keeps_every_static_object(env):
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    static = {oid for oid, d in reg.items() if not d.taskable}
    assert static <= keep


def test_preserves_every_engagement_kind(env):
    """STKG의 관계 종류가 통째로 사라지면 안 된다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    kept = filter_events(events, keep)
    kinds = lambda evs: {(unit_of(a), unit_of(t))
                         for a, t in engagement_pairs_of(evs)}
    assert kinds(kept) == kinds(events)


def test_no_orphan_events(env):
    """남은 이벤트가 명부에 없는 객체를 가리키면 안 된다."""
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    for e in filter_events(events, keep):
        for ref in (e.actor, e.target, e.source_obj):
            assert not ref or ref in keep, e.event_id


def test_no_unit_is_wiped_out(env):
    events, reg, plan = env
    keep = select_roster(events, reg, plan, _task_ids(events))
    before = {unit_of(o) for o in reg}
    after = {unit_of(o) for o in keep}
    assert before == after


def test_is_deterministic(env):
    events, reg, plan = env
    assert select_roster(events, reg, plan, _task_ids(events)) == select_roster(events, reg, plan, _task_ids(events))


def test_budget_mode_still_works_without_a_quota(env):
    """정원표를 비우면 예전 예산 방식으로 되돌아간다."""
    events, reg, _ = env
    total = len(reg)
    lo, hi = min(40, total), min(60, total)
    # 예산 방식은 먼저 교전 쌍을 남기고 남은 예산만 비교전 객체에 나눈다.
    # 교전 쌍이 예산보다 많으면 그쪽이 이긴다 — target=0으로 그 바닥값을 잰다.
    floor = len(select_roster(events, reg, RosterPlan(0, 0.4, {})))
    small = select_roster(events, reg, RosterPlan(lo, 0.4, {}))
    big = select_roster(events, reg, RosterPlan(hi, 0.4, {}))
    assert len(small) == max(lo, floor) and len(big) == max(hi, floor)
    # 교전 쌍 선택이 같으므로 작은 명부의 교전 참여자는 큰 쪽에도 있어야 한다
    fighters = {o for p in engagement_pairs_of(events) for o in p}
    assert (small & fighters) <= big
