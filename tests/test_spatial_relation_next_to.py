"""next_to는 거리만 본다. '옆'이라는 말이 좌우를 뜻하지 않는다."""
from vtmak.ranges import RangeSpec
from vtmak.spatial.profile import EntityProfile
from vtmak.spatial.relation import judge_next_to, next_to_threshold
from vtmak.spatial.thresholds import Thresholds

INF = EntityProfile("US Army M4", "보병 - 소총(M4 계열)", 2.0, RangeSpec(0.0, 500.0), None)
TANK = EntityProfile("T-72 MBT", "차량/장갑차 - M2HB 계열", 10.0, RangeSpec(0.0, 2500.0), None)
HOW = EntityProfile("CAESAR SP Howitzer", "포병 - 155mm 자주포", 15.0, None, RangeSpec(2000.0, 42000.0))
T = Thresholds()


def test_infantry_pair_uses_six_metres():
    assert next_to_threshold(INF, INF, T) == 6.0


def test_tank_pair_uses_thirty_metres():
    assert next_to_threshold(TANK, TANK, T) == 30.0


def test_mixed_pair_uses_the_larger_spacing():
    assert next_to_threshold(INF, TANK, T) == 30.0


def test_howitzer_pair_uses_fortyfive_metres():
    assert next_to_threshold(HOW, HOW, T) == 45.0


def test_inside_the_threshold_holds():
    assert judge_next_to(5.9, INF, INF, T) is True


def test_exactly_at_the_threshold_holds():
    assert judge_next_to(6.0, INF, INF, T) is True


def test_beyond_the_threshold_does_not_hold():
    assert judge_next_to(6.1, INF, INF, T) is False


def test_overlapping_coordinates_still_count():
    assert judge_next_to(0.0, INF, INF, T) is True


def test_missing_profile_never_holds():
    assert judge_next_to(1.0, None, INF, T) is False
    assert judge_next_to(1.0, INF, None, T) is False


def test_multiplier_comes_from_thresholds():
    assert judge_next_to(19.0, INF, INF, Thresholds(next_to_multiplier=10.0)) is True
