"""후보 쌍 — 짧은 거리와 포병 사거리는 탐색 반경이 두 자릿수 차이라 경로를 나눈다."""
import pytest

from vtmak.geometry import Coord, deg_scales, ground_distance
from vtmak.ranges import RangeSpec
from vtmak.spatial.pair import Placement, engagement_pairs, local_pairs
from vtmak.spatial.profile import EntityProfile

LAT, LON = 21.38, -157.74
LAT_M, LON_M = deg_scales(LAT)


def _profile(direct=None, indirect=None, spacing=2.0):
    return EntityProfile(
        entity_class="X", type_group="보병 - 소총(M4 계열)", spacing_m=spacing,
        direct=None if direct is None else RangeSpec(*direct),
        indirect=None if indirect is None else RangeSpec(*indirect),
    )


def _at(name, east_m=0.0, north_m=0.0, profile=None, force="1", heading=0.0):
    return Placement(
        subject=name,
        coord=Coord(LAT + north_m / LAT_M, LON + east_m / LON_M, 0.0),
        heading_deg=heading, profile=profile, force=force,
    )


def test_deg_scales_is_public_and_positive():
    lat_m, lon_m = deg_scales(21.38)
    assert lat_m > 100_000
    assert 0 < lon_m < lat_m


class TestLocalPairs:
    def test_yields_pairs_within_the_radius(self):
        pairs = list(local_pairs([_at("A"), _at("B", east_m=30.0)], 100.0))
        assert len(pairs) == 1
        assert pairs[0][2] == pytest.approx(30.0, abs=0.5)

    def test_excludes_pairs_beyond_the_radius(self):
        assert list(local_pairs([_at("A"), _at("B", east_m=500.0)], 100.0)) == []

    def test_yields_each_unordered_pair_once(self):
        given = [_at("A"), _at("B", east_m=1.0), _at("C", east_m=2.0)]
        names = {tuple(sorted((a.subject, b.subject))) for a, b, _ in local_pairs(given, 100.0)}
        assert names == {("A", "B"), ("A", "C"), ("B", "C")}

    def test_finds_pairs_straddling_a_grid_cell_boundary(self):
        given = [_at("A", east_m=99.0), _at("B", east_m=101.0)]
        assert len(list(local_pairs(given, 100.0))) == 1

    def test_handles_identical_coordinates(self):
        pairs = list(local_pairs([_at("A"), _at("B")], 100.0))
        assert len(pairs) == 1
        assert pairs[0][2] == pytest.approx(0.0, abs=1e-6)

    def test_distance_matches_ground_distance(self):
        a, b = _at("A"), _at("B", east_m=250.0, north_m=120.0)
        pairs = list(local_pairs([a, b], 500.0))
        assert pairs[0][2] == pytest.approx(ground_distance(a.coord, b.coord))

    def test_empty_input_yields_nothing(self):
        assert list(local_pairs([], 100.0)) == []


class TestEngagementPairs:
    def test_only_armed_entities_seed_pairs(self):
        given = [_at("S", profile=_profile(direct=(0.0, 1000.0))),
                 _at("T", east_m=500.0, profile=_profile())]
        assert [(a.subject, b.subject) for a, b, _ in engagement_pairs(given, 4000.0)] == [("S", "T")]

    def test_unarmed_entities_can_still_be_targets(self):
        given = [_at("S", profile=_profile(direct=(0.0, 1000.0))),
                 _at("T", east_m=100.0, profile=None)]
        assert len(list(engagement_pairs(given, 4000.0))) == 1

    def test_yields_both_directions_when_both_are_armed(self):
        given = [_at("A", profile=_profile(direct=(0.0, 1000.0))),
                 _at("B", east_m=100.0, profile=_profile(direct=(0.0, 1000.0)))]
        assert {(a.subject, b.subject) for a, b, _ in engagement_pairs(given, 4000.0)} == {
            ("A", "B"), ("B", "A")}

    def test_excludes_targets_beyond_the_seed_max_range(self):
        given = [_at("S", profile=_profile(direct=(0.0, 400.0))),
                 _at("T", east_m=900.0, profile=_profile())]
        assert list(engagement_pairs(given, 4000.0)) == []

    def test_artillery_reaching_past_the_field_sweeps_everything(self):
        given = [_at("G", profile=_profile(indirect=(2000.0, 42000.0))),
                 _at("F", east_m=3000.0, profile=_profile())]
        assert [(a.subject, b.subject) for a, b, _ in engagement_pairs(given, 4000.0)] == [("G", "F")]

    def test_never_pairs_an_entity_with_itself(self):
        assert list(engagement_pairs([_at("G", profile=_profile(direct=(0.0, 1000.0)))], 4000.0)) == []

    def test_no_armed_entity_yields_nothing(self):
        assert list(engagement_pairs([_at("A"), _at("B", east_m=10.0)], 4000.0)) == []
