from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import PatternMap, parse_scenario
from vtmak.registry import ClassMap, build_registry, collect_locations, faction_of

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scenario_original" / "scenario_v3.txt"


@pytest.fixture(scope="module")
def ctx():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(SRC.read_text(encoding="utf-8"), pm)
    lay = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    cm = ClassMap.load(ROOT / "config" / "entity_class_map.csv")
    return res, cm, lay, build_registry(res.events, cm, lay.static_ids())


def test_registry_has_335_objects(ctx):
    _, _, _, reg = ctx
    assert len(reg) == 335


def test_taskable_split_matches_scenario(ctx):
    _, _, _, reg = ctx
    assert len([e for e in reg.values() if e.taskable]) == 328
    assert len([e for e in reg.values() if not e.taskable]) == 7


def test_faction_from_id_prefix():
    assert faction_of("FR-INF-001") == "BLUE"
    assert faction_of("EN-T72-001") == "RED"
    assert faction_of("OBJ-009") == "NEUTRAL"


def test_every_taskable_class_is_known_to_class_map(ctx):
    _, cm, _, reg = ctx
    unknown = sorted({e.entity_class for e in reg.values()
                      if e.taskable and not cm.known(e.entity_class)})
    assert unknown == []


def test_class_map_covers_26_models(ctx):
    _, _, _, reg = ctx
    assert len({e.entity_class for e in reg.values() if e.taskable}) == 26


def test_initial_location_and_state_captured(ctx):
    _, _, _, reg = ctx
    e = reg["FR-INF-001"]
    assert e.entity_class == "US Army M4"
    assert e.role == "방어 보병 1"
    assert e.initial_location == "LOC_남측제1방어선"
    assert e.initial_state == "대기"
    assert e.type_group == "보병 - 소총(M4 계열)"
    assert "M4 rifle" in e.weapons


def test_new_models_have_type_groups(ctx):
    _, _, _, reg = ctx
    assert reg["EN-M1A2-001"].type_group == "차량/장갑차 - M2HB 계열"
    assert reg["EN-SA7-001"].type_group == "보병 - RPG 계열"


def test_patriots_are_unclassified_by_design(ctx):
    # 설계 스펙 §8.3 — 무기체계 미확정. 조용히 넘기지 않고 미분류로 남긴다.
    _, _, _, reg = ctx
    assert reg["FR-M901-001"].type_group == "미분류"
    assert reg["EN-MIM-001"].type_group == "미분류"


def test_static_objects_have_no_class_but_keep_role(ctx):
    _, _, _, reg = ctx
    e = reg["EN-FP-001"]
    assert e.taskable is False
    assert e.role == "적 자주포 사격진지"
    assert e.entity_class == "포병진지"


def test_every_taskable_object_has_an_initial_location(ctx):
    _, _, _, reg = ctx
    missing = sorted(o for o, e in reg.items()
                     if e.taskable and not e.initial_location)
    assert missing == []


def test_all_27_locations_resolve_in_layout(ctx):
    res, _, lay, _ = ctx
    missing = [l for l in collect_locations(res.events) if lay.local(l) is None]
    assert missing == []


def test_registry_is_deterministic(ctx):
    res, cm, lay, reg = ctx
    again = build_registry(res.events, cm, lay.static_ids())
    assert list(reg) == list(again)
    assert reg == again
