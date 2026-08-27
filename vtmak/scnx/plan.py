"""이벤트 → VR-Forces PLN(Task/Set) 블록.

선행 프로젝트와 세 가지가 다르다.
1) 사거리 상수를 코드에 두지 않는다. WeaponRanges가 판정한다.
2) '지점 사격 → 근처 적 객체로 승격'을 하지 않는다. 원문이 모든 사격에
   목표 객체를 명시하므로 추측할 필요가 없다.
3) task_kind를 코드가 아니라 pattern_map.csv에서 읽는다.

무기 이름은 치환하지 않는다. task_catalog의 템플릿이 type_group별로 이미
검증된 무기명을 담고 있고, 그게 VR-Forces에서 실제로 도는 값이다.

태스크를 만들지 않는 경우가 둘 있다. 둘 다 VR-Forces가 실행을 거부하는 것을
2026-08-04 vrfSim.log에서 실측한 결과다(설계 결정이 아니라 관측이다).
1) 모델에 그 task의 컨트롤러가 없다 — entity_class_map.csv의 unsupported_tasks.
2) 간접사격이 최소사거리에 못 미친다 — weapon_ranges.csv의 indirect_min_m.
어느 쪽이든 이벤트·원문 술어·STKG 관계는 그대로 남는다. 빠지는 것은 .pln의
태스크뿐이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ..geometry import Coord, bearing_elevation, ground_distance
from ..parser import Event, PatternMap
from ..ranges import OK, TOO_CLOSE, UNVERIFIED, WeaponRanges
from ..registry import EntityDef
from .catalog import TaskCatalog, TaskKinds

if TYPE_CHECKING:
    # engagements.py가 이미 `from .plan import PlanStep, SPEED_LABEL`을
    # 쓴다. 여기서 engagements를 런타임에 import하면 순환 import로 두
    # 모듈이 함께 깨진다. 타입 힌트에만 필요하므로 TYPE_CHECKING 아래에
    # 두고, `from __future__ import annotations`가 문자열로 미룬다.
    from .engagements import ActorClock, EngagementSlot, EnrichmentConfig

# (task_kind, ref_kind) → 행동 후보, 참조 필드, 사거리 종류는 이제
# config/task_kinds.csv에 있다. 여기에 표를 두면 매핑 하나를 늘릴 때마다
# CSV 두 장과 코드 세 곳을 같이 고쳐야 하고, 실제로 그래서 task_catalog의
# 행동 33종 중 8종만 도달 가능한 상태로 굳어 있었다.

# 보급 차량 저속 기동(m/s). set-speed 템플릿의 기본값을 이걸로 바꾼다.
SUPPLY_SPEED_MPS = 8.0
# 속도만 값을 코드에서 정한다. 나머지 동반 행동은 템플릿을 그대로 쓴다.
SPEED_LABEL = "속도 지정"


class PlanContext(Protocol):
    """spec.py가 주입하는 uuid·좌표·ref_kind 해석기.

    좌표 해석기에 시각이 들어간다. 사격 좌표는 **쏘는 그 순간** 표적이 있는
    곳이어야 한다 — 초기 배치를 쓰면 1.7km를 이동해 온 적을 두고 빈 집결지를
    쏜다.
    """
    def entity_uuid(self, object_id: str) -> str | None: ...
    def ref_uuid(self, ref: str) -> str: ...
    def coord_of(self, ref: str, time_s: int = -1,
                 actor: str = "") -> Coord: ...
    def actor_coord(self, actor: str, time_s: int, src: str = "") -> Coord: ...
    def ref_kind(self, ref: str) -> str: ...   # ENTITY | COORD
    def unit_leader(self, object_id: str) -> str | None: ...
    def choose_firing_location(self, entity_class: str, shooter: Coord,
                               target: Coord) -> tuple[str, Coord] | None: ...
    def choose_cover_location(self, actor: str, actor_coord: Coord,
                              threat_coord: Coord
                              ) -> tuple[str, Coord] | None: ...


# pln을 만들지 않은 이유 중 '의도한 것'. VR-Forces가 실행을 거부한다는 사실이
# 실측으로 확인돼 일부러 저작하지 않은 경우다. 값이 비어 있으면 결함이다
# (템플릿 없음·참조 미해결 등) — G3가 그 둘을 다른 심각도로 다룬다.
SKIP_UNSUPPORTED = "unsupported_task"     # 모델에 그 task의 컨트롤러가 없다
SKIP_MIN_RANGE = "below_min_range"        # 간접사격 최소사거리 미달
# find_firing_position(21/21 실패)·find_cover(다수 모델 실패)를 좌표 이동으로
# 대체할 때 golden 지형점이 세 제약(위협과 멀어짐·경계 안·최소 이격)을 하나도
# 만족하지 못한 경우. 실패하는 find task로 되돌아가지 않고 이 사유로 남긴다.
SKIP_NO_VERIFIED_POSITION = "no_verified_position"


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
    # slot_id는 교전 슬롯 lowering(build_engagement_steps)만 쓴다 — 슬롯이
    # 아닌 단계는 기본값(빈 문자열)으로 남는다. planned_intent·intent_object
    # 는 그보다 넓다 — 슬롯 lowering뿐 아니라 find_firing_position·find_cover
    # 대체(_verified_move, Task 5)도 채운다. 둘 다 스크립트 task가 아닌
    # 좌표 이동으로 내리면서 원래 의도를 GT에 안 나가는 계획 메타데이터로
    # 남기는 자리라 같은 필드를 공유한다.
    slot_id: str = ""
    planned_intent: str = ""
    intent_object: str = ""


def build_entity_plan(events: list[Event], entity: EntityDef,
                      pattern_map: PatternMap, catalog: TaskCatalog,
                      kinds: TaskKinds,
                      ranges: WeaponRanges, ctx: PlanContext,
                      fire_distance: dict[str, float],
                      slots_by_event: dict[str, EngagementSlot],
                      clock: ActorClock,
                      config: EnrichmentConfig) -> list[PlanStep]:
    """fire_distance는 gates.engagement_pairs가 계산한 {event_id: 거리 m}.

    사거리 거리를 여기서 다시 계산하지 않는다. 교전 시점의 위치를 푸는
    로직(피격 문장 우선, 이동 추적)이 두 벌 있으면 반드시 어긋난다.

    slots_by_event는 {원문 event_id: EngagementSlot}. directFireAt
    이벤트에 슬롯이 있으면 fire-at-target/provide_suppressive_fire_loc을
    양자택일로 대체하던 옛 로직 대신 build_engagement_steps가 이동·대기·
    직접사격·제압사격 네 단계를 붙여서 낸다(설계 §5). clock은 이 객체의
    큐를 따라 누적되는 ActorClock이다 — 슬롯이 아닌 단계도 진행 시각을
    반영해야 뒤에 오는 슬롯의 대기가 정확해지므로, 여기서 단계마다
    clock.advance를 부른다.
    """
    steps: list[PlanStep] = []
    ordered = sorted(events, key=lambda x: (x.time_s, x.event_id))
    for i, e in enumerate(ordered):
        slot = slots_by_event.get(e.event_id)
        if slot is not None:
            new_steps = build_engagement_steps(slot, entity, catalog, kinds,
                                               ranges, ctx, clock, config)
            steps.extend(new_steps)
            continue
        kind = pattern_map.task_kind_of(e)
        if kind in ("", "noop"):
            continue
        if kind == "follow" and _has_later_task(ordered[i + 1:], pattern_map):
            # 후속 task가 있는 follow는 종단이 아니다. follow-entity는 끝나는
            # 시각을 모른다(estimate_step_duration이 UNBOUNDED로 돌린다) —
            # 뒤에 큐를 둔 모든 task가 영영 실행되지 않는다. 원래 목적지(dst)로
            # 향하는 평범한 이동으로 내린다. 뒤에 아무 task도 없는 종단
            # follow만 이 분기를 타지 않고 follow로 남는다.
            kind = "move"
        if kind in ("move_firing_position", "move_cover"):
            new_steps = _verified_move(e, entity, kind, catalog, kinds, ctx,
                                       ordered)
        else:
            new_steps = _one(e, entity, kind, catalog, kinds, ranges, ctx,
                             fire_distance, ordered)
        for s in new_steps:
            clock.advance(s)
        steps.extend(new_steps)
    return steps


def _has_later_task(events: list[Event], pattern_map: PatternMap) -> bool:
    """이 이후에 이 객체가 받을 task_kind가 하나라도 있는가(noop 제외)."""
    return any(pattern_map.task_kind_of(x) not in ("", "noop")
              for x in events)


# '후속 사격 문장'으로 볼 템플릿. 사격 준비 상태가 된 객체의 위협 대상은
# 그 객체가 곧이어 쏘는 표적이다. 2026-08-05 실측: 사격 준비 전이 21건
# 전부 이 세 템플릿 중 하나로 표적이 잡힌다(실패 0).
FIRE_REF_TEMPLATES = ("indirectFireAt", "aimAt", "engAttacker")


def _resolve_ref(e: Event, kind: str, ctx: PlanContext, kinds: TaskKinds,
                 actor_events: list[Event]) -> str:
    field = kinds.ref_field(kind)
    if field == "unit_leader":
        return ctx.unit_leader(e.actor) or ""
    if field == "next_fire_target":
        # actor_events는 (time_s, event_id)로 정렬돼 들어온다.
        for x in actor_events:
            if x.time_s >= e.time_s and x.template in FIRE_REF_TEMPLATES \
                    and x.target:
                return x.target
        return ""
    return getattr(e, field, "") or e.dst or e.target


def _one(e: Event, entity: EntityDef, kind: str, catalog: TaskCatalog,
         kinds: TaskKinds, ranges: WeaponRanges, ctx: PlanContext,
         fire_distance: dict[str, float],
         actor_events: list[Event]) -> list[PlanStep]:
    step = PlanStep(e.event_id, e.time_s, e.template, kind, None, None)
    if not kinds.known(kind):
        step.issues.append(f"task_kinds.csv에 없는 task_kind: {kind}")
        return [step]

    # 참조_필드가 빈 kind(wait)는 해석할 참조가 애초에 없다. "참조 대상
    # 없음"은 참조가 있어야 하는데 못 찾았을 때만 나오는 결함 메시지이므로,
    # 여기서는 시도조차 하지 않고 ref_kind="*"로 아래 공통 경로를 태운다.
    has_ref = bool(kinds.ref_field(kind))
    if has_ref:
        ref = _resolve_ref(e, kind, ctx, kinds, actor_events)
        if not ref:
            if kind == "follow":
                # 부대 선두 자신은 추종할 대상이 없다 — 평범한 이동으로 처리한다.
                return _one(e, entity, "move", catalog, kinds, ranges, ctx,
                            fire_distance, actor_events)
            step.issues.append("참조 대상 없음")
            return [step]

        fire = kinds.fire_kind(kind) or None
        if fire:
            d = fire_distance.get(e.event_id)
            if d is None:
                step.issues.append("교전 거리 미산출 — G0가 이 사격을 못 봤다")
                return [step]
            verdict = ranges.check(entity.entity_class, fire, d)
            if verdict == TOO_CLOSE:
                # 최소사거리 미달은 min_severity와 무관하게 태스크를 만들지 않는다.
                # REPORT는 '파이프라인을 멈추지 않는다'는 뜻이지 '쏠 수 있다'는 뜻이
                # 아니다. VR-Forces는 실제로 거부한다 — 2026-08-04 vrfSim.log 실측:
                # "Indirect fire target less than min range (2000 m)". 태스크를 내면
                # 로그만 더럽히고 사격은 일어나지 않는다. 이벤트·STKG 관계는 남는다.
                step.issues.append(
                    f"최소사거리 미달 ({d:.0f}m) — VR-Forces가 사격을 거부한다")
                step.skip_reason = SKIP_MIN_RANGE
                return [step]
            if verdict not in (OK, UNVERIFIED):
                step.issues.append(
                    f"사거리 {verdict} ({d:.0f}m) — G0가 먼저 잡았어야 함")
                return [step]

        ref_kind = ctx.ref_kind(ref)
    else:
        ref, ref_kind = "", "*"

    tmpl, label = _pick_template(kind, ref_kind, entity.type_group, catalog,
                                 kinds)
    if tmpl is None:
        step.issues.append(
            f"템플릿 없음: kind={kind} ref_kind={ref_kind} "
            f"type_group={entity.type_group}")
        return [step]
    step.action_label = label
    if tmpl.task_or_request_type in entity.unsupported_tasks:
        # 이 모델에는 그 task를 실행할 컨트롤러(=시스템)가 없다. 태스크를 내면
        # VR-Forces가 "No controller or Controller is disabled"로 거절한다.
        # type_group은 템플릿 선택 단위라 이 판정에 쓰기엔 굵다(T-72는 실패,
        # 같은 그룹의 T-80은 성공). 근거는 entity_class_map.csv의 note.
        step.issues.append(
            f"{entity.entity_class}에 {tmpl.task_or_request_type} 컨트롤러 없음"
            " — VR-Forces 실측(vrfSim.log)")
        step.skip_reason = SKIP_UNSUPPORTED
        return [step]
    if has_ref:
        step.pln, step.refs = _fill(
            tmpl.pln, ref_kind, ref, ctx,
            ctx.actor_coord(e.actor or entity.object_id, e.time_s, e.src),
            time_s=e.time_s, actor=e.actor)
        step.pln = with_weapon(step.pln, entity.weapons)
    else:
        # wait-duration에는 치환할 자리표시자가 없다 — 템플릿을 그대로 쓴다.
        step.pln = tmpl.pln.strip()

    # 한 문장이 두 블록을 내는 경우(보급 기동의 set-speed, 감시 이동의 방향
    # 조준)는 코드가 아니라 task_kinds.csv의 선행_행동·후행_행동이 정한다.
    self_coord = ctx.actor_coord(e.actor or entity.object_id, e.time_s, e.src)
    out: list[PlanStep] = []
    for label in kinds.pre_labels(kind):
        out.append(_companion(e, entity, kind, label, catalog, ctx, ref,
                              ref_kind, self_coord))
    out.append(step)
    for label in kinds.post_labels(kind):
        out.append(_companion(e, entity, kind, label, catalog, ctx, ref,
                              ref_kind, self_coord))
    return out


def _companion(e: Event, entity: EntityDef, kind: str, label: str,
               catalog: TaskCatalog, ctx: PlanContext, ref: str,
               ref_kind: str, self_coord: Coord) -> PlanStep:
    """선행·후행 행동 한 개를 블록으로.

    템플릿이 없으면 예외다. 조용히 빠지면 보급 차량이 왜 전속력으로 달리는지,
    감시조가 왜 엉뚱한 데를 보는지 `.scnx`를 열어보기 전엔 알 수 없다
    (`build_fixed_plans`와 같은 규칙).
    """
    t = catalog.get(entity.type_group, label)
    if t is None:
        raise KeyError(
            f"task_kinds.csv가 '{label}'을 {kind}의 동반 행동으로 선언했는데 "
            f"task_catalog에 ({entity.type_group}, {label}) 행이 없다")
    pln = t.pln.strip()
    if label == SPEED_LABEL:
        # 저속 보급 기동. 템플릿의 기본 속도(100km/h)를 낮춘다.
        pln = pln.replace("(speed 27.777778)", f"(speed {SUPPLY_SPEED_MPS:.6f})")
    if any(tok in pln for tok in ("TARGET_UUID", "ENTITY_UUID",
                                  "CONTROL_POINT_UUID", "X Y Z", "SX SY SZ",
                                  "AZIMUTH_RAD", "ELEVATION_RAD")):
        pln, refs = _fill(pln, ref_kind, ref, ctx, self_coord,
                          time_s=e.time_s, actor=e.actor)
        pln = with_weapon(pln, entity.weapons)
    else:
        refs = []
    return PlanStep(e.event_id, e.time_s, e.template, f"{kind}:{label}",
                    label, pln, refs)


def _pick_template(kind: str, ref_kind: str, type_group: str,
                   catalog: TaskCatalog, kinds: TaskKinds):
    spec = kinds.get(kind, ref_kind)
    if spec is None:
        return None, None
    for label in spec.labels:
        t = catalog.get(type_group, label)
        if t is not None:
            return t, label
    return None, None


# find_firing_position → move_firing_position, hitBy → move_cover가 공유하는
# '원래 의도' 이름. GT에는 안 나가는 계획 메타데이터로만 남는다(설계 §5).
_VERIFIED_MOVE_INTENT = {
    "move_firing_position": "takes_firing_position_against",
    "move_cover": "takes_cover_from",
}


def _coord_move_step(e: Event, entity: EntityDef, kind: str, intent: str,
                     intent_object: str, coord: Coord, catalog: TaskCatalog,
                     kinds: TaskKinds) -> PlanStep:
    """검증된 좌표 하나로의 이동 단계.

    ref_kind를 무조건 COORD로 고정해 템플릿을 고른다 — _one·_fill이 하듯
    ctx.ref_kind(threat)를 따라가면 위협 엔티티 자신의 좌표가 X Y Z에 들어가
    이동이 위협 쪽으로 향해버린다(찾아야 할 버그를 스스로 재현하게 된다).
    이 함수가 받는 coord는 choose_firing_location/choose_cover_location이
    이미 검증까지 마친 golden 지형점이므로, 여기서는 그대로 꽂기만 한다.
    """
    step = PlanStep(e.event_id, e.time_s, e.template, kind, None, None,
                    planned_intent=intent, intent_object=intent_object)
    tmpl, label = _pick_template(kind, "COORD", entity.type_group, catalog,
                                 kinds)
    if tmpl is None:
        # move_cover는 task_kinds.csv에 ENTITY 행만 있다 — 참조(threat)가
        # 실제로 엔티티이기 때문이다(비고 칸 참고). 행동_후보는 두 행 모두
        # "좌표로 이동" 하나뿐이라 ENTITY 키로 찾아도 catalog에서 나오는
        # 템플릿은 COORD 키로 찾았을 때와 완전히 같다 — 아래에서 실제로
        # 채우는 좌표는 이 조회와 무관하게 인자로 받은 검증된 coord이지
        # ctx.ref_kind(threat)로 다시 묻지 않으므로 위협 쪽으로 가는 버그는
        # 재도입되지 않는다.
        tmpl, label = _pick_template(kind, "ENTITY", entity.type_group,
                                     catalog, kinds)
    if tmpl is None:
        step.issues.append(
            f"템플릿 없음: kind={kind} ref_kind=COORD/ENTITY "
            f"type_group={entity.type_group}")
        return step
    step.action_label = label
    if tmpl.task_or_request_type in entity.unsupported_tasks:
        # move_firing_position·move_cover도 결국 move-to-location-task다 —
        # 견인 장비처럼 이동 컨트롤러가 아예 없는 모델은 여기서도 똑같이 막힌다
        # (entity_class_map.csv unsupported_tasks, _one의 같은 검사와 동일 규칙).
        step.issues.append(
            f"{entity.entity_class}에 {tmpl.task_or_request_type} 컨트롤러 없음"
            " — VR-Forces 실측(vrfSim.log)")
        step.skip_reason = SKIP_UNSUPPORTED
        return step
    x, y, z = coord.to_ecef()
    pln = tmpl.pln.strip().replace("X Y Z", f"{x:.6f} {y:.6f} {z:.6f}")
    step.pln = with_weapon(pln, entity.weapons)
    return step


def _verified_move(e: Event, entity: EntityDef, kind: str,
                   catalog: TaskCatalog, kinds: TaskKinds, ctx: PlanContext,
                   actor_events: list[Event]) -> list[PlanStep]:
    """find_firing_position(21/21 실패)·find_cover(다수 모델 실패)를 대체한다.

    둘 다 2026-08 vrfSim.log 실측으로 "No controller or Controller is
    disabled"가 확인된 스크립트 task다. 대체는 그 task를 다시 시도하는 대신
    컴파일 시점에 좌표를 계산해 평범한 좌표 이동으로 내리는 것이다. 원래
    의도는 버리지 않는다 — 이 PlanStep의 planned_intent/intent_object에
    남는다. 둘 다 GT가 읽는 필드가 아니라 저작 메타데이터다.

    검증된 golden 지점이 없으면(choose_firing_location/choose_cover_location이
    None을 돌려주면) 실패하는 find task로 되돌아가지 않는다 — pln=None +
    skip_reason=SKIP_NO_VERIFIED_POSITION만 남긴다. G3 C3.5가 skip_reason이
    붙은 단계를 이미 REPORT로 낮추므로 새 분기가 필요 없다.
    """
    step = PlanStep(e.event_id, e.time_s, e.template, kind, None, None)
    threat = _resolve_ref(e, kind, ctx, kinds, actor_events)
    if not threat:
        step.issues.append("참조 대상 없음")
        return [step]

    intent = _VERIFIED_MOVE_INTENT[kind]
    actor_id = e.actor or entity.object_id
    actor_coord = ctx.actor_coord(actor_id, e.time_s, e.src)
    if kind == "move_firing_position":
        # threat = next_fire_target: 이 객체가 곧이어 쏠 표적이다. 좌표는
        # 그 표적을 향한 다른 사격 task(aim 등)와 같은 규칙으로 푼다 —
        # actor=e.actor(사수)를 줘야 hit_at의 (사수, 표적) 우선순위가 산다.
        threat_coord = ctx.coord_of(threat, e.time_s, e.actor)
        loc = ctx.choose_firing_location(entity.entity_class, actor_coord,
                                         threat_coord)
    else:
        # threat = source_obj: 나(e.actor)를 쏜 공격자다. hit_at은
        # (공격자, 피격자) 순으로 저장되므로 actor 인자를 주면 순서가
        # 뒤집혀 아무것도 못 찾는다 — 공격자 자신의 추적 위치를 그대로 쓴다.
        threat_coord = ctx.coord_of(threat, e.time_s)
        loc = ctx.choose_cover_location(actor_id, actor_coord, threat_coord)

    if loc is None:
        step.issues.append(
            "검증된 golden 위치 없음(위협과 멀어짐·경계 안·최소 이격 중 "
            "하나를 만족하는 지형점이 없다) — find task로 되돌아가지 않는다")
        step.skip_reason = SKIP_NO_VERIFIED_POSITION
        step.planned_intent = intent
        step.intent_object = threat
        return [step]

    _, coord = loc
    step = _coord_move_step(e, entity, kind, intent, threat, coord, catalog,
                            kinds)
    out = [step]
    if step.pln:
        for label in kinds.post_labels(kind):
            if kind == "move_cover" and label == "방향 조준":
                # 엄폐 이동 뒤 위협을 향해 방향 조준한다 — 군사적으로 옳은
                # 순서(엄폐 → 위협 관측)이고, task_kinds.csv의 후행_행동
                # 칸이 move_watch가 먼저 쓰던 것과 같은 칸이다(리뷰 라운드 1).
                # 방금 계산한 threat_coord·coord를 그대로 쓴다.
                out.append(_orient_on_threat_step(e, entity, catalog, coord,
                                                  threat_coord))
            else:
                raise KeyError(
                    f"_verified_move은 {kind}의 후행_행동 '{label}'을 모른다")
    return out


def _orient_on_threat_step(e: Event, entity: EntityDef, catalog: TaskCatalog,
                           dest_coord: Coord, threat_coord: Coord) -> PlanStep:
    """엄폐 지점에 도착한 뒤 위협 쪽으로 방향 조준(aiming-type 2)한다.

    move_watch의 방향 조준 동반 행동(_companion)과 같은 카탈로그 라벨이지만
    기준점이 다르다 — move_watch는 '출발 지점에서 목적지를 볼 때'의 방위를
    쓰고(도착 뒤 진행 방향을 계속 본다는 근사), move_cover는 '도착한
    엄폐 지점에서 위협을 볼 때'의 방위를 쓴다(엄폐했으면 위협을 관측해야
    한다). 엄폐 지점은 golden 지명이 아니라 합성 오프셋 좌표일 수 있어
    ctx.coord_of로 다시 풀 수 없다 — _verified_move가 이미 계산해 둔
    dest_coord·threat_coord를 그대로 받는다.
    """
    label = "방향 조준"
    t = catalog.get(entity.type_group, label)
    if t is None:
        raise KeyError(
            f"task_kinds.csv가 '{label}'을 move_cover의 후행_행동으로 "
            f"선언했는데 task_catalog에 ({entity.type_group}, {label}) 행이 없다")
    az, el = bearing_elevation(dest_coord, threat_coord)
    pln = t.pln.strip()
    pln = pln.replace("AZIMUTH_RAD", f"{az:.6f}")
    pln = pln.replace("ELEVATION_RAD", f"{el:.6f}")
    pln = with_weapon(pln, entity.weapons)
    return PlanStep(e.event_id, e.time_s, e.template, "move_cover:방향 조준",
                    label, pln)


# 태스크 템플릿에 무기 이름이 들어가는 자리. variable-data-types 블록의
# "direct fire weapon"은 자료형 문자열이라 값이 아니다 — 건드리지 않는다.
_RE_WEAPON_SLOT = re.compile(
    r'(\((?:weapon-to-fire|weapon-name|weapon)\s+")([^"]+)(")'
    r'|(\(DtRw\w+\s+\((?:useGun|gunToUse)\s+")([^"]+)(")')
_WEAPON_TYPE_WORDS = {"direct fire weapon", "indirect fire weapon"}


def with_weapon(pln: str, weapons: tuple[str, ...]) -> str:
    """템플릿의 무기 이름을 이 객체가 실제로 가진 무기로 바꾼다.

    task_catalog의 템플릿은 type_group 단위라 무기 이름이 하나로 박혀 있다.
    그런데 같은 그룹 안에 다른 무기를 든 모델이 있다 — '보병 - 소총(M4 계열)'에는
    M4를 든 미군과 AK-47을 든 적군이 같이 있다. 박힌 이름을 그대로 두면 적 보병이
    "M4 rifle"로 쏘라는 태스크를 받고, 그 무기가 없어 사격을 실행하지 못한다.
    이름의 정본은 golden `.oob`의 display-name이고 entity_class_map이 그 사본이다.
    """
    if not weapons or not weapons[0]:
        return pln

    def sub(m: re.Match[str]) -> str:
        head, val, tail = (m.group(1), m.group(2), m.group(3)) if m.group(1)             else (m.group(4), m.group(5), m.group(6))
        if val in _WEAPON_TYPE_WORDS:
            return m.group(0)
        return f"{head}{weapons[0]}{tail}"

    return _RE_WEAPON_SLOT.sub(sub, pln)


def _fill(template: str, ref_kind: str, ref: str, ctx: PlanContext,
          self_coord: Coord | None = None, time_s: int = -1,
          actor: str = "") -> tuple[str, list[str]]:
    """placeholder 치환. 좌표는 ECEF geocentric 미터로 넣는다.

    X Y Z    = 참조 대상의 **그 시각** 좌표
    SX SY SZ = 이 객체 자신의 그 시각 좌표(find_cover의 StartingLocation)
    AZIMUTH_RAD / ELEVATION_RAD = 이 객체에서 참조 대상을 볼 때의 방위·고각

    `time_s`는 이벤트 시각이다. 안 주면 -1이라 초기 배치가 나온다 — 옛 동작이
    필요한 호출자를 위한 값이 아니라, 시각이 없는 참조(지명·정적 객체)에서
    아무 차이가 없기 때문이다.
    """
    out, refs = template.strip(), []
    needs_uuid = any(tok in out for tok in
                     ("TARGET_UUID", "ENTITY_UUID", "CONTROL_POINT_UUID"))
    if needs_uuid:
        uuid = (ctx.entity_uuid(ref) if ref_kind == "ENTITY" else None) \
            or ctx.ref_uuid(ref)
        refs.append(uuid)
        for tok in ("TARGET_UUID", "ENTITY_UUID", "CONTROL_POINT_UUID"):
            out = out.replace(tok, uuid)
    if "SX SY SZ" in out and self_coord is not None:
        x, y, z = self_coord.to_ecef()
        out = out.replace("SX SY SZ", f"{x:.6f} {y:.6f} {z:.6f}")
    if "X Y Z" in out:
        x, y, z = ctx.coord_of(ref, time_s, actor).to_ecef()
        out = out.replace("X Y Z", f"{x:.6f} {y:.6f} {z:.6f}")
    if "AZIMUTH_RAD" in out or "ELEVATION_RAD" in out:
        if self_coord is None:
            raise ValueError("방향 조준에 사수 좌표가 없다")
        az, el = bearing_elevation(self_coord, ctx.coord_of(ref, time_s, actor))
        out = out.replace("AZIMUTH_RAD", f"{az:.6f}")
        out = out.replace("ELEVATION_RAD", f"{el:.6f}")
    return out, refs


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


_SUPPRESSION_FIELDS = (
    (re.compile(r"\(ammoLimit\s+\d+\)"), "(ammoLimit {ammo})"),
    (re.compile(r"\(durationRapid\s+[-\d.]+\)"),
     "(durationRapid {rapid:.6f})"),
    (re.compile(r"\(durationTotal\s+[-\d.]+\)"),
     "(durationTotal {total:.6f})"),
)


def with_suppression_limits(pln: str, slot: EngagementSlot) -> str:
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


def build_engagement_steps(slot: EngagementSlot, entity: EntityDef,
                           catalog: TaskCatalog, kinds: TaskKinds,
                           ranges: WeaponRanges, ctx: PlanContext,
                           clock: ActorClock,
                           config: EnrichmentConfig) -> list[PlanStep]:
    """교전 슬롯 하나 → 이동·대기·직접사격·제압사격 최대 네 단계(설계 §5).

    직접사격과 제압사격은 반드시 붙어 있어야 한다 — 그 사이에 다른 task가
    끼면 두 관측이 서로 다른 교전으로 갈라져 슬롯을 둔 의미가 사라진다.
    이동·대기는 사격 앞에만 놓는다.

    합성 Event는 여기서만 산다 — build/events/battle.jsonl에는 쓰지 않는다
    (설계 §3 제외 항목). 네 단계 모두 같은 슬롯이므로 event_id를
    slot.slot_id로 통일한다: fire_distance 조회(_one이 e.event_id로 찾는다)
    와 감사 도구가 한 슬롯의 네 단계를 하나로 묶어 볼 수 있어야 한다.
    """
    fire_distance = {slot.slot_id: slot.distance_m}
    out: list[PlanStep] = []

    if slot.firing_ref:
        move_event = Event(slot.slot_id, slot.scheduled_time_s, 0, "",
                           "moveTo", actor=slot.shooter_id,
                           dst=slot.firing_ref)
        move_steps = _one(move_event, entity, "move", catalog, kinds, ranges,
                          ctx, fire_distance, [])
        move_distance_m = ground_distance(slot.shooter_coord,
                                          slot.firing_coord)
        for step in move_steps:
            step.slot_id = slot.slot_id
            step.planned_intent = "takes_firing_position_against"
            step.intent_object = slot.target_id
            clock.advance(step, move_distance_m)
        out.extend(move_steps)

    wait_s = clock.wait_needed_for(slot.scheduled_time_s)
    if wait_s is not None and wait_s > config.minimum_observation_duration_s:
        wait_event = Event(slot.slot_id, slot.scheduled_time_s, 0, "",
                           "engagementSlot", actor=slot.shooter_id)
        wait_steps = _one(wait_event, entity, "wait", catalog, kinds, ranges,
                          ctx, fire_distance, [])
        for step in wait_steps:
            step.slot_id = slot.slot_id
            if step.pln:
                step.pln = with_wait_seconds(step.pln, wait_s)
            clock.advance(step)
        out.extend(wait_steps)

    fire_event = Event(slot.slot_id, slot.scheduled_time_s, 0, "",
                       "directFireAt", actor=slot.shooter_id,
                       target=slot.target_id, src=slot.firing_ref or "")
    fire_steps = _one(fire_event, entity, "fire_direct", catalog, kinds,
                      ranges, ctx, fire_distance, [])
    for step in fire_steps:
        step.slot_id = slot.slot_id
        clock.advance(step)
    out.extend(fire_steps)

    suppress_event = Event(slot.slot_id, slot.scheduled_time_s, 0, "",
                           "directFireAt", actor=slot.shooter_id,
                           target=slot.target_ref, src=slot.firing_ref or "")
    suppress_steps = _one(suppress_event, entity, "suppress", catalog, kinds,
                          ranges, ctx, fire_distance, [])
    for step in suppress_steps:
        step.slot_id = slot.slot_id
        if step.pln:
            step.pln = with_suppression_limits(step.pln, slot)
        clock.advance(step)
    out.extend(suppress_steps)

    live_kinds = [s.task_kind for s in out if s.pln]
    if live_kinds[-2:] != ["fire_direct", "suppress"]:
        raise ValueError(
            f"교전 슬롯 {slot.slot_id}의 마지막 두 저작 단계가 "
            f"[fire_direct, suppress]로 끝나지 않는다: {live_kinds} — "
            "직접사격·제압사격 사이(또는 뒤)에 다른 task가 끼면 두 관측이 "
            "서로 다른 교전으로 갈라진다")
    return out


def balanced(pln: str) -> bool:
    depth = 0
    for ch in pln:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
