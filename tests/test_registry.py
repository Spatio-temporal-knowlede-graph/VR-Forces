from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import UNVERIFIED, WeaponRanges
from vtmak.registry import (UNCLASSIFIED, ClassMap, build_registry,
                            collect_locations, faction_of)

ROOT = Path(__file__).resolve().parents[1]
SRC = SCENARIO


@pytest.fixture(scope="module")
def ctx():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(SRC.read_text(encoding="utf-8"), pm)
    lay = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    cm = ClassMap.load(ROOT / "config" / "entity_class_map.csv")
    return res, cm, lay, build_registry(res.events, cm, lay.static_ids())


def test_registry_covers_every_actor(ctx):
    """원문에 등장한 객체가 하나도 빠지지 않았는가.

    개수는 원문마다 다르다. 불변식은 '이벤트가 가리키는 객체는 전부 레지스트리에
    있다'이다 — 빠지면 그 객체의 태스크가 조용히 사라진다.
    """
    res, _, _, reg = ctx
    refs = {r for e in res.events for r in (e.actor, e.target, e.source_obj) if r}
    assert refs - set(reg) == set()


def test_taskable_split_matches_layout(ctx):
    """정적 객체는 레이아웃이 정하고, 나머지는 전부 task 대상이다."""
    _, _, lay, reg = ctx
    static = [o for o, e in reg.items() if not e.taskable]
    assert set(static) == lay.static_ids() & set(reg)
    assert len(reg) == len(static) + len([e for e in reg.values() if e.taskable])


def test_faction_from_id_prefix():
    assert faction_of("FR-INF-001") == "BLUE"
    assert faction_of("EN-T72-001") == "RED"
    assert faction_of("OBJ-009") == "NEUTRAL"


def test_every_taskable_class_is_known_to_class_map(ctx):
    _, cm, _, reg = ctx
    unknown = sorted({e.entity_class for e in reg.values()
                      if e.taskable and not cm.known(e.entity_class)})
    assert unknown == []


def test_class_map_covers_every_model_in_the_scenario(ctx):
    """원문에 나오는 모델이 전부 entity_class_map에 있는가.

    빠진 모델은 미분류가 되어 태스크를 하나도 못 받는다. 새 원문으로 갈아끼울 때
    가장 먼저 깨지는 자리라 개수가 아니라 커버리지를 본다.
    """
    _, cmap, _, reg = ctx
    models = {e.entity_class for e in reg.values() if e.taskable}
    missing = sorted(m for m in models if not cmap.known(m))
    assert missing == [], missing
    # 표에 있어도 '미분류'면 템플릿을 못 골라 플랜이 빈다. 지금은 전 모델이
    # 분류돼 있고, 새 모델을 미분류로 넣으면 여기서 걸린다.
    declared = sorted(m for m in models
                      if cmap.known(m) and cmap.type_group(m) == UNCLASSIFIED)
    assert declared == [], declared


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


def test_patriots_have_their_own_group_but_stay_weapon_unverified(ctx):
    """§8.3 보류는 무기 쪽에만 남는다.

    type_group은 '이 모델이 어떤 태스크 템플릿을 쓰는가'를 고르는 키다.
    미분류로 두면 원문이 이동·사격을 시켜도 플랜이 비고, 차량 그룹에 넣으면
    BTR·트럭까지 간접사격 템플릿을 갖는다. 그래서 전용 그룹을 준다(사용자 결정
    2026-08-03). '지상 간접사격이 성립하는가'라는 §8.3 질문은 그대로 미확정이고
    weapon_ranges.csv의 unverified가 계속 붙잡는다.
    """
    _, _, _, reg = ctx
    wr = WeaponRanges.load(ROOT / "config" / "weapon_ranges.csv")
    for oid in ("FR-M901-001", "EN-MIM-001"):
        assert reg[oid].type_group == "미사일 발사대 - Patriot", oid
        assert wr.check(reg[oid].entity_class, "indirect", 3000.0) == UNVERIFIED


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
    missing = [l for l in collect_locations(res.events) if not lay.has(l)]
    assert missing == []


def test_registry_is_deterministic(ctx):
    res, cm, lay, reg = ctx
    again = build_registry(res.events, cm, lay.static_ids())
    assert list(reg) == list(again)
    assert reg == again
