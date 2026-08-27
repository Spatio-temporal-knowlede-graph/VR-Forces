"""시각별 후보 쌍. 짧은 거리와 포병 사거리는 탐색 반경이 두 자릿수 차이다.

하나의 격자로 처리하면 셀 크기를 어느 쪽에 맞춰도 손해라 경로를 나눈다.

거리는 언제나 ground_distance다. 격자는 도 단위로 나눈다 — 평면 투영을 따로
만들면 사거리 판정과 근접 판정이 다른 거리를 쓰게 된다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from ..geometry import Coord, deg_scales, ground_distance
from .profile import EntityProfile


@dataclass(frozen=True)
class Placement:
    """한 시각의 엔티티 상태."""
    subject: str
    coord: Coord
    heading_deg: float | None
    profile: EntityProfile | None
    force: str


def _cells(placements: list[Placement], radius_m: float
           ) -> dict[tuple[int, int], list[Placement]]:
    """반경 크기의 셀로 나눈다. 셀 폭은 위도에 따라 도로 환산한다."""
    lat_m, lon_m = deg_scales(placements[0].coord.lat)
    d_lat = radius_m / lat_m
    d_lon = radius_m / lon_m
    out: dict[tuple[int, int], list[Placement]] = defaultdict(list)
    for p in placements:
        out[(int(math.floor(p.coord.lat / d_lat)),
             int(math.floor(p.coord.lon / d_lon)))].append(p)
    return out


def _neighbourhood(cells, key) -> list[Placement]:
    x, y = key
    found: list[Placement] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            found.extend(cells.get((x + dx, y + dy), ()))
    return found


def local_pairs(placements: list[Placement], radius_m: float
                ) -> Iterator[tuple[Placement, Placement, float]]:
    """반경 안의 순서 없는 쌍을 한 번씩 낸다."""
    if not placements:
        return
    cells = _cells(placements, radius_m)
    for key, members in cells.items():
        neighbours = _neighbourhood(cells, key)
        for first in members:
            for second in neighbours:
                # 이웃 셀을 훑으므로 인덱스 비교로는 중복을 못 자른다.
                # 이름 순서로 자른다.
                if second.subject <= first.subject:
                    continue
                gap = ground_distance(first.coord, second.coord)
                if gap <= radius_m:
                    yield (first, second, gap)


def engagement_pairs(placements: list[Placement], field_span_m: float
                     ) -> Iterator[tuple[Placement, Placement, float]]:
    """(사수, 표적, 거리). 무장한 객체만 시드가 되고, 반경은 시드 자신의 사거리다."""
    if not placements:
        return
    seeds = [p for p in placements
             if p.profile is not None and p.profile.max_range_m]
    # 사거리별로 격자를 한 번만 만든다. weapon_ranges.csv의 사거리 종류는
    # 열 개가 안 되는데, 시드마다(실측에서 약 290개) 다시 만들면 그만큼
    # 낭비다 — 사거리 값으로 캐시해 시드 루프 안에서 지연 생성한다.
    grids_by_reach: dict[float, dict[tuple[int, int], list[Placement]]] = {}
    lat_m, lon_m = deg_scales(placements[0].coord.lat)
    for seed in seeds:
        reach = seed.profile.max_range_m
        if reach >= field_span_m:
            # 포병 사거리가 전장보다 크면 격자가 이득을 주지 않는다.
            candidates = placements
        else:
            cells = grids_by_reach.get(reach)
            if cells is None:
                cells = _cells(placements, reach)
                grids_by_reach[reach] = cells
            key = (int(math.floor(seed.coord.lat / (reach / lat_m))),
                   int(math.floor(seed.coord.lon / (reach / lon_m))))
            candidates = _neighbourhood(cells, key)
        for target in candidates:
            if target.subject == seed.subject:
                continue
            gap = ground_distance(seed.coord, target.coord)
            if gap <= reach:
                yield (seed, target, gap)
