import dataclasses
import json
import math
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout, Coord, ground_distance
from vtmak.parser import Event
from vtmak.ranges import WeaponRanges
from vtmak.registry import EntityDef
from vtmak.scnx.engagements import (EnrichmentConfig, EngagementSlot,
                                    UNBOUNDED, ActorClock,
                                    build_enrichment_slots, build_source_slots,
                                    choose_cover_location,
                                    estimate_step_duration,
                                    expected_suppress_spo)
from vtmak.scnx.plan import PlanStep, with_wait_seconds

ROOT = Path(__file__).resolve().parents[1]


def _entity(oid, faction, weapon="M4 rifle"):
    return EntityDef(oid, "US Army M4", "소총수", faction,
                     "보병 - 소총(M4 계열)", (weapon,),
                     "LOC_A" if faction == "BLUE" else "LOC_B",
                     "기동 또는 사격 가능", True)


def test_config_loads_exact_limits(tmp_path):
    path = tmp_path / "engagement.json"
    path.write_text('{"enabled":true,"min_new_unique_pairs":20,'
                    '"target_new_unique_pairs":25,"max_new_unique_pairs":30,'
                    '"max_slots_per_shooter":2,"max_slots_per_target":1,'
                    '"max_target_task_count":2,"direct_fire_rounds":1,'
                    '"suppress_rapid_duration_s":5,"suppress_duration_s":10,'
                    '"suppress_ammo_limit":10,'
                    '"minimum_observation_duration_s":3,"slot_spacing_s":15}',
                    encoding="utf-8")
    cfg = EnrichmentConfig.load(path)
    assert (cfg.min_new_unique_pairs, cfg.target_new_unique_pairs,
            cfg.max_new_unique_pairs) == (20, 25, 30)
    assert (cfg.direct_fire_rounds, cfg.suppress_duration_s,
            cfg.suppress_ammo_limit) == (1, 10, 10)
    # 뒤에 붙은 스케줄·엄폐 설정은 기본값을 갖는다 — 옛 JSON도 그대로 읽힌다.
    assert cfg.movement_speed_mps == 6.0
    assert cfg.min_expected_suppress_spo == 70


def test_repository_config_matches_defaults():
    loaded = EnrichmentConfig.load(
        ROOT / "config" / "engagement_enrichment.json")
    assert loaded == EnrichmentConfig.defaults()


def test_direct_fire_event_becomes_one_source_slot():
    layout = BattlefieldLayout({"locations": {
        "LOC_A": {"lat": 21.0, "lon": 105.0},
        "LOC_B": {"lat": 21.001, "lon": 105.0}}})
    event = Event("E1", 30, 1, "directFireAt", "directFireAt",
                  actor="FR-A", src="LOC_A", target="EN-B")
    registry = {"FR-A": _entity("FR-A", "BLUE"),
                "EN-B": _entity("EN-B", "RED", "AK-47")}
    slots = build_source_slots([event], registry, layout,
                               EnrichmentConfig.defaults())
    assert len(slots) == 1
    assert slots[0].slot_id == "SRC-E1"
    assert slots[0].origin == "source"
    assert (slots[0].shooter_id, slots[0].target_id) == ("FR-A", "EN-B")
    assert slots[0].source_event_ids == ("E1",)
    assert slots[0].provenance == "directFireAt:E1"
    assert slots[0].target_ref == "LOC_B"
    assert slots[0].firing_ref == ""          # 원문 슬롯은 제자리에서 쏜다
    assert slots[0].firing_coord is None


# ---------------------------------------------------------------------------
# choose_cover_location 픽스처 — 전부 좌표 산술뿐이며 시나리오 파일을 읽지
# 않는다. _actor()는 위협에서 서쪽, _threat()는 그보다 동쪽 약 208m다.
#

def _actor() -> Coord:
    return Coord(21.0, 105.0, 0.0)


def _threat() -> Coord:
    return Coord(21.0, 105.002, 0.0)


def _pt(north_m, east_m=0.0, src="golden"):
    return {"lat": 21.0 + north_m / 110_574.0,
            "lon": 105.0 + east_m / 103_900.0, "src": src}


