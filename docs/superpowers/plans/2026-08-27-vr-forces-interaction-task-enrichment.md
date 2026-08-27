# VR-Forces Interaction Task Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 객체만 사용하여 VR-Forces에서 도달 가능한 직접사격·제압사격 task를 약 100개 고유 교전으로 늘리고, GT에는 직접 관측되는 `Fire-Weapon`과 `Provide-Suppressive-Fire-Loc`만 새로 저장한다.

**Architecture:** 원문 이벤트를 직접 PLN으로 내리기 전에 결정적인 `EngagementSlot` 중간 표현으로 바꾼다. 기존 직접사격 77개와 저-task 무장 표적을 사용하는 신규 슬롯 20~30개를 같은 lowering 경로로 보내 `move-to → wait-duration → fire-at-target → provide_suppressive_fire_loc`을 연속 생성하고, 객체별 정적 시계로 도달 가능성을 확보한다. 도달 불가능한 follow와 실패하는 위치 탐색 task는 유한 이동으로 바꾼다. 후처리는 제압사격 task를 위치 관계로만 정규화하며 객체 간 `suppresses`는 만들지 않는다.

**Tech Stack:** Python 3, 표준 라이브러리 `dataclasses`·`json`·`csv`·`re`·`zipfile`, pytest, VR-Forces PLN S-expression 템플릿, 기존 `vtmak` 패키지

**Spec:** `docs/superpowers/specs/2026-08-27-vr-forces-interaction-task-enrichment-design.md`

## Global Constraints

- 신규 시뮬레이션 객체를 만들지 않는다.
- UAV 객체, 순찰 경로, `fixed_plans`, 관측 로직을 수정하지 않는다.
- 기존 `directFireAt` 77건은 모두 직접사격과 제압사격 두 task를 갖는다.
- 신규 고유 공격자–표적 쌍은 최소 20개, 목표 25개, 최대 30개다.
- 신규 슬롯은 공격자당 최대 2개, 표적당 최대 1개다.
- 신규 표적은 반대 진영의 기존 무장 객체이며 실행 가능한 원문 task 수가 2개 이하다.
- 직접사격은 `max-rounds-to-fire=1`을 사용한다.
- 제압사격은 `durationRapid=5초`, `durationTotal=10초`, `ammoLimit=10발`을 사용한다.
- 같은 슬롯의 `fire-at-target`과 `provide_suppressive_fire_loc` 사이에는 다른 task를 두지 않는다.
- 슬롯의 사격 지점 이동과 대기는 `fire-at-target` **앞**에만 놓는다.
- 모든 `wait-duration`은 유한하고 양수이며 `(seconds-to-wait N.NNNNNN)` 값이 템플릿 기본값 60초에서 실제로 치환돼야 한다.
- 슬롯은 종료 시각을 계산할 수 없는 선행 task 뒤에 놓지 않는다.
- 후속 task가 있는 무기한 `follow-entity`는 유한 이동으로 바꾼다.
- 최종 PLN에는 `find_firing_position`과 `find_cover`가 없어야 한다.
- 엄폐 이동 지점은 golden 지형점이며 위협과의 거리를 늘리고 전장 경계 안에 있고 다른 객체와 최소 이격을 지킨다.
- 전체 슬롯에서 예상되는 고유 `(공격자, 정규화된 표적 위치)` 제압사격 SPO가 70개 미만이면 컴파일을 실패시킨다.
- GT에는 제압사격을 `Provide-Suppressive-Fire-Loc`으로 저장하고 객체 간 `suppresses`를 저장하지 않는다.
- `FFE-on-Location`은 유지하며 `Provide-Suppressive-Fire-Loc`과 합치지 않는다.
- 기존 부대·편제 술어(`partOf`, `supports`, `reinforces`, `unitSuppressed`, 부대 주어 `movesToward`·`occupies`·`firesUpon`) 제거 상태를 회귀 테스트로 고정한다.
- 같은 입력은 같은 슬롯 JSONL과 같은 `.scnx`를 만들어야 한다.
- 정적 검사 통과만으로 VR-Forces 런타임 성공을 주장하지 않는다. 최종 합격은 새 GT 수집 후 판정한다.

## File Structure

- Create `config/engagement_enrichment.json`: 슬롯 수, 발수, 지속시간, 이동 속도, 배정 상한의 정본.
- Create `vtmak/scnx/engagements.py`: 설정 로더, 슬롯·거절 자료형, 기존 슬롯 추출, 결정적 신규 쌍 선택, 검증된 지점 선택, 객체별 정적 시계와 소요시간 추정, 감사 행 생성.
- Create `tests/test_engagements.py`: 슬롯 모델, 결정성, 고유성, 진영, 상한, 위치 선택, 스케줄 추정의 단위 테스트.
- Create `tests/test_scnx_engagement_integration.py`: 저작된 `.scnx` 안의 PLN을 되읽어 두 단계 사격과 UAV 불변을 검증.
- Modify `vtmak/scnx/plan.py`: 슬롯을 이동·대기·직접사격·제압사격 네 단계로 lowering하고 duration·ammo·대기 초를 치환하며 계획 의도를 기록.
- Modify `vtmak/scnx/spec.py`: 원문 계획 작성, task 통계, 신규 슬롯 생성, 정적 스케줄 삽입, PLN 병합 순서를 조정하고 슬롯을 `ScnxSpec`에 보관.
- Modify `vtmak/scnx/gates.py`: 게이트 G4(`validate_interaction_plan`) 추가. `Violation`과 `check_g3`가 여기 있으므로 새 차단 검사도 여기 둔다. `vtmak/scnx/audit.py`는 저작된 `.scnx`를 되읽는 리포터이지 게이트가 아니다 — 검사 로직을 넣지 않는다.
- Modify `scripts/04_compile_scnx.py`: 설정 로드, G4 차단, `slots.jsonl`·`audit.csv` 출력.
- Modify `config/task_kinds.csv`: `move_firing_position`과 `move_cover`을 위치 이동 의도로 lowering할 task kind 선언.
- Modify `config/pattern_map.csv`: 기존 원문 의미(`preparesFiringPosition`, `hitBy`)는 유지하면서 실패 task의 lowering kind를 새 이름으로 연결.
- Modify `config/task_catalog.csv`: 검증된 제압사격·대기 템플릿의 제한값을 설정에서 치환 가능하게 유지(행 추가·삭제 없음).
- Modify `vtmak/stkg/predicate.py`: 제압사격의 내부 이름을 효과 관계가 아닌 관측 task 이름으로 변경.
- Modify `vtmak/stkg/rewrite.py`: `Provide-Suppressive-Fire-Loc` 정규형 추가.
- Modify `config/derive_rules.csv`: R1 `suppresses` 매핑 제거.
- Modify `vtmak/derive/relations.py`: R1·R2 결합 함수를 R2 손상 전용 함수로 축소.
- Modify `scripts/07_derive_relations.py`: 손상 전용 파생 함수만 호출.
- Modify `tests/test_spec.py`, `tests/test_audit.py`, `tests/test_task_kinds.py`, `tests/test_fixed_objects.py`, `tests/test_writer.py`, `tests/test_stkg_predicate.py`, `tests/test_stkg_rewrite.py`, `tests/test_derive_config.py`, `tests/test_derive_relations.py`: 새 계약의 회귀 테스트.
- Modify `README.md`: 네 단계 사격, 관측 전용 GT, 파생 `suppresses` 제외, 실행·검증 절차 설명.

---

### Task 1: Engagement Configuration and Source Slot Model

**Files:**
- Create: `config/engagement_enrichment.json`
- Create: `vtmak/scnx/engagements.py`
- Create: `tests/test_engagements.py`

**Interfaces:**
- Consumes: `Event`, `EntityDef`, `BattlefieldLayout`, `PositionTracker`, `engagement_locations`, `resolve_coord`.
- Produces: `EnrichmentConfig.load(path)`, `EnrichmentConfig.defaults()`, `EngagementSlot`, `SlotRejection`, `SlotBuildResult`, `build_source_slots(events, registry, layout, config)`.

- [ ] **Step 1: Write the failing configuration and source-slot tests**

```python
# tests/test_engagements.py
from pathlib import Path

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import Event
from vtmak.registry import EntityDef
from vtmak.scnx.engagements import EnrichmentConfig, build_source_slots

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
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m pytest tests/test_engagements.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'vtmak.scnx.engagements'`.

- [ ] **Step 3: Add the exact configuration file**

`config/engagement_enrichment.json`:

```json
{
  "enabled": true,
  "min_new_unique_pairs": 20,
  "target_new_unique_pairs": 25,
  "max_new_unique_pairs": 30,
  "max_slots_per_shooter": 2,
  "max_slots_per_target": 1,
  "max_target_task_count": 2,
  "direct_fire_rounds": 1,
  "suppress_rapid_duration_s": 5,
  "suppress_duration_s": 10,
  "suppress_ammo_limit": 10,
  "minimum_observation_duration_s": 3,
  "slot_spacing_s": 15,
  "movement_speed_mps": 6.0,
  "direct_fire_duration_s": 5.0,
  "default_task_duration_s": 2.0,
  "min_expected_suppress_spo": 70,
  "max_cover_move_m": 100.0,
  "min_entity_separation_m": 15.0
}
```

설계 §11은 앞 13개만 열거하고 "주요 설정은 다음과 같다"라고 적는다. 뒤 6개는 설계 §7(정적 스케줄의 이동 속도·고정 duration), §6.3(예상 제압 SPO 하한), §8(엄폐 지점 제약)이 값을 요구하는데 §11이 이름을 주지 않은 것들이다. 코드에 박지 않는다는 §11의 규칙을 따라 여기에 둔다.

- [ ] **Step 4: Implement immutable configuration and slot types**

