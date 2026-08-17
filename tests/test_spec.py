import re
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.plan import SKIP_MIN_RANGE, balanced
from vtmak.scnx.spec import build_spec

ROOT = Path(__file__).resolve().parents[1]


def _build(orbat=None):
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    # 파이프라인과 같게 명부를 감축한다(02_parse_events.py와 동일).
    task_ids = {e.event_id for e in res.events
                if pm.task_kind_of(e) not in ("", "noop")}
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"),
                         task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    # 편제는 감축된(=328객체가 아니라 축소된) reg로 지어야 한다. 감축 전 reg를
    # 넘기면 편제에 명부 밖 객체가 섞여 unit_of_entity가 어긋난다.
    ob = build_orbat(reg, OrbatConfig.load(cfg / "orbat.json")) if orbat else None
    return build_spec(events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"),
                      TaskKinds.load(cfg / "task_kinds.csv"),
                      DisCatalog.load(cfg / "dis_catalog.csv"),
                      WeaponRanges.load(cfg / "weapon_ranges.csv"),
                      scenario_id="battle", orbat=ob)


@pytest.fixture(scope="module")
def spec():
    return _build()


@pytest.fixture(scope="module")
def spec_with_orbat():
    return _build(orbat=True)


def test_entities_exclude_static_objects(spec):
    ids = {e.object_id for e in spec.entities}
    assert ids
    assert "EN-FP-001" not in ids
    assert "OBJ-009" not in ids


def test_every_entity_has_dis_and_nonzero_coord(spec):
    for e in spec.entities:
        assert e.dis is not None, e.object_id
        assert not e.coord.is_zero(), e.object_id


def test_entities_sharing_a_location_are_jittered(spec):
    at = [e for e in spec.entities if e.object_id.startswith("FR-INF-")][:20]
    assert len({e.coord.as_tuple() for e in at}) == len(at)


def test_every_entity_gets_a_pln(spec):
    """플랜이 빈 엔티티는 '실행할 수 없는 태스크만 받은' 객체뿐이어야 한다.

    플랜이 비면 VR-Forces에서 그 객체는 초기 배치 자리에 가만히 서 있는다.
    원문이 이동·사격을 시켰는데 저작이 안 된 것이면 조용히 넘기지 않는다.
    반대로 VR-Forces가 실행을 거부하는 것이 실측된 조합(skip_reason)만 남아
    비었다면 그건 의도한 결과다 — 견인 대공포처럼 이 시나리오에서 할 수 있는
    일이 하나도 없는 모델이 있다.
    """
    for oid, steps in sorted(spec.entity_plans.items()):
        if any(s.pln for s in steps):
            continue
        assert steps, oid
        assert all(s.skip_reason for s in steps), \
            (oid, [s.issues for s in steps if not s.skip_reason])


def test_empty_plans_are_only_towed_equipment(spec):
    """플랜이 빈 객체가 실제로 어느 모델인지 못 박아 둔다.

    unsupported_tasks가 넓어지면 여기서 먼저 걸린다 — 조용히 객체가
    늘어나면 시나리오가 소리 없이 비어 간다.
    """
    cls = {e.object_id: e.entity_class for e in spec.entities}
    empty = {cls[oid] for oid, steps in spec.entity_plans.items()
             if not any(s.pln for s in steps)}
    # M901 Patriot Launcher는 더 이상 여기 없다 — aimAt이 noop이던 시절엔
    # 이 모델의 유일한 이벤트가 aimAt이라 플랜이 통째로 비었다. Task 4에서
    # aim이 방향 조준 Set을 내면서 빈 플랜에서 빠졌다.
    assert empty == {"ZPU-4 AA Gun"}, empty


def test_no_synthesised_plan_steps(spec):
    # 플랜 보강을 제거했으므로 원문 이벤트가 아닌 스텝이 있으면 안 된다.
    for steps in spec.entity_plans.values():
        for s in steps:
            assert s.event_id.startswith("E"), s


