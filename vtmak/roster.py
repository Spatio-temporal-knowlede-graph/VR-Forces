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

    @classmethod
    def load(cls, path) -> "RosterPlan":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(int(d["target_objects"]), float(d["engagement_ratio"]))


def engagement_pairs_of(events: list[Event]) -> set[tuple[str, str]]:
    return {(e.actor, e.target) for e in events
            if e.template in _FIRE and e.actor and e.target}


def select_roster(events: list[Event], registry: dict[str, EntityDef],
                  plan: RosterPlan) -> set[str]:
    """남길 객체 id 집합. plan.target에 최대한 맞춘다."""
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