def _layout_with_golden_points():
    # 위협은 동쪽에 있다. 서쪽 두 점이 멀어지는 방향, 동쪽 한 점이 가까워진다.
    return BattlefieldLayout({"locations": {
        "LOC_W1": _pt(0.0, -40.0), "LOC_W2": _pt(0.0, -80.0),
        "LOC_E1": _pt(0.0, 60.0)}})


def _layout_with_point_at(move_m):
    return BattlefieldLayout({"locations": {"LOC_W": _pt(0.0, -move_m)}})


def _layout_with_single_valid_point():
    return BattlefieldLayout({"locations": {"LOC_W": _pt(0.0, -40.0)}})


def _layout_with_only_points_toward_the_threat():
    return BattlefieldLayout({"locations": {
        "LOC_E1": _pt(0.0, 60.0), "LOC_E2": _pt(0.0, 120.0)}})


def test_cover_point_must_increase_threat_distance_and_stay_in_bounds():
    layout = _layout_with_golden_points()      # 위협 쪽 1개, 반대쪽 2개
    cfg = EnrichmentConfig.defaults()
    ref, coord = choose_cover_location(layout, _actor(), _threat(), cfg)
    assert ground_distance(coord, _threat()) > ground_distance(_actor(),
                                                               _threat())
    assert layout.source_of(ref) == "golden"


def test_cover_point_at_exactly_the_move_limit_is_accepted():
    cfg = EnrichmentConfig.defaults()
    # _pt는 위도 21도의 실제 WGS84 도-미터 환산이 아니라 구형 지구 근사
    # 상수(110_574.0/103_900.0)를 쓴다 — ground_distance(WGS84 타원체)와
    # 상수가 어긋나 nominal 값이 실측으로는 약 0.068% 더 길게 잡힌다(실측
    # 확인). cfg.max_cover_move_m을 그대로 쓰면 '경계에서 받아들여진다'는
    # 이 테스트의 의도와 반대로 항상 거부돼 버리므로, 그 드리프트를 감안해
    # 한도보다 1m 못 미치는 지점을 쓴다 — 이 값 범위에서 드리프트(약
    # 0.3m)를 확실히 흡수한다. 하드코드된 100.0이 아니라 설정값에 상대적으로
    # 키를 잡아, 설정이 바뀌어도(2026-08-27: 100.0→400.0) 경계 자체를
    # 계속 검증한다 — 굳어버린 옛 숫자를 검증하지 않는다.
    layout = _layout_with_point_at(cfg.max_cover_move_m - 1.0)
    assert choose_cover_location(layout, _actor(), _threat(), cfg) is not None


def test_cover_point_just_past_the_move_limit_is_rejected():
    cfg = EnrichmentConfig.defaults()
    layout = _layout_with_point_at(cfg.max_cover_move_m + 1.0)
    assert choose_cover_location(layout, _actor(), _threat(), cfg) is None


def test_no_verified_cover_point_returns_none_not_a_find_task():
    layout = _layout_with_only_points_toward_the_threat()
    assert choose_cover_location(layout, _actor(), _threat(),
                                 EnrichmentConfig.defaults()) is None


# choose_cover_location은 최소 이격을 지점 선택 필터로도, 지점 안 배치
# 규칙으로도 걸지 않는다(설계 §8 개정, 2026-08-27, 사용자 결정). golden
# 지점 21개 대 hitBy 77건 밀도에서 필터로 두면 지울 수만 있지 채울 수
# 없다는 게 두 번의 실측(t=0 배치 좌표: 50/77, 이번 빌드 예약: 2/77)으로
# 확인됐고, 지점 안에서 벌려 세우는 배치도 목적지를 지명 중심에서
# 15~90m 밀어내 후처리 snap이 대부분을 이름 없는 좌표 노드로 남긴다
# (실측: 52개 중 50개). 여러 객체가 같은 golden 지점으로 향하는 것은
# 그대로 허용한다 — 지점 안에서 어디에 서는지는 VR-Forces가 정한다.
def test_cover_point_still_leaves_the_actor_free_when_no_one_shares_it():
    """이격이 지점 선택 필터가 아님을 회귀로 잡는다.

    occupied가 다시 필터로 걸리면 이 테스트 자체는 여전히 통과하지만
    (occupied 인자가 아예 없으므로), 시그니처 회귀는 여기서 걸린다 —
    choose_cover_location이 occupied를 다시 받으면 TypeError가 난다.
    """
    layout = _layout_with_single_valid_point()
    cfg = EnrichmentConfig.defaults()
    ref, coord = choose_cover_location(layout, _actor(), _threat(), cfg)
    assert ref == layout.location_ids()[0]
    assert coord == layout.coord(ref)


