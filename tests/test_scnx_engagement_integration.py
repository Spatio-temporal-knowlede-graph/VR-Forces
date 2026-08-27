"""저작된 .scnx를 되읽어 검증한다 — 스펙(ScnxSpec)이 아니라 파일 그 자체.

이 파일이 스펙 테스트와 따로 있는 이유: ScnxSpec은 메모리 안의 모델이고,
VR-Forces가 실행하는 건 writer가 zip으로 눌러 담은 .scnx다. 스펙이 옳아도
writer가 블록 순서를 바꾸거나 하나를 빠뜨리면 시뮬레이터는 스펙이 말하는
것과 다른 걸 돌린다. 여기서는 그 간극 자체를 검사한다 — build/scnx/battle.scnx
를 vtmak.scnx.audit로 다시 파싱해서 슬롯 짝맞춤·금지 태스크·follow 종단·
고정 UAV 저작 여부를 파일에서 직접 확인한다.

이 파일이 요구하는 성질(§13 통합 테스트, 전역 제약과 대응):
- 같은 슬롯의 fire-at-target과 provide_suppressive_fire_loc 사이에는 다른
  task를 두지 않는다 → 짝은 바로 인접해야 하고, 짝 수는 슬롯 수와 같아야 한다.
- 최종 PLN에는 find_firing_position과 find_cover가 없어야 한다.
- 후속 task가 있는 무한한 follow-entity는 없어야 한다 → follow-entity는
  항상 그 플랜의 마지막 태스크여야 한다.
- config/fixed_objects.json이 선언한 고정 객체(UAV·순찰로)는 모두 저작돼야
  한다.
"""
import json
from pathlib import Path

import pytest

from vtmak.scnx.audit import read_scnx

ROOT = Path(__file__).resolve().parents[1]
SCNX = ROOT / "build" / "scnx" / "battle.scnx"
SLOTS = ROOT / "build" / "engagements" / "slots.jsonl"

pytestmark = pytest.mark.skipif(
    not SCNX.exists(), reason="04를 먼저 실행할 것")


@pytest.fixture(scope="module")
def plans():
    # read_scnx가 .pln 원문을 이미 parse_pln으로 파싱해 .plans에 담아
    # 돌려준다 — ScnxContents에는 원문 .pln 필드가 따로 없다. 여기서
    # parse_pln을 다시 부르면 존재하지 않는 속성을 읽으려다 죽는다.
    return read_scnx(SCNX).plans


def test_written_pln_pairs_every_direct_fire_with_suppressive_fire(plans):
    pairs = 0
    for plan_uuid, tasks in plans.items():
        types = [t.task_type for t in sorted(tasks, key=lambda x: x.seq)]
        for i, t in enumerate(types):
            if t != "fire-at-target":
                continue
            assert i + 1 < len(types), (plan_uuid, i)
            assert types[i + 1] == "provide_suppressive_fire_loc", \
                (plan_uuid, types[i:i + 2])
            pairs += 1
    slots = [json.loads(x) for x in
             SLOTS.read_text(encoding="utf-8").splitlines() if x]
    assert pairs == len(slots)


def test_written_pln_has_no_failing_find_tasks(plans):
    types = {t.task_type for tasks in plans.values() for t in tasks}
    assert "find_firing_position" not in types
    assert "find_cover" not in types


def test_written_pln_never_places_work_after_an_unbounded_follow(plans):
    for plan_uuid, tasks in plans.items():
        ordered = sorted(tasks, key=lambda x: x.seq)
        for i, t in enumerate(ordered):
            if t.task_type == "follow-entity":
                assert i == len(ordered) - 1, plan_uuid


def test_written_scnx_keeps_the_fixed_uav_objects_and_routes():
    contents = read_scnx(SCNX)
    declared = json.loads(
        (ROOT / "config" / "fixed_objects.json").read_text(encoding="utf-8"))
    markings = {o.marking for o in contents.objects}

    # config/fixed_objects.json에는 브리핑이 가정한 "objects": [{"marking": ..}]
    # 배열이 없다. 실제 스키마는 "markings"(UAV 마킹 목록)와
    # "patrol_centers"(순찰 중심이 있는 마킹 → 지명)다. UAV 자신은 markings가
    # 곧 선언이므로 그대로 검사한다.
    declared_markings = declared.get("markings", [])
    assert declared_markings, "fixed_objects.json에 markings가 없다"
    for marking in declared_markings:
        assert marking in markings, marking

    # 순찰로는 config가 이름으로 선언하지 않는다 — vtmak/scnx/fixed.py의
    # load_fixed가 markings 안 순번 n(1부터)과 f"UAV{n}RTE"로 결정론적으로
    # 파생시키고, patrol_centers에 그 마킹이 있을 때만 만든다. "config가
    # 선언한 고정 객체가 모두 저작됐다"는 이 테스트의 뜻을 순찰로까지
    # 넓히려면, 그 파생 규칙을 그대로 재현해서 저작된 마킹 집합에 있는지
    # 확인하는 수밖에 없다 — patrol_centers가 어떤 UAV의 라우트를 만들지
    # 결정하는 유일한 config 신호이기 때문이다.
    centers = declared.get("patrol_centers", {})
    for n, marking in enumerate(declared_markings, 1):
        if marking in centers:
            route_marking = f"UAV{n}RTE"
            assert route_marking in markings, route_marking
