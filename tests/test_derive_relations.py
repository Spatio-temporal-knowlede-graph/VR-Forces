"""R3·R4·R7 — 원문에 문장으로 없는 관계를 이벤트에서 합성한다.

실측 기대치(2026-08-07, build/events/battle.jsonl 3,000건)는 데이터를 세어
얻은 값이다. 숫자가 틀어지면 규칙이 아니라 입력이 바뀐 것이니 둘 다 본다.
"""
from collections import Counter
from pathlib import Path

import pytest

from vtmak.derive.config import DeriveRules
from vtmak.derive.events import EventIndex
from vtmak.derive.relations import (r1r2_hit_state, r3_direct_fire,
                                    r4_indirect_fire, r6_unit_suppressed,
                                    r7_precedes, unit_members)
from vtmak.parser import Event

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "build" / "events" / "battle.jsonl"
CFG = ROOT / "config"


@pytest.fixture(scope="module")
def idx():
    return EventIndex.load(EVENTS)


@pytest.fixture(scope="module")
def rules():
    return DeriveRules.load(CFG / "derive_rules.csv")


def ev(event_id, time_s, predicate, **kw):
    """합성 이벤트 — 시간 조건처럼 실데이터가 커버 못 하는 경우에만 쓴다."""
    return Event(event_id=event_id, time_s=time_s, line_no=kw.pop("line_no", 1),
                 predicate=predicate, template=kw.pop("template", predicate), **kw)


# ── R1·R2 suppresses/damages(피격 → 같은 줄의 상태 전이) ─────────────────
def test_r1r2_consume_every_hit(idx, rules):
    """계약은 51+26=77이라는 합이 아니라 hitBy 77건 전량 소비다."""
    res = r1r2_hit_state(idx, rules)
    assert not res.unmatched
    assert len(res.relations) == len(idx.by_predicate("hitBy")) == 77
    kinds = Counter(r.predicate for r in res.relations)
    assert kinds == {"suppresses": 51, "damages": 26}


def test_r1r2_run_from_attacker_to_victim(idx, rules):
    """쌍은 (source_obj, actor)다 — 피격 라인의 actor는 맞은 쪽이다."""
    by_id = {e.event_id: e for e in idx.events}
    ids = {"suppresses": "R1", "damages": "R2"}
    for r in r1r2_hit_state(idx, rules).relations:
        hit, change = (by_id[p] for p in r.provenance)
        assert r.rule_id == ids[r.predicate]
        assert (hit.predicate, change.template) == ("hitBy", "stateChange")
        assert (r.subject, r.object) == (hit.source_obj, hit.actor)
        assert change.actor == hit.actor and change.line_no == hit.line_no
        assert r.provenance == (hit.event_id, change.event_id)


def test_r1r2_need_a_state_change_not_a_hold():
    """같은 줄에 stateHold가 있어도 관계는 안 생긴다.

    현 데이터는 hold가 전부 다른 줄에 있어 우연히 안전하다. 그건 데이터의
    사실이지 규칙의 계약이 아니라, 계약 쪽을 합성 이벤트로 못 박는다.
    """
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="V", template="stateHold",
           state_from="", state_to="제압"),
    ])
    res = r1r2_hit_state(idx, DeriveRules.load(CFG / "derive_rules.csv"))
    assert res.relations == ()
    assert res.unmatched == ("H1",)


def test_r1r2_ignore_another_objects_state_change_on_the_same_line(rules):
    """같은 줄이어도 주체가 다르면 그 피격의 결과가 아니다."""
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="OTHER", template="stateChange",
           state_from="기동 또는 사격 가능", state_to="제압"),
    ])
    res = r1r2_hit_state(idx, rules)
    assert res.relations == ()
    assert res.unmatched == ("H1",)


def test_r1r2_only_map_states_the_table_knows(rules):
    """표에 없는 전이는 조용히 다른 관계가 되지 않고 미매칭으로 남는다."""
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="V", template="stateChange",
           state_from="기동 또는 사격 가능", state_to="표에 없는 상태"),
    ])
    assert r1r2_hit_state(idx, rules).unmatched == ("H1",)


# ── R3 causes(직접사격 → 피격) ────────────────────────────────────────────
def test_r3_pairs_every_direct_fire_with_its_hit(idx):
    res = r3_direct_fire(idx)
    assert len(res.relations) == 77
    assert not res.unmatched
    assert {r.predicate for r in res.relations} == {"causes"}
    assert {r.rule_id for r in res.relations} == {"R3"}


def test_r3_points_from_the_shot_to_the_impact(idx):
    """방향이 뒤집히면 인과가 거꾸로 선다 — subject가 사격이다."""
    by_id = {e.event_id: e for e in idx.events}
    for r in r3_direct_fire(idx).relations:
        fire, hit = by_id[r.subject], by_id[r.object]
        assert (fire.predicate, hit.predicate) == ("directFireAt", "hitBy")
        assert (fire.actor, fire.target) == (hit.source_obj, hit.actor)
        assert hit.time_s >= fire.time_s