# ---------------------------------------------------------------------------
# build_enrichment_slots 픽스처
#
# BLUE 사수 3명(FR-S1..3, 모두 LOC_A), RED 표적 최대 6명(EN-T1..6, 각자
# LOC_T1..6)을 만든다. task_counts로 표적 집합을 직접 지정하면(예: test 1)
# target_pairs는 무시되고 그 키들만 표적이 된다 — 패딩 표적이 결과를
# 오염시키지 않게 하기 위해서다. weapon_ranges는 임시 CSV에서 읽는다.
# ---------------------------------------------------------------------------

_ENRICH_RANGES_CSV = (
    "entity_class,direct_min_m,direct_max_m,indirect_min_m,indirect_max_m,"
    "unverified,min_severity\n"
    "US Army M4,0,5000,,,0,\n"
)


def _enrichment_ranges() -> WeaponRanges:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False,
                                    encoding="utf-8", newline="")
    f.write(_ENRICH_RANGES_CSV)
    f.close()
    return WeaponRanges.load(f.name)


def _enrichment_layout() -> BattlefieldLayout:
    locs = {"LOC_A": {"lat": 21.000, "lon": 105.000, "alt": 0.0,
                      "src": "golden"}}
    for i in range(1, 7):
        locs[f"LOC_T{i}"] = {"lat": 21.000 + i * 0.001, "lon": 105.000,
                             "alt": 0.0, "src": "golden"}
    return BattlefieldLayout({"locations": locs})


def _enrichment_shooter(oid: str) -> EntityDef:
    return EntityDef(oid, "US Army M4", "소총수", "BLUE",
                     "보병 - 소총(M4 계열)", ("M4 rifle",), "LOC_A",
                     "기동 또는 사격 가능", True)


def _enrichment_target(oid: str, loc: str, weapons=("AK-47",),
                       faction="RED") -> EntityDef:
    return EntityDef(oid, "Russian Soldier AK47", "소총수", faction,
                     "보병 - 소총(M4 계열)", weapons, loc,
                     "기동 또는 사격 가능", True)


