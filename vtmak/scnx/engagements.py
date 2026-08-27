"""교전 슬롯 — 원문 사건과 PLN 사이의 결정적 중간 표현.

원문 directFireAt를 바로 PLN으로 내리면 '직접사격이냐 제압사격이냐'를
저작 시점에 골라야 하고, 실제로 그래서 77건이 26 + 51로 갈렸다. 슬롯을
두면 한 교전이 두 단계(직접 → 제압)를 모두 갖는다.

무작위를 쓰지 않는다. 모든 순회와 동률 해소는 객체 id와 사건 id의 정렬
순서로 끝낸다 — 같은 입력이 같은 .scnx를 내야 한다(설계 §4).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ..gates import PositionTracker, engagement_locations, resolve_coord
from ..geometry import BattlefieldLayout, Coord, ground_distance
from ..parser import Event
from ..ranges import RangeSpec, WeaponRanges
from ..registry import EntityDef
from .plan import PlanStep, SPEED_LABEL

# 종료 시각을 계산할 수 없다는 표시. 이 뒤에는 슬롯을 놓지 않는다.
UNBOUNDED = -1.0

_RE_TASK_TYPE = re.compile(r'\(task-type\s+"([^"]*)"\)')
_RE_WAIT_VALUE = re.compile(r"\(seconds-to-wait\s+([-\d.]+)\)")

# 끝나는 시각을 아는 task만 여기 있다. 없는 task-type은 전부 UNBOUNDED다 —
# 모르는 것을 짧게 잡으면 뒤의 교전이 표적이 도착하기도 전에 실행된다.
_MOVE_TASKS = {"move-to-location-task", "move-to", "move-to-entity"}


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


def _resolve_pair_coords(actor: str, target: str, time_s: int, src: str,
                         registry: dict[str, EntityDef],
                         layout: BattlefieldLayout, tracker: PositionTracker,
                         hit_at: dict[tuple[str, str], str]
                         ) -> tuple[Coord, Coord, str]:
    """(사수, 표적) → 그 시각의 좌표와 정규화된 표적 지명.

    gates.engagement_pairs와 같은 우선순위다: 사수는 문장이 명시한 src를
    최우선하고(없으면 추적 위치), 표적은 피격 문장 > 정적 바인딩 > 시각별
    추적 순이다. 원문 슬롯(build_source_slots)과 보강 슬롯
    (build_enrichment_slots)이 이 함수 하나를 공유해야 두 우선순위가 갈라지지
    않는다 — 복사본을 두 벌 두면 언젠가 어긋난다.
    """
    shooter_coord = (layout.coord(src) if src and layout.has(src)
                     else resolve_coord(actor, time_s, registry, layout,
                                        tracker))
    tgt_loc = (hit_at.get((actor, target))
              or layout.static_target(target)
              or tracker.location_at(target, time_s))
    target_coord = (layout.coord(tgt_loc) if tgt_loc
                    else resolve_coord(target, time_s, registry, layout,
                                       tracker))
    target_ref = tgt_loc or f"{target_coord.lat:.5f},{target_coord.lon:.5f}"
    return shooter_coord, target_coord, target_ref


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
        shooter_coord, target_coord, target_ref = _resolve_pair_coords(
            e.actor, e.target, e.time_s, e.src, registry, layout, tracker,
            hit_at)
        if shooter_coord.is_zero() or target_coord.is_zero():
            continue          # G0가 이미 잡는 상태 — 슬롯을 만들지 않는다
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


def choose_firing_location(layout: BattlefieldLayout, shooter: Coord,
                           target: Coord, range_spec: RangeSpec,
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


def choose_cover_location(layout: BattlefieldLayout, actor: Coord,
                          threat: Coord, config: EnrichmentConfig,
                          occupied: list[Coord]) -> tuple[str, Coord] | None:
    """위협에서 멀어지는 golden 지형점. 없으면 None.

    find_cover가 다수 모델에서 컨트롤러 비활성으로 실패한다는 사실이
    2026-08 vrfSim.log로 실측됐다(설계 §8). 대체는 스크립트 task가 아니라
    컴파일 시점에 이 지점을 계산해 좌표 이동으로 내리는 것이다.

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


def expected_suppress_spo(
        slots: tuple[EngagementSlot, ...]) -> set[tuple[str, str]]:
    """후처리가 만들 것으로 예상되는 (공격자, 정규화된 표적 위치) 집합.

    GT의 제압사격은 객체가 아니라 위치를 목적어로 갖는다. 서로 다른 표적
    객체라도 같은 지명에 서 있으면 같은 SPO 한 개로 접힌다 — 슬롯을 세는
    것으로 고유 관계 수를 주장할 수 없다(설계 §6.3).
    """
    return {(s.shooter_id, s.target_ref) for s in slots if s.target_ref}


