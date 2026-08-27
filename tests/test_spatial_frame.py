"""한 시각의 관계 전부. 방출 정책(소속 필터·Follow 제외)이 여기 있다."""
from vtmak.geometry import Coord, deg_scales
from vtmak.ranges import RangeSpec
from vtmak.spatial.frame import judge_frame
from vtmak.spatial.pair import Placement
from vtmak.spatial.profile import EntityProfile
from vtmak.spatial.quality import COORDINATE_COLLISION, QualityLog
from vtmak.spatial.thresholds import Thresholds

LAT, LON = 21.38, -157.74
LAT_M, LON_M = deg_scales(LAT)
INF = EntityProfile("US Army M4", "보병 - 소총(M4 계열)", 2.0, RangeSpec(0.0, 500.0), None)
UNARMED = EntityProfile("M35 Truck", "차량/장갑차 - M2HB 계열", 10.0, None, None)
T = Thresholds()
SPAN = 4000.0


def _at(name, east_m=0.0, north_m=0.0, heading=0.0, profile=INF, force="1"):
    return Placement(name, Coord(LAT + north_m / LAT_M, LON + east_m / LON_M, 0.0),
                     heading, profile, force)


def _triples(obs):
    return {(o.subject, o.predicate, o.object) for o in obs}


class TestNextTo:
    def test_close_pair_produces_next_to(self):
        got = _triples(judge_frame("t0", [_at("A"), _at("B", east_m=3.0)],
                                   set(), T, SPAN, QualityLog()))
        assert ("A", "next_to", "B") in got

    def test_active_follow_pair_is_excluded(self):
        got = _triples(judge_frame("t0", [_at("A"), _at("B", east_m=3.0)],
                                   {frozenset({"A", "B"})}, T, SPAN, QualityLog()))
        assert ("A", "next_to", "B") not in got

    def test_active_follow_pair_still_gets_direction(self):
        got = _triples(judge_frame("t0", [_at("A", north_m=100.0), _at("B")],
                                   {frozenset({"A", "B"})}, T, SPAN, QualityLog()))
        assert ("A", "in_front_of", "B") in got

    def test_unmapped_profile_skips_next_to_but_keeps_direction(self):
        got = _triples(judge_frame("t0", [_at("A", north_m=100.0, profile=None), _at("B")],
                                   set(), T, SPAN, QualityLog()))
        assert ("A", "next_to", "B") not in got
        assert ("A", "in_front_of", "B") in got


class TestDirection:
    def test_uses_the_object_heading_not_the_subject_heading(self):
        # B는 북쪽을 보고 A는 B의 북쪽에 있다. A가 남쪽을 봐도 결과는 같아야 한다.
        got = _triples(judge_frame("t0", [_at("A", north_m=100.0, heading=180.0),
                                          _at("B", heading=0.0)],
                                   set(), T, SPAN, QualityLog()))
        assert ("A", "in_front_of", "B") in got
        assert ("B", "in_front_of", "A") in got

    def test_missing_heading_skips_only_that_direction(self):
        got = _triples(judge_frame("t0", [_at("A", north_m=100.0, heading=None),
                                          _at("B", heading=0.0)],
                                   set(), T, SPAN, QualityLog()))
        assert ("A", "in_front_of", "B") in got
        assert ("B", "in_front_of", "A") not in got

    def test_overlapping_coordinates_produce_no_direction_and_are_logged(self):
        log = QualityLog()
        got = _triples(judge_frame("t0", [_at("A"), _at("B")], set(), T, SPAN, log))
        assert not {p for _, p, _ in got} & {"in_front_of", "behind"}
        assert [i.code for i in log.issues()] == [COORDINATE_COLLISION]


class TestInRange:
    def test_opposing_forces_produce_in_range_of(self):
        got = _triples(judge_frame("t0", [_at("S", force="1"), _at("T", east_m=300.0, force="2")],
                                   set(), T, SPAN, QualityLog()))
        assert ("S", "in_range_of", "T") in got

    def test_same_force_is_filtered_out(self):
        got = _triples(judge_frame("t0", [_at("S", force="1"), _at("T", east_m=300.0, force="1")],
                                   set(), T, SPAN, QualityLog()))
        assert ("S", "in_range_of", "T") not in got

    def test_unarmed_shooter_produces_nothing(self):
        got = _triples(judge_frame("t0", [_at("S", profile=UNARMED, force="1"),
                                          _at("T", east_m=300.0, force="2")],
                                   set(), T, SPAN, QualityLog()))
        assert ("S", "in_range_of", "T") not in got

    def test_evidence_records_the_fire_mode(self):
        # T도 INF(사거리 500m)면 S·T가 서로의 사거리 안이라 engagement_pairs가
        # 양방향을 다 낸다(test_spatial_pair.py의
        # test_yields_both_directions_when_both_are_armed로 확정된 동작).
        # 여기서 보려는 건 evidence 문자열 하나뿐이라 T는 비무장으로 둬서
        # S→T 한 방향만 남긴다.
        obs = judge_frame("t0", [_at("S", force="1"),
                                 _at("T", east_m=300.0, force="2", profile=UNARMED)],
                          set(), T, SPAN, QualityLog())
        assert [o.evidence for o in obs if o.predicate == "in_range_of"] == ["direct"]


def test_approach_is_never_produced():
    obs = judge_frame("t0", [_at("A"), _at("B", east_m=3.0)], set(), T, SPAN, QualityLog())
    assert "approach" not in {o.predicate for o in obs}