def _build_enrichment_fixture(*, task_counts=None, target_pairs=6,
                              include_same_faction=False,
                              include_unarmed=False, blocked_shooters=None,
                              shared_target_ref=False, last_task_times=None,
                              source_slots=(), max_slots_per_target=None):
    layout = _enrichment_layout()
    ranges = _enrichment_ranges()

    shooter_ids = ["FR-S1", "FR-S2", "FR-S3"]
    registry: dict[str, EntityDef] = {
        oid: _enrichment_shooter(oid) for oid in shooter_ids}

    if task_counts is not None:
        target_ids = sorted(task_counts)
    else:
        target_ids = [f"EN-T{i}" for i in range(1, target_pairs + 1)]
    for i, oid in enumerate(target_ids, start=1):
        registry[oid] = _enrichment_target(oid, f"LOC_T{((i - 1) % 6) + 1}")

    # 표적 두 명의 추적 지명을 같은 LOC_*로 합친다 — 후처리 SPO 충돌 재현.
    if shared_target_ref and len(target_ids) >= 2:
        shared_loc = registry[target_ids[0]].initial_location
        registry[target_ids[1]] = dataclasses.replace(
            registry[target_ids[1]], initial_location=shared_loc)

    if include_same_faction:
        registry["FR-T-SAME"] = _enrichment_target(
            "FR-T-SAME", "LOC_A", weapons=("M4 rifle",), faction="BLUE")
    if include_unarmed:
        registry["EN-T-UNARMED"] = _enrichment_target(
            "EN-T-UNARMED", "LOC_A", weapons=())

    # 사수를 하나로 좁혀 같은 사수가 두 표적을 다 시도하게 만든다 — 그래야
    # duplicate_suppress_spo가 실제로 재현된다(사수가 여럿이면 부하 분산이
    # 자동으로 다른 사수를 골라 충돌을 피해 버린다).
    eligible_shooters = ["FR-S1"] if shared_target_ref else list(shooter_ids)

    # target_pairs<=2로 부르는 호출은 후보가 2쌍뿐인 최소치 미달 테스트다.
    # 이때만 실제 하한(20)을 그대로 써야 미달이 재현된다. 나머지는 상한·
    # 고유성·진영만 보므로 하한을 낮춰 20쌍 바닥과 싸우지 않게 한다.
    if target_pairs <= 2:
        config = EnrichmentConfig.defaults()
    else:
        config = dataclasses.replace(EnrichmentConfig.defaults(),
                                     min_new_unique_pairs=2)
    if max_slots_per_target is not None:
        config = dataclasses.replace(
            config, max_slots_per_target=max_slots_per_target)

    return build_enrichment_slots(
        events=[],
        registry=registry,
        layout=layout,
        ranges=ranges,
        config=config,
        task_counts=task_counts or {},
        last_task_times=last_task_times or {},
        eligible_shooter_ids=eligible_shooters,
        blocked_shooters=blocked_shooters or {},
        source_slots=source_slots,
    )


def test_enrichment_prefers_low_task_armed_targets_and_is_deterministic():
    result1 = _build_enrichment_fixture(task_counts={
        "EN-T1": 0, "EN-T2": 1, "EN-T3": 3})
    result2 = _build_enrichment_fixture(task_counts={
        "EN-T1": 0, "EN-T2": 1, "EN-T3": 3})
    assert result1 == result2
    assert {s.target_id for s in result1.slots} <= {"EN-T1", "EN-T2"}
    assert len({(s.shooter_id, s.target_id) for s in result1.slots}) == \
           len(result1.slots)


def test_enrichment_enforces_shooter_and_target_caps():
    # target_pairs=7은 사수 3명 × max_slots_per_shooter(2) = 6보다 하나
    # 많다 — 6개를 채우고 나면 남는 7번째 표적은 사수 셋 모두가 이미
    # 상한이라 shooter_cap_reached로 거절돼야 한다(파인딩 3).
    result = _build_enrichment_fixture(target_pairs=7)
    shooter_counts = Counter(s.shooter_id for s in result.slots)
    target_counts = Counter(s.target_id for s in result.slots)
    assert max(shooter_counts.values()) <= 2
    assert max(target_counts.values()) <= 1
    assert "shooter_cap_reached" in {r.reason for r in result.rejected}


def test_enrichment_rejects_same_faction_and_unarmed_targets():
    result = _build_enrichment_fixture(include_same_faction=True,
                                       include_unarmed=True)
    assert all(s.shooter_id.startswith("FR-") != s.target_id.startswith("FR-")
               for s in result.slots)
    assert {r.reason for r in result.rejected} >= {
        "same_faction", "target_unarmed"}


def test_enrichment_rejects_no_task_and_unbounded_shooters():
    # 설계 §6.1: noTask가 선언된 객체, 선행 task가 유한하게 끝나지 않는
    # 객체는 공격자가 될 수 없다. 둘 다 호출자가 blocked_shooters로 넘긴다.
    result = _build_enrichment_fixture(
        blocked_shooters={"FR-S1": "shooter_no_task",
                          "FR-S2": "shooter_unbounded_predecessor"})
    assert {"FR-S1", "FR-S2"}.isdisjoint({s.shooter_id for s in result.slots})
    assert {r.reason for r in result.rejected} >= {
        "shooter_no_task", "shooter_unbounded_predecessor"}