```python
# vtmak/scnx/engagements.py
"""교전 슬롯 — 원문 사건과 PLN 사이의 결정적 중간 표현.

원문 directFireAt를 바로 PLN으로 내리면 '직접사격이냐 제압사격이냐'를
저작 시점에 골라야 하고, 실제로 그래서 77건이 26 + 51로 갈렸다. 슬롯을
두면 한 교전이 두 단계(직접 → 제압)를 모두 갖는다.

무작위를 쓰지 않는다. 모든 순회와 동률 해소는 객체 id와 사건 id의 정렬
순서로 끝낸다 — 같은 입력이 같은 .scnx를 내야 한다(설계 §4).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..gates import PositionTracker, engagement_locations, resolve_coord
from ..geometry import BattlefieldLayout, Coord, ground_distance
from ..parser import Event
from ..registry import EntityDef


@dataclass(frozen=True)
class EnrichmentConfig:
    enabled: bool
    min_new_unique_pairs: int
    target_new_unique_pairs: int
    max_new_unique_pairs: int
    max_slots_per_shooter: int
    max_slots_per_target: int
    max_target_task_count: int
    direct_fire_rounds: int
    suppress_rapid_duration_s: int
    suppress_duration_s: int
    suppress_ammo_limit: int
    minimum_observation_duration_s: int
    slot_spacing_s: int
    # 아래는 설계 §7·§6.3·§8이 값을 요구하지만 §11이 이름을 주지 않은 설정.
    # 기본값을 두어 옛 JSON도 그대로 읽힌다.
    movement_speed_mps: float = 6.0
    direct_fire_duration_s: float = 5.0
    default_task_duration_s: float = 2.0
    min_expected_suppress_spo: int = 70
    max_cover_move_m: float = 100.0
    min_entity_separation_m: float = 15.0

    @classmethod
    def load(cls, path) -> "EnrichmentConfig":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def defaults(cls) -> "EnrichmentConfig":
        return cls(enabled=True, min_new_unique_pairs=20,
                   target_new_unique_pairs=25, max_new_unique_pairs=30,
                   max_slots_per_shooter=2, max_slots_per_target=1,
                   max_target_task_count=2, direct_fire_rounds=1,
                   suppress_rapid_duration_s=5, suppress_duration_s=10,
                   suppress_ammo_limit=10, minimum_observation_duration_s=3,
                   slot_spacing_s=15)


@dataclass(frozen=True)
class EngagementSlot:
    slot_id: str
    origin: str                     # source | enrichment
    source_event_ids: tuple[str, ...]
    scheduled_time_s: int
    shooter_id: str
    target_id: str
    shooter_coord: Coord
    target_coord: Coord
    target_ref: str                 # 정규화될 표적 위치(LOC_* 또는 좌표 문자열)
    firing_ref: str                 # 사격 지점 지명. 제자리 사격이면 ""
    firing_coord: Coord | None
    distance_m: float
    target_task_count: int
    direct_fire_rounds: int
    suppress_rapid_duration_s: int
    suppress_duration_s: int
    suppress_ammo_limit: int
    provenance: str = ""

    def to_json(self) -> dict:
        row = asdict(self)
        for key in ("shooter_coord", "target_coord", "firing_coord"):
            value = getattr(self, key)
            row[key] = value.as_tuple() if value is not None else None
        return row


@dataclass(frozen=True)
class SlotRejection:
    shooter_id: str
    target_id: str
    reason: str


@dataclass(frozen=True)
class SlotBuildResult:
    slots: tuple[EngagementSlot, ...] = ()
    rejected: tuple[SlotRejection, ...] = ()
```

`build_source_slots(events, registry, layout, config)`를 구현한다.

- `template == "directFireAt"`이고 `actor`와 `target`이 모두 있는 이벤트만 순회한다.
- 사수·표적 위치는 `gates.engagement_pairs`와 **같은 우선순위**로 푼다. 사수는 `e.src`가 레이아웃에 있으면 그 좌표, 없으면 `resolve_coord(actor, ...)`. 표적은 `engagement_locations`의 피격 지명 > `layout.static_target` > `PositionTracker.location_at` 순이다. 해석기를 두 벌 만들지 않는다.
- `target_ref`는 그 우선순위로 얻은 지명을 그대로 쓴다. 지명이 없으면 `f"{lat:.5f},{lon:.5f}"` 좌표 문자열을 쓴다.
- `slot_id = f"SRC-{event.event_id}"`, `origin="source"`, `provenance = f"directFireAt:{event.event_id}"`.
- `firing_ref=""`, `firing_coord=None` — 원문 사격은 원문이 적은 자리에서 일어난다.
- `direct_fire_rounds`와 `suppress_*` 네 값은 `config`에서 복사한다.
- 사수 또는 표적 좌표가 `is_zero()`면 슬롯을 만들지 않는다(G0가 이미 잡는 상태다).
- 반환은 `(scheduled_time_s, slot_id)`로 정렬한 `tuple`이다.

- [ ] **Step 5: Run the focused tests**

Run: `python -m pytest tests/test_engagements.py -v`

Expected: 세 테스트 모두 통과.

- [ ] **Step 6: Commit the slot foundation**

```bash
git add config/engagement_enrichment.json vtmak/scnx/engagements.py tests/test_engagements.py
git commit -m "feat(scnx): add deterministic engagement slot model"
```

### Task 2: Deterministic Enrichment Pair Selection

**Files:**
- Modify: `vtmak/scnx/engagements.py`
- Modify: `tests/test_engagements.py`

**Interfaces:**
- Consumes: `EnrichmentConfig`, source `EngagementSlot` values, task counts, last task times, eligible shooter ids, `WeaponRanges`.
- Produces: `choose_firing_location(layout, shooter, target, range_spec, reserved)`, `expected_suppress_spo(slots)`, `build_enrichment_slots(events, registry, layout, ranges, config, task_counts, last_task_times, eligible_shooter_ids, blocked_shooters, source_slots) -> SlotBuildResult`.

- [ ] **Step 1: Write failing tests for uniqueness, priority, limits, determinism, and SPO spread**

```python
from collections import Counter

from vtmak.scnx.engagements import (build_enrichment_slots,
                                    expected_suppress_spo)


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
    import pytest
    with pytest.raises(ValueError) as exc:
        _build_enrichment_fixture(target_pairs=2)   # 후보가 2쌍뿐이다
    assert "20" in str(exc.value)                   # 최소치를 메시지에 담는다
```

`_build_enrichment_fixture(**kw)`는 BLUE 사수 3명 이상, RED 표적 6명 이상, golden 지형점 2개 이상, 임시 CSV에서 로드한 `WeaponRanges`를 만들어 `build_enrichment_slots`를 부르는 헬퍼다. 전체 시나리오 파일에 의존하지 않는다. 기본값은 `min_new_unique_pairs=2`로 낮춘 설정을 써서 상한·고유성만 보고, `test_enrichment_raises_when_minimum_pairs_unreachable`만 저장소 기본 설정(최소 20)을 쓴다. `shared_target_ref=True`면 표적 두 명의 추적 지명을 같은 `LOC_*`로 둔다. `blocked_shooters`는 `{object_id: reason}`이며 헬퍼가 그대로 넘긴다.

- [ ] **Step 2: Run the new tests and verify the missing selector failure**

Run: `python -m pytest tests/test_engagements.py -k enrichment -v`

Expected: FAIL — `build_enrichment_slots`와 `expected_suppress_spo`가 정의되지 않았다.

- [ ] **Step 3: Implement verified firing-location selection and SPO accounting**

```python
def choose_firing_location(layout: BattlefieldLayout, shooter: Coord,
                           target: Coord, range_spec,
                           reserved: set[str]) -> tuple[str, Coord] | None:
    """표적을 사거리 안에 두면서 사수에게 가장 가까운 golden 지형점.

    golden만 쓴다 — derived·relocated 점은 지형(물·급경사)이 확인되지 않아
    이동 task가 도착하지 못할 수 있다(geometry.unverified_terrain_ids).
    """
    candidates = []
    for ref in layout.location_ids():
        if layout.source_of(ref) != "golden" or ref in reserved:
            continue
        coord = layout.coord(ref)
        distance = ground_distance(coord, target)
        if range_spec.min_m <= distance <= range_spec.max_m:
            candidates.append((ground_distance(shooter, coord), ref, coord))
    if not candidates:
        return None
    _, ref, coord = min(candidates, key=lambda x: (x[0], x[1]))
    return ref, coord


def expected_suppress_spo(
        slots: tuple[EngagementSlot, ...]) -> set[tuple[str, str]]:
    """후처리가 만들 것으로 예상되는 (공격자, 정규화된 표적 위치) 집합.

    GT의 제압사격은 객체가 아니라 위치를 목적어로 갖는다. 서로 다른 표적
    객체라도 같은 지명에 서 있으면 같은 SPO 한 개로 접힌다 — 슬롯을 세는
    것으로 고유 관계 수를 주장할 수 없다(설계 §6.3).
    """
    return {(s.shooter_id, s.target_ref) for s in slots if s.target_ref}
```

- [ ] **Step 4: Implement candidate ordering and assignment**

`build_enrichment_slots`는 다음 정렬 키를 정확히 쓴다.

```python
targets = sorted(target_ids,
                 key=lambda oid: (task_counts.get(oid, 0),
                                  last_task_times.get(oid, -1), oid))
shooters = sorted(shooter_ids,
                  key=lambda oid: (assigned_shooters[oid],
                                   source_fire_counts[oid], oid))
```

각 표적에 대해 사수를 위 순서로 시도하고, 처음 통과하는 쌍을 받는다. 받은 쌍마다:

- `scheduled_time_s = max(last_task_times.get(shooter, 0), last_task_times.get(target, 0)) + config.slot_spacing_s * (accepted_index + 1)`.
- 그 시각의 사수·표적 좌표를 `PositionTracker`로 다시 푼다(Task 1과 같은 우선순위).
- 거리가 사수의 `ranges.spec(entity_class, "direct")` 안이면 `firing_ref=""`로 제자리 사격.
- 아니면 `choose_firing_location`으로 golden 지점을 고르고, 고른 지점을 `reserved`에 넣어 두 사수가 같은 점에 서지 않게 한다. `shooter_coord`는 고른 지점 좌표로 바꾸고 `distance_m`도 그 지점 기준으로 다시 잰다.
- `slot_id = f"ENR-{accepted_index:03d}-{shooter}-{target}"`, `origin="enrichment"`, `source_event_ids=()`, `provenance = f"enrichment:low_task_target:{target}"`.
- `shooters`를 순회할 때마다 `assigned_shooters[shooter] += 1`로 세어 다음 표적의 정렬 키가 갱신되게 한다(부하 분산이 결정적으로 일어난다).

다음 사유로 거절하고 `SlotRejection`을 남긴 뒤 다음 후보로 넘어간다. 후보 하나의 실패는 전체 컴파일을 멈추지 않는다(설계 §12 마지막 문단).

