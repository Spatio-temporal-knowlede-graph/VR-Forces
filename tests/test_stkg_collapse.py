from vtmak.stkg.collapse import Relation, collapse
from vtmak.stkg.derive import Obs


def _obs(sec, subject="FRINF001", obj="ENINF001"):
    return Obs(subject, "follows", obj, "entity",
               f"2026-08-03T05:20:{sec:02d}.000Z", "GROUND_TRUTH",
               "observed", "raw")


def test_consecutive_ticks_become_one_interval():
    out = collapse([_obs(0), _obs(1), _obs(2)])
    assert len(out) == 1
    assert out[0].t_start == "2026-08-03T05:20:00.000Z"
    assert out[0].t_end == "2026-08-03T05:20:02.000Z"


def test_a_gap_splits_the_interval():
    """관측 공백을 이어붙이면 관측하지 않은 구간을 관측했다고 주장하게 된다."""
    out = collapse([_obs(0), _obs(1), _obs(30), _obs(31)])
    assert len(out) == 2
    assert out[0].t_end == "2026-08-03T05:20:01.000Z"
    assert out[1].t_start == "2026-08-03T05:20:30.000Z"


def test_exact_duplicates_collapse_to_one_row():
    """입력의 54.5%가 완전중복이다. 같은 tick이 여러 번 와도 한 구간이다."""
    out = collapse([_obs(0), _obs(0), _obs(0)])
    assert len(out) == 1
    assert out[0].t_start == out[0].t_end == "2026-08-03T05:20:00.000Z"


def test_different_objects_do_not_merge():
    out = collapse([_obs(0, obj="ENINF001"), _obs(1, obj="ENSA7001")])
    assert len(out) == 2


def test_different_subjects_do_not_merge():
    out = collapse([_obs(0, subject="FRINF001"), _obs(1, subject="FRINF002")])
    assert len(out) == 2


def test_unsorted_input_is_handled():
    out = collapse([_obs(2), _obs(0), _obs(1)])
    assert len(out) == 1
    assert out[0].t_start == "2026-08-03T05:20:00.000Z"


def test_empty_input_returns_empty():
    assert collapse([]) == []