def test_enrichment_never_repeats_a_suppressive_spo():
    # 설계 §6.3: 표적 위치가 후처리에서 같은 LOC_*로 합쳐지면 제압사격
    # SPO가 겹친다. 같은 (공격자, 표적 위치)를 두 번 만들지 않는다.
    result = _build_enrichment_fixture(shared_target_ref=True)
    spo = expected_suppress_spo(result.slots)
    assert len(spo) == len(result.slots)
    assert "duplicate_suppress_spo" in {r.reason for r in result.rejected}


def test_enrichment_rejects_targets_already_engaged_by_a_source_slot():
    # 설계 §6.2: 원문 슬롯이 표적의 마지막 task 시각 이후에 이미 그 표적을
    # 치고 있으면(=원문이 이미 마무리 중) 더 얹지 않는다. EN-T1의 마지막
    # task는 100초인데 원문 슬롯이 200초에 EN-T1을 친다 — 100 이후이므로
    # target_already_engaged다.
    source = EngagementSlot(
        slot_id="SRC-X1", origin="source", source_event_ids=("X1",),
        scheduled_time_s=200, shooter_id="EN-OTHER", target_id="EN-T1",
        shooter_coord=Coord(0.0, 0.0, 0.0), target_coord=Coord(0.0, 0.0, 0.0),
        target_ref="LOC_T1", firing_ref="", firing_coord=None,
        distance_m=0.0, target_task_count=0, direct_fire_rounds=1,
        suppress_rapid_duration_s=5, suppress_duration_s=10,
        suppress_ammo_limit=10)
    result = _build_enrichment_fixture(
        task_counts={"EN-T1": 0, "EN-T2": 0, "EN-T3": 0},
        last_task_times={"EN-T1": 100},
        source_slots=(source,))
    assert "EN-T1" not in {s.target_id for s in result.slots}
    assert {s.target_id for s in result.slots} == {"EN-T2", "EN-T3"}
    assert "target_already_engaged" in {r.reason for r in result.rejected}


def test_enrichment_round_loop_makes_duplicate_pair_reachable_at_higher_cap():
    # max_slots_per_target>1이면 build_enrichment_slots가 표적 목록을 그
    # 값만큼 라운드로 돈다(단일 패스로는 이 config 값이 아무 것도 하지
    # 않는 죽은 설정 키였다). 사수를 하나로 좁혀 두 번째 라운드도 같은
    # 사수를 다시 시도하게 만든다 — 그래야 duplicate_pair가 실제로
    # 재현된다. 상한(2)은 그대로 지켜진다 — 라운드가 둘뿐이라 표적 하나가
    # 받는 슬롯은 최대 하나(같은 사수가 재시도마다 duplicate_pair로
    # 막히므로), 즉 라운드 수 자체가 상한을 강제한다는 것을 이 테스트가
    # 보여준다.
    layout = _enrichment_layout()
    ranges = _enrichment_ranges()
    registry = {
        "FR-S1": _enrichment_shooter("FR-S1"),
        "EN-T1": _enrichment_target("EN-T1", "LOC_T1"),
        "EN-T2": _enrichment_target("EN-T2", "LOC_T2"),
    }
    config = dataclasses.replace(EnrichmentConfig.defaults(),
                                 min_new_unique_pairs=2,
                                 max_slots_per_target=2,
                                 max_slots_per_shooter=5)
    result = build_enrichment_slots(
        events=[], registry=registry, layout=layout, ranges=ranges,
        config=config, task_counts={}, last_task_times={},
        eligible_shooter_ids=["FR-S1"], blocked_shooters={},
        source_slots=())
    assert Counter(s.target_id for s in result.slots) == \
           Counter({"EN-T1": 1, "EN-T2": 1})
    assert Counter(r.reason for r in result.rejected) == \
           Counter({"duplicate_pair": 2})


def test_enrichment_raises_when_minimum_pairs_unreachable():
    with pytest.raises(ValueError) as exc:
        _build_enrichment_fixture(target_pairs=2)   # 후보가 2쌍뿐이다
    assert "20" in str(exc.value)                   # 최소치를 메시지에 담는다


