from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.stkg.locate import Snap, snap

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def layout():
    return BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")


def test_exact_match_returns_the_place_name(layout):
    lid = layout.location_ids()[0]
    result = snap(layout.coord(lid).to_ecef(), layout)
    assert result.object_id == lid
    assert result.object_type == "location"
    assert result.distance_m < 1.0


def test_nearby_control_point_is_used_when_no_place_matches(layout):
    """지명에서 멀지만 통제점 반경 안이면 통제점을 쓴다."""
    x, y, z = layout.coord(layout.location_ids()[0]).to_ecef()
    far = (x + 3000.0, y + 3000.0, z + 3000.0)
    result = snap(far, layout, control_points={"P7": (far[0] + 5.0,
                                                     far[1], far[2])})
    assert result.object_id == "P7"
    assert result.object_type == "location"
    assert 0.0 < result.distance_m < 50.0


def test_falls_back_to_coord_when_nothing_is_near(layout):
    x, y, z = layout.coord(layout.location_ids()[0]).to_ecef()
    far = (x + 5000.0, y + 5000.0, z + 5000.0)
    result = snap(far, layout)
    assert result.object_type == "coord"
    assert result.distance_m == -1.0
    assert result.object_id == f"{far[0]:.6f},{far[1]:.6f},{far[2]:.6f}"


def test_control_points_absent_skips_step_two(layout):
    """현재 빌드는 통제점을 저작하지 않는다. None이 와도 죽지 않아야 한다."""
    x, y, z = layout.coord(layout.location_ids()[0]).to_ecef()
    result = snap((x + 100.0, y, z), layout, control_points=None)
    assert result.object_type == "coord"


def test_place_name_wins_over_a_closer_control_point(layout):
    """1단계 정확 일치가 2단계보다 항상 먼저다."""
    lid = layout.location_ids()[0]
    exact = layout.coord(lid).to_ecef()
    result = snap(exact, layout,
                  control_points={"P1": (exact[0] + 0.1, exact[1], exact[2])})
    assert result.object_id == lid


def test_real_destination_from_measured_data_resolves(layout):
    """실측: Move to 목적지 27,342행이 LOC_중앙킬존에 0.0m로 붙는다."""
    result = snap((-5499123.141030, -2250320.406046, 2311025.754248), layout)
    assert result.object_type == "location"
    assert result.distance_m < 1.0
