import re
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout, Coord, ground_distance
from vtmak.paths import SCENARIO
from vtmak.parser import Event, PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, EntityDef, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.engagements import ActorClock, EnrichmentConfig
from vtmak.scnx.ids import IdAllocator
from vtmak.scnx.placement import PlacementRules, build_headings, build_positions
from vtmak.scnx.plan import SKIP_MIN_RANGE, balanced, build_entity_plan
from vtmak.scnx.spec import _Ctx, build_spec

ROOT = Path(__file__).resolve().parents[1]


def _build(inputs):
    # enrichment_config를 안 주면 spec.engagement_slots가 source 77건뿐이라
    # 이 파일의 20~30건 보강 단언이 전부 빈 집합을 본다.
    return build_spec(**inputs, enrichment_config=EnrichmentConfig.defaults())


def _parse_build_inputs() -> dict:
    """원문을 처음부터 다시 파싱·명부 감축해 build_spec 인자 9개를 만든다.

    호출할 때마다 SCENARIO를 새로 읽고 새로 파싱한다 — 캐시하지 않는다.
    full_build_inputs 픽스처(모듈 스코프, 한 번만 파싱)와 test_spec_is_
    deterministic(두 번째 독립 파싱이 필요하다, 아래 참고)가 이 하나를
    공유해서 두 구성 경로가 갈라지지 않게 한다.
    """
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
    return dict(events=events, registry=reg, layout=lay, pattern_map=pm,
               catalog=TaskCatalog.load(cfg / "task_catalog.csv"),
               kinds=TaskKinds.load(cfg / "task_kinds.csv"),
               dis=DisCatalog.load(cfg / "dis_catalog.csv"),
               ranges=WeaponRanges.load(cfg / "weapon_ranges.csv"),
               scenario_id="battle")


@pytest.fixture(scope="module")
def full_build_inputs():
    """_build()가 build_spec에 넘기는 인자들을 dict로 돌려준다(한 번만 파싱)."""
    return _parse_build_inputs()


@pytest.fixture(scope="module")
def spec(full_build_inputs):
    return _build(full_build_inputs)


def test_spec_contains_source_and_enrichment_slots(spec):
    source = [s for s in spec.engagement_slots if s.origin == "source"]
    added = [s for s in spec.engagement_slots if s.origin == "enrichment"]
    assert len(source) == 77
    assert 20 <= len(added) <= 30
    assert len({(s.shooter_id, s.target_id) for s in added}) == len(added)


def test_expected_suppressive_spo_clears_the_threshold(spec):
    from vtmak.scnx.engagements import expected_suppress_spo
    assert len(expected_suppress_spo(tuple(spec.engagement_slots))) >= 70


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
    #
    # MO-120RT-61 Mortar는 Task 5에서 새로 추가된다(2026-08-27). FR-MORT-004는
    # aim·fire_indirect가 최소사거리 미달로 원래도 실패하고, 남은 유일한
    # 이벤트가 사격 준비 전이였다 — 예전엔 find_fp가 사거리 검사 없이 항상
    # 저작돼(그래도 VR-Forces에서 21/21 실패) 표면적으로만 안 비어 보였다.
    # move_firing_position은 견인 박격포의 move-to-location-task 컨트롤러
    # 부재를 정직하게 report하므로 이제 플랜이 실제로 빈다 — 실제 실행 능력은
    # 달라지지 않았다(전이든 후든 이 객체는 VR-Forces에서 아무것도 안 한다).
    assert empty == {"ZPU-4 AA Gun", "MO-120RT-61 Mortar"}, empty


def test_no_synthesised_plan_steps(spec):
    # 플랜 보강을 제거했으므로 원문 이벤트가 아닌 스텝이 있으면 안 된다 —
    # 단, 교전 슬롯 lowering(build_engagement_steps)이 만드는 이동·대기·
    # 직접사격·제압사격 네 단계는 예외다. 이 넷은 slot_id로 표시되고
    # event_id는 원문 event_id가 아니라 슬롯 id(SRC-*)를 쓴다(설계 §5) —
    # 한 슬롯의 네 단계를 event_id 하나로 묶어 봐야 하기 때문이다.
    for steps in spec.entity_plans.values():
        for s in steps:
            assert s.event_id.startswith("E") or s.slot_id, s


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