@pytest.fixture
def full_inputs():
    """battle.jsonl과 저장소 config에서 만든 실제 규모 입력.

    task_counts·last_task_times는 아직 정식 task 집계 모듈이 없어(그 모듈은
    이후 태스크의 몫이다) 이벤트에서 정직하게 파생한다: 객체별 이벤트 중
    pattern_map task_kind가 ''·'noop'이 아닌 것을 세고, 시각은 그 객체가
    행위자인 이벤트의 최댓값을 쓴다. blocked_shooters는 아직 없는 입력이라
    빈 dict로 둔다 — noTask·선행task 무한 여부 판정은 이 태스크의 범위 밖.
    공격자 후보는 BLUE 진영의 taskable 객체 전체다(설계 §6.2: 표적은 공격자와
    반대 진영이어야 하고, 이번 보강은 원문에서 대응이 적은 RED 표적을 겨눈다).
    """
    from vtmak.parser import PatternMap
    from vtmak.registry import ClassMap, build_registry

    jsonl = ROOT / "build" / "events" / "battle.jsonl"
    if not jsonl.exists():
        pytest.skip("build/events/battle.jsonl 없음 — 02를 먼저 실행")

    events = [Event(**json.loads(line)) for line in
             jsonl.read_text(encoding="utf-8").splitlines() if line]
    cfg_dir = ROOT / "config"
    layout = BattlefieldLayout.load(cfg_dir / "battlefield_layout.json")
    cmap = ClassMap.load(cfg_dir / "entity_class_map.csv")
    registry = build_registry(events, cmap, layout.static_ids())
    ranges = WeaponRanges.load(cfg_dir / "weapon_ranges.csv")
    config = EnrichmentConfig.load(cfg_dir / "engagement_enrichment.json")
    pmap = PatternMap.load(cfg_dir / "pattern_map.csv")

    task_counts: dict[str, int] = {}
    last_task_times: dict[str, int] = {}
    for e in events:
        if not e.actor:
            continue
        last_task_times[e.actor] = max(last_task_times.get(e.actor, 0),
                                       e.time_s)
        if pmap.task_kind_of(e) not in ("", "noop"):
            task_counts[e.actor] = task_counts.get(e.actor, 0) + 1

    source_slots = build_source_slots(events, registry, layout, config)
    eligible_shooter_ids = sorted(
        oid for oid, d in registry.items() if d.taskable and d.faction == "BLUE")

    return dict(events=events, registry=registry, layout=layout, ranges=ranges,
               config=config, task_counts=task_counts,
               last_task_times=last_task_times,
               eligible_shooter_ids=eligible_shooter_ids,
               blocked_shooters={}, source_slots=source_slots)


def test_full_scenario_can_supply_at_least_twenty_new_pairs(full_inputs):
    result = build_enrichment_slots(**full_inputs)
    assert 20 <= len(result.slots) <= 30
    assert len({(s.shooter_id, s.target_id) for s in result.slots}) == \
           len(result.slots)


CFG = EnrichmentConfig.defaults()


def _step(pln, kind="move"):
    return PlanStep("E1", 0, "moveTo", kind, None, pln)


def test_wait_duration_is_read_from_the_template_value():
    step = _step('(Task (task-type "wait-duration") (subtask False) '
                 '(seconds-to-wait 12.500000))', kind="wait")
    assert estimate_step_duration(step, CFG, 0.0) == 12.5


def test_move_duration_is_distance_over_configured_speed():
    step = _step('(Task (task-type "move-to-location-task") '
                 '(aiming-point 1 2 3))')
    assert estimate_step_duration(step, CFG, 60.0) == 10.0     # 60m / 6 m/s


def test_fire_and_suppress_use_configured_durations():
    fire = _step('(Task (task-type "fire-at-target") '
                 '(max-rounds-to-fire 1))', kind="fire_direct")
    supp = _step('(Task (task-type "provide_suppressive_fire_loc") '
                 '(DtRwReal (durationTotal 10.000000) ))', kind="suppress")
    assert estimate_step_duration(fire, CFG, 0.0) == 5.0
    assert estimate_step_duration(supp, CFG, 0.0) == 10.0