| reason | 조건 |
| --- | --- |
| `same_faction` | 사수와 표적의 `faction`이 같다 |
| `target_unarmed` | 표적의 `weapons`가 비었거나 첫 원소가 빈 문자열 |
| `target_not_taskable` | 표적이 `taskable`이 아니거나 UAV·통제점·발사체다 |
| `target_task_count_too_high` | `task_counts.get(target, 0) > config.max_target_task_count` |
| `target_cap_reached` | 그 표적이 이미 `config.max_slots_per_target`개 |
| `shooter_cap_reached` | 그 사수가 이미 `config.max_slots_per_shooter`개 |
| `duplicate_pair` | `(shooter, target)`이 이미 채택됨 |
| `duplicate_suppress_spo` | `(shooter, target_ref)`가 이미 채택된 슬롯의 SPO와 같다 |
| `no_direct_range` | `ranges.spec(entity_class, "direct")`가 없다 |
| `no_verified_firing_location` | 사거리를 만족하는 golden 지점이 없다 |
| `shooter_no_task` | 호출자가 `blocked_shooters`로 넘긴 사유 |
| `shooter_unbounded_predecessor` | 호출자가 `blocked_shooters`로 넘긴 사유 |
| `target_already_engaged` | 그 표적을 마지막 원문 task 시각 이후에 치는 source 슬롯이 이미 있다 |

`blocked_shooters`에 든 사수는 후보 순회 전에 한 번씩 `SlotRejection(shooter, "", reason)`으로 기록하고 `shooters`에서 제외한다 — 감사표에서 "왜 이 객체가 안 뽑혔나"를 바로 읽을 수 있어야 한다.

`duplicate_suppress_spo`로 걸린 후보는 사유만 남기고 버린다. 같은 SPO를 만들지 않는 것이 목적이므로 나중에 다시 꺼내도 결과가 같다 — 재시도 큐를 만들지 않는다.

`target_new_unique_pairs`에서 멈추고 `max_new_unique_pairs`를 절대 넘지 않는다. 채택 수가 `min_new_unique_pairs` 미만이면 채택 수, 최소치, 사유별 집계를 담아 `ValueError`를 올린다.

- [ ] **Step 5: Run selector tests**

Run: `python -m pytest tests/test_engagements.py -k enrichment -v`

Expected: 두 번 호출한 결과가 같고, 상한·진영·고유성·SPO·최소치 테스트가 모두 통과.

- [ ] **Step 6: Add the full-scenario candidate-count test**

```python
def test_full_scenario_can_supply_at_least_twenty_new_pairs(full_inputs):
    result = build_enrichment_slots(**full_inputs)
    assert 20 <= len(result.slots) <= 30
    assert len({(s.shooter_id, s.target_id) for s in result.slots}) == \
           len(result.slots)
```

`full_inputs`는 `build/events/battle.jsonl`과 저장소 config에서 만든다. JSONL이 없을 때만 skip하고, 있을 때 20쌍 단언을 약화하지 않는다.

- [ ] **Step 7: Commit deterministic selection**

```bash
git add vtmak/scnx/engagements.py tests/test_engagements.py
git commit -m "feat(scnx): select low-task engagement targets"
```

### Task 3: Static Schedule and Bounded Wait Insertion

설계 §7이 요구하는 도달 가능성 장치다. PLN에는 절대 시각 트리거가 없고 객체별 큐가 즉시 순차 실행되므로, 사건 시각을 맞추려면 앞선 task의 예상 종료 시각을 누적하고 남는 시간만큼 유한 `wait-duration`을 넣어야 한다. 이건 실행시간 예측이 아니라 **도달 가능성 확보용 정적 스케줄**이다.

**Files:**
- Modify: `vtmak/scnx/engagements.py`
- Modify: `vtmak/scnx/plan.py`
- Modify: `tests/test_engagements.py`

**Interfaces:**
- Consumes: `PlanStep`, `EnrichmentConfig`, `Coord`, `ground_distance`.
- Produces: `UNBOUNDED`, `estimate_step_duration(step, config, move_distance_m) -> float`, `ActorClock`, `plan.with_wait_seconds(pln, seconds) -> str`.

- [ ] **Step 1: Write the failing duration and clock tests**

```python
import math

from vtmak.scnx.engagements import UNBOUNDED, ActorClock, estimate_step_duration
from vtmak.scnx.plan import PlanStep, with_wait_seconds

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
```

- [ ] **Step 2: Run the tests and verify the missing schedule API**

Run: `python -m pytest tests/test_engagements.py -k 'duration or clock or wait' -v`

Expected: FAIL — `UNBOUNDED`, `ActorClock`, `estimate_step_duration`, `with_wait_seconds`가 없다.

- [ ] **Step 3: Add the wait substitution helper to `plan.py`**

수확된 템플릿은 `(Task (task-type "wait-duration") (subtask False) (allow-task-visualizations True) (seconds-to-wait 60.000000))`이다. 기본값 60초를 그대로 두면 큐가 밀려 뒤의 교전이 도달하지 못한다.

```python
_RE_WAIT_SECONDS = re.compile(r"\(seconds-to-wait\s+[-\d.]+\)")


def with_wait_seconds(pln: str, seconds: float) -> str:
    """대기 템플릿의 초를 치환한다. 자리가 없으면 예외다.

    조용히 넘기면 60초 기본값이 남아 뒤의 사격이 시나리오 끝까지 밀린다 —
    .scnx를 열어보기 전엔 보이지 않는 종류의 실패다.
    """
    if seconds <= 0:
        raise ValueError(f"대기 초가 양수가 아니다: {seconds}")
    out, count = _RE_WAIT_SECONDS.subn(f"(seconds-to-wait {seconds:.6f})",
                                       pln, count=1)
    if count != 1:
        raise ValueError("wait-duration 템플릿에 seconds-to-wait 자리가 없다")
    return out
```

- [ ] **Step 4: Implement duration estimation and the actor clock**

`vtmak/scnx/engagements.py`에 추가한다.

```python
import re

from .plan import PlanStep

# 종료 시각을 계산할 수 없다는 표시. 이 뒤에는 슬롯을 놓지 않는다.
UNBOUNDED = -1.0

_RE_TASK_TYPE = re.compile(r'\(task-type\s+"([^"]*)"\)')
_RE_WAIT_VALUE = re.compile(r"\(seconds-to-wait\s+([-\d.]+)\)")

# 끝나는 시각을 아는 task만 여기 있다. 없는 task-type은 전부 UNBOUNDED다 —
# 모르는 것을 짧게 잡으면 뒤의 교전이 표적이 도착하기도 전에 실행된다.
_MOVE_TASKS = {"move-to-location-task", "move-to", "move-to-entity"}


def estimate_step_duration(step: PlanStep, config: EnrichmentConfig,
                           move_distance_m: float) -> float:
    """PlanStep 하나의 예상 소요 시간(초). 모르면 UNBOUNDED.

    설계 §7: 완전한 실행시간 예측이 아니라 도달 가능성을 확보하기 위한
    정적 스케줄이다. 이동은 설정 속도로 나누고, 고정 지속시간 task는
    템플릿·설정의 값을 쓴다.
    """
    if not step.pln:
        return 0.0                      # 저작되지 않은 단계는 큐에 없다
    m = _RE_TASK_TYPE.search(step.pln)
    task_type = m.group(1) if m else ""
    if task_type == "wait-duration":
        v = _RE_WAIT_VALUE.search(step.pln)
        return float(v.group(1)) if v else UNBOUNDED
    if task_type == "provide_suppressive_fire_loc":
        return float(config.suppress_duration_s)
    if task_type == "fire-at-target":
        return config.direct_fire_duration_s
    if task_type in _MOVE_TASKS:
        return move_distance_m / config.movement_speed_mps
    if task_type.startswith("set-") or step.action_label == SPEED_LABEL:
        return config.default_task_duration_s
    if task_type in ("aim-at-location", "aim-at-entity"):
        return config.default_task_duration_s
    return UNBOUNDED


class ActorClock:
    """한 객체의 큐를 따라 누적되는 정적 시계.

    UNBOUNDED task를 한 번 지나면 그 뒤로는 시각을 말할 수 없다. 멈춘 시계로
    슬롯을 배치하지 않도록 bounded가 False로 굳는다(설계 §7 마지막 문단).
    """

    def __init__(self, start_s: float, config: EnrichmentConfig) -> None:
        self._now = float(start_s)
        self._cfg = config
        self._bounded = True

    @property
    def now_s(self) -> float:
        return self._now

    @property
    def bounded(self) -> bool:
        return self._bounded

    def advance(self, step: PlanStep, move_distance_m: float = 0.0) -> None:
        if not self._bounded:
            return
        d = estimate_step_duration(step, self._cfg, move_distance_m)
        if d == UNBOUNDED:
            self._bounded = False
            return
        self._now += d

    def wait_needed_for(self, scheduled_time_s: int) -> float | None:
        """scheduled_time_s에 다음 task를 시작하려면 얼마나 기다려야 하나.

        None은 '스케줄할 수 없다'는 뜻이다. 이미 지난 시각이면 최소 관측
        시간만큼만 기다린다 — 음수 대기는 만들지 않는다.
        """
        if not self._bounded:
            return None
        return max(float(self._cfg.minimum_observation_duration_s),
                   float(scheduled_time_s) - self._now)
```

`SPEED_LABEL`은 `plan.py`에서 import한다.

- [ ] **Step 5: Run the schedule tests**

Run: `python -m pytest tests/test_engagements.py -k 'duration or clock or wait' -v`

Expected: 여섯 테스트 모두 통과.

- [ ] **Step 6: Commit the static schedule**

```bash
git add vtmak/scnx/engagements.py vtmak/scnx/plan.py tests/test_engagements.py
git commit -m "feat(scnx): estimate task durations for reachable queues"
```

### Task 4: Lower Every Slot to Move, Wait, Direct Fire, Suppressive Fire

**Files:**
- Modify: `vtmak/scnx/plan.py:65-105`
- Modify: `vtmak/scnx/plan.py:127-216`
- Modify: `tests/test_spec.py`

**Interfaces:**
- Consumes: `EngagementSlot`, `EnrichmentConfig`, `ActorClock`, existing `_one`, `_pick_template`, `_fill`, `with_weapon`, `with_wait_seconds`.
- Produces: `build_engagement_steps(slot, entity, catalog, kinds, ranges, ctx, clock, config) -> list[PlanStep]`, `with_suppression_limits(pln, slot) -> str`.

- [ ] **Step 1: Replace the old mutually exclusive behavior test with failing sequence tests**

