"""이벤트 → VR-Forces PLN(Task/Set) 블록.

선행 프로젝트와 세 가지가 다르다.
1) 사거리 상수를 코드에 두지 않는다. WeaponRanges가 판정한다.
2) '지점 사격 → 근처 적 객체로 승격'을 하지 않는다. 원문이 모든 사격에
   목표 객체를 명시하므로 추측할 필요가 없다.
3) task_kind를 코드가 아니라 pattern_map.csv에서 읽는다.

무기 이름은 치환하지 않는다. task_catalog의 템플릿이 type_group별로 이미
검증된 무기명을 담고 있고, 그게 VR-Forces에서 실제로 도는 값이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..geometry import Coord
from ..parser import Event, PatternMap
from ..gates import REPORT
from ..ranges import OK, TOO_CLOSE, UNVERIFIED, WeaponRanges
from ..registry import EntityDef
from .catalog import TaskCatalog

# (task_kind, ref_kind) → task_catalog '행동' 후보. 앞에서부터 type_group에
# 존재하는 첫 템플릿을 쓴다. 라벨은 task_catalog.csv '행동' 컬럼과 일치해야 한다.
LABEL_CANDIDATES: dict[tuple[str, str], list[str]] = {
    ("move", "COORD"): ["좌표로 이동", "통제점으로 이동"],
    ("move", "ENTITY"): ["좌표로 이동", "통제점으로 이동"],
    ("move_slow", "COORD"): ["좌표로 이동", "통제점으로 이동"],
    ("fire_direct", "ENTITY"): ["대상 직접사격", "대상 자동무장 사격"],
    ("fire_direct", "COORD"): ["대상 직접사격"],
    ("fire_indirect", "COORD"): ["좌표 대상 간접사격"],
    ("fire_indirect", "ENTITY"): ["Entity 대상 간접사격", "좌표 대상 간접사격"],
    ("aim", "ENTITY"): ["객체 조준"],
    ("aim", "COORD"): ["객체 조준"],
    # yewon_test.pln에서 수확한 스크립트 태스크
    ("suppress", "ENTITY"): ["제압사격"],       # 표적 좌표만 필요(uuid 불필요)
    ("suppress", "COORD"): ["제압사격"],
    ("take_cover", "ENTITY"): ["피격 후 엄폐"],  # Threat = 피격 원천 객체
    ("follow", "ENTITY"): ["대형 추종 이동"],    # 부대 선두를 추종
}

# task_kind → 사거리 종류. 이동·엄폐는 사거리 검사 대상이 아니다.
FIRE_KIND = {"fire_direct": "direct", "suppress": "direct",
             "fire_indirect": "indirect", "aim": "indirect"}

# task_kind → 참조 대상을 어느 필드에서 가져오는가.
REF_FIELD = {"fire_direct": "target", "suppress": "target",
             "fire_indirect": "target", "aim": "target",
             "move": "dst", "move_slow": "dst",
             "take_cover": "source_obj", "follow": "unit_leader"}

# 보급 차량 저속 기동(m/s). set-speed 템플릿의 기본값을 이걸로 바꾼다.
SUPPLY_SPEED_MPS = 8.0


class PlanContext(Protocol):
    """spec.py가 주입하는 uuid·좌표·ref_kind 해석기."""
    def entity_uuid(self, object_id: str) -> str | None: ...
    def ref_uuid(self, ref: str) -> str: ...
    def coord_of(self, ref: str) -> Coord: ...
    def ref_kind(self, ref: str) -> str: ...   # ENTITY | COORD
    def unit_leader(self, object_id: str) -> str | None: ...


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


def build_entity_plan(events: list[Event], entity: EntityDef,
                      pattern_map: PatternMap, catalog: TaskCatalog,
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
    for e in sorted(events, key=lambda x: (x.time_s, x.event_id)):
        kind = pattern_map.task_kind(e.template, e.action_label)
        if kind in ("", "noop"):
            continue
        if kind == "fire_direct" and e.event_id in suppression:
            kind = "suppress"
        steps.extend(_one(e, entity, kind, catalog, ranges, ctx, fire_distance))
    return steps


def _resolve_ref(e: Event, kind: str, ctx: PlanContext) -> str:
    field = REF_FIELD.get(kind, "dst")
    if field == "unit_leader":
        return ctx.unit_leader(e.actor) or ""
    return getattr(e, field, "") or e.dst or e.target


def _one(e: Event, entity: EntityDef, kind: str, catalog: TaskCatalog,
         ranges: WeaponRanges, ctx: PlanContext,
         fire_distance: dict[str, float]) -> list[PlanStep]:
    step = PlanStep(e.event_id, e.time_s, e.template, kind, None, None)
    ref = _resolve_ref(e, kind, ctx)
    if not ref:
        if kind == "follow":
            # 부대 선두 자신은 추종할 대상이 없다 — 평범한 이동으로 처리한다.
            return _one(e, entity, "move", catalog, ranges, ctx, fire_distance)
        step.issues.append("참조 대상 없음")
        return [step]

    fire = FIRE_KIND.get(kind)
    if fire:
        d = fire_distance.get(e.event_id)
        if d is None:
            step.issues.append("교전 거리 미산출 — G0가 이 사격을 못 봤다")
            return [step]
        verdict = ranges.check(entity.entity_class, fire, d)
        relaxed = (verdict == TOO_CLOSE
                   and ranges.min_severity(entity.entity_class) == REPORT)
        if relaxed:
            # 교리상 최소사거리 미달이지만 사람이 감수하기로 한 모델이다.
            # 태스크는 만들고 사실만 남긴다(G0가 REPORT로 이미 알렸다).
            step.issues.append(f"교리상 최소사거리 미달 ({d:.0f}m) — 감수")
        elif verdict not in (OK, UNVERIFIED):
            step.issues.append(
                f"사거리 {verdict} ({d:.0f}m) — G0가 먼저 잡았어야 함")
            return [step]

    ref_kind = ctx.ref_kind(ref)
    tmpl, label = _pick_template(kind, ref_kind, entity.type_group, catalog)
    if tmpl is None:
        step.issues.append(
            f"템플릿 없음: kind={kind} ref_kind={ref_kind} "
            f"type_group={entity.type_group}")
        return [step]
    step.action_label = label
    step.pln, step.refs = _fill(tmpl.pln, ref_kind, ref, ctx,
                                ctx.coord_of(entity.object_id))
    step.pln = with_weapon(step.pln, entity.weapons)

    out: list[PlanStep] = []
    if kind == "move_slow":
        # 보급 기동은 속도를 먼저 낮춘다(set-speed → 이동).
        spd = catalog.get(entity.type_group, "속도 지정")
        if spd is not None:
            pln = spd.pln.strip().replace("(speed 27.777778)",
                                          f"(speed {SUPPLY_SPEED_MPS:.6f})")
            out.append(PlanStep(e.event_id, e.time_s, e.template,
                                "set_speed", "속도 지정", pln))
    out.append(step)
    return out


def _pick_template(kind: str, ref_kind: str, type_group: str,
                   catalog: TaskCatalog):
    for label in LABEL_CANDIDATES.get((kind, ref_kind), []):
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
          self_coord: Coord | None = None) -> tuple[str, list[str]]:
    """placeholder 치환. 좌표는 ECEF geocentric 미터로 넣는다.

    X Y Z    = 참조 대상의 좌표
    SX SY SZ = 이 객체 자신의 좌표(find_cover의 StartingLocation)
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
        x, y, z = ctx.coord_of(ref).to_ecef()
        out = out.replace("X Y Z", f"{x:.6f} {y:.6f} {z:.6f}")
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
