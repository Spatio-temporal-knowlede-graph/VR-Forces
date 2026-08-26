"""R8~R12 — 편제와 이벤트에서 부대가 주어인 fact를 만든다.

백마고지 데이터셋은 주어가 부대인 fact가 0건이었다(변환 후 116,680행 전수).
여기서 그 자리를 메운다.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from vtmak.derive.config import DeriveRules
from vtmak.derive.events import EventIndex
from vtmak.derive.orbat_relations import (r8_part_of, r9_task_organization,
                                          r10_unit_moves, r11_unit_occupies,
                                          r12_unit_fires)
from vtmak.geometry import BattlefieldLayout
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.parser import Event
from vtmak.registry import ClassMap, build_registry

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
EVENTS = ROOT / "build" / "events" / "battle.jsonl"


@pytest.fixture(scope="module")
def orbat():
    evs = [Event(**{k: v for k, v in json.loads(l).items()
                    if k != "source_line"})
           for l in open(EVENTS, encoding="utf-8")]
    layout = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    reg = build_registry(evs, ClassMap.load(CFG / "entity_class_map.csv"),
                         layout.static_ids())
    return build_orbat(reg, OrbatConfig.load(CFG / "orbat.json"))


def test_r8_covers_every_entity_and_child_unit(orbat):
    """엔티티 전원 + 상위가 있는 부대 전부. 대대만 상위가 없다."""
    rels = r8_part_of(orbat).relations
    assert all(r.predicate == "partOf" for r in rels)
    n_members = sum(len(u.members) for u in orbat.units())
    n_children = sum(1 for u in orbat.units() if u.parent)
    assert len(rels) == n_members + n_children


def test_r8_chain_reaches_the_battalion(orbat):
    """엔티티 → 소대 → (중대) → 대대로 닫힌다. 홉은 2단과 3단이 섞인다."""
    up = {r.subject: r.object for r in r8_part_of(orbat).relations}
    for u in orbat.units():
        for oid in u.members:
            cur, hops = oid, 0
            while cur in up:
                cur, hops = up[cur], hops + 1
            assert orbat.get(cur).echelon == "대대", oid
            assert hops in (2, 3), (oid, hops)


def test_r8_is_layered_as_orbat(orbat):
    """편제표가 선언한 값이지 관측에서 파생한 값이 아니다."""
    from vtmak.derive.orbat_relations import LAYER_ORBAT
    assert {r.layer for r in r8_part_of(orbat).relations} == {LAYER_ORBAT}


def test_r9_uses_only_declared_pairs(orbat):
    """개수(Counter)만이 아니라 (subject, object) 쌍 자체가 일치해야 한다.

    술어별 개수만 맞춰서는 한 쌍의 subject/object가 뒤바뀌어도 통과한다 —
    오늘은 supports 5·reinforces 3으로 개수가 달라 우연히 걸리지 않을
    뿐이다. 그래서 쌍 집합을 orbat.supports()/reinforces()와 그대로
    맞춘다.
    """
    rels = r9_task_organization(orbat).relations
    assert Counter(r.predicate for r in rels) == {
        "supports": len(orbat.supports()),
        "reinforces": len(orbat.reinforces())}
    ids = {u.unit_id for u in orbat.units()}
    for r in rels:
        assert r.subject in ids and r.object in ids

    got = {p: {(r.subject, r.object) for r in rels if r.predicate == p}
          for p in ("supports", "reinforces")}
    assert got["supports"] == set(orbat.supports())
    assert got["reinforces"] == set(orbat.reinforces())


# ── R10~R12 관측에서 나오는 부대 사실 ────────────────────────────────────
@pytest.fixture(scope="module")
def idx():
    return EventIndex.load(EVENTS)


@pytest.fixture(scope="module")
def rules():
    return DeriveRules.load(CFG / "derive_rules.csv")


def _unit_subject(rels, orbat):
    ids = {u.unit_id for u in orbat.units()}
    return all(r.subject in ids for r in rels)


def test_r10_subject_is_a_unit(idx, orbat, rules):
    """부대가 주어인 fact를 만든다 — 백마고지에는 0건이었다."""
    rels = r10_unit_moves(idx, orbat, rules).relations
    assert rels, "0건이면 unit_move_ratio나 moveTo 이벤트를 본다"
    assert {r.predicate for r in rels} == {"movesToward"}
    assert _unit_subject(rels, orbat)


def test_r10_keys_on_time_not_just_unit_and_destination(idx, orbat, rules):
    """국면을 접기 키에서 빼면(모든 시각을 하나로) 같은 (소대, 목적지)가
    한 건으로 합쳐진다 — 백마고지가 걸린 바로 그 함정이다. 실측값
    (2026-08-18, unit_fold_window_s=5: 119건, 고유 (소대,목적지) 쌍 106개)은
    그 둘이 다르다는 것 자체가 국면 구분이 산출물에 남아 있다는 증거다.
    창을 300초로 올리면(서로 다른 국면이 합쳐짐) 106건으로 줄어 이 부등식이
    깨진다(직접 확인함 — 아래 리뷰 회귀 확인 항목 참고).
    """
    rels = r10_unit_moves(idx, orbat, rules).relations
    pairs = {(r.subject, r.object) for r in rels}
    assert len(rels) == 119
    assert len(pairs) == 106
    assert len(rels) > len(pairs)


def test_r10_window_absorbs_report_jitter_across_the_whole_platoon(idx, orbat,
                                                                    rules):
    """1초 입도(창=0)의 결함 — 리뷰에서 지적된 사실을 고정한다.

    20명짜리 보병소대가 통째로 이동해도 보고가 60·61·62초로 갈리면 창=0에서는
    과반을 못 채운다. 리뷰 실측: 52개 소대 중 16개(20명 보병소대 8개 포함)가
    '실제로 이동했는데 R10이 0건'이었다. unit_fold_window_s=5로 그 16개가
    전부 사라지는지 여기서 확인한다.
    """
    move_platoons = {orbat.platoon_of(e.actor) for e in idx.events
                     if e.template == "moveTo" and orbat.platoon_of(e.actor)}
    subjects = {r.subject for r in r10_unit_moves(idx, orbat, rules).relations}
    assert move_platoons - subjects == set()


def test_r11_occupies_a_place(idx, orbat, rules):
    rels = r11_unit_occupies(idx, orbat, rules).relations
    assert rels, "0건이면 unit_occupy_ratio나 stopAt/stayAt 이벤트를 본다"
    assert {r.predicate for r in rels} == {"occupies"}
    assert _unit_subject(rels, orbat)
    assert all(r.object.startswith("LOC_") for r in rels)
    #  2026-08-18 실측: EN 기갑 1중대 1소대가 중앙킬존을 점령한다.
    pairs = {(r.subject, r.object) for r in rels}
    assert ("UNIT-EN-ARM-CO1-PL1", "LOC_중앙킬존") in pairs


def test_r12_fires_upon_something(idx, orbat, rules):
    rels = r12_unit_fires(idx, orbat, rules).relations
    assert rels, "0건이면 unit_fire_ratio를 본다(사격은 소수가 한다)"
    assert {r.predicate for r in rels} == {"firesUpon"}
    assert _unit_subject(rels, orbat)
    #  2026-08-18 실측: EN 화기 1중대 1소대가 FR-LN-001(방어선)에 사격한다.
    pairs = {(r.subject, r.object) for r in rels}
    assert ("UNIT-EN-FIRE-CO1-PL1", "FR-LN-001") in pairs


def test_observed_unit_facts_are_not_layered_as_orbat(idx, orbat, rules):
    """관측에서 나온 값은 편제표 선언과 다른 레이어여야 한다."""
    from vtmak.derive.orbat_relations import LAYER_ORBAT
    for res in (r10_unit_moves(idx, orbat, rules),
                r11_unit_occupies(idx, orbat, rules),
                r12_unit_fires(idx, orbat, rules)):
        assert LAYER_ORBAT not in {r.layer for r in res.relations}


def test_r6_counts_by_platoon_when_orbat_is_given(idx, orbat, rules):
    """편제를 주면 R6의 분모가 타입 접두사가 아니라 소대가 된다."""
    from vtmak.derive.relations import r6_unit_suppressed
    ids = {u.unit_id for u in orbat.units()}
    res = r6_unit_suppressed(idx, rules, orbat=orbat).relations
    assert res, "0건이면 orbat 경로의 unit_members가 조용히 비었다는 뜻이다"
    for r in res:
        assert r.subject in ids
    #  2026-08-18 실측: 타입 접두사(EN-INF·FR-INF) 대신 소대 단위로 갈린다.
    assert {r.subject for r in res} == {
        "UNIT-EN-INF-CO1-PL1", "UNIT-EN-INF-CO1-PL2", "UNIT-FR-INF-CO1-PL1"}


def test_r10_produces_a_known_platoon_time_destination_triple(idx, orbat, rules):
    """구체값 단언 — 술어·부대 소속만 맞고 내용이 틀려도 위 구조적 단언들은
    통과한다. 여기서는 실측으로 확인한 (소대, 목적지) 조합 하나가 실제로
    나오는지 고정한다. 값이 바뀌면 _fold의 접기 로직이나 임계값이 바뀐
    것이다.
    """
    rels = r10_unit_moves(idx, orbat, rules).relations
    pairs = {(r.subject, r.object) for r in rels}
    #  2026-08-18 실측: 대공소대(UNIT-EN-AD-PL1)가 적북측접근로로 이동한다.
    #  이 조합이 없어지면 _fold의 접기 로직이나 unit_move_ratio가 바뀐 것이다.
    assert ("UNIT-EN-AD-PL1", "LOC_적북측접근로") in pairs