def test_every_source_direct_fire_is_followed_by_suppressive_fire(spec):
    """원문 directFireAt 77건은 대체가 아니라 순서다 — 직접사격 다음에
    반드시 같은 슬롯의 제압사격이 붙는다(설계 §5)."""
    pairs = []
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        for i, step in enumerate(live[:-1]):
            if step.task_kind != "fire_direct":
                continue
            nxt = live[i + 1]
            assert nxt.task_kind == "suppress", (oid, step.event_id)
            assert nxt.slot_id == step.slot_id
            pairs.append((step, nxt))
    assert len([p for p in pairs if p[0].slot_id.startswith("SRC-")]) == 77


def test_suppressive_step_uses_bounded_duration_and_ammo(spec):
    suppress = [s for steps in spec.entity_plans.values() for s in steps
                if s.task_kind == "suppress" and s.pln]
    assert suppress
    for step in suppress:
        assert "(durationRapid 5.000000)" in step.pln
        assert "(durationTotal 10.000000)" in step.pln
        assert "(ammoLimit 10)" in step.pln


def test_slot_preparation_steps_come_before_the_direct_fire(spec):
    # 이동·대기는 사격 앞에만 붙는다. 사격과 제압 사이에 끼면 두 관측이
    # 다른 교전으로 갈라진다.
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        for slot_id in {s.slot_id for s in live if s.slot_id}:
            block = [s for s in live if s.slot_id == slot_id]
            kinds = [s.task_kind for s in block]
            assert kinds[-2:] == ["fire_direct", "suppress"], (oid, slot_id)
            assert set(kinds[:-2]) <= {"move", "wait"}, (oid, slot_id)


def test_every_wait_task_is_bounded_and_substituted(spec):
    waits = [s for steps in spec.entity_plans.values() for s in steps
             if s.pln and 'task-type "wait-duration"' in s.pln]
    assert waits
    for step in waits:
        m = re.search(r"\(seconds-to-wait ([-\d.]+)\)", step.pln)
        assert m, step.event_id
        assert 0.0 < float(m.group(1)) <= 3600.0, step.event_id


def test_being_hit_produces_a_take_cover_move(spec):
    """find_cover(다수 모델 컨트롤러 비활성 실측)를 좌표 이동으로 대체한다
    (Task 5). 원래 의도는 script task가 아니라 planned_intent/intent_object에
    남는다 — GT에는 안 나가는 계획 메타데이터다. 저작 여부와 무관하게 남는다.

    max_cover_move_m=400.0(2026-08-27 실측으로 100.0에서 조정 — golden
    지점 21개의 간격이 246~832m라 100m로는 아예 저작되지 않았다)과 반원형
    고리 배치(같은 지점, 리뷰 라운드 1)로 hitBy 77건 중 52건이 저작되고
    25건이 skip_reason=no_verified_position이다(이동예산·이격을 오프셋
    좌표까지 재검증하며 실측). '전부 스킵'이던 시절의 가드 부재를 되돌리지
    않도록 저작된 단계가 실제로 있는지 먼저 확인한다 — live가 조용히
    0으로 돌아가면 이 assert가 먼저 잡는다.
    """
    cover = [s for steps in spec.entity_plans.values() for s in steps
             if s.task_kind == "move_cover"]
    assert cover
    live = [s for s in cover if s.pln]
    assert live, "move_cover 중 저작된 단계가 하나도 없다"
    for s in live:
        assert s.template == "hitBy"
        assert s.planned_intent == "takes_cover_from"
        assert s.intent_object, "Threat = 피격 원천 객체"
        assert '(task-type "move-to-location-task")' in s.pln
        assert "X Y Z" not in s.pln
        assert "find_cover" not in s.pln
    for s in cover:
        if not s.pln:
            assert s.skip_reason == "no_verified_position", s.event_id
            assert s.planned_intent == "takes_cover_from"
            assert s.intent_object


def test_cover_move_is_followed_by_an_orientation_toward_the_threat(spec):
    """엄폐 이동에 성공한 뒤에는 위협 쪽으로 방향 조준한다(리뷰 라운드 1).

    move_watch와 같은 후행_행동 칸('방향 조준')을 쓰지만 기준점이 다르다 —
    move_watch는 출발 지점에서 목적지를 볼 때의 방위를, move_cover는 도착한
    엄폐 좌표에서 위협을 볼 때의 방위를 쓴다. 저작되지 못한
    (no_verified_position) move_cover는 목적지 자체가 없어 이 동반 행동도
    붙지 않는다 — 저작된 것만 확인한다.
    """
    seen = 0
    for steps in spec.entity_plans.values():
        for i, s in enumerate(steps):
            if s.task_kind != "move_cover" or not s.pln:
                continue
            seen += 1
            nxt = steps[i + 1]
            assert nxt.task_kind == "move_cover:방향 조준"
            assert "(aiming-type 2)" in nxt.pln
            assert "AZIMUTH_RAD" not in nxt.pln and "ELEVATION_RAD" not in nxt.pln
    assert seen, "저작된 move_cover task가 하나도 없다"


