"""매초 방출은 2m 컷에서도 원본의 15배다. 구간 인코딩은 전제조건이다."""
from vtmak.spatial.interval import IntervalAccumulator
from vtmak.spatial.models import Observation

NEXT_TO = Observation("A", "next_to", "B")
OTHER = Observation("A", "next_to", "C")


def test_single_observation_becomes_a_degenerate_interval():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [NEXT_TO])
    out = acc.close()
    assert len(out) == 1
    assert (out[0].t_start, out[0].t_end, out[0].support_count) == ("t0", "t0", 1)


def test_consecutive_observations_merge_into_one_interval():
    acc = IntervalAccumulator(3.0)
    for i in range(4):
        acc.observe(f"t{i}", float(i), [NEXT_TO])
    out = acc.close()
    assert len(out) == 1
    assert (out[0].t_start, out[0].t_end, out[0].support_count) == ("t0", "t3", 4)


def test_a_gap_within_the_limit_still_merges():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [NEXT_TO])
    acc.observe("t3", 3.0, [NEXT_TO])
    assert len(acc.close()) == 1


def test_a_gap_beyond_the_limit_splits_the_interval():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [NEXT_TO])
    acc.observe("t227", 227.0, [NEXT_TO])
    out = acc.close()
    assert len(out) == 2
    assert [i.support_count for i in out] == [1, 1]


def test_relation_dropping_out_closes_the_interval():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [NEXT_TO])
    acc.observe("t1", 1.0, [])
    acc.observe("t2", 2.0, [NEXT_TO])
    out = acc.close()
    assert len(out) == 2
    assert out[0].t_end == "t0"
    assert out[1].t_start == "t2"


def test_independent_relations_track_separately():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [NEXT_TO, OTHER])
    acc.observe("t1", 1.0, [NEXT_TO])
    assert {(i.object, i.support_count) for i in acc.close()} == {("B", 2), ("C", 1)}


def test_support_count_totals_the_observed_samples():
    acc = IntervalAccumulator(3.0)
    for i in range(10):
        acc.observe(f"t{i}", float(i), [NEXT_TO])
    assert sum(i.support_count for i in acc.close()) == 10


def test_evidence_is_carried_onto_the_interval():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [Observation("S", "in_range_of", "T", "direct")])
    assert acc.close()[0].evidence == "direct"


def test_intervals_come_back_sorted():
    acc = IntervalAccumulator(3.0)
    acc.observe("t0", 0.0, [OTHER, NEXT_TO])
    rows = [(i.subject, i.predicate, i.object) for i in acc.close()]
    assert rows == sorted(rows)


def test_no_interval_spans_a_gap_beyond_the_limit():
    acc = IntervalAccumulator(3.0)
    times = [0.0, 1.0, 2.0, 60.0, 61.0]
    for i, s in enumerate(times):
        acc.observe(f"t{i}", s, [NEXT_TO])
    out = acc.close()
    assert len(out) == 2
    assert [i.support_count for i in out] == [3, 2]


def test_intervals_for_one_triple_come_back_in_time_order():
    # 문자열 정렬이면 't10'이 't9'보다 앞선다. 구간 순서는 시각을 따라야 한다.
    acc = IntervalAccumulator(3.0)
    acc.observe("t9", 9.0, [NEXT_TO])
    acc.observe("t10", 100.0, [NEXT_TO])      # 간격이 상한을 넘어 구간이 갈린다
    out = acc.close()
    assert [i.t_start for i in out] == ["t9", "t10"]
