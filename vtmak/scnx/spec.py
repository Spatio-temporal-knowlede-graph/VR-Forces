"""이벤트 + 사전 + 레이아웃 → ScnxSpec(결정적 확정 스펙).

writer가 읽는 유일한 입력. 좌표·uuid·DIS가 여기서 전부 확정된다.
선행 프로젝트의 _enrich_plans(백마고지 탈환 기본행동 주입)는 없다 —
task 가능 328객체 전원이 실제 이벤트를 갖고 있다(설계 스펙 §4.5).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..gates import PositionTracker, engagement_locations, engagement_pairs
from ..geometry import BattlefieldLayout, Coord
from ..parser import Event, PatternMap
from ..paths import CONFIG
from ..ranges import WeaponRanges
from ..registry import EntityDef
from ..roster import unit_of
from .catalog import DisCatalog, TaskCatalog, TaskKinds
from .fixed import FixedObject
from .ids import IdAllocator
from .placement import PlacementRules, build_headings, build_positions
from .plan import PlanStep, balanced, build_entity_plan


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


SUPPRESSED_STATES = {"제압"}

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


def suppression_events(events: list[Event]) -> set[str]:
    """표적이 제압 상태가 된 직접사격 event_id.

    원문은 사격 → 피격 → 상태전환을 세 문장으로 나눠 쓴다. 셋을 이어붙여
    '이 사격은 제압사격이었다'를 판정한다. 그런 사격은 fire-at-target 대신
    provide_suppressive_fire_loc으로 저작한다(yewon_test.pln에서 수확).
    """
    became: dict[str, int] = {}      # 객체 → 제압된 시각
    for e in events:
        if e.template == "stateChange" and e.state_to in SUPPRESSED_STATES:
            became.setdefault(e.actor, e.time_s)
    out: set[str] = set()
    for e in events:
        if e.template != "directFireAt" or not e.target:
            continue
        t = became.get(e.target)
        if t is not None and t >= e.time_s:
            out.add(e.event_id)
    return out


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
                 coords: dict[str, Coord] | None = None,
                 orbat=None) -> None:
        self._layout = layout
        self._ids = ids
        self._reg = registry
        self._uuids = entity_uuids
        self._coords = coords or {}
        self._tracker = PositionTracker(events, registry)
        self._hit_at = engagement_locations(events)
        self.referenced_locs: set[str] = set()
        # 부대 선두 — 대형 추종 이동(follow-entity)의 추종 대상. 편제가 있으면
        # 소대 선두를, 없으면 타입 접두사 선두를 쓴다.
        self._orbat = orbat
        self._leader: dict[str, str] = {}
        for oid in sorted(entity_uuids):
            self._leader.setdefault(self._unit(oid), oid)

    def _unit(self, object_id: str) -> str:
        if self._orbat is not None:
            pl = self._orbat.platoon_of(object_id)
            if pl:
                return pl
        return unit_of(object_id)

    def unit_leader(self, object_id: str) -> str | None:
        lead = self._leader.get(self._unit(object_id))
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


def build_spec(events: list[Event], registry: dict[str, EntityDef],
               layout: BattlefieldLayout, pattern_map: PatternMap,
               catalog: TaskCatalog, kinds: TaskKinds,
               dis: DisCatalog, ranges: WeaponRanges,
               scenario_id: str, seed: str = "",
               fixed: list[FixedObject] | None = None,
               placement: PlacementRules | None = None,
               orbat=None) -> ScnxSpec:
    ids = IdAllocator(seed or scenario_id)
    taskable = {oid: d for oid, d in sorted(registry.items()) if d.taskable}
    entity_uuids = {oid: ids.alloc("entity", oid) for oid in taskable}

    # 배치와 방위. 좌표는 대형 배치기가, 방위는 첫 이동 목적지가 정한다.
    # 태스크가 참조하는 좌표(_Ctx)도 이 배치를 봐야 하므로 먼저 만든다.
    # 방위가 먼저다 — 대형은 그 방위에 수직으로 눕는다(방어선이 적을 가로막게).
    rules = placement or PlacementRules.load(CONFIG / "placement_rules.csv")
    headings = build_headings(taskable, events, layout)
    coords = build_positions(taskable, layout, rules, headings,
                             unit_of_object=(orbat.platoon_of if orbat else None))
    ctx = _Ctx(layout, ids, registry, entity_uuids, events, coords, orbat)

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
    suppression = suppression_events(events)

    by_actor: dict[str, list[Event]] = {oid: [] for oid in taskable}
    for e in events:
        if e.actor in by_actor:
            by_actor[e.actor].append(e)
    for oid, d in taskable.items():
        spec.entity_plans[oid] = build_entity_plan(
            by_actor[oid], d, pattern_map, catalog, kinds, ranges, ctx,
            fire_distance, suppression)

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
