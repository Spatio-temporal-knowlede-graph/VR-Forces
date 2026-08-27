"""?덉쭏 由ы룷?몃뒗 (?쒓컖, 肄붾뱶)濡?臾띕뒗??

?몃? 遺뺢눼媛 ?쒓컖??4,945?띿씠?????⑥쐞濡??대㈃ 由ы룷?멸? ?곗텧臾쇰낫??而ㅼ쭊??
"""
from vtmak.spatial.quality import (COORDINATE_COLLISION, MISSING_HEADING,
                                   QualityLog)


def test_records_a_single_issue():
    log = QualityLog()
    log.record("t0", ["FRINF001"], MISSING_HEADING, "諛⑹쐞 ?놁쓬")
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


def test_issues_are_ordered_by_timestamp():
    log = QualityLog()
    log.record("t1", ["A"], MISSING_HEADING, "")
    log.record("t0", ["B"], MISSING_HEADING, "")
    assert [i.timestamp for i in log.issues()] == ["t0", "t1"]


def test_issues_at_one_timestamp_are_ordered_by_code():
    log = QualityLog()
    # 삽입 순서와 코드 순서를 어긋나게 넣는다. 정렬이 빠지면 이 순서가 그대로 나온다.
    log.record("t0", ["A"], MISSING_HEADING, "")
    log.record("t0", ["B"], COORDINATE_COLLISION, "")
    assert [i.code for i in log.issues()] == [COORDINATE_COLLISION, MISSING_HEADING]


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