def test_cover_move_substitutes_the_chosen_point_not_the_threat():
    """엄폐 이동이 위협 쪽으로 새는 회귀를 실제로 잡는다.

    'move task가 있다'만 확인하면 X Y Z에 위협의 좌표가 들어가도 통과한다
    (Task 5 브리프의 CRITICAL 경고 — ctx.ref_kind(threat)를 따라 _fill로
    가면 X Y Z에 ctx.coord_of(threat)가 들어가 위협 쪽으로 이동해버린다).
    실제 spec에도 저작된 move_cover가 있지만(52/77,
    test_being_hit_produces_a_take_cover_move), 여기서는 choose_cover_location
    이 분명히 다른 좌표를 고르는 스텁 ctx로 build_entity_plan을 직접 불러
    확인한다 — 실제 시나리오의 배치·설정에 좌우되지 않는 결정적 회귀
    테스트를 원해서다(예: config가 다시 바뀌어 저작률이 흔들려도 이 테스트는
    그대로 서 있어야 한다). 저작된 .pln에 박히는 좌표가 위협의 좌표가 아니라
    정확히 선택된 엄폐 좌표인지 본다.
    """
    cfg = ROOT / "config"
    kinds = TaskKinds.load(cfg / "task_kinds.csv")
    catalog = TaskCatalog.load(cfg / "task_catalog.csv")
    ranges = WeaponRanges.load(cfg / "weapon_ranges.csv")
    pm = PatternMap.load(cfg / "pattern_map.csv")
    entity = EntityDef("FR-VICTIM", "US Army M4", "소총수", "BLUE",
                       "보병 - 소총(M4 계열)", ("M4 rifle",), "LOC_A",
                       "기동 또는 사격 가능", True)

    threat_coord = Coord(21.0, 105.0, 0.0)
    cover_coord = Coord(21.001, 105.001, 10.0)   # 위협과 뚜렷이 다른 좌표
    assert cover_coord.to_ecef() != threat_coord.to_ecef()

    class _StubCtx:
        def entity_uuid(self, object_id):
            return None

        def ref_uuid(self, ref):
            return ""

        def coord_of(self, ref, time_s=-1, actor=""):
            return threat_coord

        def actor_coord(self, actor, time_s, src=""):
            return threat_coord

        def ref_kind(self, ref):
            return "ENTITY"

        def unit_leader(self, object_id):
            return None

        def choose_firing_location(self, entity_class, shooter, target):
            return None

        def choose_cover_location(self, actor, actor_coord, threat_coord):
            return "LOC_COVER", cover_coord

    events = [Event("E1", 10, 1, "hitBy", "hitBy", actor="FR-VICTIM",
                    source_obj="EN-THREAT", location="LOC_A")]
    enrich = EnrichmentConfig.defaults()
    steps = build_entity_plan(events, entity, pm, catalog, kinds, ranges,
                              _StubCtx(), {}, {}, ActorClock(0, enrich),
                              enrich)
    live = [s for s in steps if s.pln]
    assert live and live[0].task_kind == "move_cover"
    x, y, z = cover_coord.to_ecef()
    assert f"{x:.6f} {y:.6f} {z:.6f}" in live[0].pln
    tx, ty, tz = threat_coord.to_ecef()
    assert f"{tx:.6f} {ty:.6f} {tz:.6f}" not in live[0].pln


