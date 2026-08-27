"""R3·R4·R7 — 원문에 문장으로 없는 관계를 이벤트에서 합성한다.

실측 기대치(2026-08-07, build/events/battle.jsonl 3,000건)는 데이터를 세어
얻은 값이다. 숫자가 틀어지면 규칙이 아니라 입력이 바뀐 것이니 둘 다 본다.
"""
from collections import Counter
from pathlib import Path

import pytest

from vtmak.derive.config import DeriveRules
from vtmak.derive.events import EventIndex
from vtmak.derive.relations import (r2_damage, r3_direct_fire,
                                    r4_indirect_fire, r7_precedes)
from vtmak.parser import Event

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "build" / "events" / "battle.jsonl"
CFG = ROOT / "config"

# 설계 §10이 '제거 상태를 회귀 테스트로 고정한다'고 못박은 술어들.
REMOVED_UNIT_PREDICATES = {"partOf", "supports", "reinforces",
                           "unitSuppressed"}


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


# ── R2 damages(피격 → 같은 줄의 손상 전이) ─────────────────────────────
def test_damage_rule_emits_only_observed_damage_effect(idx, rules):
    """R2만 남는다 — suppresses는 제거됐고 미매칭도 없다.

    제압 전이 피격 51건은 미매칭이 아니라 의도적으로 안 본다(설계 §9.2).
    """
    result = r2_damage(idx, rules)
    assert not result.unmatched
    assert len(result.relations) == 26
    assert {r.rule_id for r in result.relations} == {"R2"}
    assert {r.predicate for r in result.relations} == {"damages"}


def test_r2_runs_from_attacker_to_victim(idx, rules):
    """쌍은 (source_obj, actor)다 — 피격 라인의 actor는 맞은 쪽이다."""
    by_id = {e.event_id: e for e in idx.events}
    for r in r2_damage(idx, rules).relations:
        hit, change = (by_id[p] for p in r.provenance)
        assert r.rule_id == "R2"
        assert (hit.predicate, change.template) == ("hitBy", "stateChange")
        assert (r.subject, r.object) == (hit.source_obj, hit.actor)
        assert change.actor == hit.actor and change.line_no == hit.line_no
        assert r.provenance == (hit.event_id, change.event_id)


def test_r2_needs_a_state_change_not_a_hold():
    """같은 줄에 stateHold가 있어도 관계는 안 생긴다.

    현 데이터는 hold가 전부 다른 줄에 있어 우연히 안전하다. 그건 데이터의
    사실이지 규칙의 계약이 아니라, 계약 쪽을 합성 이벤트로 못 박는다.
    """
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="V", template="stateHold",
           state_from="", state_to="손상"),
    ])
    res = r2_damage(idx, DeriveRules.load(CFG / "derive_rules.csv"))
    assert res.relations == ()
    assert res.unmatched == ()


def test_r2_ignore_another_objects_state_change_on_the_same_line(rules):
    """같은 줄이어도 주체가 다르면 그 피격의 결과가 아니다."""
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="OTHER", template="stateChange",
           state_from="기동 또는 사격 가능", state_to="손상"),
    ])
    res = r2_damage(idx, rules)
    assert res.relations == ()
    assert res.unmatched == ()


def test_r2_deliberately_ignores_suppression_state_hits(rules):
    """제압 전이 피격은 미매칭이 아니라 의도적으로 안 본다(설계 §9.2).

    표에서 R1(제압→suppresses) 행을 지웠으니 '제압'은 이제 표에 없는
    상태다. damages로도, 미매칭으로도 나오지 않고 그냥 조용히 빠진다.
    """
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="V", template="stateChange",
           state_from="기동 또는 사격 가능", state_to="제압"),
    ])
    res = r2_damage(idx, rules)
    assert res.relations == ()
    assert res.unmatched == ()


