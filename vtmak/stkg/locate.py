"""목적지 좌표를 위치 객체로 바꾼다.

태스크 저작이 지명 좌표를 그대로 넣으므로 최근접 탐색이 아니라 정확 일치로
대부분 끝난다. 실측(2026-08-03): Move to 95,444행 중 87.2%가 0.0m로 붙었다.

3단 폴백이다.
  1. 정확 일치   지명 좌표와 exact_m 이내      → 지명   (location)
  2. 최근접      통제점과 near_m 이내          → 통제점 (location)
  3. 폴백        좌표 문자열 유지              →        (coord)

2단계는 통제점이 주어졌을 때만 돈다. 현재 빌드는 통제점을 저작하지 않아
1 → 3으로 간다(스펙 §7).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Snap:
    object_id: str
    object_type: str          # location | coord
    distance_m: float         # coord 폴백이면 -1.0


def _fmt(ecef: tuple[float, float, float]) -> str:
    return ",".join(f"{v:.6f}" for v in ecef)


def snap(ecef: tuple[float, float, float], layout,
         control_points: dict[str, tuple[float, float, float]] | None = None,
         exact_m: float = 1.0, near_m: float = 50.0) -> Snap:
    best_id, best_d = None, math.inf
    for lid in layout.location_ids():
        d = math.dist(ecef, layout.coord(lid).to_ecef())
        if d < best_d:
            best_id, best_d = lid, d
    if best_id is not None and best_d <= exact_m:
        return Snap(best_id, "location", best_d)

    if control_points:
        cp_id, cp_d = None, math.inf
        for pid, coord in control_points.items():
            d = math.dist(ecef, coord)
            if d < cp_d:
                cp_id, cp_d = pid, d
        if cp_id is not None and cp_d <= near_m:
            return Snap(cp_id, "location", cp_d)

    return Snap(_fmt(ecef), "coord", -1.0)