def test_follow_and_unknown_tasks_are_unbounded():
    follow = _step('(Task (task-type "follow-entity") (offset 0 0 0))',
                   kind="follow")
    unknown = _step('(Task (task-type "orbit_object") (radius 300))',
                    kind="orbit")
    assert estimate_step_duration(follow, CFG, 0.0) == UNBOUNDED
    assert estimate_step_duration(unknown, CFG, 0.0) == UNBOUNDED


def test_clock_freezes_and_reports_unbounded_after_an_endless_task():
    clock = ActorClock(0, CFG)
    clock.advance(_step('(Task (task-type "wait-duration") '
                        '(seconds-to-wait 4.000000))', kind="wait"), 0.0)
    assert clock.now_s == 4.0 and clock.bounded
    clock.advance(_step('(Task (task-type "follow-entity") '
                        '(offset 0 0 0))', kind="follow"), 0.0)
    assert not clock.bounded
    assert clock.wait_needed_for(600) is None      # 스케줄할 수 없다


def test_clock_returns_a_bounded_positive_wait_and_never_a_negative_one():
    clock = ActorClock(0, CFG)
    clock.advance(_step('(Task (task-type "wait-duration") '
                        '(seconds-to-wait 4.000000))', kind="wait"), 0.0)
    assert clock.wait_needed_for(30) == 26.0
    # 이미 지난 시각을 요구하면 최소 관측 시간만큼만 기다린다(음수 금지).
    assert clock.wait_needed_for(1) == float(CFG.minimum_observation_duration_s)


def test_wait_seconds_are_substituted_into_the_harvested_template():
    tmpl = ('(Task (task-type "wait-duration") (subtask False) '
            '(allow-task-visualizations True) (seconds-to-wait 60.000000))')
    out = with_wait_seconds(tmpl, 26.0)
    assert "(seconds-to-wait 26.000000)" in out
    assert "60.000000" not in out


def test_wait_seconds_raises_on_a_non_positive_value():
    # 0은 순진한 스케줄러가 실제로 만들어낼 법한 값이라 특히 현실적이다.
    tmpl = ('(Task (task-type "wait-duration") (subtask False) '
            '(allow-task-visualizations True) (seconds-to-wait 60.000000))')
    with pytest.raises(ValueError):
        with_wait_seconds(tmpl, -1.0)
    with pytest.raises(ValueError):
        with_wait_seconds(tmpl, 0.0)


def test_wait_seconds_raises_when_the_template_has_no_wait_field():
    # 대기가 아닌 template(fire-at-target)을 잘못 넘긴 상황의 대역이다.
    fire = '(Task (task-type "fire-at-target") (max-rounds-to-fire 1))'
    with pytest.raises(ValueError):
        with_wait_seconds(fire, 26.0)


@pytest.mark.parametrize("pln", [
    '(Task (task-type "move-along") (subtask False) '
    '(route "VRF_UUID:ROUTE_UUID") (traversal-direction 0) '
    '(start-at-closest-point True))',
    '(Task (task-type "find_cover") (subtask False) '
    '(script-id "find_cover") (variables '
    '(DtRwReal (Range 100.000000) ) ) )',
    '(Task (task-type "find_firing_position") (subtask False) '
    '(script-id "find_firing_position") (variables '
    '(DtRwReal (Range 100.000000) ) ) )',
])
def test_patrol_and_positioning_tasks_are_unbounded(pln):
    # move-along은 UAV 순찰 task다 — _MOVE_TASKS를 "move가 들어가니 이동
    # task겠지"로 넓히면 끝나지 않는 순찰을 유한 이동으로 오판해 그 뒤에
    # 교전을 배치하게 된다. find_cover·find_firing_position도 스크립트
    # task라 종료 시각을 모른다. 세 task-type을 이름으로 못박아 두지 않으면
    # _MOVE_TASKS나 default_task_duration_s 분기가 우연히 넓어져도 이 테스트가
    # 잡아내지 못한다.
    assert estimate_step_duration(_step(pln), CFG, 0.0) == UNBOUNDED