def test_r3_matches_a_fire_line_without_engagement_pair(idx):
    """77줄 중 1줄은 directFireAt 단독이다. 동반 술어를 요구하면 76건이 된다."""
    lone = next(e for e in idx.by_predicate("directFireAt")
                if {x.predicate for x in idx.by_line(e.line_no)} == {"directFireAt"})
    assert lone.event_id in {r.subject for r in r3_direct_fire(idx).relations}


def test_r3_takes_the_nearest_later_hit_for_a_repeated_pair():
    """같은 쌍이 두 번 교전하면 시각이 짝을 가른다."""
    idx = EventIndex([
        ev("F1", 10, "directFireAt", actor="A", target="V"),
        ev("H1", 11, "hitBy", actor="V", source_obj="A"),
        ev("F2", 100, "directFireAt", actor="A", target="V"),
        ev("H2", 101, "hitBy", actor="V", source_obj="A"),
    ])
    assert {(r.subject, r.object) for r in r3_direct_fire(idx).relations} == {
        ("F1", "H1"), ("F2", "H2")}


def test_r3_reports_an_unmatched_shot_instead_of_failing():
    idx = EventIndex([ev("F1", 10, "directFireAt", actor="A", target="V")])
    res = r3_direct_fire(idx)
    assert res.relations == ()
    assert res.unmatched == ("F1",)


# ── R4 firesUpon + causes(간접사격 → 지역 피격) ──────────────────────────
def test_r4_emits_firesupon_and_causes_for_every_indirect_shot(idx, rules):
    res = r4_indirect_fire(idx, rules)
    assert not res.unmatched
    kinds = [r for r in res.relations if r.predicate == "firesUpon"]
    causes = [r for r in res.relations if r.predicate == "causes"]
    assert (len(kinds), len(causes)) == (21, 21)
    assert {r.rule_id for r in res.relations} == {"R4"}


def test_r4_firesupon_runs_attacker_to_area(idx, rules):
    """행위자는 지역이 아니라 쏜 쪽이다 — 원문 라인의 actor는 지역이라 뒤집기 쉽다."""
    fired = {(r.subject, r.object)
             for r in r4_indirect_fire(idx, rules).relations
             if r.predicate == "firesUpon"}
    assert ("FR-MORT-001", "EN-FP-001") in fired
    assert {a for a, _ in fired} == {e.actor for e in idx.by_predicate("indirectFireAt")}
    assert {b for _, b in fired} == {e.target for e in idx.by_predicate("indirectFireAt")}


def test_r4_causes_ends_at_the_area_state_change(idx, rules):
    by_id = {e.event_id: e for e in idx.events}
    before, after = rules.area_state()
    for r in r4_indirect_fire(idx, rules).relations:
        if r.predicate != "causes":
            continue
        shot, impact = by_id[r.subject], by_id[r.object]
        assert shot.predicate == "indirectFireAt"
        assert (impact.predicate, impact.state_from, impact.state_to) == (
            "stateChangedTo", before, after)
        assert impact.actor == shot.target


def test_r4_needs_the_impact_to_follow_the_shot(rules):
    """지역 7종에 21발이라 쌍만으로는 갈리지 않는다. 시각이 조건이다."""
    lines = []
    for i, (t_fire, t_hit) in enumerate(((10, 11), (100, 101)), start=1):
        lines += [
            ev(f"F{i}", t_fire, "indirectFireAt", actor="A", target="Z", line_no=i),
            ev(f"S{i}", t_hit, "hitArea", actor="Z", source_obj="A", line_no=10 + i),
            ev(f"C{i}", t_hit, "stateChangedTo", actor="Z", line_no=10 + i,
               state_from="정상", state_to="피격 지역"),
        ]
    res = r4_indirect_fire(EventIndex(lines), rules)
    assert {(r.subject, r.object) for r in res.relations if r.predicate == "causes"} == {
        ("F1", "C1"), ("F2", "C2")}


# ── R7 precedes(같은 행위자의 시간 인접) ─────────────────────────────────
def test_r7_links_only_adjacent_events_of_one_actor(idx, rules):
    by_id = {e.event_id: e for e in idx.events}
    rels = r7_precedes(idx, rules).relations
    assert {r.predicate for r in rels} == {"precedes"}
    for r in rels:
        a, b = by_id[r.subject], by_id[r.object]
        assert a.actor == b.actor != ""
        assert (a.time_s, a.event_id) < (b.time_s, b.event_id)


