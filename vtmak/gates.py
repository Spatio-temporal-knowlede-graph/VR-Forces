"""검증 게이트.

G0 사거리 — .scnx를 만들기 전에 레이아웃만으로 검사한다. 선행 프로젝트는
사거리 미달 사격을 조용히 스킵해 '의도한 스킵'과 '레이아웃 오류'가
구분되지 않았다. 여기서는 레이아웃 문제로 먼저 잡는다.
G1 파싱 — 미매칭 0(선언된 절단 제외), 지명이 전부 레이아웃에 존재.
G2 커버리지 — timetable 모듈에 있다. G3 정합성 — scnx/gates.py에 있다.

severity가 BLOCK인 위반만 파이프라인을 멈춘다. REPORT는 사람이 알아야 하지만
산출을 막지는 않는 사실이다(예: 무기체계 미확정 — 설계 스펙 §8.3).
"""
from __future__ import annotations

from dataclasses import dataclass

from .geometry import BattlefieldLayout, ground_distance
from .parser import KNOWN_TRUNCATION, Event, ParseResult
from .ranges import NO_WEAPON, OK, TOO_CLOSE, TOO_FAR, UNVERIFIED, WeaponRanges
from .registry import EntityDef

BLOCK = "BLOCK"
REPORT = "REPORT"

# 사격 템플릿 → 사거리 종류. 포신 정렬도 같은 제약을 받는다.
_FIRE_KIND = {
    "directFireAt": "direct",
    "indirectFireAt": "indirect",
    "aimAt": "indirect",
}


@dataclass(frozen=True)
class Violation:
    gate: str
    code: str
    detail: str
    severity: str = BLOCK


def blocking(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == BLOCK]


@dataclass(frozen=True)
class Engagement:
    event_id: str
    actor: str
    entity_class: str
    fire_kind: str          # direct | indirect
    label: str              # '사수위치 → 목표' 사람이 읽는 설명
    distance_m: float


def check_g1(result: ParseResult, layout: BattlefieldLayout,
             registry: dict[str, EntityDef]) -> list[Violation]:
    out: list[Violation] = []
    for line_no, frag in result.unmatched:
        if frag.startswith(KNOWN_TRUNCATION):
            continue          # 원문 PDF 절단 — 선언된 예외
        out.append(Violation("G1", "C1.1",
                             f"미매칭 문장 line {line_no}: {frag[:80]}"))
    seen: set[str] = set()
    for e in result.events:
        for lid in (e.location, e.src, e.dst):
            if lid and lid not in seen:
                seen.add(lid)
                if layout.local(lid) is None:
                    out.append(Violation(
                        "G1", "C1.2", f"레이아웃에 없는 지명: {lid}"))
    missing_actors: set[str] = set()
    for e in result.events:
        if e.actor and e.actor not in registry and e.actor not in missing_actors:
            missing_actors.add(e.actor)
            out.append(Violation("G1", "C1.3",
                                 f"사전에 없는 객체: {e.actor} ({e.event_id})"))
    return out


# 객체의 위치를 바꾸는 템플릿과, 그 위치가 담긴 필드.
_MOVES: dict[str, str] = {
    "locatedAt": "location",
    "moveTo": "dst",
    "stopAt": "location",
    "stayAt": "location",
    "hitBy": "location",
}


class PositionTracker:
    """시각별 객체 위치.

    사거리는 초기 배치가 아니라 '쏘는 그 순간'의 거리로 재야 한다. 적 보병은
    적 북측 집결지에서 출발하지만 교전 시점에는 플랜을 따라 중앙 킬존까지
    내려와 있다. 초기 배치로 재면 2.6km가 나와 소총 사거리를 넘는다.
    """

    def __init__(self, events: list[Event],
                 registry: dict[str, EntityDef]) -> None:
        self._track: dict[str, list[tuple[int, str]]] = {}
        for oid, d in registry.items():
            if d.initial_location:
                self._track[oid] = [(-1, d.initial_location)]
        for e in sorted(events, key=lambda x: (x.time_s, x.event_id)):
            field = _MOVES.get(e.template)
            if not field or not e.actor:
                continue
            loc = getattr(e, field, "")
            if loc:
                self._track.setdefault(e.actor, []).append((e.time_s, loc))

    def location_at(self, object_id: str, time_s: int) -> str:
        """time_s 시점의 지명. 기록이 없으면 빈 문자열."""
        hist = self._track.get(object_id)
        if not hist:
            return ""
        best = ""
        for t, loc in hist:
            if t <= time_s:
                best = loc
            else:
                break
        return best or hist[0][1]