def test_all_pln_blocks_are_balanced(spec):
    for oid, steps in spec.entity_plans.items():
        for s in steps:
            if s.pln:
                assert balanced(s.pln), f"{oid} {s.event_id}"


def test_artillery_fires_at_a_location_not_an_entity(spec):
    gun = next(e.object_id for e in spec.entities
               if e.entity_class == "M109 Howitzer")
    steps = [s for s in spec.entity_plans[gun] if s.pln]
    ffe = [s for s in steps if "ffe-on-location" in s.pln]
    assert ffe, [s.pln for s in steps]
    # 정적 목표는 좌표로 처리한다(설계 스펙 §5.3) — uuid 참조가 없어야 한다.
    assert all(not s.refs for s in ffe)
    assert "VRF_UUID" not in ffe[0].pln


def test_artillery_can_move(spec):
    """포병도 진지변환 이동을 한다. task_catalog에 이동 템플릿을 추가했다.

    원문의 포병 이동은 '방어선 재편성 이동'이라 통제점 이동(move-to)으로 간다.
    좌표 이동이든 통제점 이동이든 '움직인다'가 계약이다.
    """
    steps = [s for s in spec.entity_plans["FR-AHS-001"] if s.pln]
    assert any("move-to-location-task" in s.pln or '"move-to"' in s.pln
               for s in steps)


def test_infantry_direct_fire_targets_an_entity(spec):
    """제압으로 끝나지 않는 직접사격은 fire-at-target으로 남는다."""
    fire = [s for steps in spec.entity_plans.values() for s in steps
            if s.pln and "fire-at-target" in s.pln]
    assert fire
    assert fire[0].refs
    assert f'"VRF_UUID:{fire[0].refs[0]}"' in fire[0].pln


def test_suppressive_fire_replaces_plain_fire_when_target_is_suppressed(spec):
    """원문의 사격→피격→제압 3문장을 이어붙여 제압사격으로 저작한다."""
    sup = [s for steps in spec.entity_plans.values() for s in steps
           if s.pln and "provide_suppressive_fire_loc" in s.pln]
    assert sup
    # 좌표 기반 스크립트 태스크 — uuid 참조가 없어야 한다
    assert all(not s.refs for s in sup)
    assert all("targetLocation" in s.pln for s in sup)


def test_being_hit_produces_a_take_cover_task(spec):
    cover = [s for steps in spec.entity_plans.values() for s in steps
             if s.pln and "find_cover" in s.pln]
    assert cover
    for s in cover:
        assert s.template == "hitBy"
        assert s.refs, "Threat = 피격 원천 객체의 uuid"
        assert "StartingLocation" in s.pln


def test_assault_formation_move_follows_the_unit_leader(spec):
    follow = [(oid, s) for oid, steps in spec.entity_plans.items()
              for s in steps if s.pln and "follow-entity" in s.pln]
    assert follow
    leaders = {s.refs[0] for _, s in follow}
    uuids = {e.uuid: e.object_id for e in spec.entities}
    assert leaders <= set(uuids), "추종 대상이 실제 엔티티여야 한다"
    for oid, s in follow:
        assert uuids[s.refs[0]] != oid, "자기 자신을 추종하면 안 된다"


def test_supply_move_sets_speed_first(spec):
    """동반 행동은 task_kinds.csv의 선행_행동이 정한다(코드 특례가 아니다)."""
    for steps in spec.entity_plans.values():
        for i, s in enumerate(steps):
            if s.task_kind == "move_slow":
                assert i > 0 and steps[i - 1].action_label == "속도 지정"
                assert steps[i - 1].task_kind == "move_slow:속도 지정"
                assert "(speed 8.000000)" in steps[i - 1].pln