def test_r7_chains_instead_of_pairing_every_combination(idx, rules):
    """N² 조합이면 33만 건이 넘는다. 체인은 행위자당 (건수-1)이다."""
    assert len(r7_precedes(idx, rules).relations) == 2368


def test_r7_hold_exclusion_comes_from_the_flag(idx, rules, monkeypatch):
    """상태 유지 179건을 빼는 건 코드가 아니라 표의 결정이다."""
    monkeypatch.setattr(rules, "flag", lambda key: False)
    assert len(r7_precedes(idx, rules).relations) == 2547


def test_r7_drops_state_hold_but_keeps_the_initial_state(idx, rules):
    """판별자는 template=="stateHold"다.

    state_from이 빈 이벤트는 473건인데 그중 294건이 stateInit이다. 빈 값으로
    거르면 초기 상태까지 날아가 체인이 첫 링크를 잃는다(2,368 → 2,074).
    초기 상태는 '같은 상태의 재서술'이 아니라 그 행위자의 출발점이다.
    """
    linked = {x for r in r7_precedes(idx, rules).relations
              for x in (r.subject, r.object)}
    inits = [e for e in idx.events if e.template == "stateInit" and e.actor]
    holds = [e for e in idx.events if e.template == "stateHold"]
    assert (len(inits), len(holds)) == (294, 179)
    assert {e.event_id for e in inits} <= linked
    assert linked.isdisjoint({e.event_id for e in holds})


def test_r7_skips_events_without_an_actor(idx, rules):
    """목표 구역 서술 118건에는 행위자가 없다 — 체인에 낄 자리가 없다."""
    empty = [e.event_id for e in idx.events if not e.actor]
    assert len(empty) == 118
    touched = {x for r in r7_precedes(idx, rules).relations
               for x in (r.subject, r.object)}
    assert touched.isdisjoint(empty)


# ── R5 부대 아닌 객체 제외 ───────────────────────────────────────────────
def suppressed_line(no, victim, attacker="A", t=10):
    """피격 + 같은 줄 제압 전이 — R1이 관계를 만드는 최소 형태."""
    return [ev(f"H{no}", t, "hitBy", actor=victim, source_obj=attacker, line_no=no),
            ev(f"S{no}", t, "stateChangedTo", actor=victim, line_no=no,
               template="stateChange", state_from="기동 또는 사격 가능",
               state_to="제압")]


def test_r5_drops_places_and_facilities_from_the_unit_list(idx, rules):
    """지명·시설은 부대가 아니다. 무엇이 시설인지는 표가 정한다."""
    kept = unit_members(idx, rules)
    assert len(kept) == 30
    assert set(kept) & {"EN-FP", "FR-FP", "EN-RT", "FR-LN", "OBJ"} == set()
    assert sum(len(v) for v in kept.values()) == 335 - 7


def test_r5_excluded_codes_are_not_hardcoded(idx, rules, monkeypatch):
    """표를 비우면 35부대가 전부 돌아온다 — 제외는 코드가 아니라 표의 결정이다."""
    monkeypatch.setattr(rules, "excluded_unit_codes", set)
    assert len(unit_members(idx, rules)) == 35


def test_r5_excludes_the_prefixless_form(rules):
    """OBJ-009는 진영 접두가 없는 유일한 형태다 — 코드가 첫 조각에 온다."""
    idx = EventIndex([ev("E1", 1, "locatedAt", actor="OBJ-009"),
                      ev("E2", 1, "locatedAt", actor="FR-INF-001")])
    assert set(unit_members(idx, rules)) == {"FR-INF"}


# ── R6 부대 제압 판정 ────────────────────────────────────────────────────
def test_r6_marks_the_two_units_past_the_threshold(idx, rules):
    res = r6_unit_suppressed(idx, rules)
    assert {(r.rule_id, r.predicate) for r in res.relations} == {
        ("R6", "unitSuppressed")}
    assert {r.subject for r in res.relations} == {"EN-INF", "FR-INF"}


def test_r6_threshold_comes_from_the_table(idx, rules, monkeypatch):
    """0.5로는 한 건도 안 나온다 — 실측 최댓값이 0.35(EN-INF 35/100)다.

    0.25라는 값의 근거가 측정이라는 것을, 올렸을 때 0건이 되는 것으로 고정한다.
    """
    monkeypatch.setattr(rules, "threshold", lambda key: 0.5)
    assert r6_unit_suppressed(idx, rules).relations == ()
    #  두 부대는 0.2667(FR-INF 16/60)과 0.35(EN-INF 35/100) 사이에서 갈린다.
    monkeypatch.setattr(rules, "threshold", lambda key: 0.3)
    assert {r.subject for r in r6_unit_suppressed(idx, rules).relations} == {
        "EN-INF"}


