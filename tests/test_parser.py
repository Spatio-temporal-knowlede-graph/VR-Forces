from collections import Counter
from pathlib import Path

import pytest

from vtmak.parser import PatternMap, parse_scenario

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scenario_original" / "scenario_v3.txt"
PMAP = ROOT / "config" / "pattern_map.csv"


@pytest.fixture(scope="module")
def result():
    pm = PatternMap.load(PMAP)
    return parse_scenario(SRC.read_text(encoding="utf-8"), pm)


def test_matches_every_sentence_but_the_known_truncation(result):
    # 원문 PDF가 마지막 문장에서 끊겨 있다(변환 손실 아님).
    assert result.sentence_count == 3000
    assert len(result.unmatched) == 1
    line_no, frag = result.unmatched[0]
    assert line_no == 1295
    assert frag.startswith("**M1028")


def test_template_counts(result):
    c = Counter(e.template for e in result.events)
    assert c["stateChange"] == 821
    assert c["moveTo"] == 571
    assert c["locatedAt"] == 328
    assert c["stateInit"] == 294
    assert c["stateHold"] == 178
    assert c["stopAt"] == 102
    assert c["directFireAt"] == 77
    assert c["hitBy"] == 77
    assert c["stayAt"] == 77
    assert c["aimAt"] == 21
    assert c["indirectFireAt"] == 21
    assert c["hitArea"] == 21
    assert c["engAttacker"] == 118
    assert c["engSource"] == 98
    assert c["noTask"] == 77
    assert c["targetArea"] == 118


def test_fire_templates_are_not_swallowed_by_moveto(result):
    # moveTo 정규식이 '…을/를 향해 직접사격을 수행한다'도 매칭한다.
    # 사격 템플릿이 먼저 시도되지 않으면 이 테스트가 깨진다.
    fires = [e for e in result.events if e.template == "directFireAt"]
    assert len(fires) == 77
    assert all(e.target.startswith(("FR-", "EN-", "OBJ-")) for e in fires)
    assert all(not e.action_label for e in fires)


def test_actor_ids_are_explicit_not_inferred(result):
    e = next(e for e in result.events if e.template == "locatedAt")
    assert e.actor == "FR-INF-001"
    assert e.actor_class == "US Army M4"
    assert e.actor_role == "방어 보병 1"
    assert e.location == "LOC_남측제1방어선"
    assert e.time_s == 0


def test_second_mention_without_role_still_resolves(result):
    # '**US Army M4(FR-INF-001)**의 초기 상태는 …' — 역할이 빠진 2차 언급.
    inits = [e for e in result.events if e.template == "stateInit"]
    assert len(inits) == 294
    assert inits[0].actor == "FR-INF-001"
    assert inits[0].state_to == "대기"


def test_move_actions_map_to_distinct_predicates(result):
    by: dict[str, set[str]] = {}
    for e in result.events:
        if e.template == "moveTo":
            by.setdefault(e.action_label, set()).add(e.predicate)
    assert by["후퇴 이동"] == {"retreatTo"}
    assert by["방어선 재편성 이동"] == {"defend"}
    assert by["공격 대형 이동"] == {"approach"}
    assert by["지상 이동"] == {"moveTo"}
    assert by["보급 이동 및 정차"] == {"transportTo"}


def test_locations_are_normalised_to_loc_ids(result):
    locs = {e.location for e in result.events if e.location}
    locs |= {e.src for e in result.events if e.src}
    locs |= {e.dst for e in result.events if e.dst}
    assert len(locs) == 27
    assert all(l.startswith("LOC_") for l in locs)
    assert "LOC_남측제1방어선" in locs
    assert "LOC_동측측방접근로" in locs


def test_static_target_class_and_role_captured(result):
    # 정적 객체는 사격 목표로만 등장한다. 여기서 못 잡으면 레지스트리가 빈다.
    e = next(e for e in result.events
             if e.template == "indirectFireAt" and e.target == "EN-FP-001")
    assert e.target_class == "포병진지"
    assert e.target_role == "적 자주포 사격진지"


def test_time_range(result):
    times = [e.time_s for e in result.events]
    assert min(times) == 0
    assert max(times) == 6 * 60 + 56


def test_event_ids_are_unique_and_deterministic(result):
    ids = [e.event_id for e in result.events]
    assert len(ids) == len(set(ids))
    pm = PatternMap.load(PMAP)
    again = parse_scenario(SRC.read_text(encoding="utf-8"), pm)
    assert [e.event_id for e in again.events] == ids
