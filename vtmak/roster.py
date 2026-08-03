"""객체 명부 감축 — 부대별로 솎되 교전 구조를 깨지 않는다.

원문 335객체를 그대로 넣으면 VR-Forces가 버벅인다. 그런데 부대별로 비율만
곱해 자르면 교전이 깨진다 — FR-INF-036~053은 T-72/M1A2를 쏘는데 앞에서부터
26개만 남기면 그 표적들의 공격자가 사라진다.

그래서 교전 '쌍' 단위로 뽑는다:
  1) 정적 객체(포병진지·킬존 등)는 항상 남긴다
  2) 교전 유형(공격자부대 → 표적부대)마다 최소 1쌍은 남긴다 — STKG의 관계
     종류가 통째로 사라지지 않게
  3) 남은 예산을 비교전 객체에 부대별 비례로 배분한다
같은 입력이면 항상 같은 명부가 나온다(정렬 순서 고정).
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .parser import Event
from .registry import EntityDef

# 교전 쌍을 만드는 템플릿
_FIRE = {"directFireAt", "indirectFireAt", "aimAt"}


def unit_of(object_id: str) -> str:
    """객체 id → 부대. FR-INF-001 → FR-INF, OBJ-009 → OBJ."""
    parts = object_id.split("-")
    return "-".join(parts[:2]) if len(parts) > 2 else parts[0]


@dataclass(frozen=True)
class RosterPlan:
    target: int
    engagement_ratio: float
    quota: dict[str, int]      # 부대 → 상한. 정원표를 넘겨 뽑지 않는다.
    target_entities: int = 0   # task 가능 객체 총수. 있으면 수확량 방식을 쓴다.
    min_per_type: int = 0      # 엔티티 타입당 최소 보유 수
    min_per_unit: int = 0      # 부대당 최소 보유 수

    @classmethod
    def load(cls, path) -> "RosterPlan":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(int(d.get("target_objects", 0)),
                   float(d.get("engagement_ratio", 0.0)),
                   {k: int(v) for k, v in (d.get("quota") or {}).items()},
                   int(d.get("target_entities", 0)),
                   int(d.get("min_per_type", 0)),
                   int(d.get("min_per_unit", 0)))


def engagement_pairs_of(events: list[Event]) -> set[tuple[str, str]]:
    return {(e.actor, e.target) for e in events
            if e.template in _FIRE and e.actor and e.target}


def _refs_of(e: Event) -> tuple[str, ...]:
    return tuple(r for r in (e.actor, e.target, e.source_obj) if r)


def select_for_task_yield(events: list[Event], registry: dict[str, EntityDef],
                          plan: RosterPlan, task_event_ids: set[str]
                          ) -> set[str]:
    """정해진 객체 수 안에서 task를 최대로 남긴다.

    VR-Forces가 객체 수에 먼저 무릎을 꿇는다. 그래서 "몇 개를 남길까"가 아니라
    "이 수로 몇 개의 task를 살릴까"가 문제가 된다. 부대별로 균등하게 깎으면
    이벤트가 한 줄뿐인 객체와 스무 줄인 객체를 똑같이 취급해 task가 헐값에
    날아간다.

    수확량은 한계 이득으로 잰다. 어떤 객체를 넣었을 때 **그 객체 때문에 비로소
    성립하는** task 이벤트 수다 — 자기가 행위자인 이벤트뿐 아니라, 이미 뽑힌
    객체가 자기를 표적으로 삼은 이벤트도 함께 산다. 사격은 쌍이라야 성립하므로
    이 항을 빼면 표적 없는 사수만 잔뜩 남는다.

    순서: ① 정적 객체 ② 교전 유형마다 한 쌍 ③ 엔티티 타입·부대마다 최소 보유
    ④ 남은 자리를 한계 이득 큰 순서로. ②③은 정원이 아니라 구조를 지키는 몫이라
    수확량보다 앞선다. ③의 부대 바닥이 없으면 지휘소 경계 보병처럼 이벤트가
    적은 부대가 통째로 사라진다(실측: 80개에서 3개 부대가 비었다).
    """
    keep = {oid for oid, d in registry.items() if not d.taskable}
    cap = {u: n for u, n in plan.quota.items()}
    used: dict[str, int] = defaultdict(int)

    def room(oid: str) -> bool:
        u = unit_of(oid)
        return u not in cap or used[u] < cap[u]

    def take(oid: str) -> None:
        keep.add(oid)
        used[unit_of(oid)] += 1

    taskable = sorted(o for o, d in registry.items() if d.taskable)
    budget = plan.target_entities or len(taskable)

    def n_kept() -> int:
        return sum(1 for o in keep if registry[o].taskable)

    # ② 교전 유형마다 한 쌍씩 — 라운드로빈으로 유형이 통째로 죽지 않게
    by_kind: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for a, t in sorted(engagement_pairs_of(events)):
        by_kind[(unit_of(a), unit_of(t))].append((a, t))
    for kind in sorted(by_kind):
        for a, t in by_kind[kind]:
            if a in keep and t in keep:
                break
            need = [o for o in (a, t) if o not in keep]
            if n_kept() + len(need) > budget or not all(room(o) for o in need):
                continue
            for o in need:
                take(o)
            break

    # ③ 엔티티 타입마다 최소 보유 — 26종을 지키는 몫
    by_type: dict[str, list[str]] = defaultdict(list)
    for oid in taskable:
        by_type[registry[oid].entity_class].append(oid)
    for cls in sorted(by_type):
        have = sum(1 for o in by_type[cls] if o in keep)
        for oid in by_type[cls]:
            if have >= plan.min_per_type or n_kept() >= budget:
                break
            if oid not in keep and room(oid):
                take(oid)
                have += 1

    # ③' 부대마다 최소 보유 — 역할이 통째로 사라지지 않게
    by_unit: dict[str, list[str]] = defaultdict(list)
    for oid in taskable:
        by_unit[unit_of(oid)].append(oid)
    for u in sorted(by_unit):
        have = sum(1 for o in by_unit[u] if o in keep)
        for oid in by_unit[u]:
            if have >= plan.min_per_unit or n_kept() >= budget:
                break
            if oid not in keep and room(oid):
                take(oid)
                have += 1

    # ④ 남은 자리 — 한계 이득이 큰 객체부터
    ev_by_obj: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for e in events:
        if e.event_id not in task_event_ids:
            continue
        refs = _refs_of(e)
        for r in set(refs):
            ev_by_obj[r].append(refs)

    while n_kept() < budget:
        best, best_gain = None, 0
        for oid in taskable:
            if oid in keep or not room(oid):
                continue
            gain = sum(1 for refs in ev_by_obj.get(oid, ())
                       if all(r in keep or r == oid for r in refs))
            if gain > best_gain:
                best, best_gain = oid, gain
        if best is None:            # 더 이득 나는 객체가 없다 — id 순으로 채운다
            rest = [o for o in taskable if o not in keep and room(o)]
            if not rest:
                break
            best = rest[0]
        take(best)
    return keep


def select_by_quota(events: list[Event], registry: dict[str, EntityDef],
                    plan: RosterPlan) -> set[str]:
    """부대별 정원표대로 남긴다.

    사람이 (타입 x 행동) 조합을 보고 부대마다 몇 개를 남길지 직접 정한 표다.
    정원 안에서 무엇을 남길지는 여기서 정하는데, 교전에 등장하는 객체를 먼저
    채운다. 그래야 정원을 줄여도 STKG 관계 종류가 통째로 사라지지 않는다.
    """
    keep = {oid for oid, d in registry.items() if not d.taskable}
    room = dict(plan.quota)
    # 정원표에 없는 부대는 손대지 않는다(정적 객체 등).
    for oid in registry:
        room.setdefault(unit_of(oid), -1)

    def take(oid: str) -> bool:
        u = unit_of(oid)
        if oid in keep:
            return True
        if room[u] == 0:
            return False
        keep.add(oid)
        if room[u] > 0:
            room[u] -= 1
        return True

    # 1) 교전 유형별로 쌍을 먼저 채운다. 유형을 한 바퀴씩 돌며 한 쌍씩 가져간다.
    #    한 유형이 정원을 다 먹으면 다른 유형이 통째로 사라진다(실측: 그렇게
    #    21종 중 7종이 날아갔다). 라운드로빈이면 자리가 있는 한 모든 유형이
    #    최소 한 쌍을 챙긴다.
    by_kind: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for a, t in sorted(engagement_pairs_of(events)):
        by_kind[(unit_of(a), unit_of(t))].append((a, t))
    cursor = {k: 0 for k in by_kind}
    while True:
        progress = False
        for kind in sorted(by_kind):
            ps = by_kind[kind]
            i = cursor[kind]
            while i < len(ps):
                a, t = ps[i]
                i += 1
                if a in keep and t in keep:
                    continue          # 이미 성립한 쌍 — 다음 후보로
                if room[unit_of(a)] == 0 or room[unit_of(t)] == 0:
                    continue
                take(a)
                take(t)
                progress = True
                break
            cursor[kind] = i
        if not progress:
            break

    # 2) 남은 자리를 id 순서로 채운다.
    for oid in sorted(set(registry) - keep):
        take(oid)
    return keep


def select_roster(events: list[Event], registry: dict[str, EntityDef],
                  plan: RosterPlan,
                  task_event_ids: set[str] | None = None) -> set[str]:
    """남길 객체 id 집합.

    target_entities가 있으면 수확량 방식(task 최대), 없고 정원표만 있으면
    부대별 정원, 둘 다 없으면 예전 예산 방식.
    """
    if plan.target_entities:
        # task 이벤트 집합을 안 주면 모든 이벤트를 같은 무게로 본다. 호출부가
        # pattern_map을 못 읽는 상황(테스트 등)에서도 순서가 정해지게.
        return select_for_task_yield(
            events, registry, plan,
            task_event_ids or {e.event_id for e in events})
    if plan.quota:
        return select_by_quota(events, registry, plan)
    static = {oid for oid, d in registry.items() if not d.taskable}
    keep = set(static)

    # 1) 교전 유형별로 비율만큼 쌍을 남긴다(유형당 최소 1쌍)
    by_kind: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for a, t in sorted(engagement_pairs_of(events)):
        by_kind[(unit_of(a), unit_of(t))].append((a, t))
    for kind in sorted(by_kind):
        ps = by_kind[kind]
        n = max(1, round(len(ps) * plan.engagement_ratio))
        for a, t in ps[:n]:
            keep.add(a)
            keep.add(t)

    # 2) 남은 예산을 비교전 객체에 부대별 비례 배분(최대잔여법)
    rest = sorted(set(registry) - keep)
    budget = max(0, plan.target - len(keep))
    if budget and rest:
        by_unit: dict[str, list[str]] = defaultdict(list)
        for oid in rest:
            by_unit[unit_of(oid)].append(oid)
        units = sorted(by_unit)
        exact = {u: len(by_unit[u]) * budget / len(rest) for u in units}
        take = {u: min(len(by_unit[u]), int(exact[u])) for u in units}
        left = budget - sum(take.values())
        for u in sorted(units, key=lambda u: (-(exact[u] - take[u]), u)):
            if left <= 0:
                break
            if take[u] < len(by_unit[u]):
                take[u] += 1
                left -= 1
        for u in units:
            keep.update(by_unit[u][:take[u]])
    return keep


def filter_events(events: list[Event], keep: set[str]) -> list[Event]:
    """명부에 없는 객체를 참조하는 이벤트를 버린다."""
    out = []
    for e in events:
        refs = [r for r in (e.actor, e.target, e.source_obj) if r]
        if all(r in keep for r in refs):
            out.append(e)
    return out
