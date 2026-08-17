"""초기 배치 — 한 지명에 몰린 객체를 겹치지 않게 흩는다.

2026-08-09까지는 object_id 해시로 ±25m 정사각형 안에 흩었다. 그 방식은 개수와
객체 크기를 보지 않는다. 실측(2026-08-09 `battle.oob` 343객체)에서 최근접
이웃 거리 중앙값이 3.2m, 5m 미만이 232개, 2m 미만이 103개였다. T-72가 6.9m,
BTR-60이 7.6m이므로 전차 여러 대가 서로를 관통한 채 서 있었다. 적 북측
집결지 한 곳에 130객체가 50×50m 안에 들어간 것이 원인이다.

여기서는 세 가지를 바꾼다.

1. **최소 이격거리를 타입별로 보장한다.** 값은 `config/placement_rules.csv`가
   정한다. 보병 2m · 차량/전차 10m · 포병 12~15m.
2. **대형이 지명마다 다르다.** 방어선은 선(rank), 집결지는 격자, 접근로는
   종대다. 예전에는 전부 네모난 덩어리였다.
3. **결정적이다.** 난수도 해시도 쓰지 않는다. 정렬된 목록의 순서가 자리를
   정하므로 같은 입력이면 같은 좌표가 나온다.

좌표계는 지명 기준 로컬 미터 (u, v)다.

    u = 정면 축(전장 축에 수직). 대형이 늘어서는 방향. 지명을 중심으로 대칭.
    v = 깊이 축. **양수가 후방**(적에서 멀어지는 쪽)이라 진영마다 방향이 다르다.

전장 축은 나침반이 아니라 `battlefield_layout.json`의 `axis_bearing_deg`
(아군 중심 → 적 중심, 실측 163.36°)다. golden 통제점의 동/서/남/북이 실제
방위와 뒤집혀 있어 나침반을 쓰면 방어선이 엉뚱한 방향으로 눕는다.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from ..geometry import BattlefieldLayout, Coord
from ..norm import norm
from ..roster import unit_of

# 대형 이름 → 블록 한 개를 몇 열로 세울지 정하는 규칙.
LINE = "선형"
GRID = "격자"
COLUMN = "종대"
SHAPES = (LINE, GRID, COLUMN)

# 종대의 열 수. 도로 위 2열 종대.
_COLUMN_FILES = 2


@dataclass(frozen=True)
class PlacementRules:
    """타입별 최소 이격거리 + 지명별 대형. 정본은 placement_rules.csv."""
    default_spacing_m: float
    default_shape: str
    default_front_m: float
    spacing: dict[str, float]                 # norm(type_group) → m
    shape: dict[str, tuple[str, float]]       # 지명 → (대형, 최대정면 m)

    @classmethod
    def load(cls, path) -> "PlacementRules":
        d_space, d_shape, d_front = 10.0, GRID, 300.0
        spacing: dict[str, float] = {}
        shape: dict[str, tuple[str, float]] = {}
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                rule = (r.get("규칙") or "").strip()
                key = (r.get("키") or "").strip()
                s = (r.get("최소이격_m") or "").strip()
                sh = (r.get("대형") or "").strip()
                fr = (r.get("최대정면_m") or "").strip()
                if rule == "기본":
                    d_space = float(s) if s else d_space
                    d_shape = sh or d_shape
                    d_front = float(fr) if fr else d_front
                elif rule == "타입그룹":
                    if not s:
                        raise ValueError(
                            f"placement_rules.csv: 타입그룹 행에 최소이격_m이 "
                            f"없다: {key}")
                    spacing[norm(key)] = float(s)
                elif rule == "지명":
                    if sh and sh not in SHAPES:
                        raise ValueError(
                            f"placement_rules.csv: 모르는 대형 {sh!r} ({key}) "
                            f"— {SHAPES} 중 하나여야 한다")
                    shape[key] = (sh or d_shape,
                                  float(fr) if fr else d_front)
                elif rule:
                    raise ValueError(
                        f"placement_rules.csv: 모르는 규칙 {rule!r}")
        if d_shape not in SHAPES:
            raise ValueError(f"placement_rules.csv: 모르는 기본 대형 {d_shape!r}")
        return cls(d_space, d_shape, d_front, spacing, shape)

    def spacing_of(self, type_group: str) -> float:
        return self.spacing.get(norm(type_group), self.default_spacing_m)

    def shape_of(self, location_id: str) -> tuple[str, float]:
        return self.shape.get(location_id,
                              (self.default_shape, self.default_front_m))


@dataclass(frozen=True)
class Placed:
    """지명 기준 로컬 오프셋(동 +x, 북 +y 미터)."""
    east_m: float
    north_m: float


def _cols(shape: str, n: int, spacing: float, front_m: float) -> int:
    """블록 하나를 몇 열로 세울지.

    선형은 한 줄(rank)이 원칙이지만 정면 한계를 넘으면 뒤로 접는다 — 접지
    않으면 보병 100명이 200m를 넘어 지형 밖으로 나간다.
    """
    limit = max(1, int(front_m // spacing) + 1)
    if shape == LINE:
        return min(n, limit)
    if shape == COLUMN:
        return min(n, _COLUMN_FILES)
    return min(n, limit, max(1, math.ceil(math.sqrt(n))))


def _block(n: int, spacing: float, cols: int) -> tuple[list[tuple[float, float]],
                                                       float, float]:
    """n개를 cols열 격자로 찍는다. 반환 (오프셋들, 정면 폭, 깊이)."""
    out: list[tuple[float, float]] = []
    for i in range(n):
        row, col = divmod(i, cols)
        out.append((col * spacing, row * spacing))
    rows = math.ceil(n / cols)
    return out, (cols - 1) * spacing, (rows - 1) * spacing


def _axis_unit_vectors(facing_rad: float
                       ) -> tuple[tuple[float, float], tuple[float, float]]:
    """정면 방위 → (정면 축, 깊이 축)의 (동, 북) 단위 벡터.

    `facing_rad`는 그 지명의 부대가 **바라보는 쪽**(적 방향)이다. 정면 축은
    거기에 수직이라 방어선이 적을 가로막고 눕고, 깊이 축은 **후방**을 가리켜
    뒷열이 적에서 멀어진다.

    전장 축(`axis_bearing_deg`, 163°)을 전 지명에 그대로 쓰면 안 된다. 그 값은
    아군 중심 → 적 중심의 평균이고, 남측 제1방어선에서 목표 A·중앙 킬존을 보는
    실제 방위는 233° 부근이다. 70° 차이면 방어선이 적을 가로막는 게 아니라
    적을 향해 세로로 늘어선다.
    """
    rear = facing_rad + math.pi
    front = facing_rad + math.pi / 2
    return ((math.sin(front), math.cos(front)),
            (math.sin(rear), math.cos(rear)))


def _circular_mean(angles: list[float]) -> float:
    """방위 평균. 359°와 1°의 평균이 180°가 되지 않도록 벡터로 더한다."""
    if not angles:
        return 0.0
    s = sum(math.sin(a) for a in angles)
    c = sum(math.cos(a) for a in angles)
    if abs(s) < 1e-12 and abs(c) < 1e-12:
        return angles[0]
    return math.atan2(s, c)


@dataclass(frozen=True)
class _Item:
    object_id: str
    type_group: str
    faction: str
    location: str


def plan_offsets(items: list[_Item], rules: PlacementRules,
                 axis_bearing_deg: float,
                 headings: dict[str, float] | None = None) -> dict[str, Placed]:
    """객체 → 지명 기준 로컬 오프셋.

    같은 지명의 객체를 (부대, 타입그룹)별 블록으로 묶고, 블록을 정면 축을 따라
    선반(shelf)처럼 늘어놓는다. 선반이 정면 한계를 넘으면 한 줄 뒤로 간다.
    블록 사이·선반 사이 간격은 양쪽 이격거리 중 큰 값이라, 서로 다른 타입이
    붙어도 큰 쪽 규칙을 지킨다.

    대형이 눕는 방향은 그 지명에 있는 객체들의 **평균 방위**(= 적을 보는 쪽)에
    수직이다. `headings`를 안 주면 전장 축으로 폴백한다.
    """
    by_loc: dict[str, list[_Item]] = {}
    for it in items:
        if it.location:
            by_loc.setdefault(it.location, []).append(it)

    out: dict[str, Placed] = {}
    for loc, group in sorted(by_loc.items()):
        shape, front_m = rules.shape_of(loc)
        # 블록 순서: 타입그룹 → 부대 → id. 같은 부대가 흩어지지 않는다.
        blocks: dict[tuple[str, str], list[_Item]] = {}
        for it in group:
            blocks.setdefault((it.type_group, unit_of(it.object_id)),
                              []).append(it)

        # 선반 배치. u는 왼쪽부터 쌓고 마지막에 전체를 가운데로 옮긴다.
        placed_uv: list[tuple[str, float, float]] = []
        shelf_u = 0.0            # 이번 선반에서 마지막 블록이 끝난 u
        shelf_v = 0.0            # 이번 선반의 시작 깊이
        shelf_depth = 0.0        # 이번 선반에서 가장 깊은 블록
        shelf_gap = 0.0          # 이번 선반의 최대 이격거리
        shelf_n = 0              # 이번 선반에 놓인 블록 수
        u_min, u_max = 0.0, 0.0
        for (tg, _unit), members in sorted(blocks.items()):
            members.sort(key=lambda x: x.object_id)
            s = rules.spacing_of(tg)
            cols = _cols(shape, len(members), s, front_m)
            offs, width, depth = _block(len(members), s, cols)
            # 블록 사이 간격은 양쪽 이격거리 중 큰 값. 폭이 0인 블록(1개짜리)이
            # 있어도 겹치지 않으려면 '선반이 비었는가'를 u가 아니라 블록 수로
            # 판정해야 한다 — u는 1개짜리 블록을 놓아도 0에 머문다.
            gap = max(s, shelf_gap)
            start = shelf_u + (gap if shelf_n else 0.0)
            if shelf_n and start + width > front_m:
                # 이 선반에는 안 들어간다 — 한 줄 뒤로.
                shelf_v += shelf_depth + gap
                shelf_u, shelf_depth, shelf_gap, shelf_n = 0.0, 0.0, 0.0, 0
                start = 0.0
            for it, (du, dv) in zip(members, offs):
                placed_uv.append((it.object_id, start + du, shelf_v + dv))
            u_min = min(u_min, start)
            u_max = max(u_max, start + width)
            shelf_u = start + width
            shelf_depth = max(shelf_depth, depth)
            shelf_gap = max(shelf_gap, s)
            shelf_n += 1
        v_max = shelf_v + shelf_depth

        # 지명이 대형의 중심이 되도록 옮긴다.
        cu = (u_min + u_max) / 2.0
        cv = v_max / 2.0
        facing = _location_facing(group, headings or {}, axis_bearing_deg)
        (fe, fn), (re_, rn) = _axis_unit_vectors(facing)
        for oid, u, v in placed_uv:
            du, dv = u - cu, v - cv
            out[oid] = Placed(east_m=du * fe + dv * re_,
                              north_m=du * fn + dv * rn)
    return out


def _location_facing(group: list[_Item], headings: dict[str, float],
                     axis_bearing_deg: float) -> float:
    """이 지명의 부대가 바라보는 쪽(라디안). 없으면 전장 축으로 폴백."""
    hs = [headings[it.object_id] for it in group if it.object_id in headings]
    if hs:
        return _circular_mean(hs)
    axis = math.radians(axis_bearing_deg)
    return axis if group[0].faction != "RED" else axis + math.pi


def build_positions(defs, layout: BattlefieldLayout, rules: PlacementRules,
                    headings: dict[str, float] | None = None
                    ) -> dict[str, Coord]:
    """{object_id: EntityDef} → {object_id: 배치 좌표}."""
    items = [_Item(oid, d.type_group, d.faction, d.initial_location)
             for oid, d in sorted(defs.items())]
    offsets = plan_offsets(items, rules, layout.axis_bearing_deg, headings)
    out: dict[str, Coord] = {}
    for oid, d in sorted(defs.items()):
        p = offsets.get(oid)
        if p is None or not d.initial_location:
            out[oid] = layout.coord(d.initial_location)
        else:
            out[oid] = layout.offset_coord(d.initial_location,
                                           p.east_m, p.north_m)
    return out


# ---------- heading ---------------------------------------------------------

# 위치를 바꾸는 이동 템플릿. 첫 이동의 목적지가 곧 그 객체가 처음 보는 쪽이다.
_MOVE_TEMPLATES = ("moveTo",)


def build_headings(defs, events, layout: BattlefieldLayout) -> dict[str, float]:
    """객체 → 초기 방위(라디안, 진북 0 시계 방향).

    2026-08-09까지는 전원이 0(진북)이었다. `orientation-tait-bryan`을 공여체
    레코드에서 복사만 하고 덮어쓰지 않았기 때문이다. 되읽어 보면 343객체가
    전부 heading 0°·pitch 0°·roll 0°였다 — 방어부대가 적이 오는 쪽이 아니라
    엉뚱한 데를 보고 서 있었고, 아군과 적이 같은 방향을 봤다.

    기준은 둘이다.

    1. **첫 이동 목적지.** 그 객체가 처음 가는 곳이 처음 보는 쪽이다. 시작하자
       마자 제자리에서 180° 도는 일이 없어진다.
    2. 이동이 없으면 **상대 진영의 중심.** 정지한 방어부대·포병이 여기 해당한다.

    둘 다 못 구하면 전장 축을 쓴다(아군은 적 쪽, 적은 아군 쪽).

    기준점은 배치 좌표가 아니라 **지명 중심**이다. 배치가 이 방위에 의존하므로
    (대형이 방위에 수직으로 눕는다) 반대로 의존하면 순환이 된다. 대형 반경은
    최대 90m대이고 겨냥 거리는 700~2,000m라 각도 차이는 몇 도에 그친다.
    """
    from ..geometry import bearing_elevation

    first_dst: dict[str, str] = {}
    for e in sorted(events, key=lambda x: (x.time_s, x.event_id)):
        if e.template in _MOVE_TEMPLATES and e.actor and e.dst:
            first_dst.setdefault(e.actor, e.dst)

    centre = _faction_centres(defs, layout)
    axis = math.radians(layout.axis_bearing_deg)
    out: dict[str, float] = {}
    for oid, d in sorted(defs.items()):
        here = layout.coord(d.initial_location)
        aim: Coord | None = None
        dst = first_dst.get(oid)
        if dst and layout.has(dst):
            aim = layout.coord(dst)
        elif d.faction in ("BLUE", "RED"):
            aim = centre.get("RED" if d.faction == "BLUE" else "BLUE")
        if aim is None or here.is_zero() or aim.is_zero() or (
                abs(aim.lat - here.lat) < 1e-9 and abs(aim.lon - here.lon) < 1e-9):
            out[oid] = axis if d.faction != "RED" else (axis + math.pi) % (
                2 * math.pi)
            continue
        out[oid] = bearing_elevation(here, aim)[0]
    return out


def _faction_centres(defs, layout: BattlefieldLayout) -> dict[str, Coord]:
    """진영별 초기 배치 지명의 무게중심. heading의 폴백 기준점."""
    acc: dict[str, list[Coord]] = {}
    for d in defs.values():
        if d.faction in ("BLUE", "RED") and d.initial_location:
            c = layout.coord(d.initial_location)
            if not c.is_zero():
                acc.setdefault(d.faction, []).append(c)
    out: dict[str, Coord] = {}
    for f, cs in acc.items():
        out[f] = Coord(sum(c.lat for c in cs) / len(cs),
                       sum(c.lon for c in cs) / len(cs),
                       sum(c.alt for c in cs) / len(cs))
    return out
