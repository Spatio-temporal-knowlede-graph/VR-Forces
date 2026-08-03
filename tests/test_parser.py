from collections import Counter
from pathlib import Path

import pytest

from vtmak.paths import SCENARIO
from vtmak.parser import KNOWN_TRUNCATION, PatternMap, parse_scenario

ROOT = Path(__file__).resolve().parents[1]
SRC = SCENARIO
PMAP = ROOT / "config" / "pattern_map.csv"


@pytest.fixture(scope="module")
def result():
    pm = PatternMap.load(PMAP)
    return parse_scenario(SRC.read_text(encoding="utf-8"), pm)


def test_matches_every_sentence(result):
    """원문의 모든 문장이 템플릿에 걸리는가.

    문장 수는 원문마다 다르므로 못박지 않는다. 매칭률 100%가 불변식이다
    (선언된 절단 KNOWN_TRUNCATION만 예외).
    """
    assert result.sentence_count > 0
    leftovers = [(n, f) for n, f in result.unmatched
                 if not f.startswith(KNOWN_TRUNCATION)]
    assert leftovers == [], leftovers[:3]


def test_template_counts_hold_together(result):
    """템플릿 사이에 반드시 성립해야 하는 관계.

    개수 자체는 원문마다 다르다. 깨지면 안 되는 것은 관계다 — 사격 한 건에
    피격 한 건, 그리고 교전 보조문장(engAttacker/engSource)이 그만큼 있어야
    한다. 이게 어긋나면 사거리 판정과 태스크 생성이 같이 어긋난다.
    """
    c = Counter(e.template for e in result.events)
    assert c["directFireAt"] == c["hitBy"], (c["directFireAt"], c["hitBy"])
    assert c["indirectFireAt"] == c["hitArea"], (c["indirectFireAt"],
                                                 c["hitArea"])
    assert c["engAttacker"] >= c["directFireAt"] + c["indirectFireAt"]
    assert c["engSource"] >= c["hitBy"]
    # 초기 배치는 객체마다 한 번, 초기 상태는 그보다 많을 수 없다.
    assert c["locatedAt"] >= c["stateInit"], (c["locatedAt"], c["stateInit"])
    assert sum(c.values()) == len(result.events)


def test_fire_templates_are_not_swallowed_by_moveto(result):
    # moveTo 정규식이 '…을/를 향해 직접사격을 수행한다'도 매칭한다.
    # 사격 템플릿이 먼저 시도되지 않으면 이 테스트가 깨진다.
    fires = [e for e in result.events if e.template == "directFireAt"]
    assert fires
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
    assert inits
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
    assert locs
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
    """시각이 0에서 시작하고 뒤로 가지 않는가."""
    times = [e.time_s for e in result.events]
    assert min(times) == 0
    assert max(times) > 0


def test_event_ids_are_unique_and_deterministic(result):
    ids = [e.event_id for e in result.events]
    assert len(ids) == len(set(ids))
    pm = PatternMap.load(PMAP)
    again = parse_scenario(SRC.read_text(encoding="utf-8"), pm)
    assert [e.event_id for e in again.events] == ids