def test_r6_counts_members_not_hits(rules):
    """한 구성원이 두 번 제압돼도 한 명이다. 비율의 분자는 개체 수다."""
    idx = EventIndex(suppressed_line(1, "FR-INF-001")
                     + suppressed_line(2, "FR-INF-001", t=20)
                     + [ev("X1", 1, "locatedAt", actor=f"FR-INF-{i:03d}")
                        for i in range(2, 5)])
    #  4명 중 1명 = 0.25 → 임계값 이상. 피격 2건을 2명으로 세면 0.5가 된다.
    res = r6_unit_suppressed(idx, rules)
    assert {r.subject for r in res.relations} == {"FR-INF"}
    assert len(res.relations) == 1


def test_r6_never_reports_an_excluded_unit(rules):
    """지역이 제압 전이를 받아도 부대가 되지는 않는다."""
    idx = EventIndex(suppressed_line(1, "OBJ-009"))
    assert r1r2_hit_state(idx, rules).relations       # R1은 관계를 만든다
    assert r6_unit_suppressed(idx, rules).relations == ()


def test_r6_provenance_reaches_the_member_evidence(idx, rules):
    """부대 판정의 근거는 구성원 하나하나의 피격·전이 이벤트다."""
    by_id = {e.event_id: e for e in idx.events}
    for r in r6_unit_suppressed(idx, rules).relations:
        actors = {by_id[p].actor for p in r.provenance}
        assert actors <= set(unit_members(idx, rules)[r.subject])
        assert len(r.provenance) == 2 * (35 if r.subject == "EN-INF" else 16)


# ── 규칙 간 정합성 ───────────────────────────────────────────────────────
def test_every_hit_state_pair_has_exactly_one_direct_fire_cause(idx, rules):
    """개체쌍 레이어(R1·R2)와 이벤트쌍 레이어(R3)를 서로 봉인한다.

    같은 피격을 두 레이어가 각자 읽으므로, 한쪽 규칙이 조용히 어긋나면 두
    레이어의 (공격자, 피격자) 집합이 갈라진다. 여기서 걸린다.
    """
    by_id = {e.event_id: e for e in idx.events}
    fired = Counter()
    for r in r3_direct_fire(idx).relations:
        shot = by_id[r.subject]
        fired[(shot.actor, shot.target)] += 1
    for r in r1r2_hit_state(idx, rules).relations:
        assert fired[(r.subject, r.object)] == 1, (r.subject, r.object)


# ── 공통 계약 ────────────────────────────────────────────────────────────
def _run_all(index, rules):
    return (r1r2_hit_state(index, rules).relations
            + r3_direct_fire(index).relations
            + r4_indirect_fire(index, rules).relations
            + r6_unit_suppressed(index, rules).relations
            + r7_precedes(index, rules).relations)


def test_derive_is_byte_stable_across_runs(rules):
    """derived.jsonl은 GT 산출물이라 재실행 산출이 같아야 한다.

    싱크는 한 번 쓰면 소진되므로 소비 순서가 결과를 정한다. 그 순서가
    dict 순회 같은 데 기대고 있으면 여기서 걸린다.
    """
    first = _run_all(EventIndex.load(EVENTS), rules)
    second = _run_all(EventIndex.load(EVENTS), rules)
    assert first == second


def test_derive_ignores_the_order_events_arrive_in(rules):
    """정렬은 EventIndex가 한 번만 정한다 — 입력 줄 순서는 산출을 못 바꾼다."""
    events = list(EventIndex.load(EVENTS).events)
    shuffled = EventIndex(events[1::2] + events[::2])
    assert _run_all(shuffled, rules) == _run_all(EventIndex(events), rules)


def test_sources_and_sinks_are_consumed_in_time_order(idx):
    """짝짓기가 보는 순서는 (time_s, event_id)다."""
    for predicate in ("directFireAt", "hitBy", "indirectFireAt", "stateChangedTo"):
        seq = idx.by_predicate(predicate)
        assert list(seq) == sorted(seq, key=lambda e: (e.time_s, e.event_id))


@pytest.mark.parametrize("rule,expected", [
    ("r1r2", {"R1", "R2"}), ("r3", {"R3"}), ("r4", {"R4"}), ("r6", {"R6"}),
    ("r7", {"R7"})])
def test_every_relation_carries_layer_rule_and_provenance(idx, rules, rule,
                                                          expected):
    res = {"r1r2": lambda: r1r2_hit_state(idx, rules),
           "r3": lambda: r3_direct_fire(idx),
           "r4": lambda: r4_indirect_fire(idx, rules),
           "r6": lambda: r6_unit_suppressed(idx, rules),
           "r7": lambda: r7_precedes(idx, rules)}[rule]()
    known = idx.ids()
    assert res.relations
    for r in res.relations:
        assert r.layer == "derived"
        assert r.rule_id in expected
        assert r.provenance and set(r.provenance) <= known
