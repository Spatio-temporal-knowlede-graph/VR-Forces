"""초기 배치·방위 — 겹침, 대형, 바라보는 쪽.

2026-08-09 이전 산출물의 실측이 이 파일의 존재 이유다.

- 최근접 이웃 거리 중앙값 3.2m, 5m 미만 232/343, 2m 미만 103/343.
  T-72가 6.9m라 전차가 서로를 관통한 채 서 있었다.
- 343객체 전부 heading 0°(진북). 아군과 적이 같은 쪽을 봤다.
- 방어선이 선이 아니라 ±25m 정사각형 덩어리였다.
"""
import math
from pathlib import Path

import pytest

from vtmak.geometry import (BattlefieldLayout, Coord, bearing_elevation,
                            ground_distance, heading_from_tait_bryan,
                            tait_bryan)
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.placement import PlacementRules
from vtmak.scnx.spec import build_spec

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"


def _build():
    pm = PatternMap.load(CFG / "pattern_map.csv")
    res = parse_scenario(SCENARIO.read_text(encoding="utf-8"), pm)
    lay = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    cm = ClassMap.load(CFG / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    task_ids = {e.event_id for e in res.events
                if pm.task_kind_of(e) not in ("", "noop")}
    keep = select_roster(res.events, reg, RosterPlan.load(CFG / "roster.json"),
                         task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    spec = build_spec(events, reg, lay, pm,
                      TaskCatalog.load(CFG / "task_catalog.csv"),
                      TaskKinds.load(CFG / "task_kinds.csv"),
                      DisCatalog.load(CFG / "dis_catalog.csv"),
                      WeaponRanges.load(CFG / "weapon_ranges.csv"),
                      scenario_id="battle")
    return spec, reg, lay, events


@pytest.fixture(scope="module")
def built():
    return _build()


@pytest.fixture(scope="module")
def rules():
    return PlacementRules.load(CFG / "placement_rules.csv")


# ---------- 겹침 -------------------------------------------------------------

def test_no_two_entities_are_closer_than_the_smaller_min_spacing(built, rules):
    """두 객체 사이 거리는 **둘 중 작은 쪽의 최소 이격거리** 이상이다.

    작은 쪽을 쓰는 이유: 보병 2m 블록이 전차 10m 블록 옆에 붙으면 경계에서
    2m가 나올 수 있고 그건 보병 기준으로 정상이다. 계약은 '보병 간격보다도
    가까운 쌍이 없다'이다.

    허용 오차는 상대값이다. 오프셋을 로컬 미터로 잡고 위경도로 옮긴 뒤 ECEF
    직선거리로 되재므로 10m에서 10μm쯤 짧게 나온다(실측 9.999988m).
    """
    spec, reg, _, _ = built
    ents = [(e.object_id, e.coord, rules.spacing_of(e.type_group))
            for e in spec.entities]
    worst = None
    for i, (a_id, a, sa) in enumerate(ents):
        for b_id, b, sb in ents[i + 1:]:
            d = ground_distance(a, b)
            need = min(sa, sb)
            if d < need * (1 - 1e-4) and (worst is None or d < worst[0]):
                worst = (d, a_id, b_id, need)
    assert worst is None, f"{worst[1]}–{worst[2]} 가 {worst[0]:.2f}m " \
                          f"(최소 {worst[3]}m)"


def test_nearest_neighbour_is_never_a_vehicle_overlap(built, rules):
    """차량 이상 크기끼리는 8m 안으로 붙지 않는다.

    옛 배치에서 전차 중심 간격이 1.24m까지 나왔다 — 차체 길이가 7m대이므로
    서로 관통한 상태다.
    """
    spec, _, _, _ = built
    big = [(e.object_id, e.coord) for e in spec.entities
           if rules.spacing_of(e.type_group) >= 10.0]
    assert len(big) > 20, "차량급 객체가 너무 적어 이 테스트가 의미 없다"
    for i, (a_id, a) in enumerate(big):
        for b_id, b in big[i + 1:]:
            assert ground_distance(a, b) >= 8.0 * (1 - 1e-4), (a_id, b_id)


def test_placement_is_deterministic():
    """두 번 만들면 좌표가 바이트 단위로 같다. 난수도 해시도 쓰지 않는다."""
    a, _, _, _ = _build()
    b, _, _, _ = _build()
    assert [e.coord.as_tuple() for e in a.entities] == \
           [e.coord.as_tuple() for e in b.entities]


# ---------- 대형 -------------------------------------------------------------

def _local_xy(centre: Coord, c: Coord) -> tuple[float, float]:
    az, _ = bearing_elevation(centre, c)
    d = ground_distance(centre, c)
    return (d * math.sin(az), d * math.cos(az))


def _major_axis_deg(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """주축 방위(0~180°)와 장축/단축 비. 고윳값 분해를 손으로 한다(2×2)."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts) / n
    syy = sum((p[1] - my) ** 2 for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    disc = max(0.0, tr * tr / 4 - det) ** 0.5
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    vx, vy = (sxy, l1 - sxx) if abs(sxy) > 1e-12 else (
        (1.0, 0.0) if sxx >= syy else (0.0, 1.0))
    return (math.degrees(math.atan2(vx, vy)) % 180.0,
            (l1 / l2) ** 0.5 if l2 > 1e-12 else float("inf"))


def test_defence_lines_are_lines_across_the_front(built):
    """방어선은 부대가 바라보는 쪽에 **수직**으로 눕는다.

    전장 축(163°)을 전 지명에 그대로 쓰면 안 된다는 것이 여기서 걸린다. 남측
    제1방어선에서 목표 A·중앙 킬존을 보는 실제 방위는 238° 부근이라 70°가
    어긋나고, 그러면 방어선이 적을 가로막는 대신 적을 향해 세로로 늘어선다.
    """
    spec, reg, lay, _ = built
    by = {}
    for e in spec.entities:
        by.setdefault(reg[e.object_id].initial_location, []).append(e)
    for loc in ("LOC_남측제1방어선", "LOC_남측제2방어선"):
        g = by.get(loc) or []
        assert len(g) >= 10, loc
        centre = lay.coord(loc)
        major, ratio = _major_axis_deg([_local_xy(centre, e.coord) for e in g])
        facing = math.degrees(sum(e.heading for e in g) / len(g)) % 180.0
        gap = abs(major - facing)
        gap = min(gap, 180.0 - gap)
        assert gap > 60.0, (loc, major, facing)
        assert ratio > 5.0, (loc, ratio)   # 덩어리가 아니라 선이다


def test_assembly_area_is_a_block_not_a_line(built):
    """집결지는 선이 아니라 덩어리다. 대형이 지명마다 다르다는 계약."""
    spec, reg, lay, _ = built
    g = [e for e in spec.entities
         if reg[e.object_id].initial_location == "LOC_적북측집결지"]
    assert len(g) > 50
    centre = lay.coord("LOC_적북측집결지")
    _, ratio = _major_axis_deg([_local_xy(centre, e.coord) for e in g])
    assert ratio < 5.0, ratio


# ---------- 방위 -------------------------------------------------------------

def test_headings_are_not_all_north(built):
    """옛 산출물은 343객체 전부 진북이었다."""
    spec, _, _, _ = built
    hs = {round(math.degrees(e.heading)) for e in spec.entities}
    assert len(hs) > 20, sorted(hs)
    assert not all(h == 0 for h in hs)


def test_each_side_faces_the_other(built):
    """진영별 평균 방위가 서로 반대쪽을 향한다(90° 넘게 벌어진다)."""
    spec, _, _, _ = built

    def mean(f):
        hs = [e.heading for e in spec.entities if e.faction == f]
        return math.atan2(sum(math.sin(h) for h in hs),
                          sum(math.cos(h) for h in hs))

    gap = abs(math.degrees(mean("BLUE") - mean("RED"))) % 360.0
    assert 90.0 < min(gap, 360.0 - gap) <= 180.0, gap


def test_tait_bryan_round_trips_at_several_latitudes():
    """DIS 오일러각은 ECEF 기준이라 위경도마다 값이 다르다. 왕복으로 고정한다."""
    for lat, lon in ((21.386, -157.739), (0.0, 0.0), (45.0, 120.0),
                     (-33.0, -70.0)):
        c = Coord(lat, lon, 12.0)
        for deg in range(0, 360, 13):
            h, p, r = heading_from_tait_bryan(
                c, *tait_bryan(c, math.radians(deg)))
            assert abs((math.degrees(h) - deg + 180) % 360 - 180) < 1e-6
            assert abs(p) < 1e-9 and abs(r) < 1e-9


# ---------- 사격 좌표는 교전 시점의 위치다 ------------------------------------

def test_suppressive_fire_aims_where_the_target_is_when_fired(built):
    """제압사격 좌표는 표적의 **그 순간** 위치다. 초기 배치가 아니다.

    적 보병은 적 북측 집결지에서 출발해 중앙 킬존까지 1.7km를 내려온다. 옛
    구현은 `initial_location`을 읽어 빈 집결지를 쏘게 했다. 51건 전부가 표적이
    이미 이동한 뒤의 사격이라, 옛 동작이 남아 있으면 이 테스트가 전부 잡는다.
    """
    import re

    from vtmak.gates import PositionTracker, engagement_locations

    spec, reg, lay, events = built
    ev = {e.event_id: e for e in events}
    tracker = PositionTracker(events, reg)
    hit_at = engagement_locations(events)
    pat = re.compile(r"\(targetLocation\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)")

    checked = moved = 0
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.task_kind != "suppress" or not s.pln:
                continue
            m = pat.search(s.pln)
            assert m, s.event_id
            e = ev[s.event_id]
            shot_at = Coord.from_ecef(*(float(x) for x in m.groups()))
            now = (hit_at.get((e.actor, e.target))
                   or tracker.location_at(e.target, e.time_s))
            assert now, s.event_id
            assert ground_distance(shot_at, lay.coord(now)) < 1.0, s.event_id
            checked += 1
            start = reg[e.target].initial_location
            if start and start != now:
                moved += 1
                assert ground_distance(shot_at, lay.coord(start)) > 100.0, \
                    (s.event_id, start, now)
    assert checked, "제압사격이 하나도 없다"
    assert moved, "표적이 이동한 뒤의 사격이 없어 이 테스트가 아무것도 못 잡는다"
