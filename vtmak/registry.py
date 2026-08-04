"""이벤트 → 객체 사전.

선행 프로젝트는 원문에서 후보를 채굴해 사람이 CSV를 검토했다. 새 원문은
객체 ID·모델명·역할이 문장에 명시되어 있어 그 단계가 필요 없다.
사람이 관리하는 것은 entity_class → type_group 매핑뿐이다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .norm import norm
from .parser import Event

UNCLASSIFIED = "미분류"


def faction_of(object_id: str) -> str:
    """ID 접두사가 소속을 결정한다. FR- 아군, EN- 적군, 그 외 중립."""
    if object_id.startswith("FR-"):
        return "BLUE"
    if object_id.startswith("EN-"):
        return "RED"
    return "NEUTRAL"


@dataclass(frozen=True)
class EntityDef:
    object_id: str
    entity_class: str
    role: str
    faction: str
    type_group: str
    weapons: tuple[str, ...]
    initial_location: str
    initial_state: str
    taskable: bool
    # 이 모델이 VR-Forces에서 실행하지 못하는 task-type. 컨트롤러(=시스템)가
    # 없으면 "No controller or Controller is disabled"로 실패한다. type_group은
    # 태스크 템플릿을 고르는 단위라 이보다 굵어서(T-72와 T-80이 같은 그룹인데
    # find_cover는 T-72만 실패한다) 모델 단위로 따로 둔다.
    unsupported_tasks: tuple[str, ...] = ()


class ClassMap:
    def __init__(self) -> None:
        self._tg: dict[str, str] = {}
        self._w: dict[str, tuple[str, ...]] = {}
        self._unsup: dict[str, tuple[str, ...]] = {}

    @classmethod
    def load(cls, path) -> "ClassMap":
        cm = cls()
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ecls = (row["entity_class"] or "").strip()
                if not ecls:
                    continue
                key = norm(ecls)
                cm._tg[key] = (row["type_group"] or "").strip() or UNCLASSIFIED
                cm._w[key] = tuple(
                    w.strip() for w in (row.get("weapons") or "").split("|")
                    if w.strip())
                cm._unsup[key] = tuple(
                    t.strip()
                    for t in (row.get("unsupported_tasks") or "").split(";")
                    if t.strip())
        return cm

    def known(self, entity_class: str) -> bool:
        return norm(entity_class) in self._tg

    def type_group(self, entity_class: str) -> str:
        return self._tg.get(norm(entity_class), UNCLASSIFIED)

    def known(self, entity_class: str) -> bool:
        """표에 행이 있는가. 미분류로 '선언된' 모델과 아예 빠진 모델을 가른다."""
        return norm(entity_class) in self._tg

    def weapons(self, entity_class: str) -> tuple[str, ...]:
        return self._w.get(norm(entity_class), ())

    def unsupported_tasks(self, entity_class: str) -> tuple[str, ...]:
        """이 모델이 실행하지 못하는 VR-Forces task-type."""
        return self._unsup.get(norm(entity_class), ())


def collect_locations(events: list[Event]) -> list[str]:
    out: set[str] = set()
    for e in events:
        for v in (e.location, e.src, e.dst):
            if v:
                out.add(v)
    return sorted(out)


def build_registry(events: list[Event], class_map: ClassMap,
                   static_ids: set[str]) -> dict[str, EntityDef]:
    """등장 객체 전부를 사전으로. 시간순으로 처음 본 값을 채택한다."""
    cls_by_id: dict[str, str] = {}
    role_by_id: dict[str, str] = {}
    loc_by_id: dict[str, str] = {}
    state_by_id: dict[str, str] = {}

    for e in sorted(events, key=lambda x: (x.time_s, x.event_id)):
        for oid, ecls, role in _mentions(e):
            if not oid:
                continue
            # 2차 언급에는 역할이 없다. 처음 본 비어있지 않은 값을 남긴다.
            if ecls and oid not in cls_by_id:
                cls_by_id[oid] = ecls
            if role and oid not in role_by_id:
                role_by_id[oid] = role
        if not e.actor:
            continue
        # 초기 배치·초기 상태는 각 객체의 첫 서술에서만 가져온다.
        if e.template == "locatedAt" and e.location:
            loc_by_id.setdefault(e.actor, e.location)
        if e.template == "stateInit" and e.state_to:
            state_by_id.setdefault(e.actor, e.state_to)
        elif e.template == "stateChange" and e.state_from:
            state_by_id.setdefault(e.actor, e.state_from)

    out: dict[str, EntityDef] = {}
    for oid in sorted(set(cls_by_id) | set(role_by_id)):
        ecls = cls_by_id.get(oid, "")
        taskable = oid not in static_ids
        out[oid] = EntityDef(
            object_id=oid,
            entity_class=ecls,
            role=role_by_id.get(oid, ""),
            faction=faction_of(oid),
            type_group=class_map.type_group(ecls) if taskable else "정적",
            weapons=class_map.weapons(ecls) if taskable else (),
            initial_location=loc_by_id.get(oid, ""),
            initial_state=state_by_id.get(oid, "대기"),
            taskable=taskable,
            unsupported_tasks=(class_map.unsupported_tasks(ecls)
                               if taskable else ()),
        )
    return out


def _mentions(e: Event):
    """이벤트가 담고 있는 (객체id, 모델명, 역할) 언급 전부.

    정적 객체 7개는 사격 목표로만 등장하므로 target 쪽 언급이 유일한
    모델명·역할 출처다.
    """
    yield (e.actor, e.actor_class, e.actor_role)
    if e.target:
        yield (e.target, e.target_class, e.target_role)
    if e.source_obj:
        yield (e.source_obj, e.source_class, "")