def test_shared_cover_point_spreads_entities_in_bounded_rings():
    """이격은 지점 선택 필터가 아니라 배치 규칙이다(2026-08-27, 세 번째 정정).

    같은 golden 지점을 고른 여러 객체는 반원형 고리(리뷰 라운드 1, 네 번째
    정정)로 벌어진다 — 군집 크기 n에 비례(직선 벌림, 폐기됨)가 아니라
    sqrt(n)에 비례해 자란다. 여섯 명을 같은 지점에 배정해 고리 1(용량 3)을
    채우고 고리 2로 넘어가는 경계를 지나면서: (a) 모두 같은 ref를 받고,
    (b) 모든 쌍의 상호 거리가 min_entity_separation_m 이상이며(인접한
    쌍만이 아니라 전부 — 직선 벌림 시절의 '한 축 위 좌우 교대'와 달리 고리
    위의 인접하지 않은 두 자리도 서로 이 최소 거리를 지켜야 한다), (c) 각자
    자기 시작점보다 위협에서 더 멀고, (d) 여섯 번째의 지점 이탈 거리가 직선
    벌림이었다면 나왔을 5*min_sep=75m보다 훨씬 작다는 것을 확인한다.
    """
    layout = BattlefieldLayout({"locations": {
        "LOC_COVER": {"lat": 21.0, "lon": 105.0 - 250.0 / 103_900.0,
                     "src": "golden"}}})
    threat_coord = Coord(21.0, 105.0, 0.0)
    actor_coord = Coord(21.0, 105.0 + 104.0 / 103_900.0, 0.0)
    ctx = _Ctx(layout, IdAllocator("test"), {}, {}, [], WeaponRanges(),
              EnrichmentConfig.defaults())
    current = ground_distance(actor_coord, threat_coord)
    min_sep = EnrichmentConfig.defaults().min_entity_separation_m

    picks = [ctx.choose_cover_location(f"E{i}", actor_coord, threat_coord)
            for i in range(6)]
    assert all(p is not None for p in picks), picks
    refs = [ref for ref, _ in picks]
    coords = [coord for _, coord in picks]
    assert len(set(refs)) == 1 and refs[0] == "LOC_COVER"
    assert coords[0] == layout.coord("LOC_COVER"), "k=0은 지점 그 자체다"

    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            sep = ground_distance(coords[i], coords[j])
            assert sep >= min_sep - 1e-3, (i, j, sep)

    for coord in coords:
        assert ground_distance(coord, threat_coord) > current

    worst_offset = max(ground_distance(layout.coord("LOC_COVER"), c)
                       for c in coords)
    assert worst_offset < 5 * min_sep, worst_offset


def test_cover_assignments_respect_budget_bearing_and_separation_on_the_real_build():
    """Finding 1의 재검증(리뷰 라운드 1)이 실제 시나리오에서 지켜지는지 본다.

    바로 위 합성 테스트는 golden 지점 하나짜리 레이아웃이라 이동예산·전장
    경계와는 무관하다 — 리뷰가 정확히 짚은 대로, 예전 Measurement 3도
    이격·위협 이격 증가만 봤지 이동예산이나(직선 벌림이 375m까지 밀어냈다)
    '어느 지점에 배정됐는가'는 보지 않았다. 여기서는 build_spec이 쓰는
    것과 같은 real layout·registry·roster로 _Ctx를 만들어 hitBy 77건
    전부를 실제와 같은 순서(액터 id 정렬)로 돌리고, choose_cover_location이
    돌려주는 좌표 자체에 세 성질을 전부 건다: 이동예산 이내, 자기 위협
    대비 이격 증가, 같은 지점에 이미 배정된 다른 목적지와 최소 이격.
    """
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(SCENARIO.read_text(encoding="utf-8"), pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    task_ids = {e.event_id for e in res.events
               if pm.task_kind_of(e) not in ("", "noop")}
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"),
                         task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}

    ids = IdAllocator("battle")
    taskable = {oid: d for oid, d in sorted(reg.items()) if d.taskable}
    entity_uuids = {oid: ids.alloc("entity", oid) for oid in taskable}
    rules = PlacementRules.load(cfg / "placement_rules.csv")
    headings = build_headings(taskable, events, lay)
    coords = build_positions(taskable, lay, rules, headings)
    ranges = WeaponRanges.load(cfg / "weapon_ranges.csv")
    enrich = EnrichmentConfig.load(cfg / "engagement_enrichment.json")
    ctx = _Ctx(lay, ids, reg, entity_uuids, events, ranges, enrich, coords)

    hitby = [e for e in events
            if e.template == "hitBy" and e.actor and e.source_obj]
    assert hitby, "hitBy 이벤트가 하나도 없다"

    by_point: dict[str, list[Coord]] = {}
    authored = 0
    for e in sorted(hitby, key=lambda x: x.actor):
        actor_coord = ctx.actor_coord(e.actor, e.time_s, e.src)
        threat_coord = ctx.coord_of(e.source_obj, e.time_s)
        loc = ctx.choose_cover_location(e.actor, actor_coord, threat_coord)
        if loc is None:
            continue
        authored += 1
        ref, coord = loc
        assert ground_distance(actor_coord, coord) <= enrich.max_cover_move_m, (
            e.actor, ground_distance(actor_coord, coord))
        assert ground_distance(coord, threat_coord) > ground_distance(
            actor_coord, threat_coord), (e.actor, "not farther than start")
        for other in by_point.get(ref, []):
            sep = ground_distance(coord, other)
            assert sep >= enrich.min_entity_separation_m - 1e-3, (
                e.actor, ref, sep)
        by_point.setdefault(ref, []).append(coord)

    # 회귀 가드: 52/77이 조용히 다시 무너져 두 자릿수 밑으로 떨어지면 여기서
    # 잡는다(이 assert가 실패해도 위 세 성질 자체는 이미 개별적으로 검증됐다).
    assert authored >= 40, (authored, len(hitby))


