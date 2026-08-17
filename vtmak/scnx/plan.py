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
from typing import Protocol

from ..geometry import Coord, bearing_elevation
from ..parser import Event, PatternMap
from ..ranges import OK, TOO_CLOSE, UNVERIFIED, WeaponRanges
from ..registry import EntityDef
from .catalog import TaskCatalog, TaskKinds

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


# pln을 만들지 않은 이유 중 '의도한 것'. VR-Forces가 실행을 거부한다는 사실이
# 실측으로 확인돼 일부러 저작하지 않은 경우다. 값이 비어 있으면 결함이다
# (템플릿 없음·참조 미해결 등) — G3가 그 둘을 다른 심각도로 다룬다.
SKIP_UNSUPPORTED = "unsupported_task"     # 모델에 그 task의 컨트롤러가 없다
SKIP_MIN_RANGE = "below_min_range"        # 간접사격 최소사거리 미달


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


def build_entity_plan(events: list[Event], entity: EntityDef,
                      pattern_map: PatternMap, catalog: TaskCatalog,
                      kinds: TaskKinds,
                      ranges: WeaponRanges, ctx: PlanContext,
                      fire_distance: dict[str, float],
                      suppression: set[str] | None = None) -> list[PlanStep]:
    """fire_distance는 gates.engagement_pairs가 계산한 {event_id: 거리 m}.

    사거리 거리를 여기서 다시 계산하지 않는다. 교전 시점의 위치를 푸는
    로직(피격 문장 우선, 이동 추적)이 두 벌 있으면 반드시 어긋난다.

    suppression은 '표적이 제압 상태가 된' 직접사격 event_id 집합. 그런 사격은
    fire-at-target 대신 provide_suppressive_fire_loc으로 저작한다.
    """
    suppression = suppression or set()
    steps: list[PlanStep] = []
    ordered = sorted(events, key=lambda x: (x.time_s, x.event_id))
    for e in ordered:
        kind = pattern_map.task_kind_of(e)
        if kind in ("", "noop"):
            continue
        if kind == "fire_direct" and e.event_id in suppression:
            kind = "suppress"
        steps.extend(_one(e, entity, kind, catalog, kinds, ranges, ctx,
                          fire_distance, ordered))
    return steps


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