```python
def test_every_source_direct_fire_is_followed_by_suppressive_fire(spec):
    pairs = []
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        for i, step in enumerate(live[:-1]):
            if step.task_kind != "fire_direct":
                continue
            nxt = live[i + 1]
            assert nxt.task_kind == "suppress", (oid, step.event_id)
            assert nxt.slot_id == step.slot_id
            pairs.append((step, nxt))
    assert len([p for p in pairs if p[0].slot_id.startswith("SRC-")]) == 77


def test_suppressive_step_uses_bounded_duration_and_ammo(spec):
    suppress = [s for steps in spec.entity_plans.values() for s in steps
                if s.task_kind == "suppress" and s.pln]
    assert suppress
    for step in suppress:
        assert "(durationRapid 5.000000)" in step.pln
        assert "(durationTotal 10.000000)" in step.pln
        assert "(ammoLimit 10)" in step.pln


def test_slot_preparation_steps_come_before_the_direct_fire(spec):
    # 이동·대기는 사격 앞에만 붙는다. 사격과 제압 사이에 끼면 두 관측이
    # 다른 교전으로 갈라진다.
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        for slot_id in {s.slot_id for s in live if s.slot_id}:
            block = [s for s in live if s.slot_id == slot_id]
            kinds = [s.task_kind for s in block]
            assert kinds[-2:] == ["fire_direct", "suppress"], (oid, slot_id)
            assert set(kinds[:-2]) <= {"move", "wait"}, (oid, slot_id)


def test_every_wait_task_is_bounded_and_substituted(spec):
    waits = [s for steps in spec.entity_plans.values() for s in steps
             if s.pln and 'task-type "wait-duration"' in s.pln]
    assert waits
    for step in waits:
        m = re.search(r"\(seconds-to-wait ([-\d.]+)\)", step.pln)
        assert m, step.event_id
        assert 0.0 < float(m.group(1)) <= 3600.0, step.event_id
```

`test_suppressive_fire_replaces_plain_fire_when_target_is_suppressed`를 삭제한다. 대체는 더 이상 계약이 아니다.

- [ ] **Step 2: Run the tests and verify they fail on 26 direct tasks**

Run: `python -m pytest tests/test_spec.py -k 'source_direct_fire or bounded_duration or preparation_steps or wait_task' -v`

Expected: 첫 테스트는 source 쌍이 26개거나 후속이 suppress가 아니라고 보고하고, duration 테스트는 옛 60초·100발 값을 본다. `slot_id` 속성이 없어 `AttributeError`가 날 수도 있다 — Step 3이 먼저 그 필드를 만든다.

- [ ] **Step 3: Extend `PlanStep` with explicit planning metadata**

```python
@dataclass
class PlanStep:
    event_id: str
    time_s: int
    template: str
    task_kind: str
    action_label: str | None
    pln: str | None
    refs: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    skip_reason: str = ""
    slot_id: str = ""
    planned_intent: str = ""
    intent_object: str = ""
```

기존 생성자는 전부 새 필드의 기본값을 쓴다.

- [ ] **Step 4: Implement suppression-limit substitution**

```python
_SUPPRESSION_FIELDS = (
    (re.compile(r"\(ammoLimit\s+\d+\)"), "(ammoLimit {ammo})"),
    (re.compile(r"\(durationRapid\s+[-\d.]+\)"),
     "(durationRapid {rapid:.6f})"),
    (re.compile(r"\(durationTotal\s+[-\d.]+\)"),
     "(durationTotal {total:.6f})"),
)


def with_suppression_limits(pln: str, slot) -> str:
    """제압사격의 지속시간·탄약을 슬롯 값으로 낮춘다.

    수확된 기본값은 60초·100발이다. 그대로 두면 한 객체가 1분을 쏘는 동안
    큐가 정체되고 표적이 과잉 피해를 입어 뒤의 교전이 사라진다(설계 §5).
    """
    out = pln
    for pattern, shape in _SUPPRESSION_FIELDS:
        value = shape.format(ammo=slot.suppress_ammo_limit,
                             rapid=float(slot.suppress_rapid_duration_s),
                             total=float(slot.suppress_duration_s))
        out, count = pattern.subn(value, out, count=1)
        if count != 1:
            raise ValueError(f"제압사격 템플릿 필드 없음: {pattern.pattern}")
    return out
```

- [ ] **Step 5: Implement four-stage slot lowering**

`build_engagement_steps(slot, entity, catalog, kinds, ranges, ctx, clock, config)`는 다음 순서로 `PlanStep`을 만든다. 모든 단계에 `step.slot_id = slot.slot_id`를 붙인다.

1. `slot.firing_ref`가 비어 있지 않으면 사격 지점 이동 한 단계. 합성 `Event(event_id=slot.slot_id, time_s=slot.scheduled_time_s, template="moveTo", actor=slot.shooter_id, dst=slot.firing_ref)`를 만들어 `_one(..., kind="move", ...)`을 부른다. `planned_intent="takes_firing_position_against"`, `intent_object=slot.target_id`를 붙인다. `clock.advance(step, ground_distance(slot.shooter_coord, slot.firing_coord))`.
2. `clock.wait_needed_for(slot.scheduled_time_s)`가 `None`이 아니고 `> config.minimum_observation_duration_s`이면 대기 한 단계. `_one(..., kind="wait", ...)`으로 템플릿을 얻고 `with_wait_seconds`로 초를 치환한다. `None`이면 대기를 넣지 않는다 — 시계가 멈춘 객체다.
3. 직접사격. 합성 `Event(template="directFireAt", actor=slot.shooter_id, target=slot.target_id, src=slot.firing_ref or "")`로 `_one(..., kind="fire_direct", ...)`. 사거리 검사가 필요로 하는 `fire_distance`에는 `{slot.slot_id: slot.distance_m}`를 넘긴다.
4. 제압사격. 합성 `Event(template="directFireAt", actor=slot.shooter_id, target=slot.target_ref, ...)`로 `_one(..., kind="suppress", ...)`을 부르고 결과 PLN에 `with_suppression_limits`를 적용한다. 제압사격은 표적 좌표만 필요하다(`task_kinds.csv` 비고).

마지막에 살아 있는(`pln`이 있는) 단계의 `task_kind`가 `[..., "fire_direct", "suppress"]`로 끝나는지 `assert`한다. 아니면 `ValueError`를 올린다 — 두 단계 사이에 무언가 끼는 것은 조용히 넘길 수 있는 결함이 아니다.

합성 `Event`는 메모리 안에서만 산다. `build/events/battle.jsonl`에 쓰지 않는다(설계 §3 제외 항목).

- [ ] **Step 6: Rewire `build_entity_plan`**

`build_entity_plan`이 `slots_by_event: dict[str, EngagementSlot]`를 받게 바꾼다. `directFireAt` 이벤트에 슬롯이 있으면 `build_engagement_steps`를 부르고, 옛 제압사격 대체 분기는 타지 않는다. `suppression` 인자와 `kind = "suppress"` 대체 로직을 지운다. 같은 함수 안에서 각 단계마다 `clock.advance`를 불러 시계를 계속 굴린다.

- [ ] **Step 7: Run the sequence tests**

Run: `python -m pytest tests/test_spec.py -k 'source_direct_fire or bounded_duration or preparation_steps or wait_task' -v`

Expected: 네 테스트 모두 통과하고 source 쌍 수가 정확히 77.

- [ ] **Step 8: Commit four-stage lowering**

```bash
git add vtmak/scnx/plan.py tests/test_spec.py
git commit -m "feat(scnx): emit direct and suppressive fire together"
```

### Task 5: Replace Blocking Follow and Failing Position-Finding Tasks

**Files:**
- Modify: `vtmak/scnx/engagements.py`
- Modify: `vtmak/scnx/plan.py`
- Modify: `vtmak/scnx/spec.py`
- Modify: `config/task_kinds.csv`
- Modify: `config/pattern_map.csv`
- Modify: `tests/test_spec.py`
- Modify: `tests/test_engagements.py`
- Modify: `tests/test_task_kinds.py`

**Interfaces:**
- Consumes: actor and threat positions, `BattlefieldLayout` golden locations, entity placement coords, ordered actor events.
- Produces: `choose_cover_location(layout, actor, threat, config, occupied)`, finite move steps carrying `planned_intent` and `intent_object`.

- [ ] **Step 1: Write failing tests for terminal-only follow and absent find tasks**

```python
def test_unbounded_follow_is_terminal(spec):
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        for i, step in enumerate(live):
            if 'task-type "follow-entity"' in step.pln:
                assert i == len(live) - 1, (oid, step.event_id,
                                            live[i + 1].event_id)


def test_find_tasks_are_lowered_to_moves_with_intent(spec):
    live = [s for steps in spec.entity_plans.values() for s in steps if s.pln]
    assert all('task-type "find_firing_position"' not in s.pln for s in live)
    assert all('task-type "find_cover"' not in s.pln for s in live)
    intents = {s.planned_intent for s in live if s.planned_intent}
    assert {"takes_firing_position_against", "takes_cover_from"} <= intents
    assert all(s.intent_object for s in live if s.planned_intent)
```

`tests/test_engagements.py`에 엄폐 지점 선택의 경계 테스트를 넣는다.

```python
def test_cover_point_must_increase_threat_distance_and_stay_in_bounds():
    layout = _layout_with_golden_points()      # 위협 쪽 1개, 반대쪽 2개
    cfg = EnrichmentConfig.defaults()
    ref, coord = choose_cover_location(layout, _actor(), _threat(), cfg,
                                       occupied=[])
    assert ground_distance(coord, _threat()) > ground_distance(_actor(),
                                                               _threat())
    assert layout.source_of(ref) == "golden"


def test_cover_point_at_exactly_the_move_limit_is_accepted():
    cfg = EnrichmentConfig.defaults()          # max_cover_move_m = 100.0
    layout = _layout_with_point_at(100.0)
    assert choose_cover_location(layout, _actor(), _threat(), cfg,
                                 occupied=[]) is not None


def test_cover_point_just_past_the_move_limit_is_rejected():
    cfg = EnrichmentConfig.defaults()
    layout = _layout_with_point_at(100.1)
    assert choose_cover_location(layout, _actor(), _threat(), cfg,
                                 occupied=[]) is None


def test_cover_point_respects_minimum_entity_separation():
    cfg = EnrichmentConfig.defaults()          # min_entity_separation_m = 15.0
    layout = _layout_with_single_valid_point()
    only = layout.coord(layout.location_ids()[0])
    assert choose_cover_location(layout, _actor(), _threat(), cfg,
                                 occupied=[only]) is None


def test_no_verified_cover_point_returns_none_not_a_find_task():
    layout = _layout_with_only_points_toward_the_threat()
    assert choose_cover_location(layout, _actor(), _threat(),
                                 EnrichmentConfig.defaults(),
                                 occupied=[]) is None
```

