import json
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout, Coord, ground_distance
from vtmak.norm import loc_id
from vtmak.scnx.golden import Golden
from vtmak.scnx.pack import ensure_golden

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "battlefield_layout.json"
RULES = ROOT / "config" / "layout_rules.json"


@pytest.fixture(scope="module")
def layout():
    return BattlefieldLayout.load(CONFIG)


@pytest.fixture(scope="module")
def rules():
    return json.loads(RULES.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden_points(rules):
    g = Golden.load(ensure_golden(ROOT / rules["golden_dir"]))
    alias = rules.get("aliases") or {}
    return {alias.get(o.marking.strip()) or loc_id(o.marking):
            Coord.from_ecef(*o.position)
            for o in g.points_and_areas() if o.position}


def test_ecef_roundtrip():
    c = Coord(21.3860, -157.7420, 0.0)
    back = Coord.from_ecef(*c.to_ecef())
    assert abs(back.lat - c.lat) < 1e-9
    assert abs(back.lon - c.lon) < 1e-9
    assert abs(back.alt - c.alt) < 1e-3


def test_golden_points_are_the_source_of_truth(layout, rules, golden_points):
    """레이아웃의 golden 지명은 golden 통제점과 좌표가 같아야 한다.

    사람이 VR-Forces에서 찍은 점이 정본이고, 레이아웃은 그 사본이다.
    누가 battlefield_layout.json을 손으로 고치면 여기서 걸린다.

    relocate 규칙으로 옮긴 점만 예외다. 그 점들은 golden에서 수확한 뒤 규칙이
    옮긴 것이라 src가 golden이 아니고, golden 통제점과 좌표도 다르다.
    """
    relocated = set(rules.get("relocate") or {})
    anchored = [i for i in layout.location_ids()
                if layout.source_of(i) == "golden"]
    assert len(anchored) + len(relocated) == len(golden_points)
    for lid in anchored:
        assert lid in golden_points, lid
        assert ground_distance(layout.coord(lid), golden_points[lid]) < 0.5
    # 옮긴 점은 golden에서 왔지만 좌표는 규칙이 정한 만큼 떨어져 있어야 한다.
    for lid, spec in (rules.get("relocate") or {}).items():
        assert layout.source_of(lid) == "relocated", lid
        assert lid in golden_points, lid
        d = ground_distance(layout.coord(lid), golden_points[lid])
        assert abs(d - float(spec["dist_m"])) < 1.0, (lid, d)


def test_every_scenario_location_resolves(layout):
    """원문이 쓰는 지명 27개가 전부 좌표를 얻는가."""
    ids = set(layout.location_ids())
    for must in ["LOC_남측제1방어선", "LOC_적북측집결지", "LOC_중앙킬존",
                 "LOC_아군포병진지", "LOC_적박격포진지", "LOC_동측측방접근로",
                 "LOC_북측전방방어선", "LOC_아군후방지휘소", "LOC_목표A남측"]:
        assert must in ids
    assert len([i for i in ids if layout.source_of(i) == "derived"]) == 6


def test_aliases_land_on_the_scenario_name(layout, rules, golden_points):
    """golden 표기와 원문 표기가 다른 두 곳이 원문 이름으로 들어왔는가."""
    for golden_name, scenario_id in rules["aliases"].items():
        assert layout.has(scenario_id), scenario_id
        assert not layout.has(loc_id(golden_name)), golden_name
        assert scenario_id in golden_points


def test_derived_points_sit_at_the_declared_distance(layout, rules):
    for lid, spec in rules["derived"].items():
        d = layout.distance_m(lid, spec["base"])
        assert abs(d - spec["dist_m"]) < 1.0, f"{lid}: {d:.0f}m"


def test_derived_direction_follows_the_battle_axis(layout):
    """dir='북'은 적 쪽, '남'은 아군 쪽이다. 실제 나침반이 아니다.

    golden 실측: 동측능선이 실제 서쪽, 서측능선이 실제 동쪽에 있다. 나침반으로
    읽으면 전부 뒤집히므로 축 기준으로 민다.
    """
    # 동측 측방 접근로는 동측 능선보다 적(= 적 북측 집결지) 쪽에 있어야 한다.
    assert (layout.distance_m("LOC_동측측방접근로", "LOC_적북측집결지")
            < layout.distance_m("LOC_동측능선", "LOC_적북측집결지"))
    # 포병진지 후방은 아군 포병진지보다 적에게서 더 멀어야 한다.
    assert (layout.distance_m("LOC_포병진지또는방어선후방", "LOC_중앙킬존")
            > layout.distance_m("LOC_아군포병진지", "LOC_중앙킬존"))
    # 목표A 남측은 목표A보다 아군 제1방어선에 가까워야 한다.
    assert (layout.distance_m("LOC_목표A남측", "LOC_남측제1방어선")
            < layout.distance_m("LOC_목표A", "LOC_남측제1방어선"))


def test_close_quarters_pair_stays_inside_rifle_range(layout):
    """원문 04:31 교전 쌍. AK47 유효사거리 400m 안이어야 한다."""
    d = layout.distance_m("LOC_중앙계곡북측", "LOC_남측제1방어선전방")
    assert d <= 400.0, f"{d:.0f}m"


def test_unknown_location_returns_zero(layout):
    assert layout.coord("LOC_없는지명").is_zero()


def test_static_targets_bind_to_locations(layout):
    assert layout.static_target("EN-FP-001") == "LOC_적포병진지"
    assert layout.static_target("OBJ-009") == "LOC_중앙킬존"
    assert layout.static_target("FR-INF-001") is None
    assert len(layout.static_ids()) == 7


def test_offset_coord_shifts_by_metres(layout):
    base = layout.coord("LOC_중앙킬존")
    for east, north, expect in [(100.0, 0.0, 100.0), (0.0, 1000.0, 1000.0),
                                (3000.0, 4000.0, 5000.0)]:
        off = layout.offset_coord("LOC_중앙킬존", east, north)
        d = ground_distance(base, off)
        assert abs(d - expect) < 0.5, f"({east},{north}): {d}"


def test_altitudes_come_from_the_terrain(layout):
    """golden 지형점은 고도를 갖고 있다. v2의 일괄 0을 대체한다."""
    alts = [layout.coord(i).alt for i in layout.location_ids()]
    assert max(alts) > 50.0
    assert all(a > -5.0 for a in alts)


def test_deterministic(layout):
    a = [layout.coord(i).as_tuple() for i in layout.location_ids()]
    b = [layout.coord(i).as_tuple() for i in layout.location_ids()]
    assert a == b


import math

from vtmak.geometry import Coord, bearing_elevation


def test_bearing_is_zero_due_north_and_grows_clockwise():
    here = Coord(21.39, -157.74, 0.0)
    north = Coord(21.40, -157.74, 0.0)
    east = Coord(21.39, -157.73, 0.0)
    south = Coord(21.38, -157.74, 0.0)

    assert bearing_elevation(here, north)[0] == pytest.approx(0.0, abs=1e-3)
    assert bearing_elevation(here, east)[0] == pytest.approx(math.pi / 2,
                                                             abs=1e-3)
    assert bearing_elevation(here, south)[0] == pytest.approx(math.pi,
                                                              abs=1e-3)


def test_bearing_stays_in_zero_to_two_pi():
    here = Coord(21.39, -157.74, 0.0)
    west = Coord(21.39, -157.75, 0.0)
    az, _ = bearing_elevation(here, west)
    assert 0.0 <= az < 2 * math.pi
    assert az == pytest.approx(3 * math.pi / 2, abs=1e-3)


def test_elevation_is_positive_when_target_is_higher():
    low = Coord(21.39, -157.74, 0.0)
    high = Coord(21.39, -157.74, 100.0)
    far_high = Coord(21.40, -157.74, 100.0)

    assert bearing_elevation(low, high)[1] > 0
    assert bearing_elevation(high, low)[1] < 0
    # 멀수록 같은 고도차의 고각은 작아진다
    assert bearing_elevation(low, far_high)[1] < bearing_elevation(low, high)[1]


def test_same_point_is_flat_and_north():
    p = Coord(21.39, -157.74, 50.0)
    assert bearing_elevation(p, p) == (0.0, 0.0)
