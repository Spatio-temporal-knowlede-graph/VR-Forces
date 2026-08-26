"""DIS 열거값 → 클래스 → type_group·사거리.

dis_catalog는 'T 72 MBT', 나머지 둘은 'T-72 MBT'로 적는다. vtmak.norm.norm이
이미 그 키를 맞춰 주므로 이 모듈은 정규화를 새로 만들지 않는다.
"""
import pytest

from vtmak.spatial.profile import ProfileIndex

DIS = """entity_class,dis,domain,source_note
T 72 MBT,1 1 222 1 2 1 0,land,하이픈 없는 표기
US Army M4,1 1 225 1 1 3 0,land,
CAESAR SP Howitzer,1 1 71 4 0 0 0,land,
M35 Truck,1 1 225 2 3 0 0,land,무장 없음
"""
CLASS_MAP = """entity_class,type_group,weapons,unsupported_tasks,note
T-72 MBT,차량/장갑차 - M2HB 계열,,,
US Army M4,보병 - 소총(M4 계열),,,
CAESAR SP Howitzer,포병 - 155mm 자주포,,,
M35 Truck,차량/장갑차 - M2HB 계열,,,
"""
RANGES = """entity_class,direct_min_m,direct_max_m,indirect_min_m,indirect_max_m,unverified,min_severity,note
T-72 MBT,0,2500,,,0,,
US Army M4,0,500,,,0,,
CAESAR SP Howitzer,,,2000,42000,0,,
M35 Truck,,,,,0,,
"""


@pytest.fixture
def index(tmp_path):
    (tmp_path / "dis_catalog.csv").write_text(DIS, encoding="utf-8")
    (tmp_path / "entity_class_map.csv").write_text(CLASS_MAP, encoding="utf-8")
    (tmp_path / "weapon_ranges.csv").write_text(RANGES, encoding="utf-8")
    return ProfileIndex.load(tmp_path)


def test_joins_across_the_hyphen_mismatch(index):
    p = index.of("1:1:222:1:2:1:0")
    assert p is not None
    assert p.entity_class == "T-72 MBT"
    assert p.type_group == "차량/장갑차 - M2HB 계열"
    assert p.spacing_m == 10.0


def test_reads_direct_range(index):
    p = index.of("1:1:222:1:2:1:0")
    assert p.direct.min_m == 0.0
    assert p.direct.max_m == 2500.0
    assert p.indirect is None


def test_reads_indirect_range_with_a_minimum(index):
    p = index.of("1:1:71:4:0:0:0")
    assert p.indirect.min_m == 2000.0
    assert p.indirect.max_m == 42000.0
    assert p.direct is None
    assert p.max_range_m == 42000.0


def test_max_range_is_none_for_an_unarmed_class(index):
    p = index.of("1:1:225:2:3:0:0")
    assert p is not None
    assert p.max_range_m is None


def test_accepts_both_colon_and_space_separated_dis(index):
    assert index.of("1 1 222 1 2 1 0") == index.of("1:1:222:1:2:1:0")


def test_unknown_entity_type_returns_none(index):
    assert index.of("9:9:999:9:9:9:9") is None


def test_blank_entity_type_returns_none(index):
    assert index.of("") is None


def test_rejects_a_class_missing_from_the_class_map(tmp_path):
    (tmp_path / "dis_catalog.csv").write_text(DIS, encoding="utf-8")
    (tmp_path / "entity_class_map.csv").write_text(
        "entity_class,type_group,weapons,unsupported_tasks,note\n"
        "US Army M4,보병 - 소총(M4 계열),,,\n", encoding="utf-8")
    (tmp_path / "weapon_ranges.csv").write_text(RANGES, encoding="utf-8")
    with pytest.raises(ValueError, match="CLASS_JOIN_MISMATCH"):
        ProfileIndex.load(tmp_path)


def test_rejects_an_unknown_type_group(tmp_path):
    (tmp_path / "dis_catalog.csv").write_text(DIS, encoding="utf-8")
    (tmp_path / "entity_class_map.csv").write_text(
        CLASS_MAP.replace("차량/장갑차 - M2HB 계열", "정체불명 계열"), encoding="utf-8")
    (tmp_path / "weapon_ranges.csv").write_text(RANGES, encoding="utf-8")
    with pytest.raises(ValueError, match="CLASS_JOIN_MISMATCH"):
        ProfileIndex.load(tmp_path)


def test_uses_the_real_config_directory():
    """실제 config가 세 파일 사이에서 어긋나지 않는지 확인한다."""
    from vtmak.paths import CONFIG
    index = ProfileIndex.load(CONFIG)
    p = index.of("1:1:222:1:2:1:0")  # T-72 MBT
    assert p is not None
    assert p.spacing_m == 10.0
    assert p.entity_class == "T-72 MBT"
