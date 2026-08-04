from pathlib import Path

import pytest

from vtmak.gates import blocking, check_g0, check_g1, engagement_pairs
from vtmak.geometry import BattlefieldLayout, Coord
from vtmak.paths import SCENARIO
from vtmak.parser import Event, PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env():
    pm = PatternMap.load(ROOT / "config" / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
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
    removed = lay._coord.pop("LOC_동측측방접근로")
    try:
        v = check_g1(res, lay, reg)
    finally:
        lay._coord["LOC_동측측방접근로"] = removed
    assert any(x.code == "C1.2" and "동측측방접근로" in x.detail for x in v)


def test_engagement_pairs_extracted(env):
    res, lay, _, _, reg = env
    pairs = engagement_pairs(res.events, reg, lay)
    assert {p.fire_kind for p in pairs} == {"direct", "indirect"}
    # 사격·조준 이벤트마다 한 건씩. 개수는 원문마다 다르므로 관계만 본다.
    fire = [e for e in res.events
            if e.template in ("directFireAt", "indirectFireAt", "aimAt")]
    assert len(pairs) == len(fire), (len(pairs), len(fire))
    assert all(p.distance_m > 0 for p in pairs)


def test_g0_passes_on_designed_layout(env):
    res, lay, _, wr, reg = env
    v = check_g0(res.events, reg, lay, wr)
    assert blocking(v) == [], [x.detail for x in blocking(v)]


def test_g0_reports_unverified_patriots_without_blocking(env):
    """unverified 무기체계 사격은 BLOCK이 아니라 C0.3 REPORT로 나간다.

    원문에 패트리어트 사격이 실제로 있는지에 매달리지 않는다(ver70은 이동만
    시킨다). 명부의 패트리어트로 사격 이벤트를 지어 넣고 판정만 본다.
    """
    res, lay, _, wr, reg = env
    patriots = sorted(o for o, d in reg.items()
                      if "Patriot" in d.entity_class)
    assert patriots, "명부에 패트리어트가 있어야 한다"
    # 원문에 이미 패트리어트 사격이 있을 수도 없을 수도 있다. 지어 넣은
    # 사격이 몇 건을 더 만드는지로 본다 — 원문 내용에 매달리지 않는다.
    base = [x for x in check_g0(res.events, reg, lay, wr) if x.code == "C0.3"]
    shots = [Event(event_id=f"ETEST{i}", time_s=9999, line_no=-1,
                   predicate="indirectFireAt", template="indirectFireAt",
                   actor=o, src=reg[o].initial_location, target="OBJ-009")
             for i, o in enumerate(patriots)]
    v = check_g0(res.events + shots, reg, lay, wr)
    unver = [x for x in v if x.code == "C0.3"]
    assert len(unver) == len(base) + len(patriots), [x.detail for x in unver]
    assert all(x.severity == "REPORT" for x in unver)
    assert all("Patriot" in x.detail for x in unver)
    assert blocking(v) == [], [x.detail for x in blocking(v)]


def test_g0_catches_a_layout_that_breaks_ranges(env):
    """배치를 망가뜨리면 G0가 잡는가.

    v3부터 좌표는 golden 지형점이라 scale 같은 전역 축소 손잡이가 없다. 대신
    전장을 한 점으로 뭉갠다 — 간접사격 최소사거리는 반드시 깨진다. 어떤 원문을
    넣어도 성립하는 망가뜨리기라서 이걸 쓴다.

    최소사거리 미달이 BLOCK인지 REPORT인지는 모델마다 다르므로(아래 테스트)
    여기서는 심각도를 묻지 않고 '잡히는가'만 본다.
    """
    res, lay, _, wr, reg = env
    saved = dict(lay._coord)
    one = lay._coord["LOC_중앙킬존"]
    try:
        for k in lay._coord:
            lay._coord[k] = one
        v = check_g0(res.events, reg, lay, wr)
    finally:
        lay._coord.clear()
        lay._coord.update(saved)
    assert any(x.code == "C0.1" for x in v), [x.detail for x in v][:5]


def test_g0_blocks_when_direct_fire_runs_out_of_range(env):
    """직접사격이 최대사거리를 넘으면 BLOCK으로 막는다.

    완화(REPORT)는 최소사거리에만, 그것도 표가 선언한 모델에만 적용된다.
    최대사거리 초과는 언제나 배치 오류라 파이프라인을 세워야 한다.
    """
    res, lay, _, wr, reg = env
    saved = dict(lay._coord)
    try:
        # 지명을 경도로 흩어 서로 수 km씩 떨어뜨린다 — 소총 사거리가 깨진다.
        for i, k in enumerate(sorted(lay._coord)):
            c = lay._coord[k]
            lay._coord[k] = Coord(c.lat, c.lon + 0.05 * i, c.alt)
        v = check_g0(res.events, reg, lay, wr)
    finally:
        lay._coord.clear()
        lay._coord.update(saved)
    hard = blocking(v)
    assert any(x.code == "C0.2" for x in hard), [x.detail for x in v][:5]


def test_g0_relaxes_min_range_only_for_the_declared_models(env):
    """min_severity를 REPORT로 선언한 모델만 완화된다(사용자 결정).

    나머지 모델은 그대로 BLOCK이어야 한다 — 완화가 전역 무력화가 되면
    진짜 배치 오류를 놓친다. 지금 완화된 모델은 155mm 자주포 3종과
    MO-120RT-61 박격포이고, 넷 다 근거가 weapon_ranges.csv의 note에 있다.
    """
    res, lay, _, wr, reg = env
    v = check_g0(res.events, reg, lay, wr)
    close = [x for x in v if x.code == "C0.1"]
    assert close, "골든 배치는 155mm 최소사거리를 못 채운다"
    assert all(x.severity == "REPORT" for x in close), [x.detail for x in close]
    relaxed = {c for c in wr.classes() if wr.min_severity(c) == "REPORT"}
    assert relaxed == {"M109 Howitzer", "AHS Krab Howitzer",
                       "CAESAR SP Howitzer", "MO-120RT-61 Mortar"}
    # 완화된 모델의 사격만 REPORT로 나왔는가.
    assert all(any(c in x.detail for c in relaxed) for x in close), \
        [x.detail for x in close]
    assert wr.min_severity("US Army Javelin") == "BLOCK"


def test_g0_reports_unverified_terrain(env):
    """규칙으로 민 점(파생·이동)은 지형이 확인되지 않았다는 사실을 남긴다."""
    res, lay, _, wr, reg = env
    v = check_g0(res.events, reg, lay, wr)
    unverified = [x for x in v if x.code == "C0.7"]
    assert {x.severity for x in unverified} == {"REPORT"}
    assert len(unverified) == len(lay.unverified_terrain_ids())
    assert any("중앙계곡북측" in x.detail for x in unverified)
    # 옮긴 golden 점도 같은 이유로 보고된다 — golden이 주던 육지 보증이 없다.
    assert any("아군포병진지" in x.detail for x in unverified)