def test_assault_formation_move_lowers_to_a_plain_move(spec):
    """공격 대형 이동(follow)은 이 시나리오에서 전부 후속 task를 가진다
    (2026-08-27 실측: follow로 매핑되는 115건 전원). follow-entity는 끝나는
    시각을 몰라 뒤에 큐를 둔 task가 영영 실행되지 않으므로, 종단이 아닌
    follow는 컴파일 시점에 원래 dst로 향하는 평범한 이동으로 내려간다 —
    그래서 이 시나리오의 최종 PLN에는 follow-entity가 하나도 남지 않는다.
    선두 uuid 해석·자기참조 금지 자체는 아래
    test_terminal_follow_resolves_the_unit_leader_and_never_self가 합성
    이벤트로 직접 검증한다(이 데이터셋에는 종단 follow 사례가 없다).
    """
    lowered = [s for steps in spec.entity_plans.values() for s in steps
              if s.pln and s.template == "moveTo" and s.task_kind == "move"]
    assert lowered
    assert all("follow-entity" not in s.pln for s in lowered)


def test_terminal_follow_resolves_the_unit_leader_and_never_self():
    """종단 follow(뒤에 아무 task도 없는)만 follow-entity로 남고, 참조는
    실제 부대 선두 uuid지 자기 자신이 아니다. 이 저장소의 실제 시나리오는
    follow 115건 전부가 후속 task를 가져(위 테스트) 이 경로를 밟지 않으므로,
    build_entity_plan을 작은 합성 이벤트로 직접 불러 확인한다 — 하나는
    선두 없이 마지막이라 follow로 남고, 하나는 뒤에 task가 있어 move로
    내려간다(원래 dst 사용).
    """
    cfg = ROOT / "config"
    kinds = TaskKinds.load(cfg / "task_kinds.csv")
    catalog = TaskCatalog.load(cfg / "task_catalog.csv")
    ranges = WeaponRanges.load(cfg / "weapon_ranges.csv")
    entity = EntityDef("FR-TERM", "US Army M4", "소총수", "BLUE",
                       "보병 - 소총(M4 계열)", ("M4 rifle",), "LOC_A",
                       "기동 또는 사격 가능", True)
    fixed_coord = Coord(21.0, 105.0, 0.0)

    class _StubCtx:
        def entity_uuid(self, object_id):
            return "lead-0001" if object_id == "FR-LEAD" else None

        def ref_uuid(self, ref):
            return ""

        def coord_of(self, ref, time_s=-1, actor=""):
            return fixed_coord

        def actor_coord(self, actor, time_s, src=""):
            return fixed_coord

        def ref_kind(self, ref):
            return "ENTITY"

        def unit_leader(self, object_id):
            return "FR-LEAD"

        def choose_firing_location(self, entity_class, shooter, target):
            return None

        def choose_cover_location(self, actor, actor_coord, threat_coord):
            return None

    ctx = _StubCtx()
    enrich = EnrichmentConfig.defaults()
    pm = PatternMap.load(cfg / "pattern_map.csv")

    # 종단 follow: FR-TERM의 마지막(그리고 유일한) 이벤트다.
    terminal_events = [Event("E1", 10, 1, "moveTo", "moveTo", actor="FR-TERM",
                             dst="LOC_B", action_label="공격 대형 이동")]
    terminal_steps = build_entity_plan(
        terminal_events, entity, pm, catalog, kinds, ranges, ctx, {}, {},
        ActorClock(0, enrich), enrich)
    live = [s for s in terminal_steps if s.pln]
    assert live and 'task-type "follow-entity"' in live[0].pln
    assert live[0].refs == ["lead-0001"]
    assert "lead-0001" != entity.object_id

    # 후속 task가 있는 follow: 원래 dst(LOC_A)로 향하는 이동으로 내려간다.
    lowered_events = [
        Event("E2", 10, 2, "moveTo", "moveTo", actor="FR-TERM", dst="LOC_A",
             action_label="공격 대형 이동"),
        Event("E3", 20, 3, "stopAt", "stopAt", actor="FR-TERM",
             location="LOC_A"),
    ]
    lowered_steps = build_entity_plan(
        lowered_events, entity, pm, catalog, kinds, ranges, ctx, {}, {},
        ActorClock(0, enrich), enrich)
    move_step = lowered_steps[0]
    assert move_step.task_kind == "move"
    assert "follow-entity" not in (move_step.pln or "")
    assert 'task-type "move-to-location-task"' in move_step.pln


