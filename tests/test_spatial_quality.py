"""품질 리포트는 (시각, 코드)로 묶는다.

편대 붕괴가 시각당 4,945쌍이라 쌍 단위로 내면 리포트가 산출물보다 커진다.
"""
from vtmak.spatial.quality import (COORDINATE_COLLISION, MISSING_HEADING,
                                   QualityLog)


def test_records_a_single_issue():
    log = QualityLog()
    log.record("t0", ["FRINF001"], MISSING_HEADING, "방위 없음")
    issues = log.issues()
    assert len(issues) == 1
    assert issues[0].subjects == "FRINF001"
    assert issues[0].code == MISSING_HEADING


def test_groups_collisions_at_the_same_timestamp_into_one_row():
    log = QualityLog()
    log.record("t0", ["ENINF001", "ENINF002"], COORDINATE_COLLISION, "")
    log.record("t0", ["ENINF002", "ENINF003"], COORDINATE_COLLISION, "")
    issues = log.issues()
    assert len(issues) == 1
    assert issues[0].subjects == "ENINF001 ENINF002 ENINF003"


def test_keeps_different_codes_apart_at_the_same_timestamp():
    log = QualityLog()
    log.record("t0", ["A", "B"], COORDINATE_COLLISION, "")
    log.record("t0", ["A"], MISSING_HEADING, "")
    assert len(log.issues()) == 2


def test_keeps_the_same_code_apart_across_timestamps():
    log = QualityLog()
    log.record("t0", ["A", "B"], COORDINATE_COLLISION, "")
    log.record("t1", ["A", "B"], COORDINATE_COLLISION, "")
    assert len(log.issues()) == 2


def test_issues_are_ordered_by_timestamp_then_code():
    log = QualityLog()
    log.record("t1", ["A"], MISSING_HEADING, "")
    log.record("t0", ["B"], MISSING_HEADING, "")
    stamps = [i.timestamp for i in log.issues()]
    assert stamps == sorted(stamps)


def test_count_reflects_grouped_rows():
    log = QualityLog()
    log.record("t0", ["A", "B"], COORDINATE_COLLISION, "")
    log.record("t0", ["C", "D"], COORDINATE_COLLISION, "")
    assert log.count == 1


def test_recording_the_same_subject_twice_does_not_duplicate_it():
    log = QualityLog()
    log.record("t0", ["A"], MISSING_HEADING, "")
    log.record("t0", ["A"], MISSING_HEADING, "")
    assert log.issues()[0].subjects == "A"