def test_watch_move_is_followed_by_a_direction_aiming_set(spec):
    """'감시 위치 이동 및 관측 방향 유지'는 두 블록을 낸다.

    이동만 저작하면 원문의 '관측 방향 유지'가 산출에서 사라진다. 이동 뒤에
    목적지 방위로 방향 조준(aiming-type 2)을 건다.
    """
    seen = 0
    for steps in spec.entity_plans.values():
        for i, s in enumerate(steps):
            if s.task_kind != "move_watch":
                continue
            seen += 1
            nxt = steps[i + 1]
            assert nxt.task_kind == "move_watch:방향 조준"
            assert "(aiming-type 2)" in nxt.pln
            assert "AZIMUTH_RAD" not in nxt.pln
    assert seen, "move_watch task가 하나도 없다"


def test_task_type_variety(spec):
    import re
    kinds = set()
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.pln:
                m = re.search(r'task-type "([^"]+)"|'
                              r'set-data-request-type "([^"]+)"', s.pln)
                kinds.add(m.group(1) or m.group(2))
    # 확장 전에는 4종. 방어 배치 이동을 통제점 이동(move-to)으로 돌리면서
    # move-to-location-task 한 종류가 전체의 45%를 먹던 편중이 풀렸다.
    assert len(kinds) >= 8, sorted(kinds)
    assert "move-to" in kinds, "방어 배치 이동은 통제점 이동으로 저작한다"


def test_no_single_task_type_dominates(spec):
    """한 task 종류가 전체의 3분의 1을 넘지 않는다.

    STKG 관계가 하나로 쏠리면 롱테일이 생겨 학습·평가가 그 하나만 본다.
    2026-08-09 이전에는 move-to-location-task가 436/974 = 45%였다.
    """
    import re
    from collections import Counter
    c = Counter()
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.pln:
                m = re.search(r'task-type "([^"]+)"|'
                              r'set-data-request-type "([^"]+)"', s.pln)
                c[m.group(1) or m.group(2)] += 1
    top, n = c.most_common(1)[0]
    assert n / sum(c.values()) < 1 / 3, (top, n, sum(c.values()), c.most_common())


def test_aim_becomes_a_direction_aiming_set(spec):
    """'포신 정렬'은 원문이 서술한 행위다. 표적이 정적 지점이라 객체 조준
    대신 방위·고각을 계산해 넣는 방향 조준(aiming-type 2)을 쓴다."""
    aims = [s for steps in spec.entity_plans.values() for s in steps
            if s.task_kind == "aim"]
    assert aims, "aim task가 하나도 없다"
    for s in aims:
        assert s.template == "aimAt", s.template
        if s.pln is None:
            # 저작하지 않은 aim은 최소사거리 미달뿐이다. 그 외에 pln이 비면
            # 템플릿·참조 결함이라 조용히 넘기면 안 된다.
            assert s.skip_reason == SKIP_MIN_RANGE, (s.event_id, s.skip_reason)
            assert s.issues, s.event_id
            continue
        assert '(set-data-request-type "set-aiming-point")' in s.pln
        assert "(aiming-type 2)" in s.pln
        assert "AZIMUTH_RAD" not in s.pln and "ELEVATION_RAD" not in s.pln


def test_aim_angles_are_real_radians(spec):
    """치환이 됐는지만이 아니라 값이 말이 되는지 본다."""
    import math
    import re
    azimuths = []
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.task_kind != "aim" or s.pln is None:
                continue
            az = float(re.search(r"\(aiming-azimuth ([-\d.]+)\)", s.pln).group(1))
            el = float(re.search(r"\(aiming-elevation ([-\d.]+)\)", s.pln).group(1))
            assert 0.0 <= az < 2 * math.pi, az
            assert -math.pi / 2 <= el <= math.pi / 2, el
            azimuths.append(az)
    assert azimuths, "검사한 aim task가 없다"
    # 전부 0이면 사수·표적 좌표가 같은 자리로 풀린 것이다
    assert any(az != 0.0 for az in azimuths)


