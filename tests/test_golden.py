from pathlib import Path

import pytest

from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.golden import Golden
from vtmak.scnx.ids import IdAllocator

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "yewon_test" / "yewon_test.scnx"

# 시나리오가 쓰는 26종 — dis_catalog와 golden 양쪽에 다 있어야 한다.
SCENARIO_CLASSES = [
    "US Army M4", "Russian Soldier AK47", "Russian Soldier SA7",
    "Russian Soldier Sniper-127", "US Army XM107", "Turkish Soldier RPG",
    "US Army Javelin", "T-69 MBT", "T-72 MBT", "T-80 MBT",
    "M1A2 Abrams MBT", "BTR-60 APC", "BTR-80 APC", "LAV III APC",
    "M113 APC", "ZPU-4 AA Gun", "GAZ-66 Truck", "M35 Truck",
    "M1028 FMTV Canvas Cargo Truck", "M1083A1 FMTV Flatbed Truck",
    "MO-120RT-61 Mortar", "M109 Howitzer", "AHS Krab Howitzer",
    "CAESAR SP Howitzer", "M901 Patriot Launcher",
    "MIM-104 Patriot Launcher",
]


@pytest.fixture(scope="module")
def dis():
    return DisCatalog.load(ROOT / "config" / "dis_catalog.csv")


@pytest.fixture(scope="module")
def golden():
    return Golden.load(GOLDEN)


def test_id_allocator_is_deterministic():
    a = IdAllocator("battle")
    b = IdAllocator("battle")
    assert a.alloc("entity", "FR-INF-001") == b.alloc("entity", "FR-INF-001")
    assert a.alloc("entity", "FR-INF-001") != a.alloc("entity", "FR-INF-002")


def test_dis_catalog_resolves_hyphen_variants(dis):
    # 원문 'T-72 MBT' ↔ dis_catalog 'T 72 MBT'
    assert dis.dis("T-72 MBT") == dis.dis("T 72 MBT")
    assert dis.dis("MO-120RT-61 Mortar") is not None


def test_dis_catalog_covers_scenario_classes(dis):
    missing = [c for c in SCENARIO_CLASSES if dis.dis(c) is None]
    assert missing == []


def test_task_catalog_has_expected_type_groups():
    tc = TaskCatalog.load(ROOT / "config" / "task_catalog.csv")
    for tg in ["보병 - 소총(M4 계열)", "보병 - RPG 계열",
               "차량/장갑차 - M2HB 계열", "포병 - 155mm 자주포",
               "포병 - 박격포(m9333he 계열)"]:
        assert tc.labels_for(tg), tg


def test_task_catalog_has_the_templates_the_plan_needs():
    tc = TaskCatalog.load(ROOT / "config" / "task_catalog.csv")
    assert tc.get("보병 - 소총(M4 계열)", "대상 직접사격") is not None
    assert tc.get("포병 - 155mm 자주포", "좌표 대상 간접사격") is not None
    assert tc.get("포병 - 박격포(m9333he 계열)", "좌표 대상 간접사격") is not None
    assert tc.get("차량/장갑차 - M2HB 계열", "통제점으로 이동") is not None
    assert tc.get("보병 - 소총(M4 계열)", "좌표로 이동") is not None


def test_golden_has_a_record_for_every_scenario_dis(dis):
    g = Golden.load(GOLDEN)
    missing = [c for c in SCENARIO_CLASSES
               if g.entity_by_dis(dis.dis(c)) is None]
    assert missing == [], f"golden에 레코드 없는 모델: {missing}"


def test_object_ids_fit_the_dis_marking_limit():
    """marking은 DIS 11byte. 객체 ID에서 하이픈을 뺀 값이 들어가야 한다."""
    import json
    ids = set()
    src = ROOT / "build" / "events" / "battle.jsonl"
    if not src.exists():
        pytest.skip("02를 먼저 실행할 것")
    for line in src.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        for k in ("actor", "target", "source_obj"):
            if e[k]:
                ids.add(e[k])
    marks = [i.replace("-", "") for i in ids]
    assert all(len(m) <= 11 and m.isascii() for m in marks)
    assert len(set(marks)) == len(marks)


def test_aggregate_templates_are_found(golden):
    """골든에 대대·중대·소대 레코드가 7개 있다(2026-08-17 갱신분)."""
    aggs = golden.aggregate_templates()
    assert len(aggs) == 7
    for a in aggs:
        assert a.kind == "aggregate"
        assert a.uuid
        assert "(aggregate-state Disaggregated)" in a.raw


def test_aggregate_header_match_excludes_hyphenated_fields(golden):
    """`(aggregate`는 레코드 안쪽의 `(aggregate-state`·`(aggregate-resolution-...`
    필드에도 부분열로 매치된다. 헤더 탐색이 공백까지 포함해 좁혀졌는지,
    그래서 그 필드들이 별도 레코드로 잘려 들어오지 않는지 직접 확인한다."""
    aggs = golden.aggregate_templates()
    for a in aggs:
        assert a.raw.startswith("(aggregate ")
        assert not a.raw.startswith("(aggregate-state")
        assert not a.raw.startswith("(aggregate-resolution")
        assert a.uuid
        assert 'marking-text "' in a.raw


def test_aggregate_is_not_mistaken_for_an_entity(golden):
    """aggregate의 object-type 첫 값이 3(보병과 같다). 엔티티 템플릿으로
    새어 들어가면 보병 대신 부대 껍데기가 복제된다."""
    for o in golden.objects:
        assert o.kind != "aggregate"


def test_aggregate_header_does_not_match_hyphenated_top_level_fields():
    """합성 `.oob` 조각으로 `_parse_aggregates`를 직접 단위 테스트한다.

    실제 골든에서는 `(aggregate-state ...)`·`(aggregate-resolution-...)`가
    항상 진짜 부대 레코드 안쪽에만 있어, 위 두 테스트는 헤더를 공백 없는
    `"(aggregate"`로 되돌려도 통과해버린다(리뷰에서 지적됨) — 어느 헤더를
    쓰든 `_balanced_records`가 바깥 레코드를 통째로 삼켜 두 매칭이 실제
    골든에 대해서는 구분되지 않기 때문이다. 이 필드가 부대 레코드 **바깥**
    (최상위)에 오는 경우를 합성으로 만들어 직접 확인해야 방어가 의미를
    가진다."""
    from vtmak.scnx.golden import _parse_aggregates

    bogus_top_level = (
        '(aggregate-resolution-process-state-repository-default\n'
        '   (object-type 3 (99 9 9 9 99 9 99))\n'
        ')\n'
    )
    real_record = (
        '(aggregate \n'
        '   (vrf-entity "vrf-entity:1")\n'
        '   (uuid "VRF_UUID:11111111-1111-1111-1111-111111111111")\n'
        '   (marking-text "1-BN")\n'
        '   (object-type 3 (11 1 0 0 34 0 11))\n'
        '   (aggregate-state Disaggregated)\n'
        ')\n'
    )
    oob = bogus_top_level + real_record

    aggs = _parse_aggregates(oob)

    assert len(aggs) == 1
    assert aggs[0].uuid == "11111111-1111-1111-1111-111111111111"
    assert aggs[0].raw.startswith("(aggregate ")
