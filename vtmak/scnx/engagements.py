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


def build_source_slots(events: list[Event], registry: dict[str, EntityDef],
                       layout: BattlefieldLayout,
                       config: EnrichmentConfig) -> tuple[EngagementSlot, ...]:
    """원문 directFireAt 사건 → 원문 슬롯.

    사수·표적 위치는 gates.engagement_pairs와 같은 우선순위로 푼다 — 해석기를
    두 벌 만들면 언젠가 어긋난다. PositionTracker와 engagement_locations는
    호출 전체에서 한 번만 만든다(사건마다 새로 만들면 매번 전체 이벤트를
    다시 훑어 O(n²)가 된다).
    """
    tracker = PositionTracker(events, registry)
    hit_at = engagement_locations(events)
    slots: list[EngagementSlot] = []
    for e in events:
        if e.template != "directFireAt" or not e.actor or not e.target:
            continue
        shooter_coord = (layout.coord(e.src)
                         if e.src and layout.has(e.src)
                         else resolve_coord(e.actor, e.time_s, registry,
                                            layout, tracker))
        tgt_loc = (hit_at.get((e.actor, e.target))
                  or layout.static_target(e.target)
                  or tracker.location_at(e.target, e.time_s))
        target_coord = (layout.coord(tgt_loc) if tgt_loc
                        else resolve_coord(e.target, e.time_s, registry,
                                           layout, tracker))
        if shooter_coord.is_zero() or target_coord.is_zero():
            continue          # G0가 이미 잡는 상태 — 슬롯을 만들지 않는다
        target_ref = tgt_loc or f"{target_coord.lat:.5f},{target_coord.lon:.5f}"
        slots.append(EngagementSlot(
            slot_id=f"SRC-{e.event_id}",
            origin="source",
            source_event_ids=(e.event_id,),
            scheduled_time_s=e.time_s,
            shooter_id=e.actor,
            target_id=e.target,
            shooter_coord=shooter_coord,
            target_coord=target_coord,
            target_ref=target_ref,
            firing_ref="",         # 원문 슬롯은 제자리에서 쏜다
            firing_coord=None,
            distance_m=ground_distance(shooter_coord, target_coord),
            target_task_count=0,   # 원문 슬롯에는 태스크 총계가 없다
            direct_fire_rounds=config.direct_fire_rounds,
            suppress_rapid_duration_s=config.suppress_rapid_duration_s,
            suppress_duration_s=config.suppress_duration_s,
            suppress_ammo_limit=config.suppress_ammo_limit,
            provenance=f"directFireAt:{e.event_id}",
        ))
    return tuple(sorted(slots, key=lambda s: (s.scheduled_time_s, s.slot_id)))
