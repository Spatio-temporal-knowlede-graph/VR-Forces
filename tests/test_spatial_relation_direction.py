"""(A, in_front_of, B)는 B의 방위 기준이다. 측면 90°는 의도적으로 비어 있다."""
import math

import pytest

from vtmak.geometry import Coord, bearing_elevation
from vtmak.spatial.relation import judge_direction, relative_bearing_deg
from vtmak.spatial.thresholds import Thresholds

T = Thresholds()


class TestRelativeBearing:
    def test_same_direction_is_zero(self):
        assert relative_bearing_deg(90.0, 90.0) == pytest.approx(0.0)

    def test_clockwise_offset_is_positive(self):
        assert relative_bearing_deg(0.0, 30.0) == pytest.approx(30.0)

    def test_counterclockwise_offset_is_negative(self):
        assert relative_bearing_deg(0.0, 330.0) == pytest.approx(-30.0)

    def test_opposite_direction_is_positive_one_eighty(self):
        assert relative_bearing_deg(0.0, 180.0) == pytest.approx(180.0)

    def test_wraps_across_north(self):
        assert relative_bearing_deg(350.0, 10.0) == pytest.approx(20.0)

    def test_result_stays_in_the_half_open_range(self):
        for heading in range(0, 360, 17):
            for bearing in range(0, 360, 13):
                value = relative_bearing_deg(float(heading), float(bearing))
                assert -180.0 < value <= 180.0


class TestJudgeDirection:
    def test_dead_ahead_is_in_front_of(self):
        assert judge_direction(100.0, 0.0, T) == "in_front_of"

    def test_boundary_fortyfive_is_in_front_of(self):
        assert judge_direction(100.0, 45.0, T) == "in_front_of"
        assert judge_direction(100.0, -45.0, T) == "in_front_of"

    def test_just_past_fortyfive_is_lateral(self):
        assert judge_direction(100.0, 45.1, T) is None
        assert judge_direction(100.0, -45.1, T) is None

    def test_dead_astern_is_behind(self):
        assert judge_direction(100.0, 180.0, T) == "behind"

    def test_boundary_onethirtyfive_is_lateral(self):
        assert judge_direction(100.0, 135.0, T) is None
        assert judge_direction(100.0, -135.0, T) is None

    def test_just_past_onethirtyfive_is_behind(self):
        assert judge_direction(100.0, 135.1, T) == "behind"
        assert judge_direction(100.0, -135.1, T) == "behind"

    def test_broadside_has_no_relation(self):
        assert judge_direction(100.0, 90.0, T) is None
        assert judge_direction(100.0, -90.0, T) is None

    def test_beyond_interest_distance_has_no_relation(self):
        assert judge_direction(500.1, 0.0, T) is None

    def test_exactly_at_interest_distance_still_holds(self):
        assert judge_direction(500.0, 0.0, T) == "in_front_of"

    def test_overlapping_coordinates_have_no_relation(self):
        assert judge_direction(0.4, 0.0, T) is None

    def test_missing_relative_bearing_has_no_relation(self):
        assert judge_direction(100.0, None, T) is None


class TestWithRealBearings:
    """B가 동쪽을 볼 때, B의 동쪽에 있는 A는 B의 앞이다."""

    def _offset(self, observer: Coord, other: Coord, heading_deg: float) -> float:
        az_rad, _ = bearing_elevation(observer, other)
        return relative_bearing_deg(heading_deg, math.degrees(az_rad))

    def test_east_facing_observer_sees_eastern_neighbour_ahead(self):
        b = Coord(21.38, -157.74, 0.0)
        a = Coord(21.38, -157.739, 0.0)          # 동쪽
        assert judge_direction(100.0, self._offset(b, a, 90.0), T) == "in_front_of"

    def test_east_facing_observer_sees_western_neighbour_behind(self):
        b = Coord(21.38, -157.74, 0.0)
        a = Coord(21.38, -157.741, 0.0)          # 서쪽
        assert judge_direction(100.0, self._offset(b, a, 90.0), T) == "behind"

    def test_east_facing_observer_sees_northern_neighbour_laterally(self):
        b = Coord(21.38, -157.74, 0.0)
        a = Coord(21.381, -157.74, 0.0)          # 북쪽
        assert judge_direction(100.0, self._offset(b, a, 90.0), T) is None
