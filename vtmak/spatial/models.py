"""공간 관계 파이프라인이 주고받는 값 타입."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Observation:
    """한 시각에 두 엔티티 사이에 성립한 관계 하나."""
    subject: str
    predicate: str
    object: str
    evidence: str = ""


@dataclass(frozen=True)
class RelationInterval:
    """한 관계가 끊기지 않고 이어진 시간 구간."""
    subject: str
    predicate: str
    object: str
    t_start: str
    t_end: str
    support_count: int
    evidence: str = ""


@dataclass(frozen=True)
class QualityIssue:
    """관계를 만들지 않은 이유, 또는 만들었지만 의심스러운 근거."""
    timestamp: str
    subjects: str
    code: str
    detail: str


@dataclass(frozen=True)
class RelationStats:
    """스크립트가 JSON으로 찍는 요약."""
    input_rows: int
    timestamps: int
    relation_counts: dict[str, int] = field(default_factory=dict)
    quality_issues: int = 0
