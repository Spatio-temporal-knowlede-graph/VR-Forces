"""이벤트 + 사전 + 레이아웃 → ScnxSpec(결정적 확정 스펙).

writer가 읽는 유일한 입력. 좌표·uuid·DIS가 여기서 전부 확정된다.
선행 프로젝트의 _enrich_plans(백마고지 탈환 기본행동 주입)는 없다 —
task 가능 328객체 전원이 실제 이벤트를 갖고 있다(설계 스펙 §4.5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..gates import PositionTracker, engagement_locations, engagement_pairs
from ..geometry import BattlefieldLayout, Coord, bearing_elevation, ground_distance
from ..parser import Event, PatternMap
from ..paths import CONFIG
from ..ranges import WeaponRanges
from ..registry import EntityDef
from ..roster import unit_of
from .catalog import DisCatalog, TaskCatalog, TaskKinds
from .engagements import (ActorClock, EngagementSlot, EnrichmentConfig,
                          SlotRejection, build_enrichment_slots,
                          build_source_slots,
                          choose_cover_location as _choose_cover_location,
                          choose_firing_location as _choose_firing_location)
from .fixed import FixedObject
from .ids import IdAllocator
from .placement import PlacementRules, build_headings, build_positions
from .plan import PlanStep, balanced, build_engagement_steps, build_entity_plan


@dataclass
class EntitySpec:
    object_id: str
    name: str
    uuid: str
    entity_class: str
    type_group: str
    faction: str
    dis: tuple[int, ...] | None
    coord: Coord
    heading: float
    initial_state: str


@dataclass
class ControlObjectSpec:
    ref_id: str
    kind: str            # COORD | CONTROL_POINT | ROUTE
    uuid: str
    name: str
    coord: Coord | None
    vertices: tuple[Coord, ...] = ()


@dataclass
class ScnxSpec:
    scenario_id: str
    terrain: str
    entities: list[EntitySpec] = field(default_factory=list)
    control_objects: list[ControlObjectSpec] = field(default_factory=list)
    entity_plans: dict[str, list[PlanStep]] = field(default_factory=dict)
    # 원문 밖에서 복제해 넣는 객체(UAV 등). 원문 규모가 바뀌어도 개수·선회
    # 중심·고도가 변하지 않는다 — 이것이 '고정'의 뜻이다.
    fixed_objects: list[FixedObject] = field(default_factory=list)
    # 고정 객체에 붙는 Plan 블록(Set·Task). marking → PLN 문자열들.
    fixed_plans: dict[str, list[str]] = field(default_factory=dict)
    # 원문 77건(origin="source") + 결정적으로 고른 신규 교전(origin=
    # "enrichment"). G4(vtmak/scnx/gates.py)와 감사 산출물
    # (engagements.slot_audit_rows)이 이 필드 하나를 공유해서 읽는다.
    engagement_slots: list[EngagementSlot] = field(default_factory=list)
    # 신규 교전 후보 중 채택되지 못한 것들의 사유. build_enrichment_slots가
    # 채운다 — enrichment_config가 없거나 비활성이면 비어 있다.
    engagement_rejections: list[SlotRejection] = field(default_factory=list)


# 고정 객체 플랜에 허용하는 Plan 요소. Set과 Task 둘 다 통과시킨다 — UAV는
# 순찰 비행(move-along)을 해야 관측 방위가 바뀌어 지형 차폐가 풀린다
# (설계 스펙 2026-08-06 §3.5). '고정'은 '안 움직인다'가 아니라 '원문 규모와
# 무관하게 같은 배치를 갖는다'로 개정됐다(같은 스펙 §3.6). 붙일 수 있는 행동은
# 여전히 task_catalog에 있는 것만이다.
FIXED_PLAN_ELEMENTS = {"Set", "Task"}

# 순찰 비행 템플릿에서 갈아끼우는 자리. task_catalog의 '교체할_파라미터' 칸과
# 같은 이름을 쓴다.
_PATROL_ROUTE = "PATROL_ROUTE_UUID"


def build_fixed_plans(fixed: list[FixedObject],
                      catalog: TaskCatalog) -> dict[str, list[str]]:
    """고정 객체가 선언한 행동 → PLN 블록.

    선언한 행동이 task_catalog에 없으면 예외다. 조용히 빠지면 UAV가 왜 안
    움직이는지 .scnx를 열어보기 전엔 알 수 없다(load_fixed의 markings와 같은
    규칙).

    순찰 비행은 `patrol_laps`만큼 반복해 붙인다. move-along은 한 번에 한 바퀴만
    돌고 끝나므로, 모자라면 UAV가 마지막 정점에 서 버린다.
    """
    plans: dict[str, list[str]] = {}
    for f in fixed:
        blocks: list[str] = []
        for label in f.plan_actions:
            t = catalog.get(f.type_group, label)
            if t is None:
                raise KeyError(
                    f"task_catalog에 없는 고정 객체 행동: "
                    f"({f.type_group}, {label}) — {f.marking}")
            if t.plan_element not in FIXED_PLAN_ELEMENTS:
                raise ValueError(
                    f"고정 객체에 붙일 수 없는 Plan 요소: {f.marking} "
                    f"'{label}'은 {t.plan_element} — "
                    f"{sorted(FIXED_PLAN_ELEMENTS)}만 된다")
            pln = t.pln.strip()
            repeat = 1
            if _PATROL_ROUTE in pln:
                if not f.patrol_route_uuid:
                    raise ValueError(
                        f"'{label}'은 순찰로가 필요하다: {f.marking} — "
                        "fixed_objects.json의 patrol_centers에 지명을 적는다")
                pln = pln.replace(_PATROL_ROUTE, f.patrol_route_uuid)
                repeat = max(1, f.patrol_laps)
            if not balanced(pln):
                raise ValueError(
                    f"괄호가 안 맞는 템플릿: ({f.type_group}, {label})")
            blocks.extend([pln] * repeat)
        if blocks:
            plans[f.marking] = blocks
    return plans


class _Ctx:
    """plan.PlanContext 구현.

    좌표는 **초기 배치가 아니라 그 시각의 위치**로 푼다. 예전에는 태스크가
    참조하는 객체의 좌표를 `initial_location`에서 가져왔다. 적 보병은 적 북측
    집결지에서 출발해 중앙 킬존까지 1.7km를 내려오는데, 그 상태에서 아군이
    제압사격을 하면 `.pln`의 사격 좌표는 집결지를 가리켰다 — 적은 킬존에 있고
    포탄은 빈 집결지에 떨어진다.

    해석기는 G0(`gates.engagement_pairs`)와 **같은 것**을 쓴다. 사거리를 재는
    위치와 사격 좌표가 다른 코드에서 나오면 반드시 어긋난다 — G0는 통과했는데
    실제 사격은 사거리를 벗어나는 식이다.
    """

    def __init__(self, layout: BattlefieldLayout, ids: IdAllocator,
                 registry: dict[str, EntityDef],
                 entity_uuids: dict[str, str],
                 events: list[Event],
                 ranges: WeaponRanges,
                 enrichment_config: EnrichmentConfig,
                 coords: dict[str, Coord] | None = None) -> None:
        self._layout = layout
        self._ids = ids
        self._reg = registry
        self._uuids = entity_uuids
        self._coords = coords or {}
        self._ranges = ranges
        self._enrichment_config = enrichment_config
        self._tracker = PositionTracker(events, registry)
        self._hit_at = engagement_locations(events)
        self.referenced_locs: set[str] = set()
        # move_cover가 같은 golden 지점을 공유하는 객체를 배정하는 상태.
        # 이격은 지점 선택 필터가 아니라 지점을 공유하는 객체들의 배치
        # 규칙이다 — choose_cover_location 아래 docstring에 네 차례
        # 정정한 근거가 있다(2026-08-27, 리뷰 라운드 1).
        self._cover_k: dict[str, int] = {}          # ref -> 다음 순번 k
        self._cover_az: dict[str, float] = {}        # ref -> 첫 배정자의 방위(고정)
        self._cover_members: dict[str, list[Coord]] = {}  # ref -> 검증 통과한 목적지들
        # 부대 선두 — 대형 추종 이동(follow-entity)의 추종 대상.
        self._leader: dict[str, str] = {}
        for oid in sorted(entity_uuids):
            self._leader.setdefault(unit_of(oid), oid)

    def unit_leader(self, object_id: str) -> str | None:
        lead = self._leader.get(unit_of(object_id))
        return None if lead == object_id else lead

    def entity_uuid(self, object_id: str) -> str | None:
        return self._uuids.get(object_id)

    def ref_kind(self, ref: str) -> str:
        """정적 객체는 좌표로 처리한다(설계 스펙 §5.3)."""
        if self._layout.static_target(ref):
            return "COORD"
        return "ENTITY" if ref in self._uuids else "COORD"

    def ref_uuid(self, ref: str) -> str:
        if ref in self._uuids and not self._layout.static_target(ref):
            return self._uuids[ref]
        lid = self._layout.static_target(ref) or ref
        self.referenced_locs.add(lid)
        return self._ids.alloc("control_object", lid)

    def coord_of(self, ref: str, time_s: int = -1, actor: str = "") -> Coord:
        """참조 대상의 **그 시각** 좌표.

        우선순위는 G0와 같다: 피격 문장이 적은 교전 지점 > 정적 바인딩 >
        시각별 위치 추적. 피격 문장을 먼저 보는 이유는 원문이 교전 지점을 직접
        진술하기 때문이다(이동 서술이 그보다 오래됐을 수 있다).

        추적된 지명이 그 객체의 초기 배치 지명과 같으면 **실제 배치 좌표**를
        쓴다. 아직 움직이지 않았다는 뜻이라 대형 안의 자기 자리를 정확히 안다.
        움직였으면 지명 중심점을 쓴다 — 목적지 안에서 어디에 서는지는 VR-Forces가
        정하므로 우리가 알 수 없고, 아는 척하면 G0와 어긋난다.
        """
        bound = self._layout.static_target(ref)
        if bound:
            return self._layout.coord(bound)
        ent = self._reg.get(ref)
        if ent is None:
            return self._layout.coord(ref)
        loc = ""
        if actor:
            loc = self._hit_at.get((actor, ref), "")
        if not loc:
            loc = self._tracker.location_at(ref, time_s)
        if not loc:
            loc = ent.initial_location
        if loc and loc == ent.initial_location and ref in self._coords:
            return self._coords[ref]
        return self._layout.coord(loc)

    def actor_coord(self, actor: str, time_s: int, src: str = "") -> Coord:
        """사수 자신의 그 시각 좌표. 문장이 명시한 출발 지명(src)이 최우선.

        `gates.engagement_pairs`의 사수 위치 규칙과 같다.
        """
        if src and self._layout.has(src):
            ent = self._reg.get(actor)
            if ent and src == ent.initial_location and actor in self._coords:
                return self._coords[actor]
            return self._layout.coord(src)
        return self.coord_of(actor, time_s)

    def choose_firing_location(self, entity_class: str, shooter: Coord,
                               target: Coord) -> tuple[str, Coord] | None:
        """find_firing_position 대체.

        직접사거리를 우선 쓰되, 없으면 간접사거리로 넘어간다. '사격 준비'
        전이는 aimAt(간접사격 준비)과 짝인 상태전이라 실측상 늘 간접사격
        장비다(2026-08-27: 이 시나리오의 사격 준비 21건 전부가 박격포·자주포·
        Patriot — 직접사거리가 아예 없다). 직접사거리만 보면 21/21 검증
        불가로 no_verified_position만 남아 find_firing_position 대체가
        사실상 죽는다. 보병처럼 직접사거리를 가진 모델이 언젠가 이 전이를
        타면 그쪽을 우선한다.
        """
        range_spec = (self._ranges.spec(entity_class, "direct")
                     or self._ranges.spec(entity_class, "indirect"))
        if range_spec is None:
            return None
        return _choose_firing_location(self._layout, shooter, target,
                                       range_spec, reserved=set())

    def choose_cover_location(self, actor: str, actor_coord: Coord,
                              threat_coord: Coord) -> tuple[str, Coord] | None:
        """find_cover 대체.

        choose_cover_location(engagements.py)은 위협거리·이동예산만 본다 —
        최소 이격은 지점 선택 필터가 아니라 지점을 공유하는 객체들의 배치
        규칙이다(2026-08-27, 세 번째 정정: t=0 배치 좌표 필터는 hitBy 77건
        중 50건만 남기고, 이번 빌드 예약 필터는 몰린 부대의 첫 사상자가
        유일한 후보를 빼앗아 2/77까지 떨어뜨렸다 — golden 21점 대 77건
        밀도에서 필터는 지울 수만 있다).

        네 번째 정정(2026-08-27, 리뷰 라운드 1): 직선 벌림(k번째 객체를
        위협→지점 축에 수직으로 15m·30m·45m·... 배치)은 군집 크기에
        비례해 자란다 — 50명 군집의 k=49가 375m까지 밀려나 이동예산
        (max_cover_move_m)과 '그 지점 자체'라는 전제를 둘 다 깼다. 대신
        반원형 고리를 쓴다: 고리 j(1부터)는 반지름 min_entity_separation_m*j,
        용량 max(1, floor(pi*j))(반원 둘레 pi*반지름을 이격 간격으로 나눈
        것과 같다) — 군집 크기에 √n으로 자라 50명이어도 j=6(90m)에서
        끝난다. 축은 첫 배정자(k=0)의 위협→지점 방위로 고정해 저장하고
        재사용한다 — 액터마다 다시 계산하면 위협 방위가 반대인 두 액터가
        같은 오프셋에 겹칠 수 있다(리뷰 발견 2: az 270도 k=1과 az 90도
        k=2가 둘 다 정북 15m에 떨어지는 사례).

        오프셋을 계산한 뒤에는 반드시 재검증한다 — 후보 지점이 아니라 최종
        목적지를 검증하는 게 불변식이다. 이동예산·자기 위협 대비 이격 증가·
        같은 지점에 이미 배정된 다른 목적지와의 최소 이격, 셋 다 못 지키면
        None(no_verified_position)이다 — 엄폐를 정직하게 잃는 게 설계된
        결과이고 감사 로그에 그대로 남는다.
        """
        loc = _choose_cover_location(self._layout, actor_coord, threat_coord,
                                     self._enrichment_config)
        if loc is None:
            return None
        ref, point_coord = loc
        k = self._cover_k.get(ref, 0)
        self._cover_k[ref] = k + 1
        if k == 0:
            self._cover_az[ref] = bearing_elevation(threat_coord,
                                                    point_coord)[0]
            dest = point_coord
        else:
            dest = self._ring_offset(ref, self._cover_az[ref], k)

        cfg = self._enrichment_config
        # 인접한 고리 위치는 설계상 정확히 min_entity_separation_m만큼
        # 떨어지도록 계산된다(고리 용량 자체가 그 간격에서 나온다) — 그런데
        # offset_coord는 위도별 국지 선형 근사를 쓰고 ground_distance는
        # 정확한 WGS84 타원체 직선거리를 쓰므로, 이론상 정확히 경계에 있는
        # 두 점이 실측으로는 수 마이크로미터 모자라게 나올 수 있다(실측
        # 확인: 15.000000m가 아니라 14.999998612m). 물리적으로 무의미한
        # 그 오차 때문에 정당한 배치가 거부되지 않도록 아주 작은 허용폭을
        # 둔다 — 이격 자체를 완화하는 게 아니라 뜨는 소수점 잡음만 흡수한다.
        # 실측 오차 규모는 ~1.4e-6m — 10배 여유를 둔다.
        _EPS_M = 1e-4
        current = ground_distance(actor_coord, threat_coord)
        move = ground_distance(actor_coord, dest)
        away = ground_distance(dest, threat_coord)
        members = self._cover_members.get(ref, [])
        if (move > cfg.max_cover_move_m or away <= current
                or any(ground_distance(dest, o)
                      < cfg.min_entity_separation_m - _EPS_M
                      for o in members)):
            return None
        self._cover_members.setdefault(ref, []).append(dest)
        return ref, dest

    def _ring_offset(self, ref: str, az: float, k: int) -> Coord:
        """k번째(k>=1) 반원 고리 배정. az는 위협에서 지점을 향하는 방위로,
        그대로 이어가면 위협에서 멀어지는 방향이다 — 반원은 그 방위를
        중심으로 ±90도를 덮어, 대부분의 자리가 지점 자체보다도 위협에서
        멀어지고 정확히 접선(±90도)인 자리만 거의 같다(재검증이 그 경우를
        거른다).
        """
        j, cap = 1, 0
        remaining = k
        while True:
            cap = max(1, math.floor(math.pi * j))
            if remaining <= cap:
                break
            remaining -= cap
            j += 1
        p = remaining - 1                       # 0부터, 고리 안에서의 순번
        radius = self._enrichment_config.min_entity_separation_m * j
        angle = az + (-math.pi / 2 + (p + 0.5) * math.pi / cap)
        east = radius * math.sin(angle)
        north = radius * math.cos(angle)
        return self._layout.offset_coord(ref, east, north)


# 교전 슬롯 블록 내부 순서(이동→대기→직접사격→제압사격, 설계 §5). 슬롯이
# 아닌 단계는 -1 하나로 묶어 time_s·event_id만으로 갈리게 한다 — 그래야
# 슬롯 블록 넷은 phase로, 나머지는 원래 순서(시각·event_id)로 유지된다.
_SLOT_PHASE_ORDER = {"move": 0, "wait": 1, "fire_direct": 2, "suppress": 3}


def _slot_phase(step: PlanStep) -> int:
    """슬롯이 아니면 -1. 동반 행동(`기반kind:행동`)은 콜론 앞만 본다 —
    안 그러면 예컨대 'suppress:방향 조준'이 알 수 없는 키로 기본값 0에
    떨어져 제압사격의 동반 행동이 블록 맨 앞(move 자리)으로 튀어 오른다.
    오늘은 move/wait/fire_direct/suppress 중 어느 것도 동반 행동을 선언하지
    않아 잠들어 있지만, task_kinds.csv에 후행_행동을 다는 패턴 자체는
    Task 5가 move_cover에 이미 썼다(Task 6 리뷰 라운드 1 minor)."""
    if not step.slot_id:
        return -1
    return _SLOT_PHASE_ORDER.get(step.task_kind.split(":")[0], 0)


def build_spec(events: list[Event], registry: dict[str, EntityDef],
               layout: BattlefieldLayout, pattern_map: PatternMap,
               catalog: TaskCatalog, kinds: TaskKinds,
               dis: DisCatalog, ranges: WeaponRanges,
               scenario_id: str, seed: str = "",
               fixed: list[FixedObject] | None = None,
               placement: PlacementRules | None = None,
               enrichment_config: EnrichmentConfig | None = None) -> ScnxSpec:
    """이벤트·사전·레이아웃 → 확정 스펙. 순서는 비순환이어야 한다(Task 6):

    1. 배치·컨텍스트·엔티티 스펙·source 슬롯·slots_by_event.
    2. 원문 행위자 계획(source 슬롯은 이동·대기·직접·제압 네 단계로 내려간다).
    3. 살아 있는 PlanStep에서 task_counts·last_task_times를 센다.
    4. 객체별 ActorClock(2단계에서 이미 굴린 것)으로 blocked_shooters를 모은다.
    5. enrichment_config가 있고 활성화됐으면 build_enrichment_slots를 부른다.
    6. 신규 슬롯을 사수의 계획 끝에 붙인다. 표적 계획은 건드리지 않는다.
    7. 사수별 계획을 (time_s, slot phase, event_id)로 재정렬한다.

    enrichment_config가 None이면 5~7단계를 건너뛴다 — 원문 77건의 슬롯
    lowering(1~2단계)과 엄폐·사격위치 대체(_Ctx)는 '보강'이 아니라 기존
    계약이라 always on이다. 그래서 None일 때도 _Ctx·ActorClock·source
    슬롯에는 EnrichmentConfig.defaults()를 대체값으로 쓴다 — 파일을 다시
    읽는 게 아니라(그러면 로딩 지점이 둘로 갈린다) 코드에 둔 기본값이다.
    설정 파일을 읽는 유일한 자리는 scripts/04_compile_scnx.py다.
    """
    ids = IdAllocator(seed or scenario_id)
    taskable = {oid: d for oid, d in sorted(registry.items()) if d.taskable}
    entity_uuids = {oid: ids.alloc("entity", oid) for oid in taskable}

    # move_firing_position·move_cover(Task 5)가 컴파일 시점에 골든 지점을
    # 검증하려면 _Ctx가 사거리표와 엄폐 설정을 미리 쥐고 있어야 한다.
    base_config = enrichment_config or EnrichmentConfig.defaults()

    # 배치와 방위. 좌표는 대형 배치기가, 방위는 첫 이동 목적지가 정한다.
    # 태스크가 참조하는 좌표(_Ctx)도 이 배치를 봐야 하므로 먼저 만든다.
    # 방위가 먼저다 — 대형은 그 방위에 수직으로 눕는다(방어선이 적을 가로막게).
    rules = placement or PlacementRules.load(CONFIG / "placement_rules.csv")
    headings = build_headings(taskable, events, layout)
    coords = build_positions(taskable, layout, rules, headings)
    ctx = _Ctx(layout, ids, registry, entity_uuids, events, ranges,
              base_config, coords)

    spec = ScnxSpec(scenario_id=scenario_id, terrain=layout.terrain,
                    fixed_objects=list(fixed or []))
    # 순찰로는 load_fixed가 라우트 객체로 함께 만들어 fixed_objects에 넣어
    # 준다. 여기서는 플랜만 잇는다.
    spec.fixed_plans = build_fixed_plans(spec.fixed_objects, catalog)
    for oid, d in taskable.items():
        spec.entities.append(EntitySpec(
            object_id=oid,
            name=d.role or oid,
            uuid=entity_uuids[oid],
            entity_class=d.entity_class,
            type_group=d.type_group,
            faction=d.faction,
            dis=dis.dis(d.entity_class),
            coord=coords[oid],
            heading=headings[oid],
            initial_state=d.initial_state,
        ))

    # 사거리 거리는 G0와 같은 계산을 쓴다(교전 시점 위치 해석이 두 벌이면
    # 반드시 어긋난다).
    fire_distance = {g.event_id: g.distance_m
                     for g in engagement_pairs(events, registry, layout)}

    # 1단계: 원문 directFireAt 77건을 결정적 EngagementSlot으로 바꾼다
    # (설계 §5). spec.engagement_slots는 여기서 source 슬롯으로 먼저 채운다
    # — 5단계가 건너뛰어도(enrichment_config=None) 원문 77건은 항상 있다.
    source_slots = build_source_slots(events, registry, layout, base_config)
    slots_by_event: dict[str, EngagementSlot] = {}
    for slot in source_slots:
        for eid in slot.source_event_ids:
            slots_by_event[eid] = slot
    spec.engagement_slots = list(source_slots)

    # 2단계: 원문 행위자 계획. source 슬롯은 build_entity_plan 안에서 Task 4의
    # 네 단계로 내려간다. 사수별 ActorClock을 clocks에 남겨 둔다 — 4단계의
    # blocked_shooters 판정과 6단계의 신규 슬롯 이어붙이기가 같은 시계를
    # 이어 쓴다(다시 굴리면 중복 계산이고, 새로 만들면 두 시계가 어긋난다).
    by_actor: dict[str, list[Event]] = {oid: [] for oid in taskable}
    for e in events:
        if e.actor in by_actor:
            by_actor[e.actor].append(e)
    clocks: dict[str, ActorClock] = {}
    for oid, d in taskable.items():
        clock = ActorClock(0, base_config)
        spec.entity_plans[oid] = build_entity_plan(
            by_actor[oid], d, pattern_map, catalog, kinds, ranges, ctx,
            fire_distance, slots_by_event, clock, base_config)
        clocks[oid] = clock

    # 3단계: 살아 있는(=.pln이 있는) PlanStep에서 표적 우선순위에 쓸
    # task_counts·last_task_times를 센다.
    task_counts: dict[str, int] = {}
    last_task_times: dict[str, int] = {}
    for oid, steps in spec.entity_plans.items():
        live = [s for s in steps if s.pln]
        if live:
            task_counts[oid] = len(live)
            last_task_times[oid] = max(s.time_s for s in live)

    # 4단계: blocked_shooters. 후보는 BLUE taskable 객체다 — 이 보강은
    # 원문에서 대응이 적은 RED 표적을 겨눈다(설계 §6.3, Task 2
    # full_inputs와 같은 관례). noTask가 선언됐거나(원문이 명시적으로
    # 금지) 원문 큐 전체가 유한하게 끝나지 않으면(clock.bounded=False,
    # 2단계에서 이미 확정) 그 뒤에 새 슬롯을 이어붙일 수 없다.
    notask_actors = {e.actor for e in events
                     if e.template == "noTask" and e.actor}
    blue_shooter_ids = sorted(oid for oid, d in taskable.items()
                              if d.faction == "BLUE")
    blocked_shooters: dict[str, str] = {}
    for oid in blue_shooter_ids:
        if oid in notask_actors:
            blocked_shooters[oid] = "shooter_no_task"
        elif not clocks[oid].bounded:
            blocked_shooters[oid] = "shooter_unbounded_predecessor"

    # 5~7단계: 신규 교전. enrichment_config가 없거나 비활성화면 건너뛴다 —
    # source 슬롯 77건과 그 lowering은 이미 끝났으므로 영향받지 않는다.
    if enrichment_config is not None and enrichment_config.enabled:
        result = build_enrichment_slots(
            events, registry, layout, ranges, enrichment_config,
            task_counts, last_task_times, blue_shooter_ids,
            blocked_shooters, source_slots)
        spec.engagement_rejections = list(result.rejected)
        spec.engagement_slots.extend(result.slots)

        # 6단계: 각 보강 슬롯을 사수의 계획 끝에 붙인다. 표적 계획은
        # 절대 건드리지 않는다 — 슬롯은 사수의 행동이지 표적의 사건이
        # 아니다.
        for slot in sorted(result.slots,
                           key=lambda s: (s.shooter_id, s.scheduled_time_s,
                                         s.slot_id)):
            shooter_entity = taskable[slot.shooter_id]
            new_steps = build_engagement_steps(
                slot, shooter_entity, catalog, kinds, ranges, ctx,
                clocks[slot.shooter_id], enrichment_config)
            spec.entity_plans[slot.shooter_id].extend(new_steps)

        # 7단계: 새 슬롯이 끝에 붙었으니 시각순으로 되정렬한다. 한 슬롯의
        # 네 합성 이벤트는 전부 slot.scheduled_time_s를 공유해 time_s만으로는
        # 안 갈리므로 _slot_phase로 내부 순서를 못 박는다.
        for oid in {s.shooter_id for s in result.slots}:
            spec.entity_plans[oid] = sorted(
                spec.entity_plans[oid],
                key=lambda s: (s.time_s, _slot_phase(s), s.event_id))

    # 통제점(= VR-Forces 전술 그래픽)은 태스크가 실제로 참조할 때만 만든다.
    # 예전에는 배치 지명까지 전부 찍었는데, 그건 지도 표시용일 뿐 태스크가
    # 쓰지 않았다. 전술 그래픽이 시나리오 로딩을 느리게 해서 뺐다(사용자 결정
    # 2026-08-03). 엔티티는 자기 좌표를 이미 갖고 있어 배치에는 영향이 없다.
    for lid in sorted(ctx.referenced_locs):
        spec.control_objects.append(ControlObjectSpec(
            ref_id=lid, kind="COORD",
            uuid=ids.alloc("control_object", lid),
            name=lid.removeprefix("LOC_"),
            coord=layout.coord(lid)))
    return spec
