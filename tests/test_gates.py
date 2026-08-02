from pathlib import Path

import pytest

from vtmak.gates import blocking, check_g0, check_g1, engagement_pairs
from vtmak.geometry import BattlefieldLayout
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(
        (ROOT / "scenario_original" / "scenario_v3.txt").read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    cm = ClassMap.load(ROOT / "config" / "entity_class_map.csv")
    wr = WeaponRanges.load(ROOT / "config" / "weapon_ranges.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    return res, lay, cm, wr, reg


def test_g1_passes_on_real_scenario(env):
    res, lay, _, _, reg = env
    v = check_g1(res, lay, reg)
    assert v == [], [x.detail for x in v]


def test_g1_reports_unmatched_beyond_known_truncation(env):
    res, lay, _, _, reg = env
    res.unmatched.append((999, "이건 매칭 안 되는 문장이다"))
    try:
        v = check_g1(res, lay, reg)
    finally:
        res.unmatched.pop()
    assert any(x.code == "C1.1" for x in v)
    assert blocking(v)


def test_g1_reports_location_missing_from_layout(env):
    res, lay, _, _, reg = env
    removed = lay._local.pop("LOC_동측측방접근로")
    try:
        v = check_g1(res, lay, reg)
    finally:
        lay._local["LOC_동측측방접근로"] = removed
    assert any(x.code == "C1.2" and "동측측방접근로" in x.detail for x in v)


def test_engagement_pairs_extracted(env):
    res, lay, _, _, reg = env
    pairs = engagement_pairs(res.events, reg, lay)
    assert {p.fire_kind for p in pairs} == {"direct", "indirect"}
    # 직접 77 + 간접 21 + 조준 21
    assert len(pairs) == 119
    assert all(p.distance_m > 0 for p in pairs)


def test_g0_passes_on_designed_layout(env):
    res, lay, _, wr, reg = env
    v = check_g0(res.events, reg, lay, wr)
    assert blocking(v) == [], [x.detail for x in blocking(v)]


def test_g0_reports_unverified_patriots_without_blocking(env):
    res, lay, _, wr, reg = env
    v = check_g0(res.events, reg, lay, wr)
    unver = [x for x in v if x.code == "C0.3"]
    assert unver, "Patriot 2종이 UNVERIFIED로 보고돼야 한다"
    assert all(x.severity == "REPORT" for x in unver)
    assert all("Patriot" in x.detail for x in unver)


def test_g0_catches_shrunk_layout(env):
    res, lay, _, wr, reg = env
    lay.scale = 0.5          # M109 최소사거리 2km가 깨진다
    try:
        v = check_g0(res.events, reg, lay, wr)
    finally:
        lay.scale = 1.0
    hard = blocking(v)
    assert any(x.code == "C0.1" for x in hard)


def test_v2_layout_has_no_shrink_headroom_left(env):
    """v2는 사거리 제약에서 역산한 최소 배치라 더 줄일 여지가 없다.

    포병-킬존이 2052m로 최소사거리 2000m 바로 위다. scale을 조금만 내려도
    G0가 막는다. 즉 scale은 더 이상 축소 손잡이가 아니다.
    """
    res, lay, _, wr, reg = env
    try:
        lay.scale = 0.95
        assert blocking(check_g0(res.events, reg, lay, wr)) != []
    finally:
        lay.scale = 1.0


def test_g0_blocks_when_a_location_goes_into_the_sea(env):
    res, lay, _, wr, reg = env
    saved = lay._local["LOC_적포병진지"]
    lay._local["LOC_적포병진지"] = (1400, 2900)   # v1에서 실제로 물에 떴던 자리
    try:
        v = check_g0(res.events, reg, lay, wr)
    finally:
        lay._local["LOC_적포병진지"] = saved
    assert any(x.code == "C0.5" for x in blocking(v)), [x.detail for x in v]
