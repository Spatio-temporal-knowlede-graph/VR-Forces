"""이벤트 → 객체별 타임테이블 + G2 커버리지.

선행 프로젝트는 플랜 없는 객체에 코드 상수로 기본 행동을 주입했다
(커버리지 49% → 98%). 새 원문은 task 가능 객체가 실제 행동을 갖고 있으므로
그 주입을 하지 않는다. 비어 있으면 G2가 잡는다 — 단, 무기체계가 미확정이라
의도적으로 태스크를 만들지 않는 객체는 보고만 한다(설계 스펙 §8.3).
"""
from __future__ import annotations

from dataclasses import dataclass

from .gates import REPORT, Violation
from .parser import Event
from .registry import UNCLASSIFIED, EntityDef

# 플랜(태스크)을 만드는 템플릿. 나머지는 상태·서술이라 PLN에 남지 않는다.
PLAN_TEMPLATES = {"moveTo", "directFireAt", "indirectFireAt", "aimAt"}

# 객체의 위치를 바꾸는 템플릿과 그 위치가 담긴 필드.
_MOVES: dict[str, str] = {
    "locatedAt": "location",
    "moveTo": "dst",
    "stopAt": "location",
    "stayAt": "location",
    "hitBy": "location",
}


@dataclass(frozen=True)
class Cell:
    object_id: str
    t0: int
    t1: int
    state: str
    location: str


def boundaries(events: list[Event]) -> list[int]:
    return sorted({e.time_s for e in events})


def plan_coverage(events: list[Event],
                  registry: dict[str, EntityDef]) -> tuple[set[str], set[str]]:
    """(플랜 있는 객체, task 가능하나 플랜 없는 객체)."""
    have = {e.actor for e in events
            if e.template in PLAN_TEMPLATES and e.actor}
    taskable = {oid for oid, d in registry.items() if d.taskable}
    return have & taskable, taskable - have


def check_g2(events: list[Event],
             registry: dict[str, EntityDef]) -> list[Violation]:
    _, missing = plan_coverage(events, registry)
    out: list[Violation] = []
    for oid in sorted(missing):
        d = registry[oid]
        if d.type_group == UNCLASSIFIED:
            out.append(Violation(
                "G2", "C2.2",
                f"무기체계 미확정으로 태스크 없음: {oid} ({d.entity_class})",
                REPORT))
        else:
            out.append(Violation("G2", "C2.1",
                                 f"플랜 없는 task 가능 객체: {oid}"))
    return out


def build_timetable(events: list[Event],
                    registry: dict[str, EntityDef]) -> list[Cell]:
    """객체별로 상태·위치가 바뀌는 시점마다 셀을 끊는다.

    셀은 [t0, t1)이며 같은 객체의 셀은 0부터 끝까지 빈틈 없이 이어진다.
    """
    bounds = boundaries(events)
    if not bounds:
        return []
    end = bounds[-1] + 1

    changes: dict[str, dict[int, list[str | None]]] = {}
    for e in sorted(events, key=lambda x: (x.time_s, x.event_id)):
        if not e.actor:
            continue
        slot = changes.setdefault(e.actor, {}).setdefault(e.time_s, [None, None])
        if e.state_to:
            slot[0] = e.state_to
        field = _MOVES.get(e.template)
        if field:
            loc = getattr(e, field, "")
            if loc:
                slot[1] = loc

    cells: list[Cell] = []
    for oid in sorted(registry):
        d = registry[oid]
        state, loc = d.initial_state, d.initial_location
        marks = sorted({0} | set(changes.get(oid, {})))
        for i, t0 in enumerate(marks):
            slot = changes.get(oid, {}).get(t0)
            if slot:
                state = slot[0] or state
                loc = slot[1] or loc
            t1 = marks[i + 1] if i + 1 < len(marks) else end
            cells.append(Cell(oid, t0, t1, state, loc))
    return cells