def test_no_tactical_graphics_leak_beyond_firing_prep(spec):
    """통제점(= VR-Forces 전술 그래픽)은 find_firing_position 표적에만 쓰인다.

    전술 그래픽이 시나리오 로딩을 느리게 해서, find_fp 이외의 모든 태스크는
    통제점 uuid 대신 좌표를 직접 적는다(사용자 결정 2026-08-03). Task 5부터
    find_fp의 위협(정적 지점)만 예외다 — 조준·사격 대상을 실제로 찍어야 해서
    좌표만으로는 대체할 수 없다(2026-08-05). 2026-08-09부터 방어 배치 이동
    (`move_cp`)이 하나 더 붙는다 — '지정된 방어 위치로 간다'는 서술이라
    좌표가 아니라 통제점을 참조하고, 지도에 찍혀야 사람이 배치를 확인한다.
    """
    ALLOWED = {"find_fp", "move_cp"}
    ctl_uuids = {c.uuid for c in spec.control_objects}
    for oid, steps in spec.entity_plans.items():
        for s in steps:
            if s.task_kind in ALLOWED:
                continue
            assert "control-point" not in (s.pln or ""), f"{oid} {s.event_id}"
            for ref in s.refs:
                assert ref not in ctl_uuids, (oid, s.event_id, s.task_kind)


def test_move_tasks_carry_real_coordinates(spec):
    """좌표 이동 태스크에 자리표시자가 남아 있으면 안 된다."""
    moves = [s for steps in spec.entity_plans.values() for s in steps
             if s.pln and "move-to-location-task" in s.pln]
    assert moves
    for s in moves:
        assert "X Y Z" not in s.pln, s.event_id
        assert re.search(r"\(aiming-point\s+-?\d+\.\d+\s+-?\d+\.\d+\s+"
                         r"-?\d+\.\d+\)", s.pln), s.event_id


def test_uuids_are_unique(spec):
    uids = [e.uuid for e in spec.entities] + [c.uuid for c in spec.control_objects]
    assert len(uids) == len(set(uids))


def test_spec_is_deterministic(spec):
    other = _build()
    assert [(e.object_id, e.uuid, e.coord.as_tuple()) for e in spec.entities] == \
           [(e.object_id, e.uuid, e.coord.as_tuple()) for e in other.entities]
    assert [(c.ref_id, c.uuid) for c in spec.control_objects] == \
           [(c.ref_id, c.uuid) for c in other.control_objects]


def test_stop_and_stay_become_wait_tasks(spec):
    """'정지한다'·'잔류한다'는 원문이 서술한 행위다. 버리지 않는다."""
    waits = [(oid, s) for oid, steps in spec.entity_plans.items()
             for s in steps if s.task_kind == "wait"]
    assert waits, "wait task가 하나도 없다"
    for _, s in waits:
        assert s.template in ("stopAt", "stayAt"), s.template
        assert s.pln is not None, s.event_id
        assert '(task-type "wait-duration")' in s.pln
        assert "(seconds-to-wait" in s.pln


def test_wait_task_has_no_placeholder_left(spec):
    """참조 대상이 없는 kind라 치환할 자리도 없어야 한다."""
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.task_kind != "wait":
                continue
            for tok in ("TARGET_UUID", "ENTITY_UUID", "CONTROL_POINT_UUID",
                        "X Y Z", "SX SY SZ"):
                assert tok not in s.pln, (s.event_id, tok)
            assert s.refs == [], s.event_id


