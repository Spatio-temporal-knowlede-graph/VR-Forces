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

이 파일의 네 테스트는 모두 커밋된 build/scnx/battle.scnx를 읽는다 — 그래서
누군가 plan.py를 고치고 04를 다시 안 돌리면, 파일은 그대로인데 코드만
바뀌어도 이 네 테스트는 낡은 zip을 상대로 계속 통과한다(리뷰 라운드 2
Fix 4). 아래 test_committed_scnx_matches_a_fresh_rebuild가 그 간극을
닫는다 — build_spec을 지금 코드로 다시 돌려 tmp_path에 쓰고, 그 바이트가
커밋된 파일과 정확히 같은지 SHA-256으로 확인한다. 같으면 위 네 테스트가
검사하는 파일이 지금 코드가 만드는 파일과 같다는 뜻이고, 다르면 04를 다시
돌려 build/를 재커밋해야 한다는 뜻이다. 결정성 자체(같은 입력 → 같은
바이트)는 이 비교가 자동으로 함께 증명한다 — 기존 결정성 테스트가 한
프로세스 안에서 두 번 빌드해 비교하던 것과 달리, 이번에는 그 두 번째
빌드가 애초에 커밋 시점에 다른 프로세스(04 실행)가 만든 것이라 더 강하다.
"""
import hashlib
import json
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import Event, PatternMap
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.scnx.audit import read_scnx
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.engagements import EnrichmentConfig
from vtmak.scnx.fixed import load_fixed
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.spec import build_spec
from vtmak.scnx.writer import get_writer

ROOT = Path(__file__).resolve().parents[1]
SCNX = ROOT / "build" / "scnx" / "battle.scnx"
SLOTS = ROOT / "build" / "engagements" / "slots.jsonl"
CFG = ROOT / "config"
EVENTS = ROOT / "build" / "events" / "battle.jsonl"

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


def test_committed_scnx_matches_a_fresh_rebuild(tmp_path):
    """커밋된 build/scnx/battle.scnx가 **지금** 코드로 다시 빌드한 것과
    바이트 단위로 같은가. scripts/04_compile_scnx.py의 빌드 절차(레지스트리
    →스펙→writer)를 그대로 재현해 tmp_path에 쓰고 SHA-256을 비교한다 —
    build/를 실제로 덮어쓰지 않는다.

    다르면 둘 중 하나다: (a) 코드가 바뀌었는데 04를 다시 안 돌려 build/가
    낡았다 — 04를 다시 돌리고 build/를 재커밋한다. (b) writer나 IdAllocator
    같은 결정성 불변식이 깨졌다 — 그 자체가 버그다. 이 테스트는 둘을
    구분하지 않는다(구분은 사람이 diff를 보고 한다), 다만 간극이 조용히
    지나가는 것만 막는다.
    """
    events = [Event(**json.loads(line))
              for line in EVENTS.read_text(encoding="utf-8").splitlines()
              if line]
    layout = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    pmap = PatternMap.load(CFG / "pattern_map.csv")
    cmap = ClassMap.load(CFG / "entity_class_map.csv")
    ranges = WeaponRanges.load(CFG / "weapon_ranges.csv")
    dis = DisCatalog.load(CFG / "dis_catalog.csv")
    registry = build_registry(events, cmap, layout.static_ids())
    fixed = load_fixed(CFG / "fixed_objects.json", ROOT, layout)
    enrichment_config = EnrichmentConfig.load(CFG / "engagement_enrichment.json")

    spec = build_spec(events, registry, layout, pmap,
                      TaskCatalog.load(CFG / "task_catalog.csv"),
                      TaskKinds.load(CFG / "task_kinds.csv"),
                      dis, ranges,
                      scenario_id="battle", fixed=fixed,
                      enrichment_config=enrichment_config)

    golden_path = ensure_golden(ROOT / "yewon_test")
    out = get_writer("template", str(golden_path)).write(spec, tmp_path)

    rebuilt = hashlib.sha256(out.read_bytes()).hexdigest()
    committed = hashlib.sha256(SCNX.read_bytes()).hexdigest()
    assert rebuilt == committed, (
        "build/scnx/battle.scnx가 현재 코드의 재빌드와 다르다 — "
        "scripts/04_compile_scnx.py를 다시 돌리고 build/를 재커밋할 것")