def _target_precheck(target_id: str, registry: dict[str, EntityDef],
                     task_counts: dict[str, int], config: EnrichmentConfig,
                     already_engaged: set[str]) -> str | None:
    """사수와 무관한, 표적 자체의 자격 검사. 첫 실패 사유를 돌려준다.

    target_not_taskable은 registry의 taskable 플래그로만 판정한다. UAV와
    발사체는 이 registry(사건 기반)에 애초에 들어오지 않는다 — UAV는
    scnx/fixed.py가 별도로 붙이고, 발사체는 GT 사후 확정물이라 사건 파싱
    단계에는 존재하지 않는다. 통제점은 이미 taskable=False로 들어온다
    (registry.build_registry가 layout.static_ids()로 표시).

    표적당 상한(max_slots_per_target)은 여기서 검사하지 않는다 — 라운드
    수 자체가 그 상한을 강제한다(build_enrichment_slots의 라운드 루프 주석
    참고). 표적별 카운트를 여기서 또 세면 절대 참이 될 수 없는 분기가
    생긴다.
    """
    target = registry[target_id]
    if not target.taskable:
        # taskable=False인 객체는 registry.build_registry가 weapons도 항상
        # 비워 둔다 — 검사 순서를 뒤집으면 target_not_taskable이 매번
        # target_unarmed에 가려져 죽은 코드가 된다. 먼저 걸러야 트럭처럼
        # taskable이지만 비무장인 객체와 통제점을 서로 다른 사유로 남긴다.
        return "target_not_taskable"
    if not target.weapons or target.weapons[0] == "":
        return "target_unarmed"
    if task_counts.get(target_id, 0) > config.max_target_task_count:
        return "target_task_count_too_high"
    if target_id in already_engaged:
        return "target_already_engaged"
    return None


def _pair_precheck(shooter_id: str, target_id: str,
                   registry: dict[str, EntityDef], config: EnrichmentConfig,
                   assigned_shooters: dict[str, int],
                   accepted_pairs: set[tuple[str, str]]) -> str | None:
    """특정 (사수, 표적) 조합만의 자격 검사. 위치 계산 전에 끝낸다."""
    shooter, target = registry[shooter_id], registry[target_id]
    if shooter.faction == target.faction:
        return "same_faction"
    if assigned_shooters.get(shooter_id, 0) >= config.max_slots_per_shooter:
        return "shooter_cap_reached"
    if (shooter_id, target_id) in accepted_pairs:
        return "duplicate_pair"
    return None