def test_firing_prep_becomes_find_firing_position(spec):
    """'사격 준비 대기 → 사격 준비'는 짝이 있는 전이지만 별개 행위로 남긴다.

    stateChange 계열 1,294건 중 745건은 같은 시각 같은 객체에 이미 task를
    내는 이벤트가 붙어 있어 중복이다(2026-08-05 재실측) — 이 전이는 그
    규칙의 예외다. 같은 시각·같은 객체·같은 원문 줄의 aimAt과 21/21 전부
    짝을 이루지만, 포신 정렬(aimAt → set-aiming-point)과 사격위치 확보(이
    전이 → find_firing_position)는 같은 순간을 말하는 서로 다른 두 행위라
    둘 다 task로 남긴다. 부작용: 조준이 재배치보다 먼저라 재배치 반경(100m)
    안에서 조준각이 몇 도 어긋난다 — 받아들인 대가다.
    """
    preps = [s for steps in spec.entity_plans.values() for s in steps
             if s.task_kind == "find_fp"]
    assert preps, "find_fp task가 하나도 없다"
    for s in preps:
        assert s.template == "stateChange", s.template
        assert s.pln is not None, s.event_id
        assert '(task-type "find_firing_position")' in s.pln
        assert "TARGET_UUID" not in s.pln, s.event_id
        assert s.refs, s.event_id


# 사격 준비 전이가 참조하는 정적 표적 7종(2026-08-05 실측).
FIRE_PREP_LOCATIONS = {
    "LOC_중앙킬존", "LOC_적포병진지", "LOC_적박격포진지", "LOC_적북측접근로",
    "LOC_남측제1방어선", "LOC_아군포병진지", "LOC_아군박격포진지",
}

# 방어 배치 이동(move_cp)의 목적지. 원문의 '방어선 재편성 이동'·'방어 위치
# 이동'이 가리키는 자리이고, 통제점으로 찍혀야 사람이 배치를 확인한다.
DEFEND_LOCATIONS = {
    "LOC_중앙킬존남측", "LOC_목표A남측", "LOC_중앙킬존",
    "LOC_동측능선", "LOC_서측능선",
}


def test_find_firing_position_threat_is_a_control_point(spec):
    """위협 대상이 정적 지점이라 통제점 uuid로 풀린다.

    2026-08-03에 통제점을 뺀 것은 배치 지명 29개를 전부 찍어 로딩이 느려졌기
    때문이다. 여기서 생기는 것은 실제로 조준·사격 대상이 되는 곳뿐이다.

    개수를 못 박지 않는다. 이 테스트의 _build()는 roster.json으로 명부를
    200객체로 줄이는데(파이프라인 02는 감축하지 않는다 — 328객체), 그래서
    여기서 보이는 통제점은 전체의 부분집합이다. 못 박으면 roster.json을
    건드릴 때마다 깨진다. 전체 목록은 04를 돌려 확인한다.
    """
    ctl = {c.uuid: c.ref_id for c in spec.control_objects}
    assert ctl, "통제점이 하나도 없다"
    for steps in spec.entity_plans.values():
        for s in steps:
            if s.task_kind != "find_fp":
                continue
            assert s.refs[0] in ctl, (s.event_id, s.refs)
    # 통제점이 사격 준비 표적·방어 배치 목적지 말고 다른 데서 새면 여기서 잡힌다.
    assert set(ctl.values()) <= FIRE_PREP_LOCATIONS | DEFEND_LOCATIONS, \
        sorted(ctl.values())


def test_no_task_objects_get_no_move_or_fire_after_that_line(spec):
    """원문이 'task를 부여하지 않는다'고 적은 객체를 지키고 있는가.

    2026-08-05 실측으로 그 시각 이후 이동·사격 이벤트가 0건이라 지금은
    강제 로직이 없어도 지켜진다. 원문이 바뀌어 어긋나면 여기서 잡는다.
    """
    import json
    from pathlib import Path
    jsonl = Path(__file__).resolve().parents[1] / "build" / "events" / "battle.jsonl"
    if not jsonl.exists():
        pytest.skip("build/events/battle.jsonl 없음 — 02를 먼저 실행")
    rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l]
    cutoff = {}
    for r in rows:
        if r["template"] == "noTask":
            cutoff.setdefault(r["actor"], r["time_s"])
    assert cutoff, "noTask 이벤트가 하나도 없다 — 원문이 바뀐 것이다"
    bad = [(oid, s.event_id, s.task_kind) for oid, steps in spec.entity_plans.items()
           if oid in cutoff
           for s in steps
           if s.time_s > cutoff[oid]
           and s.task_kind in ("move", "move_slow", "follow",
                               "fire_direct", "fire_indirect", "suppress")]
    assert bad == [], bad[:5]