def test_unbounded_follow_is_terminal(spec):
    """follow-entity는 끝나는 시각을 모른다(설계 §7) — 뒤에 task를 두면 그
    task는 영영 실행되지 않는다. 후속 task가 있는 follow는 컴파일 시점에
    평범한 이동으로 내려야 하고, follow로 남는 것은 정말 마지막인 것뿐이다.
    """
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        for i, step in enumerate(live):
            if 'task-type "follow-entity"' in step.pln:
                assert i == len(live) - 1, (oid, step.event_id,
                                            live[i + 1].event_id)


def test_find_tasks_are_lowered_to_moves_with_intent(spec):
    """find_firing_position(21/21 실패)·find_cover(다수 모델 실패)는 최종
    PLN 어디에도 없어야 한다. 원래 의도는 버려지지 않고 planned_intent/
    intent_object에 남는다(GT에는 안 나가는 계획 메타데이터).

    브리프 원안대로 intents를 live(=pln 있는) 단계에서만 모은다. 리뷰
    라운드 1 이전에는 이 범위를 전체 단계로 넓혀 뒀었다 — max_cover_move_m
    =100.0이던 시절 hitBy 77건 전부가 no_verified_position이라 저작된
    move_cover가 하나도 없었기 때문이다. 지금은 400.0 + 반원형 고리
    배치로 52/77이 저작되므로(test_being_hit_produces_a_take_cover_move)
    live 범위로 되돌린다 — 그래야 move_cover 저작이 다시 0으로 회귀해도
    이 assert가 잡는다(전체 단계로 넓혀 두면 no_verified_position 단계의
    planned_intent만으로도 통과해 회귀를 놓친다).
    """
    live = [s for steps in spec.entity_plans.values() for s in steps if s.pln]
    assert all('task-type "find_firing_position"' not in s.pln for s in live)
    assert all('task-type "find_cover"' not in s.pln for s in live)
    intents = {s.planned_intent for s in live if s.planned_intent}
    assert {"takes_firing_position_against", "takes_cover_from"} <= intents
    assert all(s.intent_object for s in live if s.planned_intent)


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