헬퍼는 전부 좌표 산술뿐이며 시나리오 파일을 읽지 않는다. `_actor()`는 `Coord(21.0, 105.0)`, `_threat()`는 `Coord(21.0, 105.002)`(동쪽 약 208m)를 돌려준다. 레이아웃 헬퍼는 `BattlefieldLayout({"locations": {...}})`를 직접 만들고 각 지점에 `"src": "golden"`을 붙인다.

```python
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
```

`_layout_with_point_at(100.0)`과 `(100.1)`이 경계 두 개를 만든다. `ground_distance`가 경도 스케일을 위도로 보정하므로 정확히 100.0 m가 아니라 100.0 m 이하·초과만 보장된다 — 테스트는 `is not None` / `is None`만 단언하고 거리 자체를 단언하지 않는다.

- [ ] **Step 2: Run the tests and verify current find/follow failures**

Run: `python -m pytest tests/test_spec.py tests/test_engagements.py -k 'unbounded_follow or find_tasks_are_lowered or cover_point' -v`

Expected: FAIL — follow 뒤에 후속 task가 있고, 두 find task가 남아 있고, `choose_cover_location`이 없다.

- [ ] **Step 3: Implement a verified cover-location selector**

```python
def choose_cover_location(layout: BattlefieldLayout, actor: Coord,
                          threat: Coord, config: EnrichmentConfig,
                          occupied: list[Coord]) -> tuple[str, Coord] | None:
    """위협에서 멀어지는 golden 지형점. 없으면 None.

    설계 §8의 세 제약을 모두 건다. 위협에서 멀어질 것, 전장 경계(=레이아웃이
    아는 지명) 안일 것, 다른 객체와 최소 이격을 지킬 것. 셋 중 하나라도
    못 지키면 이동 task를 만들지 않고 None을 돌려준다 — 실패하는 find_cover로
    되돌아가지 않는다.
    """
    current = ground_distance(actor, threat)
    choices = []
    for ref in layout.location_ids():
        if layout.source_of(ref) != "golden":
            continue                      # 지형 미확인 점에는 보내지 않는다
        coord = layout.coord(ref)
        move = ground_distance(actor, coord)
        away = ground_distance(coord, threat)
        if move > config.max_cover_move_m or away <= current:
            continue
        if any(ground_distance(coord, o) < config.min_entity_separation_m
               for o in occupied):
            continue
        choices.append((-away, move, ref, coord))
    if not choices:
        return None
    _, _, ref, coord = min(choices)
    return ref, coord
```

`occupied`는 `build_spec`이 넘기는 다른 객체의 배치 좌표 목록이다. 레이아웃의 `location_ids()`만 순회하므로 전장 경계는 자동으로 지켜진다 — 레이아웃 밖 좌표는 애초에 후보에 없다.

- [ ] **Step 4: Lower follow and find behaviors**

- `follow`로 매핑된 이벤트는 그 객체의 이후 이벤트 중 `noop`이 아닌 task kind가 하나라도 있는지 본다. 있으면 `_one`을 `move`로 부르고 이벤트의 원래 `dst`를 목적지로 쓴다. 뒤에 아무것도 없는 종단 follow만 `follow`로 남는다.
- 사격 준비 매핑을 `find_fp`에서 `move_firing_position`으로 바꾼다. `next_fire_target`을 풀고, 그 표적에 대해 사수의 직접사거리를 만족하는 golden 지점을 `choose_firing_location`으로 고른 뒤 좌표 이동 단계를 만든다. `planned_intent="takes_firing_position_against"`, `intent_object=<위협 객체 id>`.
- `hitBy` 매핑을 `take_cover`에서 `move_cover`로 바꾼다. `choose_cover_location`으로 지점을 고르고 좌표 이동 단계를 만든다. `planned_intent="takes_cover_from"`, `intent_object=<피격 원천 객체 id>`.
- 검증된 지점이 없으면 `pln=None`, 명시적 `issues`, 새 `skip_reason="no_verified_position"`인 `PlanStep`을 만든다. 실패하는 find task로 되돌아가지 않는다.
- `vtmak/scnx/gates.py::check_g3`의 C3.5는 `skip_reason`이 붙은 단계를 REPORT로 낮춘다. `no_verified_position`도 그 규칙을 그대로 받는다 — 새 분기를 만들지 않는다.

`config/task_kinds.csv`에 두 행을 추가한다. 기존 `좌표로 이동` 행동 라벨을 그대로 쓴다.

```csv
move_firing_position,COORD,next_fire_target,,좌표로 이동,,,"사격위치 탐색 대체 — find_firing_position은 2026-08 실측 21/21 실패(컨트롤러 비활성). 위협 표적과 사거리로 사격 지점을 컴파일 시 계산해 좌표 이동으로 내린다. 원래 의도는 PlanStep.planned_intent에 남는다"
move_cover,ENTITY,source_obj,,좌표로 이동,,,"피격 후 엄폐 대체 — find_cover는 다수 모델에서 컨트롤러 비활성. 위협에서 멀어지는 golden 지형점을 골라 좌표 이동으로 내린다. Threat = 피격 원천 객체"
```

`config/pattern_map.csv`는 `task_kind` 칸만 바꾼다. `predicate` 칸(`preparesFiringPosition`, `hitBy`)은 원문 의미이므로 건드리지 않는다.

```csv
hitBy,template,hitBy,move_cover
사격 준비 대기>사격 준비,state_transition,preparesFiringPosition,move_firing_position
```

`take_cover`와 `find_fp` 행은 `config/task_kinds.csv`에서 지운다. 남겨 두면 최종 PLN에 실패 task가 다시 나올 경로가 남는다.

- [ ] **Step 5: Update obsolete spec and task-kind tests**

- `find_cover`·`find_firing_position`을 요구하던 `tests/test_spec.py` 테스트를 이동 블록과 의도 메타데이터 단언으로 바꾼다.
- 전술 그래픽 allowlist를 `{"find_fp", "move_cp"}`에서 `{"move_cp"}`로 바꾼다. 사격 지점 이동은 좌표를 쓰므로 통제점 UUID가 필요 없다.
- `tests/test_task_kinds.py`가 `task_kinds.csv`의 모든 행동 라벨이 `task_catalog.csv`에 있는지 검사한다면, 새 두 행의 `좌표로 이동`도 그 검사를 그대로 통과해야 한다. 라벨을 새로 만들지 않았으므로 테스트 수정 없이 통과하는 것이 정상이다 — 통과하지 않으면 CSV 오타다.

- [ ] **Step 6: Run affected tests**

Run: `python -m pytest tests/test_engagements.py tests/test_spec.py tests/test_task_kinds.py -k 'cover or firing_position or follow or tactical_graphics or kinds' -v`

Expected: 선택된 테스트 전부 통과. 생성된 PLN 어디에도 두 find task가 없다.

- [ ] **Step 7: Commit finite task queues**

```bash
git add vtmak/scnx/engagements.py vtmak/scnx/plan.py vtmak/scnx/spec.py config/task_kinds.csv config/pattern_map.csv tests/test_engagements.py tests/test_spec.py tests/test_task_kinds.py
git commit -m "fix(scnx): keep interaction queues reachable"
```

### Task 6: Integrate Slots, Gate G4, and Build Artifacts

**Files:**
- Modify: `vtmak/scnx/spec.py:49-59`
- Modify: `vtmak/scnx/spec.py:235-298`
- Modify: `vtmak/scnx/gates.py`
- Modify: `vtmak/scnx/engagements.py`
- Modify: `scripts/04_compile_scnx.py:43-105`
- Modify: `tests/test_spec.py`
- Modify: `tests/test_audit.py`
- Modify: `tests/test_fixed_objects.py`

**Interfaces:**
- Consumes: `build_source_slots`, `build_enrichment_slots`, `build_engagement_steps`, `ActorClock`, `expected_suppress_spo`.
- Produces: `ScnxSpec.engagement_slots`, `ScnxSpec.engagement_rejections`, `gates.validate_interaction_plan(spec, config) -> list[Violation]`, `engagements.slot_audit_rows(spec) -> list[list[str]]`.

`Violation`과 `blocking`은 `vtmak/gates.py`에, 게이트 함수는 `vtmak/scnx/gates.py`에 있다. `vtmak/scnx/audit.py`는 저작된 `.scnx`를 되읽어 타임테이블 CSV를 만드는 리포터다 — 차단 검사를 거기 넣지 않는다.

- [ ] **Step 1: Write failing integration tests for counts, adjacency, and UAV stability**

```python
def test_spec_contains_source_and_enrichment_slots(spec):
    source = [s for s in spec.engagement_slots if s.origin == "source"]
    added = [s for s in spec.engagement_slots if s.origin == "enrichment"]
    assert len(source) == 77
    assert 20 <= len(added) <= 30
    assert len({(s.shooter_id, s.target_id) for s in added}) == len(added)


def test_expected_suppressive_spo_clears_the_threshold(spec):
    from vtmak.scnx.engagements import expected_suppress_spo
    assert len(expected_suppress_spo(tuple(spec.engagement_slots))) >= 70


def test_enrichment_does_not_change_fixed_uav_plans(full_build_inputs):
    off = build_spec(**full_build_inputs, enrichment_config=None)
    on = build_spec(**full_build_inputs,
                    enrichment_config=EnrichmentConfig.defaults())
    assert on.fixed_objects == off.fixed_objects
    assert on.fixed_plans == off.fixed_plans
```

`tests/test_audit.py`에 합성 spec 세 개를 만들고 각각 차단 위반이 나오는지 본다.