def test_units_are_built_when_orbat_is_given(spec_with_orbat):
    spec = spec_with_orbat
    assert len(spec.units) == 67
    by_ech = {}
    for u in spec.units:
        by_ech[u.echelon] = by_ech.get(u.echelon, 0) + 1
    assert by_ech == {"소대": 52, "중대": 13, "대대": 2}


def _full_members(spec, uuid: str, platoon_members: dict) -> list:
    """부대 uuid → 예하 **전 구성원** object_id(소대는 자기 자신을 재귀 종료로).

    소대는 unit_of_entity로 바로 나오고, 중대·대대는 자식 부대(parent_uuid로
    연결됨)의 전 구성원을 이어붙여 재귀적으로 접어 올린다.
    """
    u = next(x for x in spec.units if x.uuid == uuid)
    if u.echelon == "소대":
        return list(platoon_members.get(uuid, []))
    kids = [x.uuid for x in spec.units if x.parent_uuid == uuid]
    out = []
    for k in kids:
        out += _full_members(spec, k, platoon_members)
    return out


def test_unit_coord_is_the_member_centroid(spec_with_orbat):
    """부대 위치 = 구성원 배치 좌표의 중심점(연구내용 §3.2).

    소대 하나만 보면 대대가 직할 소대만 반영하고 예하 중대 구성원을 놓치는
    버그(2026-08-17 리뷰에서 실측: 42m 오차)를 못 잡는다. 소대·중대·대대
    전부를, 각 부대의 예하 전 구성원 기준으로 검사한다.
    """
    spec = spec_with_orbat
    coords = {e.object_id: e.coord for e in spec.entities}
    platoon_members: dict[str, list[str]] = {}
    for oid, uu in spec.unit_of_entity.items():
        platoon_members.setdefault(uu, []).append(oid)

    seen_echelons = set()
    for u in spec.units:
        members = _full_members(spec, u.uuid, platoon_members)
        assert members, u.unit_id
        lat = sum(coords[o].lat for o in members) / len(members)
        lon = sum(coords[o].lon for o in members) / len(members)
        assert abs(u.coord.lat - lat) < 1e-9, u.unit_id
        assert abs(u.coord.lon - lon) < 1e-9, u.unit_id
        seen_echelons.add(u.echelon)
    assert seen_echelons == {"소대", "중대", "대대"}


def test_company_centroid_differs_from_average_of_platoon_centroids(spec_with_orbat):
    """중대 좌표는 소대 중심점들의 평균이 아니라, 예하 전 구성원의 중심점이다.

    소대 인원이 같으면 두 값이 우연히 일치할 수 있으므로, 인원이 다른 소대를
    둔 중대를 찾아서 확인한다 — 이 계약을 지키지 않으면 값이 갈리지 않는다.
    """
    spec = spec_with_orbat
    platoon_members: dict[str, list[str]] = {}
    for oid, uu in spec.unit_of_entity.items():
        platoon_members.setdefault(uu, []).append(oid)

    checked = False
    for co in spec.units:
        if co.echelon != "중대":
            continue
        kids = [u for u in spec.units if u.parent_uuid == co.uuid]
        sizes = {len(platoon_members.get(k.uuid, [])) for k in kids}
        if len(kids) < 2 or len(sizes) < 2:
            continue
        naive_lat = sum(k.coord.lat for k in kids) / len(kids)
        assert abs(co.coord.lat - naive_lat) > 1e-6, co.unit_id
        checked = True
    assert checked, "인원이 다른 소대를 둔 중대를 찾지 못했다 — 이 테스트가 아무것도 못 지킨다"


def test_every_entity_maps_to_a_platoon_uuid(spec_with_orbat):
    spec = spec_with_orbat
    assert set(spec.unit_of_entity) == {e.object_id for e in spec.entities}
