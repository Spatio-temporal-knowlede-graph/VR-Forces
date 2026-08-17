"""R8~R12 — 편제와 이벤트에서 부대가 주어인 fact를 만든다.

백마고지 데이터셋은 주어가 부대인 fact가 0건이었다(변환 후 116,680행 전수).
여기서 그 자리를 메운다.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from vtmak.derive.orbat_relations import r8_part_of, r9_task_organization
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
    rels = r9_task_organization(orbat).relations
    assert Counter(r.predicate for r in rels) == {
        "supports": len(orbat.supports()),
        "reinforces": len(orbat.reinforces())}
    ids = {u.unit_id for u in orbat.units()}
    for r in rels:
        assert r.subject in ids and r.object in ids