```python
def test_follow_before_fire_is_blocked():
    spec = _synthetic_spec(steps=[_follow_step("O1", "E1"),
                                  _fire_step("O1", "E2")])
    v = validate_interaction_plan(spec, EnrichmentConfig.defaults())
    assert any(x.code == "C4.2" and "O1" in x.detail and "E1" in x.detail
               and "E2" in x.detail for x in v)


def test_duplicate_slot_id_is_blocked():
    spec = _synthetic_spec(slots=[_slot("ENR-000"), _slot("ENR-000")])
    assert any(x.code == "C4.1"
               for x in validate_interaction_plan(
                   spec, EnrichmentConfig.defaults()))


def test_same_faction_slot_is_blocked():
    spec = _synthetic_spec(slots=[_slot("ENR-000", shooter_faction="RED",
                                        target_faction="RED")])
    assert any(x.code == "C4.5"
               for x in validate_interaction_plan(
                   spec, EnrichmentConfig.defaults()))
```

합성 헬퍼는 전체 파이프라인을 돌리지 않는다. 필요한 필드만 채운 `ScnxSpec`를 손으로 만든다.

```python
def _slot(slot_id, shooter="FR-A", target="EN-B", origin="enrichment",
          shooter_faction="BLUE", target_faction="RED"):
    """EngagementSlot 하나와 그 두 진영을 함께 돌려준다."""
    slot = EngagementSlot(slot_id, origin, (), 100, shooter, target,
                          Coord(21.0, 105.0), Coord(21.001, 105.0),
                          "LOC_B", "", None, 111.0, 0, 1, 5, 10, 10, "")
    return slot, {shooter: shooter_faction, target: target_faction}


def _follow_step(oid, event_id):
    return PlanStep(event_id, 0, "moveTo", "follow", "대형 추종 이동",
                    '(Task (task-type "follow-entity") (offset 0 0 0) )')


def _fire_step(oid, event_id, slot_id="SRC-E2"):
    step = PlanStep(event_id, 10, "directFireAt", "fire_direct",
                    "대상 직접사격",
                    '(Task (task-type "fire-at-target") '
                    '(max-rounds-to-fire 1))')
    step.slot_id = slot_id
    return step


def _synthetic_spec(steps=(), slots=()):
    """steps는 객체 O1의 계획, slots는 (slot, factions) 쌍의 목록."""
    spec = ScnxSpec(scenario_id="t", terrain="t")
    if steps:
        spec.entity_plans["O1"] = list(steps)
    factions = {}
    for slot, f in slots:
        spec.engagement_slots.append(slot)
        factions.update(f)
    spec.entities = [EntitySpec(object_id=o, name=o, uuid=o, entity_class="c",
                                type_group="g", faction=fac, dis=None,
                                coord=Coord(21.0, 105.0), heading=0.0,
                                initial_state="")
                     for o, fac in sorted(factions.items())]
    return spec
```

`EntitySpec` 생성자 인자 이름은 `vtmak/scnx/spec.py`의 정의에 맞춘다. 합성 spec에는 `dis=None`이 들어가는데 G4는 DIS를 보지 않으므로 문제가 되지 않는다 — DIS는 G3의 몫이다.

`test_follow_before_fire_is_blocked`가 쓰는 spec에는 슬롯이 없으므로 C4.6·C4.7 위반이 함께 나온다. 테스트는 `any(...)`로 C4.2만 본다 — 개수를 단언하지 않는다.

`tests/test_spec.py`의 `full_build_inputs` fixture는 기존 `_build()`가 `build_spec`에 넘기던 인자들을 그대로 dict로 돌려준다(`events`, `registry`, `layout`, `pattern_map`, `catalog`, `kinds`, `dis`, `ranges`, `scenario_id`). `_build()`를 그 fixture를 쓰도록 고쳐 두 곳이 갈라지지 않게 한다.

- [ ] **Step 2: Run integration tests and verify missing fields/functions**

Run: `python -m pytest tests/test_spec.py tests/test_audit.py tests/test_fixed_objects.py -k 'slots or uav or interaction or suppressive_spo or blocked' -v`

Expected: FAIL — `ScnxSpec`에 슬롯 필드가 없고 `validate_interaction_plan`이 없다.

- [ ] **Step 3: Integrate slots into `build_spec` in a non-circular order**

```python
@dataclass
class ScnxSpec:
    # 기존 필드는 그대로 둔다
    engagement_slots: list[EngagementSlot] = field(default_factory=list)
    engagement_rejections: list[SlotRejection] = field(default_factory=list)
```

`build_spec`이 `enrichment_config: EnrichmentConfig | None = None`을 받게 하고 다음 순서로 돈다.

1. 배치·컨텍스트·엔티티 스펙·source 슬롯·`slots_by_event`를 만든다.
2. 원문 행위자 계획을 만든다. source 슬롯은 Task 4의 네 단계로 내려간다.
3. 살아 있는 `PlanStep`에서 `task_counts`(객체별 pln 보유 단계 수)와 `last_task_times`(그 단계들의 최대 `time_s`)를 센다.
4. 객체별 `ActorClock`을 큐 끝까지 굴려 `bounded`가 False인 사수와, 원문에 `noTask`가 선언된 사수를 `blocked_shooters`로 모은다.
5. `enrichment_config`가 있고 `enabled`면 `build_enrichment_slots`를 부른다. 반환된 `rejected`를 `spec.engagement_rejections`에 넣는다.
6. 각 보강 슬롯을 내려 **사수의** 계획 끝에 붙인다.
7. 행위자별 계획을 `(time_s, slot phase, event_id)`로 정렬하되 같은 `slot_id` 블록의 내부 순서(이동 → 대기 → 직접 → 제압)는 깨지 않는다.

표적 계획에는 아무것도 붙이지 않는다. 입력 `events` 리스트를 변형하지 않는다.

- [ ] **Step 4: Add gate G4 to `vtmak/scnx/gates.py`**

```python
from .engagements import EnrichmentConfig, expected_suppress_spo


def validate_interaction_plan(spec: ScnxSpec,
                              config: EnrichmentConfig) -> list[Violation]:
    """G4 — 교전 슬롯과 큐 도달 가능성.

    G3가 '파일이 말이 되는가'라면 G4는 '이 큐가 VR-Forces에서 끝까지
    도는가'다. 여기서 잡히는 것들은 전부 실행 로그에서만 보이던 실패였다.
    """
    out: list[Violation] = []
    seen_slot_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    factions = {e.object_id: e.faction for e in spec.entities}

    for slot in spec.engagement_slots:
        if slot.slot_id in seen_slot_ids:
            out.append(Violation("G4", "C4.1", f"slot_id 중복: {slot.slot_id}"))
        seen_slot_ids.add(slot.slot_id)
        pair = (slot.shooter_id, slot.target_id)
        if slot.origin == "enrichment":
            if pair in seen_pairs:
                out.append(Violation("G4", "C4.1", f"중복 신규 교전: {pair}"))
            seen_pairs.add(pair)
        if factions.get(slot.shooter_id) == factions.get(slot.target_id):
            out.append(Violation("G4", "C4.5",
                                 f"같은 진영 교전: {slot.slot_id} {pair}"))

    source = [s for s in spec.engagement_slots if s.origin == "source"]
    added = [s for s in spec.engagement_slots if s.origin == "enrichment"]
    if len(source) != 77:
        out.append(Violation("G4", "C4.6", f"원문 교전 슬롯 {len(source)}개 (77 기대)"))
    if not (config.min_new_unique_pairs <= len(added)
            <= config.max_new_unique_pairs):
        out.append(Violation("G4", "C4.6", f"신규 교전 슬롯 {len(added)}개"))
    spo = expected_suppress_spo(tuple(spec.engagement_slots))
    if len(spo) < config.min_expected_suppress_spo:
        out.append(Violation("G4", "C4.7",
                             f"예상 고유 제압사격 SPO {len(spo)}개 "
                             f"({config.min_expected_suppress_spo} 미만)"))

    for oid, steps in sorted(spec.entity_plans.items()):
        live = [s for s in steps if s.pln]
        for i, step in enumerate(live):
            if 'task-type "follow-entity"' in step.pln and i + 1 < len(live):
                out.append(Violation(
                    "G4", "C4.2",
                    f"{oid}: 무기한 follow 뒤 후속 task "
                    f"({step.event_id} → {live[i + 1].event_id})"))
            if 'task-type "find_firing_position"' in step.pln or \
                    'task-type "find_cover"' in step.pln:
                out.append(Violation("G4", "C4.3",
                                     f"{oid}: 실패 task 잔존 {step.event_id}"))
            if 'task-type "wait-duration"' in step.pln and \
                    "(seconds-to-wait 60.000000)" in step.pln:
                out.append(Violation("G4", "C4.8",
                                     f"{oid}: 대기 초 미치환 {step.event_id}"))
        for slot_id in sorted({s.slot_id for s in live if s.slot_id}):
            block = [s for s in live if s.slot_id == slot_id]
            kinds = [s.task_kind for s in block]
            if kinds[-2:] != ["fire_direct", "suppress"]:
                out.append(Violation("G4", "C4.4",
                                     f"{oid} {slot_id}: 사격 두 단계가 인접하지 "
                                     f"않는다 {kinds}"))
    return out
```

여기에 더해, 남은 자리표시자(`TARGET_UUID`, `X Y Z`, `SX SY SZ`, `AZIMUTH_RAD`, `ELEVATION_RAD`)가 살아 있는 PLN에 남아 있으면 `C4.9`로 차단한다.

설계 §12의 나머지 두 항목은 기존 게이트가 이미 덮으므로 G4에서 다시 검사하지 않는다. 괄호 불균형은 G3의 C3.6이, "공격자에게 유효한 직접사격 무기 또는 task 템플릿이 없음"은 G3의 C3.5(`템플릿 없음` issue → BLOCK)와 C3.8(무기 실재 검사)이 잡는다. 사거리 표에 직접사거리가 없는 경우만 슬롯 선택 단계의 `no_direct_range` 거절로 걸러진다.

- [ ] **Step 5: Produce audit rows in `engagements.py`**

```python
AUDIT_COLUMNS = ["slot_id", "origin", "scheduled_time_s", "shooter_id",
                 "target_id", "target_ref", "firing_ref", "distance_m",
                 "target_task_count", "status", "reason"]


def slot_audit_rows(spec) -> list[list[str]]:
    """채택 슬롯과 거절 후보를 한 표에 담는다. 정렬은 결정적이다."""
    rows = [[s.slot_id, s.origin, str(s.scheduled_time_s), s.shooter_id,
             s.target_id, s.target_ref, s.firing_ref, f"{s.distance_m:.1f}",
             str(s.target_task_count), "accepted", ""]
            for s in sorted(spec.engagement_slots,
                            key=lambda x: (x.origin, x.slot_id))]
    rows += [["", "enrichment", "", r.shooter_id, r.target_id, "", "", "", "",
              "rejected", r.reason]
             for r in sorted(spec.engagement_rejections,
                             key=lambda r: (r.reason, r.shooter_id,
                                            r.target_id))]
    return rows
```