def build_enrichment_slots(
        events: list[Event], registry: dict[str, EntityDef],
        layout: BattlefieldLayout, ranges: WeaponRanges,
        config: EnrichmentConfig, task_counts: dict[str, int],
        last_task_times: dict[str, int], eligible_shooter_ids: list[str],
        blocked_shooters: dict[str, str],
        source_slots: tuple[EngagementSlot, ...]) -> SlotBuildResult:
    """저-task 표적을 우선해 신규 교전 쌍을 고른다(설계 §6.3).

    표적을 바깥 루프로 돈다. 각 표적에는 사수를 정렬 순서대로 시도해 처음
    통과하는 조합 하나만 받는다 — 부하 분산은 accepted마다 assigned_shooters
    를 갱신해 다음 표적의 사수 정렬을 바꾸는 방식으로 결정적으로 일어난다.
    후보 하나의 실패는 SlotRejection만 남기고 다음 후보로 넘어간다. 전체
    컴파일을 멈추지 않는다(설계 §12) — min_new_unique_pairs 미달만 예외다.

    사전조건: eligible_shooter_ids와 blocked_shooters의 키는 반드시
    registry에 있는 object_id여야 한다. registry에 없는 id를 넘기면
    KeyError가 난다 — 호출부가 registry와 다른 소스에서 후보를 모았다는
    뜻이므로 조용히 넘기지 않고 그 자리에서 드러내는 편이 낫다.
    """
    tracker = PositionTracker(events, registry)
    hit_at = engagement_locations(events)

    rejected: list[SlotRejection] = []
    for shooter_id in sorted(blocked_shooters):
        rejected.append(SlotRejection(shooter_id, "",
                                      blocked_shooters[shooter_id]))

    all_shooter_ids = set(eligible_shooter_ids) | set(blocked_shooters)
    shooter_pool = sorted(set(eligible_shooter_ids) - set(blocked_shooters))
    target_ids = sorted(oid for oid in registry if oid not in all_shooter_ids)

    targets = sorted(target_ids, key=lambda oid: (task_counts.get(oid, 0),
                                                   last_task_times.get(oid, -1),
                                                   oid))
    source_fire_counts = Counter(s.shooter_id for s in source_slots)
    # 그 표적을 마지막 원문 task 시각 이후에 치는 source 슬롯이 이미 있다 —
    # 원문이 이미 이 표적을 교전으로 마무리하고 있다는 뜻이라 더 얹지 않는다.
    already_engaged = {
        s.target_id for s in source_slots
        if s.scheduled_time_s >= last_task_times.get(s.target_id, -1)}

    assigned_shooters: dict[str, int] = {oid: 0 for oid in shooter_pool}
    accepted_pairs: set[tuple[str, str]] = set()
    accepted_spo: set[tuple[str, str]] = set()
    reserved_firing_refs: set[str] = set()
    accepted: list[EngagementSlot] = []

    # 표적당 상한(max_slots_per_target)은 이 라운드 수 자체가 강제한다 —
    # 별도 카운터나 검사가 없다. 한 라운드는 targets를 한 바퀴 돌며 표적당
    # 최대 슬롯 하나를 낸다(안쪽 for가 첫 통과 쌍에서 break한다). 그래서
    # 라운드를 상한만큼 돌리면 표적 하나가 받을 수 있는 슬롯은 최대
    # max_slots_per_target개다. 상한=1이면 라운드가 하나뿐이라 기존 단일
    # 패스와 완전히 같다.
    reached_limit = False
    for _round in range(config.max_slots_per_target):
        if reached_limit:
            break
        for target_id in targets:
            if len(accepted) >= config.target_new_unique_pairs:
                reached_limit = True
                break              # 목표 수에서 멈춘다

            precheck = _target_precheck(target_id, registry, task_counts,
                                        config, already_engaged)
            if precheck:
                rejected.append(SlotRejection("", target_id, precheck))
                continue

            shooters = sorted(shooter_pool,
                              key=lambda oid: (assigned_shooters[oid],
                                               source_fire_counts[oid], oid))
            picked: EngagementSlot | None = None
            for shooter_id in shooters:
                reason = _pair_precheck(shooter_id, target_id, registry,
                                        config, assigned_shooters,
                                        accepted_pairs)
                if reason:
                    rejected.append(SlotRejection(shooter_id, target_id,
                                                  reason))
                    continue

                shooter = registry[shooter_id]
                range_spec = ranges.spec(shooter.entity_class, "direct")
                if range_spec is None:
                    rejected.append(SlotRejection(shooter_id, target_id,
                                                  "no_direct_range"))
                    continue

                accepted_index = len(accepted)
                scheduled_time_s = (
                    max(last_task_times.get(shooter_id, 0),
                       last_task_times.get(target_id, 0))
                    + config.slot_spacing_s * (accepted_index + 1))
                shooter_coord, target_coord, target_ref = _resolve_pair_coords(
                    shooter_id, target_id, scheduled_time_s, "", registry,
                    layout, tracker, hit_at)

                spo = (shooter_id, target_ref)
                if spo in accepted_spo:
                    # 같은 SPO를 다시 만들지 않는 것이 목적이므로 사유만
                    # 남기고 버린다 — 재시도 큐를 두지 않는다(다음 사수로
                    # 넘어간다).
                    rejected.append(SlotRejection(shooter_id, target_id,
                                                  "duplicate_suppress_spo"))
                    continue

                distance = ground_distance(shooter_coord, target_coord)
                firing_ref, firing_coord = "", None
                if not (range_spec.min_m <= distance <= range_spec.max_m):
                    loc = choose_firing_location(layout, shooter_coord,
                                                 target_coord, range_spec,
                                                 reserved_firing_refs)
                    if loc is None:
                        rejected.append(SlotRejection(
                            shooter_id, target_id,
                            "no_verified_firing_location"))
                        continue
                    firing_ref, firing_coord = loc
                    reserved_firing_refs.add(firing_ref)
                    shooter_coord = firing_coord
                    distance = ground_distance(firing_coord, target_coord)

                picked = EngagementSlot(
                    slot_id=f"ENR-{accepted_index:03d}-{shooter_id}-"
                           f"{target_id}",
                    origin="enrichment",
                    source_event_ids=(),
                    scheduled_time_s=scheduled_time_s,
                    shooter_id=shooter_id,
                    target_id=target_id,
                    shooter_coord=shooter_coord,
                    target_coord=target_coord,
                    target_ref=target_ref,
                    firing_ref=firing_ref,
                    firing_coord=firing_coord,
                    distance_m=distance,
                    target_task_count=task_counts.get(target_id, 0),
                    direct_fire_rounds=config.direct_fire_rounds,
                    suppress_rapid_duration_s=config.suppress_rapid_duration_s,
                    suppress_duration_s=config.suppress_duration_s,
                    suppress_ammo_limit=config.suppress_ammo_limit,
                    provenance=f"enrichment:low_task_target:{target_id}",
                )
                assigned_shooters[shooter_id] += 1
                accepted_pairs.add((shooter_id, target_id))
                accepted_spo.add(spo)
                break

            if picked is not None:
                accepted.append(picked)
                if len(accepted) >= config.max_new_unique_pairs:
                    reached_limit = True
                    break          # 상한을 절대 넘지 않는다

    if len(accepted) < config.min_new_unique_pairs:
        tally = dict(sorted(Counter(r.reason for r in rejected).items()))
        raise ValueError(
            f"신규 교전 쌍 {len(accepted)}개 — 최소 {config.min_new_unique_pairs}"
            f"개가 필요하다. 사유별 집계: {tally}")

    return SlotBuildResult(slots=tuple(accepted), rejected=tuple(rejected))


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
