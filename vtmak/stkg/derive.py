"""발사체 → fired_by 관계 추론.

발사체가 처음 관측된 시각의 최근접 엔티티를 발사자로 본다. 최근접만으로는
틀린다 — 실측에서 PAC-3 1(패트리엇 요격탄)이 19.1m 떨어진 박격포에 붙었다.
그래서 무기·탄약 정합성 검사를 함께 건다. 정합하지 않으면 **관계를 만들지
않고** 사유를 돌려준다. 억지로 붙이면 틀린 관계가 정답 행세를 한다.
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Obs:
    """관계 한 건의 tick 단위 관측. collapse가 이걸 구간으로 접는다."""
    subject: str
    predicate: str
    object: str
    object_type: str
    timestamp: str
    source: str
    confidence: str           # observed | inferred
    evidence: str


def load_munition_map(path) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(Path(path), encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["munition_prefix"]] = row["firer_marking_pattern"]
    return out


def _prefix_of(marking: str, munition_map: dict[str, str]) -> str | None:
    # 'M933HE 2' → 'M933HE'. 접두가 긴 것부터 봐야 M107과 M1077을 안 헷갈린다.
    for prefix in sorted(munition_map, key=len, reverse=True):
        if marking.startswith(prefix):
            return prefix
    return None


def fired_by(first_seen: dict[tuple[str, str],
                              tuple[str, tuple[float, float, float]]],
             candidates: dict[tuple[str, str],
                              list[tuple[str, tuple[float, float, float]]]],
             munition_map: dict[str, str],
             max_m: float = 200.0) -> tuple[list[Obs], list[str]]:
    """키가 (source, ...)인 이유는 같은 발사체가 여러 관측자에게 보이기
    때문이다. 실측에서 M933HE 1이 GROUND_TRUTH와 UAV 2 양쪽에 나온다.
    섞으면 UAV가 본 발사체가 GT가 본 박격포에 붙어 서로 다른 시간대의
    관측을 하나로 잇는다."""
    rels: list[Obs] = []
    unresolved: list[str] = []

    for (source, munition), (ts, ecef) in sorted(first_seen.items()):
        prefix = _prefix_of(munition, munition_map)
        if prefix is None:
            unresolved.append(f"[{source}] {munition}: 탄약 접두 미등록")
            continue
        pattern = re.compile(munition_map[prefix])

        best, best_d = None, math.inf
        for marking, pos in candidates.get((source, ts), []):
            if not pattern.search(marking):
                continue
            d = math.dist(ecef, pos)
            if d < best_d:
                best, best_d = marking, d

        if best is None:
            unresolved.append(f"[{source}] {munition}: {prefix}에 맞는 발사 "
                              f"무기가 {ts}에 없음")
            continue
        if best_d > max_m:
            unresolved.append(f"[{source}] {munition}: 최근접 {best}이 "
                              f"{best_d:.1f}m로 임계 {max_m:.0f}m 초과")
            continue

        rels.append(Obs(munition, "fired_by", best, "entity", ts, source,
                        "inferred", f"최근접 {best_d:.1f}m, 정합 {prefix}"))
    return rels, unresolved