- [ ] **Step 6: Wire script 04**

`scripts/04_compile_scnx.py`에서:

- `EnrichmentConfig.load(CFG / "engagement_enrichment.json")`을 읽어 `build_spec`에 넘긴다.
- G3 통과 뒤 G4를 돌린다. `if _report(validate_interaction_plan(spec, cfg)): print("G4 차단 — .scnx를 쓰지 않는다"); return 1`.
- G4까지 통과한 뒤에만 산출물을 쓴다.

```python
engagement_dir = ROOT / "build" / "engagements"
engagement_dir.mkdir(parents=True, exist_ok=True)
(engagement_dir / "slots.jsonl").write_text(
    "".join(json.dumps(s.to_json(), ensure_ascii=False, sort_keys=True) + "\n"
            for s in spec.engagement_slots), encoding="utf-8")
with open(engagement_dir / "audit.csv", "w", encoding="utf-8",
          newline="") as fh:
    w = csv.writer(fh)
    w.writerow(AUDIT_COLUMNS)
    w.writerows(slot_audit_rows(spec))
```

요약 출력에 `원문 교전 {n} · 신규 교전 {m} · 예상 제압 SPO {k}` 한 줄을 더한다.

- [ ] **Step 7: Run integration and audit tests**

Run: `python -m pytest tests/test_spec.py tests/test_audit.py tests/test_fixed_objects.py -v`

Expected: 전부 통과. source 슬롯 77개, 보강 20~30개, UAV 고정 계획이 보강 on/off에서 동일.

- [ ] **Step 8: Commit build integration**

```bash
git add vtmak/scnx/spec.py vtmak/scnx/gates.py vtmak/scnx/engagements.py scripts/04_compile_scnx.py tests/test_spec.py tests/test_audit.py tests/test_fixed_objects.py
git commit -m "feat(scnx): compile and audit enriched engagements"
```

### Task 7: Normalize Observable Suppressive Fire in GT

**Files:**
- Modify: `vtmak/stkg/predicate.py:37-78`
- Modify: `vtmak/stkg/rewrite.py:62-81`
- Modify: `tests/test_stkg_predicate.py`
- Modify: `tests/test_stkg_rewrite.py`

**Interfaces:**
- Consumes: raw `provide_suppressive_fire_loc: ... targetLocation={x,y,z}`.
- Produces: internal `provides_suppressive_fire_at` and canonical `Provide-Suppressive-Fire-Loc` with a snapped location object.

- [ ] **Step 1: Write failing parser and rewrite tests**

```python
def test_suppressive_fire_is_an_observed_location_task():
    parsed = parse("provide_suppressive_fire_loc: "
                   "targetLocation={1.0, 2.0, 3.0}")
    assert parsed.predicate == "provides_suppressive_fire_at"
    assert parsed.object_raw == "1.0,2.0,3.0"
    assert parsed.object_kind == "coord"


def test_rewrite_names_suppressive_fire_without_suppresses(layout):
    rows = [_row(predicate="provide_suppressive_fire_loc: "
                           "targetLocation={1.0, 2.0, 3.0}")]
    out, _, _, tally = rewrite(rows, layout)
    assert out[0]["predicate"] == "Provide-Suppressive-Fire-Loc"
    assert out[0]["object"]
    assert "suppresses" not in tally.predicates


def test_indirect_ffe_stays_a_separate_predicate(layout):
    # 설계 §9.1: FFE-on-Location과 제압사격은 둘 다 위치 사격이지만 간접
    # 화력타격과 직접 제압사격이라 실행 의미가 다르다. 합치지 않는다.
    rows = [_row(predicate="fire_for_effect_loc: "
                           "targetLocation={1.0, 2.0, 3.0}"),
            _row(predicate="provide_suppressive_fire_loc: "
                           "targetLocation={1.0, 2.0, 3.0}")]
    out, _, _, _ = rewrite(rows, layout)
    assert {r["predicate"] for r in out} == {"FFE-on-Location",
                                             "Provide-Suppressive-Fire-Loc"}
    assert "Fires-At-Location" not in {r["predicate"] for r in out}
```

세 번째 테스트의 `fire_for_effect_loc` 원문 문자열은 저장소의 기존 FFE 테스트에서 쓰는 것과 **같은 값**을 복사해 쓴다. 이 계약은 이번 변경의 대상이 아니라 회귀 고정이다.

- [ ] **Step 2: Run the tests and verify the old internal name failure**

Run: `python -m pytest tests/test_stkg_predicate.py tests/test_stkg_rewrite.py -k 'suppressive or ffe' -v`

Expected: FAIL — 파서가 `suppresses`를 돌려주고 rewrite에 매핑이 없다.

- [ ] **Step 3: Add the canonical mapping**

파서 반환을 바꾼다.

```python
return Parsed("provides_suppressive_fire_at", _coord(m.group(1)), "coord")
```

`rewrite.py`에 더한다.

```python
PRED_SUPPRESSIVE_FIRE = "Provide-Suppressive-Fire-Loc"

_NAME = {
    # 기존 항목은 그대로 둔다
    "provides_suppressive_fire_at": PRED_SUPPRESSIVE_FIRE,
}
```

`Fires-At-Location`이나 `suppresses` 행을 추가하지 않는다. 좌표 목적어는 기존 `snap` 분기가 그대로 공급한다 — 지명으로 접히면 `LOC_*`, 아니면 좌표 문자열이 남는다.

- [ ] **Step 4: Run all STKG predicate/rewrite tests**

Run: `python -m pytest tests/test_stkg_predicate.py tests/test_stkg_rewrite.py -v`

Expected: 전부 통과. 미매핑 카운터에 `provides_suppressive_fire_at`이 없다.

- [ ] **Step 5: Commit observable GT normalization**

```bash
git add vtmak/stkg/predicate.py vtmak/stkg/rewrite.py tests/test_stkg_predicate.py tests/test_stkg_rewrite.py
git commit -m "feat(stkg): preserve observable suppressive fire"
```

### Task 8: Remove Derived `suppresses` and Freeze Unit-Predicate Removal

**Files:**
- Modify: `config/derive_rules.csv`
- Modify: `vtmak/derive/relations.py:60-84`
- Modify: `scripts/07_derive_relations.py:22-46`
- Modify: `tests/test_derive_config.py`
- Modify: `tests/test_derive_relations.py`
- Modify: `README.md:190-216`

**Interfaces:**
- Consumes: `hitBy` plus same-line `stateChange` events.
- Produces: `r2_damage(index, rules) -> RuleResult`; no R1 relation and no `suppresses` predicate.

- [ ] **Step 1: Write failing tests for observation-only final relations**

```python
# 설계 §10이 '제거 상태를 회귀 테스트로 고정한다'고 못박은 술어들.
REMOVED_UNIT_PREDICATES = {"partOf", "supports", "reinforces",
                           "unitSuppressed"}


def test_damage_rule_emits_only_observed_damage_effect(idx, rules):
    result = r2_damage(idx, rules)
    assert not result.unmatched
    assert len(result.relations) == 26
    assert {r.rule_id for r in result.relations} == {"R2"}
    assert {r.predicate for r in result.relations} == {"damages"}


def test_final_derived_relations_never_emit_suppresses(idx, rules):
    relations = (r2_damage(idx, rules).relations
                 + r3_direct_fire(idx).relations
                 + r4_indirect_fire(idx, rules).relations
                 + r7_precedes(idx, rules).relations)
    assert "suppresses" not in {r.predicate for r in relations}


def test_unit_and_formation_predicates_stay_removed(idx, rules):
    relations = (r2_damage(idx, rules).relations
                 + r3_direct_fire(idx).relations
                 + r4_indirect_fire(idx, rules).relations
                 + r7_precedes(idx, rules).relations)
    assert REMOVED_UNIT_PREDICATES.isdisjoint({r.predicate
                                               for r in relations})
    # 부대가 주어인 movesToward·occupies·firesUpon도 생성하지 않는다.
    # firesUpon은 지역 대상만 남는다 — 주어가 객체인지로 판별한다.
    assert all(not r.subject.startswith("UNIT-") for r in relations)


def test_derive_rules_config_has_no_suppression_mapping():
    rules = load_rules(ROOT / "config" / "derive_rules.csv")
    assert "R1" not in {r.rule_id for r in rules.rows()}
    assert "suppresses" not in {r.value for r in rules.rows()}
```

`rules.rows()`는 저장소의 기존 로더가 노출하는 접근자 이름으로 맞춘다. 이름이 다르면 그 이름을 쓰되 단언 내용은 바꾸지 않는다.

- [ ] **Step 2: Run derive tests and verify missing `r2_damage`**

Run: `python -m pytest tests/test_derive_config.py tests/test_derive_relations.py -v`

Expected: `r2_damage`가 없어 수집이 실패한다.

- [ ] **Step 3: Remove R1 config and implement R2-only derivation**

`config/derive_rules.csv`에서 R1 행을 지운다.

```python
def r2_damage(index: EventIndex, rules) -> RuleResult:
    """피격 + 같은 줄의 손상 전이 → damages.

    옛 r1r2_hit_state는 제압 전이도 받아 suppresses를 만들었다. 제압사격을
    했다는 사실만으로 특정 객체가 실제로 제압됐다고 단정할 수 없고, 위치
    기반 제압 task에는 표적 UUID조차 없다 — 관측 전용 GT 원칙에서 벗어난다
    (설계 §9.2). 제압 전이 피격은 미매칭이 아니라 '의도적으로 안 본다'.
    """
    states = rules.hit_states()
    rels = []
    for hit in index.by_predicate("hitBy"):
        change = next(
            (e for e in index.by_line(hit.line_no)
             if e.template == "stateChange" and e.actor == hit.actor), None)
        if change is None or change.state_to not in states:
            continue
        rule_id, predicate = states[change.state_to]
        rels.append(Relation(rule_id, predicate, hit.source_obj, hit.actor,
                             (hit.event_id, change.event_id)))
    return RuleResult(tuple(rels), ())
```

이제 설정된 hit state는 `손상 → (R2, damages)` 하나뿐이다.

- [ ] **Step 4: Update the derive script and deterministic test helpers**