def test_r2_only_emits_states_the_table_knows(rules):
    """표에 없는 전이는 조용히 다른 관계가 되지 않는다."""
    idx = EventIndex([
        ev("H1", 10, "hitBy", actor="V", source_obj="A"),
        ev("S1", 10, "stateChangedTo", actor="V", template="stateChange",
           state_from="기동 또는 사격 가능", state_to="표에 없는 상태"),
    ])
    res = r2_damage(idx, rules)
    assert res.relations == ()
    assert res.unmatched == ()


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


# ── 규칙 간 정합성 ───────────────────────────────────────────────────────
def test_every_hit_state_pair_has_exactly_one_direct_fire_cause(idx, rules):
    """개체쌍 레이어(R2)와 이벤트쌍 레이어(R3)를 서로 봉인한다.

    같은 피격을 두 레이어가 각자 읽으므로, 한쪽 규칙이 조용히 어긋나면 두
    레이어의 (공격자, 피격자) 집합이 갈라진다. 여기서 걸린다.
    """
    by_id = {e.event_id: e for e in idx.events}
    fired = Counter()
    for r in r3_direct_fire(idx).relations:
        shot = by_id[r.subject]
        fired[(shot.actor, shot.target)] += 1
    for r in r2_damage(idx, rules).relations:
        assert fired[(r.subject, r.object)] == 1, (r.subject, r.object)


# ── 공통 계약 ────────────────────────────────────────────────────────────
def _run_all(index, rules):
    return (r2_damage(index, rules).relations
            + r3_direct_fire(index).relations
            + r4_indirect_fire(index, rules).relations
            + r7_precedes(index, rules).relations)


def test_final_derived_relations_never_emit_suppresses(idx, rules):
    """R1이 빠졌으니 최종 산출 어디에도 suppresses는 없다."""
    relations = _run_all(idx, rules)
    assert "suppresses" not in {r.predicate for r in relations}


def test_unit_and_formation_predicates_stay_removed(idx, rules):
    """설계 §10 — 부대·편제 술어 제거 상태를 회귀 테스트로 고정한다.

    옛 R5·R6·R8~R12는 UNIT-* 접두사가 붙은 부대 id를 주어로 삼았다
    (config/roster.json·2026-08-17 편제 설계 참고). 현 산출은 R2·R3·R4·R7
    뿐이고 전부 battle.jsonl의 객체·이벤트 id만 주어로 쓴다 — 부대 id는
    애초에 이 코드가 아는 값이 아니다.
    """
    relations = _run_all(idx, rules)
    assert REMOVED_UNIT_PREDICATES.isdisjoint({r.predicate
                                               for r in relations})
    # 부대가 주어인 movesToward·occupies·firesUpon도 생성하지 않는다.
    # firesUpon은 지역 대상만 남는다 — 주어가 객체인지로 판별한다.
    assert all(not r.subject.startswith("UNIT-") for r in relations)


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
    ("r2", {"R2"}), ("r3", {"R3"}), ("r4", {"R4"}), ("r7", {"R7"})])
def test_every_relation_carries_layer_rule_and_provenance(idx, rules,
                                                          rule, expected):
    """규칙마다 layer·rule_id·provenance 셋을 다 달고 나오는지 본다.

    provenance는 event_id여야 한다. 다른 id를 넣으면 `idx.ids()` 밖의 값이라
    `set(r.provenance) <= known`에서 바로 걸린다 — 원문 문장까지 되짚는 길이
    끊긴 것을 조용히 넘기지 않는다.
    """
    res = {"r2": lambda: r2_damage(idx, rules),
           "r3": lambda: r3_direct_fire(idx),
           "r4": lambda: r4_indirect_fire(idx, rules),
           "r7": lambda: r7_precedes(idx, rules)}[rule]()
    known = idx.ids()
    assert res.relations
    for r in res.relations:
        assert r.layer == "derived"
        assert r.rule_id in expected
        assert r.provenance and set(r.provenance) <= known