def test_no_task_family_dominates(spec):
    """'어딘가로 이동한다'는 하나의 관계 부류(move-to-location-task +
    move-to)가 전체의 58%를 넘지 않는다.

    test_no_single_task_type_dominates(바로 아래)는 task-type 하나만 본다
    — 그런데 move-to-location-task와 move-to는 둘 다 '어딘가로 간다'는
    같은 관계의 서로 다른 문법일 뿐이다. 2026-08-09에 move-to-location-task
    45%를 move-to로 갈라 "고쳤을" 때 실제로 한 일은 관계를 다양화한 게
    아니라 이동을 두 회계 항목으로 나눈 것이었다 — 단일 타입 지표는 그걸
    개선으로 읽는다. 리뷰 라운드 1(2026-08-27)이 이 결함을 지적했다.

    58%는 리뷰 지시대로 이번 라운드의 다른 변경(엄폐 뒤 방향 조준
    후행_행동 배선) *이전*, 즉 Finding 1~4를 반영한 상태에서 잰 값
    608/1089 = 55.83%에 여유를 둔 것이다. 방향 조준 배선은 이동이 아닌
    task를 더해 오히려 비율을 낮춘다(당시 실측 608/1141 = 53.29%) — 그
    변경이 이 한도를 통과시키려고 골라진 게 아님을 한도를 먼저 고정해
    보장한다.

    Task 6(2026-08-27)이 신규 교전 25건을 슬롯으로 얹은 뒤 재측정:
    613/1221 = 50.20%. fire-at-target·provide_suppressive_fire_loc이
    77→102로 늘고 wait-duration도 늘어(새 슬롯의 대기) move류 비중이
    오히려 더 내려갔다 — 58% 한도를 옮길 필요가 없다.
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
    total = sum(c.values())
    family = c.get("move-to-location-task", 0) + c.get("move-to", 0)
    assert family / total < 0.58, (family, total, c.most_common())


def test_no_single_task_type_dominates(spec):
    """한 task 종류가 전체의 37%를 넘지 않는다.

    STKG 관계가 하나로 쏠리면 롱테일이 생겨 학습·평가가 그 하나만 본다.

    임계값 이력: 2026-08-09 이전 move-to-location-task 436/974 = 45%가
    원래 문제였다. 그 직후 1/3(33%)로 좁혔고, Task 5(2026-08-27)가
    find_firing_position·find_cover를 없애면서 34.5%(358/1037)로 살짝
    올라 35%로 재조정했다.

    엄폐 배치가 병리적으로 무너져(리뷰 라운드 1 이전) 2/77만 저작되던
    상태의 실측은 34.65%(360/1039)로 35% 한도 안이었다. 거기서 74/77까지
    회복시킨 뒤 실측한 38.88%(432/1111)를 근거로 40%까지 재조정했었는데,
    이건 틀렸다 — Δtop=+72, Δtotal=+72로 그 상승 전부가 되살린 74건의
    엄폐 이동이지, find_firing_position·find_cover를 별개 task-type에서
    뺀 효과가 아니었다(그 효과는 34.65%로 이미 반영이 끝나 있었다).
    "사격 준비 관측 블록이 77건에서 154건으로 두 배가 된다"는 근거도
    Task 4의 성과이고 이미 이 태스크의 베이스 커밋에 들어 있었다 — 다른
    태스크의 성과를 이 태스크 것으로 잘못 돌린 것이었다. 40%는 리뷰에서
    취소한다.

    같은 리뷰가 지적한 진짜 결함(반원형 고리로 이동예산을 재검증하지 않고
    선형으로 벌리던 것)을 고치자 저작률이 52/77로 낮아졌고, 엄폐 뒤 방향
    조준 후행_행동을 배선하면서(비-이동 task 추가) 최종 실측은
    35.93%(410/1141)다 — 원래 35% 한도에서 1포인트 안쪽이다. 그 위에
    여유를 둬 37%로 잡는다. 두 번째로 이 값을 옮기는 것이라 다음 사람이
    또 조용히 옮기지 않도록 근거를 여기 전부 남긴다.

    실측 전체 분포(2026-08-27, 리뷰 라운드 1 마지막 재측정):
      move-to-location-task        410
      wait-duration                 256
      move-to                       198
      set-aiming-point                89
      fire-at-target                  77
      provide_suppressive_fire_loc    77
      ffe-on-location                 17
      set-speed                       17
      합계                          1141 → top 비율 410/1141 = 35.93%

    move-to-location-task와 move-to를 하나로 보는 진짜 의미 있는 지표는
    바로 위 test_no_task_family_dominates다. 여기 37%는 저작 단계에서
    45%로 되돌아가는 뻔한 회귀만 잡는 하한선이지 영구 목표가 아니다.
    정직한 측정은 VR-Forces 실행 뒤의 GT 수준 분포이고, Task 10의 수락
    단계가 그걸 모은다.

    Task 6(2026-08-27)이 신규 교전 25건(직접·제압사격 각 25건, 대기·이동
    포함)을 슬롯으로 얹은 뒤 재측정: 415/1221 = 33.99% — fire-at-target·
    provide_suppressive_fire_loc이 77→102로 함께 늘어 top 비율은 오히려
    내려갔다. 37% 한도를 옮길 필요가 없다.
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
    assert n / sum(c.values()) < 0.37, (top, n, sum(c.values()), c.most_common())


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
    """통제점(= VR-Forces 전술 그래픽)은 방어 배치 이동에만 쓰인다.

    전술 그래픽이 시나리오 로딩을 느리게 해서, move_cp 이외의 모든 태스크는
    통제점 uuid 대신 좌표를 직접 적는다(사용자 결정 2026-08-03). Task 5부터
    find_fp가 사라졌다 — 사격위치 확보를 좌표 이동으로 내리면서 통제점 uuid가
    더는 필요 없어졌다(2026-08-27). 2026-08-09부터 남아 있는 유일한 예외는
    방어 배치 이동(`move_cp`)이다 — '지정된 방어 위치로 간다'는 서술이라
    좌표가 아니라 통제점을 참조하고, 지도에 찍혀야 사람이 배치를 확인한다.
    """
    ALLOWED = {"move_cp"}
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
    # full_build_inputs를 재사용하면 build_spec의 입력 불변성(events를
    # 바꾸지 않는가)만 검증하고, 파싱·명부 감축까지 포함한 진짜 결정성은
    # 놓친다 — 두 번째 실행은 처음부터 다시 파싱한다(Task 6 리뷰 라운드 1
    # minor: fixture 리팩터로 이 커버리지가 조용히 좁아졌었다).
    other = _build(_parse_build_inputs())
    assert [(e.object_id, e.uuid, e.coord.as_tuple()) for e in spec.entities] == \
           [(e.object_id, e.uuid, e.coord.as_tuple()) for e in other.entities]
    assert [(c.ref_id, c.uuid) for c in spec.control_objects] == \
           [(c.ref_id, c.uuid) for c in other.control_objects]


