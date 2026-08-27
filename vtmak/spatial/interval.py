"""시각별 관계를 이어진 구간으로 접는다.

매초 트리플을 내면 2m 컷에서도 원본 STKG의 15배, 1,500m면 63배다. 실측 압축비는
관계에 따라 17~117배다.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import Observation, RelationInterval
from .thresholds import SYMMETRIC_PREDICATES

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


def canonicalize(observations: Iterable[Observation],
                 storage: str) -> list[Observation]:
    """한 시각의 관측에 대칭 저장 정책을 적용한다.

    next_to와 approach는 대칭이라 양방향이 같은 정보를 담는다. canonical은
    쌍마다 트리플 하나만 남기고 작은 식별자를 주어로 삼아 그 둘을 절반으로
    줄인다. both는 양쪽을 다 써서, 평범한 directed triple만 가정하는 소비자가
    대칭성을 몰라도 되게 한다.

    판정은 두 방식에서 같고 방출만 갈린다 — 그래서 바꾸는 비용이 설정 한 줄이다.
    """
    if storage not in {"canonical", "both"}:
        raise ValueError(f"모르는 symmetric_storage: {storage!r}")

    seen: set[tuple[str, str, str]] = set()
    out: list[Observation] = []

    def _add(item: Observation) -> None:
        key = (item.subject, item.predicate, item.object)
        if key in seen:
            return
        seen.add(key)
        out.append(item)

    for item in observations:
        if item.predicate not in SYMMETRIC_PREDICATES:
            _add(item)
            continue
        low, high = sorted((item.subject, item.object))
        _add(Observation(low, item.predicate, high, item.evidence))
        if storage == "both":
            _add(Observation(high, item.predicate, low, item.evidence))
    return out
