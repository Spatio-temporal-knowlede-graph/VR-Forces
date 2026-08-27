"""시각별 관계를 이어진 구간으로 접는다.

매초 트리플을 내면 2m 컷에서도 원본 STKG의 15배, 1,500m면 63배다. 실측 압축비는
관계에 따라 17~117배다.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import Observation, RelationInterval

_Key = tuple[str, str, str]


@dataclass
class _Open:
    t_start: str
    t_end: str
    last_seconds: float
    support_count: int
    evidence: str


class IntervalAccumulator:
    """시각마다 그때의 관계 집합을 통째로 넣으면 구간을 낸다.

    관계가 이어지려면 양 끝에서 성립하는 것만으로 부족하고 두 시각의 간격이
    max_merge_gap_s 이하여야 한다. 이 규칙이 없으면 실측 227초 결측을 가로질러
    구간이 이어지고, 관측이 없는 구간을 관측했다고 주장하게 된다.
    """

    def __init__(self, max_merge_gap_s: float) -> None:
        self._max_gap = max_merge_gap_s
        self._open: dict[_Key, _Open] = {}
        self._closed: list[RelationInterval] = []

    def observe(self, timestamp: str, seconds: float,
                observations: Iterable[Observation]) -> None:
        current: dict[_Key, Observation] = {
            (o.subject, o.predicate, o.object): o for o in observations
        }
        for key in list(self._open):
            if key not in current:
                self._shut(key)

        for key, item in current.items():
            state = self._open.get(key)
            if state is not None and seconds - state.last_seconds <= self._max_gap:
                state.t_end = timestamp
                state.last_seconds = seconds
                state.support_count += 1
                continue
            if state is not None:
                self._shut(key)
            self._open[key] = _Open(timestamp, timestamp, seconds, 1, item.evidence)

    def close(self) -> list[RelationInterval]:
        for key in list(self._open):
            self._shut(key)
        self._closed.sort(key=lambda r: (r.subject, r.predicate, r.object, r.t_start))
        return self._closed

    def _shut(self, key: _Key) -> None:
        state = self._open.pop(key)
        subject, predicate, obj = key
        self._closed.append(RelationInterval(
            subject=subject, predicate=predicate, object=obj,
            t_start=state.t_start, t_end=state.t_end,
            support_count=state.support_count, evidence=state.evidence,
        ))
