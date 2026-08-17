"""내보내기 판마다 다른 열 이름 → 표준 이름. 05와 06이 같이 쓴다."""
from vtmak.stkg.schema import REQUIRED, object_of, standardize

# 실측 헤더 그대로다.
_20260803 = ["subject", "predicate", "object", "latitude", "longitude",
             "timestamp", "source", "CID"]
_20260804 = ["object", "event", "subject", "lat", "lon", "timestamp",
             "source", "CID"]
_20260809 = ["subject", "predicate", "object", "timestamp", "latitude",
             "longitude", "source", "force", "tracking_id", "uuid",
             "entity_type", "damage", "smoke", "flaming", "mobility_kill",
             "firepower_kill", "suppression_level"]


def _row(cols, **values):
    return {c: values.get(c, "") for c in cols}


def test_20260803_passes_through_unchanged():
    row = standardize(_row(_20260803, subject="FRINF001", predicate="None"))
    assert row["subject"] == "FRINF001"
    assert row["predicate"] == "None"


def test_20260804_swaps_subject_and_object_back():
    """이름을 바꾸면서 뜻까지 맞바꿔 놓은 판이다. 20260804의 `object`가 행위
    주체이고 `subject`가 전 행 '-'인 대상 자리다. 열 하나씩 별칭을 걸면 두
    이름이 서로 덮어써서 못 푼다."""
    row = standardize(_row(_20260804, object="FRINF001", event="None",
                           subject="-", lat="21.3", lon="-157.7"))
    assert row["subject"] == "FRINF001"
    assert row["predicate"] == "None"
    assert row["object"] == "-"
    assert row["latitude"] == "21.3"
    assert row["longitude"] == "-157.7"


def test_20260809_needs_no_renaming_and_keeps_its_new_columns():
    """CID가 빠지고 상태 열 10개가 붙었지만 표준 이름은 그대로다. 새 열은
    건드리지 않고 통과시킨다 — 열 목록을 우리 쪽에 못박지 않는 이유다."""
    row = standardize(_row(_20260809, subject="ENM1A2003", damage="0",
                           entity_type="1:1:225:1:1:3:0"))
    assert row["subject"] == "ENM1A2003"
    assert row["damage"] == "0"
    assert row["entity_type"] == "1:1:225:1:1:3:0"
    assert list(row) == _20260809


def test_every_schema_supplies_the_required_columns():
    for cols in (_20260803, _20260804, _20260809):
        row = standardize(_row(cols))
        assert not [c for c in REQUIRED if c not in row]


def test_dash_means_the_object_column_is_empty():
    """내보내기는 빈 자리를 '-'로 채운다. 06이 이걸 주체로 읽어 모든 행의
    주체가 '-'가 된 적이 있다."""
    assert object_of({"object": "-"}) == ""
    assert object_of({"object": " "}) == ""
    assert object_of({}) == ""


def test_a_filled_object_column_survives():
    """20260809판 `Fire Weapon` 행만 대상이 미리 채워져 온다."""
    assert object_of({"object": "ENT72006"}) == "ENT72006"
