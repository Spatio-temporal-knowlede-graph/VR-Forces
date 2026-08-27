"""(A, in_range_of, B) = B가 A의 명목 사거리 안에 있다. 최소사거리를 지킨다."""
from vtmak.ranges import RangeSpec
from vtmak.spatial.profile import EntityProfile
from vtmak.spatial.relation import judge_in_range

RIFLE = EntityProfile("US Army M4", "보병 - 소총(M4 계열)", 2.0, RangeSpec(0.0, 500.0), None)
JAVELIN = EntityProfile("US Army Javelin", "보병 - RPG 계열", 2.0, RangeSpec(65.0, 2500.0), None)
HOW = EntityProfile("CAESAR SP Howitzer", "포병 - 155mm 자주포", 15.0, None, RangeSpec(2000.0, 42000.0))
TRUCK = EntityProfile("M35 Truck", "차량/장갑차 - M2HB 계열", 10.0, None, None)
HYBRID = EntityProfile("가상", "차량/장갑차 - M2HB 계열", 10.0, RangeSpec(0.0, 3000.0), RangeSpec(1000.0, 8000.0))


def test_direct_fire_inside_range():
    assert judge_in_range(300.0, RIFLE) == "direct"


def test_direct_fire_at_the_maximum_holds():
    assert judge_in_range(500.0, RIFLE) == "direct"


def test_direct_fire_beyond_the_maximum_does_not_hold():
    assert judge_in_range(500.1, RIFLE) is None


def test_minimum_range_is_enforced():
    assert judge_in_range(64.0, JAVELIN) is None
    assert judge_in_range(65.0, JAVELIN) == "direct"


def test_indirect_fire_respects_its_minimum():
    assert judge_in_range(1999.0, HOW) is None
    assert judge_in_range(2000.0, HOW) == "indirect"


def test_indirect_fire_inside_range():
    assert judge_in_range(3000.0, HOW) == "indirect"


def test_unarmed_class_never_holds():
    assert judge_in_range(10.0, TRUCK) is None


def test_missing_profile_never_holds():
    assert judge_in_range(10.0, None) is None


def test_both_conditions_yield_one_combined_evidence():
    assert judge_in_range(1500.0, HYBRID) == "direct|indirect"


def test_only_direct_below_the_indirect_minimum():
    assert judge_in_range(500.0, HYBRID) == "direct"


def test_only_indirect_beyond_the_direct_maximum():
    assert judge_in_range(5000.0, HYBRID) == "indirect"
