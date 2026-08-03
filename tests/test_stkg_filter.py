import pytest

from vtmak.stkg.filter import Disposition, classify

TS = "2026-08-03T05:20:00.000Z"


@pytest.mark.parametrize("subject", ["1 Force", "2 Force", "3 Force",
                                     "Observer 1", "GlobalEnv 1"])
def test_infra_subjects_are_dropped(subject):
    assert classify(subject, TS) is Disposition.DROP_INFRA


@pytest.mark.parametrize("subject", ["Observer 2", "Observer 7",
                                     "4 Force", "GlobalEnv 2"])
def test_unseen_infra_numbers_are_also_dropped(subject):
    """실측 회귀 케이스. 이름을 그대로 나열했더니 다음 내보내기에 생긴
    Observer 2가 767행짜리 관측 데이터인 척 위치 테이블로 새어 들어갔다.
    VR-Forces가 인프라 객체를 몇 개 만드는지는 세션마다 다르다."""
    assert classify(subject, TS) is Disposition.DROP_INFRA


@pytest.mark.parametrize("subject", ["Observer", "Forces", "1 Forcex",
                                     "GlobalEnvoy 1", "FRINF001"])
def test_lookalike_names_are_not_dropped(subject):
    """패턴이 넓어져 실제 객체를 삼키면 안 된다."""
    assert classify(subject, TS) is Disposition.KEEP


@pytest.mark.parametrize("subject", ["E1", "E7", "E62"])
def test_effect_objects_are_dropped(subject):
    assert classify(subject, TS) is Disposition.DROP_EFFECT


@pytest.mark.parametrize("subject", ["ENINF001", "FRM109003", "P17",
                                     "M107 3", "UAV 2"])
def test_scenario_objects_are_kept(subject):
    assert classify(subject, TS) is Disposition.KEEP


def test_epoch_timestamp_is_quarantined():
    assert classify("ENT72003", "1970-01-01T12:00:04.040Z") \
        is Disposition.QUARANTINE_EPOCH


def test_quarantine_wins_over_keep_but_not_over_drop():
    """제외 대상은 격리 이전에 걸러진다 — 인프라 객체를 격리 목록에
    올려봐야 쓸 데가 없다."""
    assert classify("GlobalEnv 1", "1970-01-01T12:00:00.000Z") \
        is Disposition.DROP_INFRA


def test_entity_named_like_effect_is_not_dropped():
    """E로 시작해도 숫자만 뒤따르지 않으면 효과 객체가 아니다.
    ENINF001, ENT72003이 여기 걸리면 적군 전체가 사라진다."""
    for subject in ("ENINF001", "ENT72003", "ENCAESAR002", "ENMORT001"):
        assert classify(subject, TS) is Disposition.KEEP
