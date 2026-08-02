import math
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout, Coord, ground_distance

CONFIG = Path(__file__).resolve().parents[1] / "config" / "battlefield_layout.json"


@pytest.fixture(scope="module")
def layout():
    return BattlefieldLayout.load(CONFIG)


def test_ecef_roundtrip():
    c = Coord(21.3860, -157.7420, 0.0)
    back = Coord.from_ecef(*c.to_ecef())
    assert abs(back.lat - c.lat) < 1e-9
    assert abs(back.lon - c.lon) < 1e-9
    assert abs(back.alt - c.alt) < 1e-3


def test_origin_maps_to_killzone():
    # 중앙 킬존이 로컬 원점이므로 layout origin과 같은 좌표여야 한다.
    lay = BattlefieldLayout.load(CONFIG)
    c = lay.coord("LOC_중앙킬존")
    assert abs(c.lat - 21.38001) < 1e-9
    assert abs(c.lon - (-157.74632)) < 1e-9


def test_local_meters_survive_projection(layout):
    # 설계 스펙 §3.5의 검증 거리가 실제로 재현되는가.
    for a, b, expect in [
        ("LOC_중앙킬존", "LOC_중앙킬존남측", 200.0),
        ("LOC_아군포병진지", "LOC_중앙킬존", 2052.0),
        ("LOC_적포병진지", "LOC_아군포병진지", 2850.0),
    ]:
        d = layout.distance_m(a, b)
        assert abs(d - expect) / expect < 0.002, f"{a}->{b}: {d} vs {expect}"


def test_all_27_locations_present(layout):
    ids = layout.location_ids()
    assert len(ids) == 27
    for must in ["LOC_남측제1방어선", "LOC_적북측집결지", "LOC_중앙킬존",
                 "LOC_아군포병진지", "LOC_적박격포진지", "LOC_동측측방접근로"]:
        assert must in ids


def test_unknown_location_returns_zero(layout):
    assert layout.coord("LOC_없는지명").is_zero()


def test_static_targets_bind_to_locations(layout):
    assert layout.static_target("EN-FP-001") == "LOC_적포병진지"
    assert layout.static_target("OBJ-009") == "LOC_중앙킬존"
    assert layout.static_target("FR-INF-001") is None
    assert len(layout.static_ids()) == 7


def test_scale_multiplies_distances():
    lay = BattlefieldLayout.load(CONFIG)
    base = lay.distance_m("LOC_아군포병진지", "LOC_중앙킬존")
    lay.scale = 0.5
    assert abs(lay.distance_m("LOC_아군포병진지", "LOC_중앙킬존") - base / 2) < 5.0


def test_deterministic(layout):
    a = [layout.coord(i).as_tuple() for i in layout.location_ids()]
    b = [layout.coord(i).as_tuple() for i in layout.location_ids()]
    assert a == b


def test_declared_metres_equal_measured_metres(layout):
    # 레이아웃이 선언한 로컬 미터가 실제 ECEF 거리와 같아야 한다.
    # 사거리 판정 전체가 이 등식에 의존한다.
    base = layout.coord("LOC_중앙킬존")
    for dx, dy, expect in [(1000.0, 0.0, 1000.0), (0.0, 1000.0, 1000.0),
                           (3000.0, 4000.0, 5000.0)]:
        d = ground_distance(base, layout.offset_coord("LOC_중앙킬존", dx, dy))
        assert abs(d - expect) < 0.5, f"({dx},{dy}): {d} != {expect}"


def test_offset_coord_shifts_by_local_meters(layout):
    base = layout.coord("LOC_중앙킬존")
    off = layout.offset_coord("LOC_중앙킬존", 100.0, 0.0)
    assert abs(ground_distance(base, off) - 100.0) < 0.5


def test_layout_is_compact_enough_for_the_terrain(layout):
    """v1은 6.8x4.0km로 퍼져 북동쪽 객체가 만에 빠졌다. v2는 압축본이다."""
    xs = [layout.local(i)[0] for i in layout.location_ids()]
    ys = [layout.local(i)[1] for i in layout.location_ids()]
    assert max(xs) - min(xs) <= 3000
    assert max(ys) - min(ys) <= 3500


def test_every_location_is_on_land(layout):
    wet = [(i, layout.land_margin_m(i)) for i in layout.location_ids()
           if layout.land_margin_m(i) < layout.coast_margin_m]
    assert wet == [], wet


def test_land_boundary_reproduces_the_observed_wet_objects(layout):
    """v1에서 실제로 바다에 떴던 세 지점을 해안선 모델이 바다로 판정하는가.

    좌표는 v1 로컬 프레임 기준이라 원점 이동분(북북동 800m)을 더해서 본다.
    """
    nx, ny = layout.coast_normal
    for x, y, name in [(200, 2800, "적포병진지"), (900, 2600, "적북측지휘소"),
                       (1400, 2900, "북측관측소")]:
        margin = layout.coast_offset_m - 800 - (nx * x + ny * y)
        assert margin < 0, f"{name} 은 바다로 판정돼야 한다 (여유 {margin:.0f}m)"
    for x, y, name in [(-200, 2400, "적북측집결지"), (-900, 2400, "적박격포진지"),
                       (-1500, 3400, "적후방보급집결지")]:
        margin = layout.coast_offset_m - 800 - (nx * x + ny * y)
        assert margin > 0, f"{name} 은 육지로 판정돼야 한다 (여유 {margin:.0f}m)"
