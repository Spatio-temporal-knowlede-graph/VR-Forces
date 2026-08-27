import dataclasses
import json
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import Event
from vtmak.ranges import WeaponRanges
from vtmak.registry import EntityDef
from vtmak.scnx.engagements import (EnrichmentConfig, build_enrichment_slots,
                                    build_source_slots, expected_suppress_spo)

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
                              shared_target_ref=False, last_task_times=None):
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
        source_slots=(),
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
    result = _build_enrichment_fixture(target_pairs=6)
    shooter_counts = Counter(s.shooter_id for s in result.slots)
    target_counts = Counter(s.target_id for s in result.slots)
    assert max(shooter_counts.values()) <= 2
    assert max(target_counts.values()) <= 1


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