`scripts/07_derive_relations.py`의 `("R1·R2", r1r2_hit_state(...))` 항목을 `("R2", r2_damage(...))`로 바꾼다. `_run_all`, 파라미터화된 규칙 기대값, 교차 규칙 테스트, 리포트 기대값을 hit-state 관계 77개에서 damages 26개로 고친다. R3는 77 그대로다 — 직접사격 원인은 여전히 모든 피격을 덮는다.

- [ ] **Step 5: Run derive tests and the script**

Run: `python -m pytest tests/test_derive_config.py tests/test_derive_relations.py -v`

Expected: 전부 통과.

Run: `python scripts/07_derive_relations.py`

Expected: exit 0. `build/derive/relations.csv`에 `suppresses` 술어가 없고, 이벤트 파일이 그대로일 때 `damages` 26, `causes` 98, `firesUpon` 21, `precedes` 2368을 보고한다.

- [ ] **Step 6: Update README and commit**

GT 사격 보강이 관측 전용이며 R1이 빠지고 R2·R3·R4·R7만 남는다는 것, 부대·편제 술어는 계속 생성하지 않는다는 것을 문서화한다.

```bash
git add config/derive_rules.csv vtmak/derive/relations.py scripts/07_derive_relations.py tests/test_derive_config.py tests/test_derive_relations.py README.md
git commit -m "refactor(derive): drop inferred suppresses relation"
```

### Task 9: Verify the Written `.scnx`, Not Just the Spec

설계 §13 통합 테스트가 요구하는 검증이다. 스펙이 맞아도 writer가 순서를 바꾸거나 블록을 빠뜨리면 시뮬레이터는 다른 것을 실행한다. 압축 안의 PLN을 되읽어 확인한다.

**Files:**
- Create: `tests/test_scnx_engagement_integration.py`

**Interfaces:**
- Consumes: `vtmak.scnx.audit.read_scnx`, `vtmak.scnx.audit.parse_pln`, `build/scnx/battle.scnx`.
- Produces: 저작 산출물 수준의 회귀 단언.

- [ ] **Step 1: Write the failing scnx-level tests**

```python
# tests/test_scnx_engagement_integration.py
import json
from pathlib import Path

import pytest

from vtmak.scnx.audit import parse_pln, read_scnx

ROOT = Path(__file__).resolve().parents[1]
SCNX = ROOT / "build" / "scnx" / "battle.scnx"
SLOTS = ROOT / "build" / "engagements" / "slots.jsonl"

pytestmark = pytest.mark.skipif(
    not SCNX.exists(), reason="04를 먼저 실행할 것")


@pytest.fixture(scope="module")
def plans():
    return parse_pln(read_scnx(SCNX).pln)


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
    for entry in declared.get("objects", []):
        assert entry["marking"] in markings, entry["marking"]
```

마지막 테스트의 `declared["objects"]`와 `entry["marking"]` 키 이름은 `config/fixed_objects.json`의 실제 구조에 맞춘다. 구조가 다르면 키만 바꾸고, "선언된 고정 객체가 모두 저작됐다"는 단언 내용은 유지한다.

- [ ] **Step 2: Build and run the integration tests**

Run:

```bash
python scripts/04_compile_scnx.py
python -m pytest tests/test_scnx_engagement_integration.py -v
```

Expected: 네 테스트 모두 통과. `.scnx`가 없으면 skip이 아니라 04가 먼저 성공해야 한다.

- [ ] **Step 3: Commit scnx-level verification**

```bash
git add tests/test_scnx_engagement_integration.py
git commit -m "test(scnx): verify engagement pairs inside the written scenario"
```

### Task 10: End-to-End Build, Static Acceptance, and Runtime Handoff

**Files:**
- Modify: `README.md`
- Test: `tests/test_spec.py`
- Test: `tests/test_audit.py`
- Test: `tests/test_writer.py`

**Interfaces:**
- Consumes: all preceding task outputs.
- Produces: deterministic `.scnx`, slot manifest, audit CSV, postprocessed GT mapping, and a documented VR-Forces runtime checklist.

- [ ] **Step 1: Add the final static acceptance test**

```python
def test_interaction_enrichment_static_acceptance(spec):
    slots = spec.engagement_slots
    assert len([s for s in slots if s.origin == "source"]) == 77
    assert 20 <= len([s for s in slots if s.origin == "enrichment"]) <= 30
    live = [s for steps in spec.entity_plans.values() for s in steps if s.pln]
    assert sum(s.task_kind == "fire_direct" for s in live) == len(slots)
    assert sum(s.task_kind == "suppress" for s in live) == len(slots)
    assert not any("find_firing_position" in s.pln or "find_cover" in s.pln
                   for s in live)
    assert not validate_interaction_plan(spec, EnrichmentConfig.defaults())
```

- [ ] **Step 2: Run the focused acceptance tests**

Run: `python -m pytest tests/test_engagements.py tests/test_spec.py tests/test_audit.py tests/test_writer.py -v`

Expected: 전부 통과.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -q`

Expected: exit 0, 실패 없음.

- [ ] **Step 4: Rebuild the deterministic scenario twice**

Run:

```bash
python scripts/04_compile_scnx.py
python -c "from pathlib import Path; import hashlib; p=Path('build/scnx/battle.scnx'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
python -c "from pathlib import Path; import hashlib; p=Path('build/engagements/slots.jsonl'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
python scripts/04_compile_scnx.py
python -c "from pathlib import Path; import hashlib; p=Path('build/scnx/battle.scnx'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
python -c "from pathlib import Path; import hashlib; p=Path('build/engagements/slots.jsonl'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
```

Expected: 두 컴파일 모두 exit 0이고, `.scnx`와 `slots.jsonl`의 SHA-256이 각각 두 번 같다.

- [ ] **Step 5: Validate generated artifacts**

Run:

```bash
python -c "import json; from pathlib import Path; rows=[json.loads(x) for x in Path('build/engagements/slots.jsonl').read_text(encoding='utf-8').splitlines() if x]; src=[r for r in rows if r['origin']=='source']; new=[r for r in rows if r['origin']=='enrichment']; assert len(src)==77, len(src); assert 20<=len(new)<=30, len(new); assert len({(r['shooter_id'],r['target_id']) for r in new})==len(new); spo={(r['shooter_id'],r['target_ref']) for r in rows if r['target_ref']}; assert len(spo)>=70, len(spo); print(len(src),len(new),len(spo))"
python -c "import csv; from pathlib import Path; rows=list(csv.DictReader(Path('build/engagements/audit.csv').open(encoding='utf-8'))); print(len(rows),'rows'); print(sorted({r['reason'] for r in rows if r['status']=='rejected'}))"
python scripts/07_derive_relations.py
python -c "import csv; from pathlib import Path; p=Path('build/derive/relations.csv'); preds={r['predicate'] for r in csv.DictReader(p.open(encoding='utf-8'))}; assert 'suppresses' not in preds; print(sorted(preds))"
```

Expected: 슬롯 단언이 통과하고 예상 제압 SPO가 70 이상. 파생 술어에 `suppresses`가 없다.

- [ ] **Step 6: Postprocess the available CSV fixture**

Run: `python scripts/05_data_postprocessing.py`

Expected: exit 0. 입력 원시 CSV에 해당 task가 있으면 `build/stkg/ground_truth_ver1.0.csv`에 정규형 `Provide-Suppressive-Fire-Loc` 행이 있고, 어떤 행도 `suppresses`로 정규화되지 않는다.

가용한 CSV가 새 시나리오 이전 것이라 원시 제압사격 관측이 없으면, 이 사전 실행 fixture에서는 0이 기대값임을 기록한다. 파서·rewrite 테스트를 약화하지 않는다.

- [ ] **Step 7: Document the manual VR-Forces acceptance run**

README에 이 체크리스트를 넣는다.

1. `build/scnx/battle.scnx`를 VR-Forces에서 연다.
2. 시나리오를 끝까지 실행하고 새 ground-truth CSV를 `build/csv/` 아래에 저장한다.
3. `python scripts/05_data_postprocessing.py`를 실행한다.
4. 고유 `(subject, predicate, object)` 삼중항 수를 센다.
5. 고유 `Fire-Weapon` 70개 이상, 고유 `Provide-Suppressive-Fire-Loc` 70개 이상을 요구한다.
6. 반복 행 수와 고유 SPO 수를 **따로** 보고한다. 행 수 증가는 성공 지표가 아니다.
7. 관측되지 않은 `slot_id`를 `build/engagements/audit.csv`와 대조해 실패한 선행 task 또는 런타임 오류를 보고한다.
8. UAV 검출률은 측정만 하고 합격 판정에 쓰지 않는다.

- [ ] **Step 8: Commit final verification documentation**

```bash
git add README.md tests/test_spec.py tests/test_audit.py tests/test_writer.py
git commit -m "test(scnx): verify interaction enrichment end to end"
```

## Execution Notes

- 각 task의 집중 테스트는 그 task의 커밋 전에 돌린다. 전체 스위트는 Task 10이 파이프라인을 조립한 뒤에만 돌린다.
- 관련 없는 untracked 공간 관계 plan/spec 파일과 작업 트리에 이미 있는 사용자 변경을 보존한다.
- 새 VR-Forces 실행에서 나온 것이 아니면 재생성된 GT CSV를 런타임 성공의 증거로 커밋하지 않는다.
- 컴파일러가 유효한 저-task 표적 쌍 20개를 못 찾으면 거절 감사와 함께 멈춘다. 진영·무장·고유성·검증된 위치 제약을 조용히 완화하지 않는다.
- 예상 고유 제압 SPO가 70 미만이면 슬롯 수를 늘리기 전에 표적 위치 분산을 먼저 본다. 같은 지명에 몰린 표적은 슬롯을 아무리 늘려도 SPO가 늘지 않는다.
- VR-Forces가 제한된 제압사격 값을 거부하면 정확한 `vrfSim.log` 오류를 캡처하고 다른 필드나 값을 고르기 전에 설계로 돌아간다.
- `follow-entity`의 시간·거리 종료 필드를 나중에 실제로 수확하더라도, 이번 구현에 추정 필드를 넣지 않는다(설계 §7).
- 게이트를 늘릴 때 `vtmak/scnx/audit.py`에 검사를 넣지 않는다. 그 모듈은 저작된 `.scnx`를 되읽는 리포터다. 차단 검사는 `vtmak/scnx/gates.py`에 둔다.