def test_stop_and_stay_become_wait_tasks(spec):
    """'정지한다'·'잔류한다'는 원문이 서술한 행위다. 버리지 않는다.

    교전 슬롯의 대기(slot_id가 있는 wait)는 원문 stopAt/stayAt이 아니라
    사격 시각을 맞추려고 build_engagement_steps가 합성한 것이다 — 그 계약은
    test_every_wait_task_is_bounded_and_substituted가 별도로 검증한다.
    """
    waits = [(oid, s) for oid, steps in spec.entity_plans.items()
             for s in steps if s.task_kind == "wait" and not s.slot_id]
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


def test_firing_prep_becomes_a_coordinate_move(spec):
    """'사격 준비 대기 → 사격 준비'는 짝이 있는 전이지만 별개 행위로 남긴다.

    stateChange 계열 1,294건 중 745건은 같은 시각 같은 객체에 이미 task를
    내는 이벤트가 붙어 있어 중복이다(2026-08-05 재실측) — 이 전이는 그
    규칙의 예외다. 같은 시각·같은 객체·같은 원문 줄의 aimAt과 21/21 전부
    짝을 이루지만, 포신 정렬(aimAt → set-aiming-point)과 사격위치 확보는
    같은 순간을 말하는 서로 다른 두 행위라 둘 다 남긴다.

    find_firing_position은 2026-08 실측 21/21 실패(컨트롤러 비활성)라
    좌표 이동으로 대체한다(Task 5) — 원래 의도는 planned_intent/
    intent_object에 남는다. 견인 장비(포병 - 박격포·미사일 발사대 - Patriot
    일부)는 move-to-location-task 자체도 컨트롤러가 없어(entity_class_map.csv)
    skip_reason=unsupported_task로 저작되지 않을 수 있다 — 그래서 저작된
    것만 골라 pln 내용을 검사한다.
    """
    preps = [s for steps in spec.entity_plans.values() for s in steps
             if s.task_kind == "move_firing_position"]
    assert preps, "move_firing_position task가 하나도 없다"
    live = [s for s in preps if s.pln]
    assert live, "move_firing_position 중 저작된 단계가 하나도 없다"
    for s in live:
        assert s.template == "stateChange", s.template
        assert '(task-type "move-to-location-task")' in s.pln
        assert "X Y Z" not in s.pln, s.event_id
        assert s.planned_intent == "takes_firing_position_against"
        assert s.intent_object, s.event_id


# 방어 배치 이동(move_cp)의 목적지. 원문의 '방어선 재편성 이동'·'방어 위치
# 이동'이 가리키는 자리이고, 통제점으로 찍혀야 사람이 배치를 확인한다.
DEFEND_LOCATIONS = {
    "LOC_중앙킬존남측", "LOC_목표A남측", "LOC_중앙킬존",
    "LOC_동측능선", "LOC_서측능선",
}


def test_move_cp_stays_the_only_control_point_consumer(spec):
    """find_fp가 사라지면서 통제점(= VR-Forces 전술 그래픽)을 참조하는
    유일한 task_kind는 방어 배치 이동(move_cp)뿐이어야 한다.

    2026-08-03에 통제점을 뺀 것은 배치 지명 29개를 전부 찍어 로딩이 느려졌기
    때문이다. move_firing_position은 좌표로 이동하므로 통제점이 필요 없다
    (Task 5) — 통제점이 여기서 새면 잡힌다.
    """
    ctl = {c.uuid: c.ref_id for c in spec.control_objects}
    assert ctl, "통제점이 하나도 없다"
    for steps in spec.entity_plans.values():
        for s in steps:
            # 견인 장비(ZPU-4·Mortar·Patriot 일부)는 move-to 컨트롤러 자체가
            # 없어 move_cp도 저작되지 않는다 — 그 경우 refs가 비어 있는 것이
            # 정상이다(entity_class_map.csv unsupported_tasks, Task 5 이전과
            # 동일한 기존 동작). 저작된 단계만 통제점 참조를 검사한다.
            if s.task_kind != "move_cp" or not s.pln:
                continue
            assert s.refs[0] in ctl, (s.event_id, s.refs)
    assert set(ctl.values()) <= DEFEND_LOCATIONS, sorted(ctl.values())


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
