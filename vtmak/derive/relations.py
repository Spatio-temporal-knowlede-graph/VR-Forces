"""R3·R4·R7 — 이벤트 사이의 관계를 합성한다.

세 규칙이 공유하는 것은 '소스 이벤트 하나가 싱크 이벤트 하나를 고른다'는 모양
이고, 고르는 기준은 전부 시간이다. 그래서 짝짓기는 `_match` 한 곳에만 있다.
규칙마다 따로 쓰면 R3의 '최근접'과 R4의 'Δt=+1'이 서로 다른 정렬을 보고 조용히
다른 답을 낸다.

싱크는 한 번 쓰면 소진된다. 같은 피격을 두 발이 나눠 갖는 인과는 없다.

짝을 못 찾은 소스는 예외가 아니라 `RuleResult.unmatched`로 나간다. 파생은
원문 검증이 아니라 합성이라, 여기서 멈추면 나머지 76건도 같이 사라진다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..parser import Event
from .events import EventIndex

# 관계가 붙는 층. Track A(추출 정본)와 섞였을 때 이 값이 유일한 구분자다.
LAYER = "derived"


@dataclass(frozen=True)
class Relation:
    rule_id: str
    predicate: str
    subject: str
    object: str
    provenance: tuple[str, ...]
    layer: str = LAYER


@dataclass(frozen=True)
class RuleResult:
    relations: tuple[Relation, ...] = ()
    unmatched: tuple[str, ...] = field(default=())


def _match(source: Event, pool: list[Event], used: set[str],
           prefer_delta: int | None = None) -> Event | None:
    """소스보다 나중(또는 동시)인 싱크 중 가장 가까운 것.

    prefer_delta가 주어지면 그 간격이 정확히 맞는 싱크를 먼저 본다. 지역은
    7종뿐인데 21발이 떨어져 (공격자, 지역) 쌍만으로는 갈리지 않기 때문이다.
    없으면 최근접으로 물러선다.
    """
    live = [e for e in pool
            if e.event_id not in used and e.time_s >= source.time_s]
    if not live:
        return None
    if prefer_delta is not None:
        exact = [e for e in live if e.time_s - source.time_s == prefer_delta]
        if exact:
            live = exact
    return min(live, key=lambda e: (e.time_s - source.time_s, e.event_id))


def r1r2_hit_state(index: EventIndex, rules) -> RuleResult:
    """suppresses/damages(공격자, 피격자) — 피격과 **같은 줄**의 상태 전이.

    조인은 세 조건이 전부 맞아야 한다: 같은 line_no · 같은 actor(맞은 쪽) ·
    template=="stateChange". 앞의 둘만 걸면 stateHold가 같은 줄에 오는 순간
    '유지'가 '전이'로 읽힌다. 현 데이터는 hold가 전부 다른 줄에 있어 우연히
    안전하지만 그건 데이터의 사실이지 규칙의 계약이 아니다.

    어떤 상태가 어떤 관계·어떤 rule_id가 되는지는 derive_rules.csv가 정한다.
    표에 없는 전이는 조용히 다른 관계가 되지 않고 미매칭으로 남는다.
    """
    states = rules.hit_states()
    rels, unmatched = [], []
    for hit in index.by_predicate("hitBy"):
        change = next(
            (e for e in index.by_line(hit.line_no)
             if e.template == "stateChange" and e.actor == hit.actor
             and e.state_to in states), None)
        if change is None:
            unmatched.append(hit.event_id)
            continue
        rule_id, predicate = states[change.state_to]
        rels.append(Relation(rule_id, predicate, hit.source_obj, hit.actor,
                             (hit.event_id, change.event_id)))
    return RuleResult(tuple(rels), tuple(unmatched))


def r3_direct_fire(index: EventIndex) -> RuleResult:
    """causes(directFireAt → hitBy). 키는 (사격자, 대상) 쌍이다.

    사격 라인의 engagementPair 동반을 요구하지 않는다. 77줄 중 1줄
    (E01494, FR-INF-001→EN-INF-001)은 directFireAt 단독이라 그 조건을 걸면
    조용히 76건이 된다.
    """
    sinks: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for hit in index.by_predicate("hitBy"):
        sinks[(hit.source_obj, hit.actor)].append(hit)

    rels, unmatched, used = [], [], set()
    for fire in index.by_predicate("directFireAt"):
        hit = _match(fire, sinks[(fire.actor, fire.target)], used)
        if hit is None:
            unmatched.append(fire.event_id)
            continue
        used.add(hit.event_id)
        rels.append(Relation("R3", "causes", fire.event_id, hit.event_id,
                             (fire.event_id, hit.event_id)))
    return RuleResult(tuple(rels), tuple(unmatched))


def _area_impacts(index: EventIndex, rules) -> dict[tuple[str, str], list[Event]]:
    """(공격자, 지역) → 지역 피격 상태 전이.

    전이 라인의 actor는 맞은 **지역**이라 공격자가 적혀 있지 않다. 공격자는
    같은 줄의 hitArea·engagementSource가 들고 있는 source_obj에서 온다.
    """
    before, after = rules.area_state()
    out: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for ev in index.by_predicate("stateChangedTo"):
        if (ev.state_from, ev.state_to) != (before, after):
            continue
        for mate in index.by_line(ev.line_no):
            if mate.source_obj:
                out[(mate.source_obj, ev.actor)].append(ev)
                break
    return out


def _attribution(index: EventIndex, impact: Event) -> str:
    """공격자를 알려준 같은 줄 이벤트 — 근거에 남긴다."""
    for mate in index.by_line(impact.line_no):
        if mate.source_obj:
            return mate.event_id
    return ""


def r4_indirect_fire(index: EventIndex, rules) -> RuleResult:
    """firesUpon(공격자, 지역) + causes(indirectFireAt → 지역 상태 전이)."""
    sinks = _area_impacts(index, rules)
    rels, unmatched, used = [], [], set()
    for fire in index.by_predicate("indirectFireAt"):
        impact = _match(fire, sinks[(fire.actor, fire.target)], used,
                        prefer_delta=1)
        if impact is None:
            unmatched.append(fire.event_id)
            continue
        used.add(impact.event_id)
        why = tuple(x for x in (fire.event_id, _attribution(index, impact),
                                impact.event_id) if x)
        rels.append(Relation("R4", "firesUpon", fire.actor, fire.target, why))
        rels.append(Relation("R4", "causes", fire.event_id, impact.event_id, why))
    return RuleResult(tuple(rels), tuple(unmatched))


def r7_precedes(index: EventIndex, rules) -> RuleResult:
    """precedes(e1, e2) — 같은 행위자의 시간순 **인접** 쌍만.

    전 조합을 이으면 3,000건에서 33만 쌍이 나오고, '다음에 무엇을 했나'라는
    질문에는 아무 답도 되지 않는다.

    빼는 것은 stateHold 179건뿐이다. 판별자는 template이지 state_from의 공백이
    아니다 — 빈 state_from은 473건이고 그중 294건이 stateInit이라, 공백으로
    거르면 각 행위자의 출발점까지 사라진다(2,368 → 2,074).
    """
    skip_hold = rules.flag("skip_state_hold")
    rels = []
    for actor in dict.fromkeys(e.actor for e in index.events if e.actor):
        chain = [e for e in index.by_actor(actor)
                 if not (skip_hold and e.template == "stateHold")]
        for a, b in zip(chain, chain[1:]):
            rels.append(Relation("R7", "precedes", a.event_id, b.event_id,
                                 (a.event_id, b.event_id)))
    return RuleResult(tuple(rels))