def resolve_coord(ref: str, time_s: int, registry: dict[str, EntityDef],
                  layout: BattlefieldLayout, tracker: PositionTracker):
    """객체 id 또는 지명 → 그 시각의 좌표.

    정적 객체(포병진지·킬존)는 레이아웃이 지명에 바인딩해 두었고 움직이지
    않는다. 일반 객체는 추적된 위치를 쓴다.
    """
    bound = layout.static_target(ref)
    if bound:
        return layout.coord(bound)
    if ref in registry:
        return layout.coord(tracker.location_at(ref, time_s))
    return layout.coord(ref)


def engagement_locations(events: list[Event]) -> dict[tuple[str, str], str]:
    """(사수, 목표) → 교전이 일어난 지명.

    피격 문장이 교전 위치의 정본이다. 예를 들어 EN-INF-001은 01:00에
    '적 북측 접근로로 이동'이 마지막 이동 서술이지만, 03:21 피격 문장은
    '중앙 킬존에서 피격된다'라고 적는다. 원문이 교전 지점을 직접 진술하므로
    이동 추적보다 이쪽을 믿는다.
    """
    out: dict[tuple[str, str], str] = {}
    for e in events:
        if e.template == "hitBy" and e.actor and e.source_obj and e.location:
            out.setdefault((e.source_obj, e.actor), e.location)
    return out


def engagement_pairs(events: list[Event], registry: dict[str, EntityDef],
                     layout: BattlefieldLayout) -> list[Engagement]:
    """사격 이벤트 → 사수·목표 거리. 둘 다 교전 시점의 위치로 잰다."""
    tracker = PositionTracker(events, registry)
    hit_at = engagement_locations(events)
    out: list[Engagement] = []
    for e in events:
        kind = _FIRE_KIND.get(e.template)
        if not kind or not e.actor or not e.target:
            continue
        # 사수 위치는 문장이 명시한 src를 우선한다(원문이 가장 정확).
        shooter = (layout.coord(e.src) if e.src and layout.local(e.src)
                   else resolve_coord(e.actor, e.time_s, registry, layout,
                                      tracker))
        # 목표 위치 우선순위: 피격 문장 > 정적 바인딩 > 시각별 추적
        tgt_loc = (hit_at.get((e.actor, e.target))
                   or layout.static_target(e.target)
                   or tracker.location_at(e.target, e.time_s))
        target = layout.coord(tgt_loc) if tgt_loc else resolve_coord(
            e.target, e.time_s, registry, layout, tracker)
        if shooter.is_zero() or target.is_zero():
            continue
        ent = registry.get(e.actor)
        out.append(Engagement(
            event_id=e.event_id,
            actor=e.actor,
            entity_class=ent.entity_class if ent else "",
            fire_kind=kind,
            label=f"{e.src or e.actor} → {e.target}@{tgt_loc}",
            distance_m=ground_distance(shooter, target),
        ))
    return out


def check_g0(events: list[Event], registry: dict[str, EntityDef],
             layout: BattlefieldLayout,
             ranges: WeaponRanges) -> list[Violation]:
    out: list[Violation] = []
    seen: set[tuple[str, str, str]] = set()
    for g in engagement_pairs(events, registry, layout):
        key = (g.entity_class, g.fire_kind, g.label)
        if key in seen:
            continue          # 같은 쌍을 여러 번 보고하지 않는다
        seen.add(key)
        verdict = ranges.check(g.entity_class, g.fire_kind, g.distance_m)
        if verdict == OK:
            continue
        where = f"{g.entity_class} {g.label} {g.distance_m:.0f}m"
        if verdict == TOO_CLOSE:
            out.append(Violation("G0", "C0.1", f"{where} — 최소사거리 미달"))
        elif verdict == TOO_FAR:
            out.append(Violation("G0", "C0.2", f"{where} — 최대사거리 초과"))
        elif verdict == UNVERIFIED:
            out.append(Violation("G0", "C0.3", f"{where} — 무기체계 미확인",
                                 REPORT))
        elif verdict == NO_WEAPON:
            out.append(Violation("G0", "C0.4",
                                 f"{where} — 사격 능력 없는 모델", REPORT))
    return out
