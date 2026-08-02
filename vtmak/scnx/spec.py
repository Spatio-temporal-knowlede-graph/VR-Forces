"""이벤트 + 사전 + 레이아웃 → ScnxSpec(결정적 확정 스펙).

writer가 읽는 유일한 입력. 좌표·uuid·DIS가 여기서 전부 확정된다.
선행 프로젝트의 _enrich_plans(백마고지 탈환 기본행동 주입)는 없다 —
task 가능 328객체 전원이 실제 이벤트를 갖고 있다(설계 스펙 §4.5).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..gates import engagement_pairs
from ..geometry import BattlefieldLayout, Coord
from ..parser import Event, PatternMap
from ..ranges import WeaponRanges
from ..registry import EntityDef
from ..roster import unit_of
from .catalog import DisCatalog, TaskCatalog
from .ids import IdAllocator
from .plan import PlanStep, build_entity_plan

DEFAULT_HEADING = 0.0   # 원문에 방위각이 없다
JITTER_M = 25.0         # 같은 지명을 공유하는 객체가 겹치지 않도록


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


def jitter_offset(key: str, meters: float = JITTER_M) -> tuple[float, float]:
    """object_id 해시로 ±meters 결정적 오프셋(로컬 미터).

    한 지명에 130객체까지 몰리므로 흩지 않으면 정확히 겹친다.
    """
    h = hashlib.sha256(key.encode("utf-8")).digest()
    dx = (int.from_bytes(h[:4], "big") / 2 ** 32 - 0.5) * 2 * meters
    dy = (int.from_bytes(h[4:8], "big") / 2 ** 32 - 0.5) * 2 * meters
    return dx, dy


SUPPRESSED_STATES = {"제압"}


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
    """plan.PlanContext 구현."""

    def __init__(self, layout: BattlefieldLayout, ids: IdAllocator,
                 registry: dict[str, EntityDef],
                 entity_uuids: dict[str, str]) -> None:
        self._layout = layout
        self._ids = ids
        self._reg = registry
        self._uuids = entity_uuids
        self.referenced_locs: set[str] = set()
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

    def coord_of(self, ref: str) -> Coord:
        """객체 id → 그 객체의 배치 좌표. 정적 객체·지명 → 레이아웃 좌표."""
        bound = self._layout.static_target(ref)
        if bound:
            return self._layout.coord(bound)
        ent = self._reg.get(ref)
        if ent and ent.initial_location:
            dx, dy = jitter_offset(ref)
            return self._layout.offset_coord(ent.initial_location, dx, dy)
        return self._layout.coord(ref)


def build_spec(events: list[Event], registry: dict[str, EntityDef],
               layout: BattlefieldLayout, pattern_map: PatternMap,
               catalog: TaskCatalog, dis: DisCatalog, ranges: WeaponRanges,
               scenario_id: str, seed: str = "") -> ScnxSpec:
    ids = IdAllocator(seed or scenario_id)
    taskable = {oid: d for oid, d in sorted(registry.items()) if d.taskable}
    entity_uuids = {oid: ids.alloc("entity", oid) for oid in taskable}
    ctx = _Ctx(layout, ids, registry, entity_uuids)

    spec = ScnxSpec(scenario_id=scenario_id, terrain=layout.terrain)
    for oid, d in taskable.items():
        dx, dy = jitter_offset(oid)
        spec.entities.append(EntitySpec(
            object_id=oid,
            name=d.role or oid,
            uuid=entity_uuids[oid],
            entity_class=d.entity_class,
            type_group=d.type_group,
            faction=d.faction,
            dis=dis.dis(d.entity_class),
            coord=layout.offset_coord(d.initial_location, dx, dy),
            heading=DEFAULT_HEADING,
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
            by_actor[oid], d, pattern_map, catalog, ranges, ctx,
            fire_distance, suppression)

    used = set(ctx.referenced_locs) | {
        d.initial_location for d in taskable.values() if d.initial_location}
    for lid in sorted(used):
        spec.control_objects.append(ControlObjectSpec(
            ref_id=lid, kind="COORD",
            uuid=ids.alloc("control_object", lid),
            name=lid.removeprefix("LOC_"),
            coord=layout.coord(lid)))
    return spec
