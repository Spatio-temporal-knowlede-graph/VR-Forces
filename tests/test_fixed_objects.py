"""고정 객체(UAV) — campaign에서 복제해 어느 규모에서든 같은 배치로 들어가는가."""
import dataclasses
import json
import math
import re  # noqa: F401  (object-identifier 유일성 검사에서 쓴다)
import zipfile
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout, ground_distance
from vtmak.parser import PatternMap, parse_scenario
from vtmak.paths import SCENARIO
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.fixed import load_fixed
from vtmak.scnx.gates import check_g3
from vtmak.scnx.golden import Golden, _parse_objects
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.spec import build_fixed_plans, build_spec
from vtmak.scnx.writer import get_writer

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
GOLDEN = ensure_golden(ROOT / "yewon_test")
LAYOUT = BattlefieldLayout.load(CFG / "battlefield_layout.json")
FIXED_CFG = json.loads((CFG / "fixed_objects.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixed():
    return load_fixed(CFG / "fixed_objects.json", ROOT, LAYOUT)


def _spec(scenario: Path, fixed, target_entities: int | None = None):
    pm = PatternMap.load(CFG / "pattern_map.csv")
    res = parse_scenario(scenario.read_text(encoding="utf-8"), pm)
    lay = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    reg = build_registry(res.events, ClassMap.load(CFG / "entity_class_map.csv"),
                         lay.static_ids())
    task_ids = {e.event_id for e in res.events
                if pm.task_kind_of(e) not in ("", "noop")}
    plan = RosterPlan.load(CFG / "roster.json")
    if target_entities is not None:
        plan = dataclasses.replace(plan, target_entities=target_entities)
    keep = select_roster(res.events, reg, plan, task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    dis = DisCatalog.load(CFG / "dis_catalog.csv")
    return build_spec(events, reg, lay, pm,
                      TaskCatalog.load(CFG / "task_catalog.csv"),
                      TaskKinds.load(CFG / "task_kinds.csv"), dis,
                      WeaponRanges.load(CFG / "weapon_ranges.csv"),
                      "battle", fixed=fixed), dis


@pytest.fixture(scope="module")
def built(fixed):
    return _spec(SCENARIO, fixed)


@pytest.fixture(scope="module")
def written(built, tmp_path_factory):
    spec, _ = built
    out = get_writer("template", str(GOLDEN)).write(
        spec, tmp_path_factory.mktemp("scnx"))
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist()}


def uavs(fixed):
    return [f for f in fixed if not f.is_route]


def routes(fixed):
    return [f for f in fixed if f.is_route]


def test_config_declares_the_uavs(fixed):
    assert [f.marking for f in uavs(fixed)] == ["UAV 1", "UAV 2", "UAV 3",
                                                "UAV 4"]
    assert all(not f.coord.is_zero() for f in fixed)
    # 전부 같은 공중 플랫폼 DIS(domain 2 = air).
    assert {f.dis for f in uavs(fixed)} == {(1, 2, 225, 50, 25, 1, 0)}
    # UAV마다 순찰로 하나. 라우트는 플랜이 붙지 않는다.
    assert [f.marking for f in routes(fixed)] == ["UAV1RTE", "UAV2RTE",
                                                  "UAV3RTE", "UAV4RTE"]
    assert all(f.plan_actions == () for f in routes(fixed))
    assert len({f.uuid for f in fixed}) == len(fixed), "uuid 충돌"


def test_identity_is_copied_verbatim_from_campaign(fixed):
    """uuid·DIS는 원본 그대로다 — 우리가 합성하면 인스턴스화가 깨진다.

    좌표만 config가 정한다(순찰 중심에서 계산). 그래서 campaign 좌표와는
    다르고, 이건 의도다.
    """
    src = {o.marking: o for o in _parse_objects(
        (ROOT / "campaign" / "campaign.oob").read_text(
            encoding="utf-8", errors="replace"))}
    for f in uavs(fixed):
        assert f.uuid == src[f.marking].uuid
        assert f.dis == src[f.marking].dis
        assert f.coord.to_ecef() != pytest.approx(src[f.marking].position)


def test_uavs_start_on_their_patrol_at_the_declared_altitude(fixed):
    """초기 좌표 = 순찰 중심에서 radius_m, 고도 = 지면 + altitude_agl_m."""
    patrol = FIXED_CFG["patrol"]
    centers = FIXED_CFG["patrol_centers"]
    for f in uavs(fixed):
        lid = centers[f.marking]
        assert f.patrol_center_loc == lid
        c = LAYOUT.coord(lid)
        # ground_distance는 ECEF 직선거리라 고도차가 섞인다. 중심을 UAV와 같은
        # 고도에 두고 재야 순수 수평 반경이 나온다.
        level = dataclasses.replace(c, alt=f.coord.alt)
        assert ground_distance(level, f.coord) == pytest.approx(
            patrol["radius_m"], abs=1.0)
        assert f.coord.alt == pytest.approx(c.alt + patrol["altitude_agl_m"])
        # 짐벌 하방각은 이 기하에서 나온다 — 반경·고도를 고치면 따라와야 한다.
        assert math.degrees(math.atan2(
            patrol["altitude_agl_m"],
            patrol["radius_m"])) == pytest.approx(21.8, abs=0.1)


def test_patrol_route_rings_the_centre_at_flight_altitude(fixed):
    """순찰로 정점이 중심 둘레 반경 radius_m에 등간격으로 놓이는가.

    정점은 레코드 position을 원점으로 한 로컬 오프셋(동 x, 북 y, 고도 z)이다
    (battle.oob 실측). 정점이 안 바뀌면 공여체 경로를 그대로 날게 된다.
    """
    patrol = FIXED_CFG["patrol"]
    centers = FIXED_CFG["patrol_centers"]
    for uav, route in zip(uavs(fixed), routes(fixed)):
        c = LAYOUT.coord(centers[uav.marking])
        assert route.coord.as_tuple() == pytest.approx(c.as_tuple())
        verts = re.findall(
            r"\(vertex\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)", route.raw)
        assert len(verts) == patrol["vertices"], route.marking
        for dx, dy, dz in verts:
            assert math.hypot(float(dx), float(dy)) == pytest.approx(
                patrol["radius_m"], abs=0.5)
            assert float(dz) == pytest.approx(patrol["altitude_agl_m"])
        # 반시계여야 짐벌 좌현 고정이 안쪽을 본다.
        (x1, y1), (x2, y2) = ((float(verts[0][0]), float(verts[0][1])),
                              (float(verts[1][0]), float(verts[1][1])))
        assert x1 * y2 - y1 * x2 > 0, f"{route.marking}: 시계 방향이다"


def test_gimbal_is_rewritten_in_the_cloned_record(fixed):
    """짐벌은 플랜 Set이 아니라 .oob PSR에 직접 쓴다(문법이 검증된 필드).

    -80°로 처박혀 있던 값이 남아 있으면 관측이 다시 시간의 4~13%로 떨어진다.
    """
    g = FIXED_CFG["gimbal"]
    want_el = -math.atan2(FIXED_CFG["patrol"]["altitude_agl_m"],
                          FIXED_CFG["patrol"]["radius_m"])
    for f in uavs(fixed):
        block = re.search(
            r"\(sensor-gimbal-controller-process-state-repository-default"
            r"(.*?)\n\s*\)\n", f.raw, re.S)
        assert block, f.marking
        body = block.group(1)
        assert f"(aiming-elevation {want_el:.6f})" in body, f.marking
        assert f"(aiming-azimuth {g['azimuth_rad']:.6f})" in body, f.marking
        assert f"(aiming-mode {g['aiming_mode']})" in body, f.marking
        assert f"(scanning-left {g['scanning_left']!s:s})".replace(
            "false", "False").replace("true", "True") in body, f.marking
        assert "-1.396263" not in f.raw, f"{f.marking}: -80° 짐벌이 남아 있다"


def test_ordered_altitude_follows_the_new_position(fixed):
    """position만 옮기고 ordered-altitude를 두면 UAV가 원래 고도로 내려간다."""
    for f in uavs(fixed):
        assert f"(ordered-altitude {f.coord.alt:.6f})" in f.raw, f.marking
        assert "73.237128" not in f.raw, f.marking


def _cfg(**over):
    base = {
        "source_dir": "campaign", "markings": ["UAV 1"],
        "patrol_centers": {"UAV 1": "LOC_중앙킬존"},
        "patrol": {"route_donor": {"source_dir": "battle",
                                   "marking": "Route 1"},
                   "radius_m": 1000.0, "vertices": 8,
                   "altitude_agl_m": 400.0},
    }
    base.update(over)
    return json.dumps(base)


def test_missing_marking_is_an_error(tmp_path):
    """조용히 빠지면 .scnx를 열어보기 전까지 없어진 걸 모른다."""
    cfg = tmp_path / "fixed_objects.json"
    cfg.write_text('{"source_dir": "campaign", "markings": ["UAV 9"]}',
                   encoding="utf-8")
    with pytest.raises(KeyError, match="UAV 9"):
        load_fixed(cfg, ROOT, LAYOUT)


def test_missing_patrol_center_is_an_error(tmp_path):
    """순찰 중심을 안 적은 UAV가 있으면 세운다 — 플랜만 비면 안 도는 걸 모른다."""
    cfg = tmp_path / "fixed_objects.json"
    cfg.write_text(_cfg(markings=["UAV 1", "UAV 2"]), encoding="utf-8")
    with pytest.raises(KeyError, match="UAV 2"):
        load_fixed(cfg, ROOT, LAYOUT)


def test_unknown_patrol_center_location_is_an_error(tmp_path):
    cfg = tmp_path / "fixed_objects.json"
    cfg.write_text(_cfg(patrol_centers={"UAV 1": "LOC_없는지명"}),
                   encoding="utf-8")
    with pytest.raises(KeyError, match="없는지명"):
        load_fixed(cfg, ROOT, LAYOUT)


def test_patrol_centers_without_a_layout_is_an_error(tmp_path):
    """지명을 좌표로 풀 수단 없이 순찰을 선언하면 조용히 제자리에 두지 않는다."""
    cfg = tmp_path / "fixed_objects.json"
    cfg.write_text(_cfg(), encoding="utf-8")
    with pytest.raises(ValueError, match="BattlefieldLayout"):
        load_fixed(cfg, ROOT)


def test_missing_route_donor_is_an_error(tmp_path):
    """golden에는 라우트 템플릿이 없다 — 공여체를 못 찾으면 순찰이 불가능하다."""
    cfg = tmp_path / "fixed_objects.json"
    cfg.write_text(_cfg(patrol={
        "route_donor": {"source_dir": "battle", "marking": "없는 라우트"},
        "radius_m": 1000.0, "vertices": 8, "altitude_agl_m": 400.0,
    }), encoding="utf-8")
    with pytest.raises(KeyError, match="라우트 공여체"):
        load_fixed(cfg, ROOT, LAYOUT)


def test_absent_config_means_no_fixed_objects(tmp_path):
    assert load_fixed(tmp_path / "none.json", ROOT, LAYOUT) == []


def test_written_oob_carries_every_fixed_object(written, fixed):
    oob = written["battle.oob"]
    got = {o.marking: o for o in _parse_objects(oob)}
    for f in fixed:
        assert f.marking in got, f.marking
        assert got[f.marking].uuid == f.uuid
        assert got[f.marking].position == pytest.approx(f.coord.to_ecef())


def test_object_identifiers_stay_unique_after_appending(written):
    ids = re.findall(r'\(object-identifier\s+"([^"]*)"', written["battle.oob"])
    assert len(ids) == len(set(ids)), "object-identifier 충돌"


def test_fixed_objects_are_in_the_object_map(written, fixed):
    """.omp에 없는 .oob 객체는 로드돼도 화면에 안 나온다."""
    for f in fixed:
        assert f.uuid in written["battle.omp"], f.marking


def _plan_block(pln: str, uuid: str) -> str:
    m = re.search(rf'\(plan-name  "VRF_UUID:{re.escape(uuid)}"\).*?'
                  r"\(plan-execution-stack", pln, re.S)
    assert m, uuid
    return m.group(0)


def test_uav_plan_reports_what_it_sees_and_flies(written, fixed):
    """관측 보고를 켜지 않으면 탐지해도 CSV에 안 남는다 — 생성기가 빼먹던 Set.

    move-along은 한 번에 한 바퀴만 돈다. laps만큼 붙지 않으면 UAV가 도중에
    마지막 정점에 서 버린다(orbit_object가 아예 안 움직였던 것과 같은 증상).
    """
    pln = written["battle.pln"]
    laps = FIXED_CFG["patrol"]["laps"]
    for f in uavs(fixed):
        assert f.uuid in pln, f.marking
        block = _plan_block(pln, f.uuid)
        assert '(set-data-request-type "set-spot-reporting-request")' in block
        assert "(spot-reporting-turned-on 2)" in block, f.marking
        assert block.count('(task-type "move-along")') == laps, f.marking
        assert "(traversal-direction 1)" not in block, f.marking
        assert "orbit_object" not in block, f"{f.marking}: 안 도는 태스크가 남았다"


def test_routes_are_written_and_referenced(written, fixed):
    """치환 안 된 자리표시자나 유령 uuid가 흘러가면 UAV가 그냥 안 움직인다."""
    pln, oob, omp = (written["battle.pln"], written["battle.oob"],
                     written["battle.omp"])
    for uav, route in zip(uavs(fixed), routes(fixed)):
        assert uav.patrol_route_uuid == route.uuid, uav.marking
        block = _plan_block(pln, uav.uuid)
        assert f'(route "VRF_UUID:{route.uuid}")' in block, uav.marking
        assert f"VRF_UUID:{route.uuid}" in oob, route.marking
        assert f"VRF_UUID:{route.uuid}" in omp, route.marking
    assert "PATROL_ROUTE_UUID" not in pln


def test_routes_have_no_plan_of_their_own(written, fixed):
    """라우트는 전술 그래픽이다 — 플랜이 붙으면 안 된다."""
    pln = written["battle.pln"]
    for r in routes(fixed):
        assert f'(plan-name  "VRF_UUID:{r.uuid}"' not in pln, r.marking


def test_uav_plan_is_declared_in_config_not_in_code(fixed):
    """어떤 행동을 붙일지는 config가 정한다 — 코드에 문법을 박지 않는다."""
    assert all(f.plan_actions == ("관측 보고 켜기", "순찰 비행")
               for f in uavs(fixed))
    assert all(f.type_group == "무인기 - 짐벌 센서" for f in uavs(fixed))


def test_fixed_plan_rejects_an_unsupported_plan_element():
    """Set·Task 밖의 요소(If/Condition)는 조용히 넘기지 않고 세운다."""
    cat = TaskCatalog.load(CFG / "task_catalog.csv")
    brancher = dataclasses.replace(
        load_fixed(CFG / "fixed_objects.json", ROOT, LAYOUT)[0],
        type_group="공통 - 조건 분기", plan_actions=("탐지 수준에 따른 분기",))
    with pytest.raises(ValueError, match="If / Condition"):
        build_fixed_plans([brancher], cat)


def test_patrol_without_a_route_is_an_error():
    """순찰 비행을 선언해 놓고 순찰로가 비면 세운다."""
    cat = TaskCatalog.load(CFG / "task_catalog.csv")
    homeless = dataclasses.replace(
        load_fixed(CFG / "fixed_objects.json", ROOT, LAYOUT)[0],
        patrol_route_uuid="")
    with pytest.raises(ValueError, match="순찰로"):
        build_fixed_plans([homeless], cat)


def test_unknown_fixed_action_is_an_error():
    cat = TaskCatalog.load(CFG / "task_catalog.csv")
    ghost = dataclasses.replace(
        load_fixed(CFG / "fixed_objects.json", ROOT, LAYOUT)[0],
        plan_actions=("없는 행동",))
    with pytest.raises(KeyError, match="없는 행동"):
        build_fixed_plans([ghost], cat)


def test_g3_catches_a_uuid_collision_with_generated_entities(built):
    spec, dis = built
    g = Golden.load(GOLDEN)
    assert [v for v in check_g3(spec, g, dis) if v.code == "C3.4"] == []

    clash = dataclasses.replace(spec.fixed_objects[0],
                                uuid=spec.entities[0].uuid)
    saved = spec.fixed_objects
    spec.fixed_objects = [clash]
    try:
        v = [x for x in check_g3(spec, g, dis) if x.code == "C3.4"]
        assert len(v) == 1 and "고정 객체" in v[0].detail
        assert v[0].severity == "BLOCK"
    finally:
        spec.fixed_objects = saved


@pytest.mark.parametrize("n", (60, 40, 20))
def test_fixed_objects_are_identical_at_every_scale(n, fixed, built):
    """명부를 줄여도 UAV는 개수·배치·uuid가 그대로다.

    원문에서 나오는 객체가 아니라 밖에서 붙이는 객체이므로, roster 규모와
    무관해야 한다. 순찰로와 플랜까지 같아야 '같은 배치'다.
    """
    base, _ = built
    spec, _ = _spec(SCENARIO, fixed, target_entities=n)
    assert len(spec.entities) < len(base.entities), "명부가 줄어야 의미가 있다"

    def shape(s):
        return ([(f.marking, f.uuid, f.coord.as_tuple(), f.patrol_center_loc,
                  f.patrol_route_uuid, f.raw) for f in s.fixed_objects],
                s.fixed_plans)

    assert shape(spec) == shape(base)
