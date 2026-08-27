"""한 시각에 성립하는 모든 관계.

방출 정책이 여기 있다 — in_range_of의 소속 필터와 next_to의 편대 제외. 둘 다
relation.py에서 일부러 뺐다. 거기는 기하가 무엇을 말하는지만 답한다.

approach는 여기서 안 만든다. 거리 변화율이 필요한데, 그 율은 내보내기가 벽시계가
아니라 시뮬레이션 시각을 줄 때에만 뜻이 있다. 설계 문서 §14를 보라.
"""
from __future__ import annotations

import math

from ..geometry import bearing_elevation
from .models import Observation
from .pair import Placement, engagement_pairs, local_pairs
from .quality import (COORDINATE_COLLISION, MISSING_HEADING,
                      UNMAPPED_ENTITY_TYPE, QualityLog)
from .relation import (judge_direction, judge_in_range, judge_next_to,
                       relative_bearing_deg)
from .thresholds import Thresholds


def judge_frame(timestamp: str, placements: list[Placement],
                follow_pairs: set[frozenset[str]], thresholds: Thresholds,
                field_span_m: float, log: QualityLog) -> list[Observation]:
    """placements 사이에 timestamp 시점으로 성립하는 관계 전부."""
    out: list[Observation] = []

    for p in placements:
        if p.profile is None:
            log.record(timestamp, [p.subject], UNMAPPED_ENTITY_TYPE,
                       "next_to·in_range_of 생략")
        if p.heading_deg is None:
            log.record(timestamp, [p.subject], MISSING_HEADING, "방향 관계 생략")

    for first, second, gap in local_pairs(placements, thresholds.interest_distance_m):
        if gap < thresholds.min_bearing_distance_m:
            log.record(timestamp, [first.subject, second.subject],
                       COORDINATE_COLLISION, "")

        # next_to — 타입이 있어야 하고, 그 시점 Follow가 활성이면 내지 않는다.
        if frozenset({first.subject, second.subject}) not in follow_pairs:
            if judge_next_to(gap, first.profile, second.profile, thresholds):
                out.append(Observation(first.subject, "next_to", second.subject))

        # 방향 — 두 방향을 각각. 기준은 언제나 목적어의 방위다.
        for subject, obj in ((first, second), (second, first)):
            if obj.heading_deg is None:
                continue
            az_rad, _ = bearing_elevation(obj.coord, subject.coord)
            offset = relative_bearing_deg(obj.heading_deg, math.degrees(az_rad))
            predicate = judge_direction(gap, offset, thresholds)
            if predicate is not None:
                out.append(Observation(subject.subject, predicate, obj.subject))

    for shooter, target, gap in engagement_pairs(placements, field_span_m):
        if shooter.force == target.force:
            continue
        evidence = judge_in_range(gap, shooter.profile)
        if evidence is not None:
            out.append(Observation(shooter.subject, "in_range_of",
                                   target.subject, evidence))

    return out
