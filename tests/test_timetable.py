from pathlib import Path

import pytest

from vtmak.gates import blocking
from vtmak.geometry import BattlefieldLayout
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.registry import ClassMap, build_registry
from vtmak.timetable import build_timetable, check_g2, plan_coverage

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    cm = ClassMap.load(ROOT / "config" / "entity_class_map.csv")
    return res.events, build_registry(res.events, cm, lay.static_ids())


def test_every_taskable_object_has_plan_events(env):
    """설계 스펙 §4.5 — 플랜 보강 없이 328/328이 실제 행동을 갖는다.

    Patriot 2종도 원문에서 사격 이벤트를 갖는다. 이들이 실행 가능한 태스크를
    못 얻는 것은 type_group이 미분류라 템플릿이 없어서이며, 그건 G3가 잡는다.
    """
    events, reg = env
    have, missing = plan_coverage(events, reg)
    assert missing == set()
    assert len(have) == len([e for e in reg.values() if e.taskable])


def test_g2_passes_on_real_scenario(env):
    events, reg = env
    assert check_g2(events, reg) == []


def test_g2_blocks_when_a_classified_object_has_no_plan(env):
    events, reg = env
    # 분류된 객체의 플랜 유발 이벤트를 전부 지우면 차단되어야 한다.
    trimmed = [e for e in events
               if not (e.actor == "FR-INF-005"
                       and e.template in {"moveTo", "directFireAt"})]
    v = check_g2(trimmed, reg)
    hard = blocking(v)
    assert any("FR-INF-005" in x.detail for x in hard)


def test_timetable_covers_all_objects(env):
    events, reg = env
    cells = build_timetable(events, reg)
    assert {c.object_id for c in cells} == set(reg)


def test_cells_are_contiguous_per_object(env):
    events, reg = env
    by: dict[str, list] = {}
    for c in build_timetable(events, reg):
        by.setdefault(c.object_id, []).append(c)
    for oid, cs in by.items():
        cs.sort(key=lambda c: c.t0)
        assert cs[0].t0 == 0, oid
        for a, b in zip(cs, cs[1:]):
            assert a.t1 == b.t0, f"{oid}: {a.t1} != {b.t0}"


def test_suppressed_object_keeps_final_state(env):
    events, reg = env
    cells = [c for c in build_timetable(events, reg)
             if c.object_id == "FR-INF-001"]
    assert cells[-1].state == "제압"


def test_enemy_infantry_ends_in_killzone(env):
    events, reg = env
    cells = [c for c in build_timetable(events, reg)
             if c.object_id == "EN-INF-001"]
    assert cells[-1].location == "LOC_중앙킬존"


def test_timetable_is_deterministic(env):
    events, reg = env
    assert build_timetable(events, reg) == build_timetable(events, reg)
