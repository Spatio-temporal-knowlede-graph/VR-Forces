"""scnx 단계 전용 사전 로더 — task_catalog / dis_catalog.

.scnx 저작에만 필요한 사전을 읽는다. 코드에 어휘·문법을 하드코딩하지 않는다는
원칙을 이 단계에도 적용한다.

선행 프로젝트에서 두 가지를 고쳤다.
1) DisCatalog가 entity_class를 원문 그대로 매칭했다. 새 원문은 'T-72 MBT',
   dis_catalog는 'T 72 MBT'라 정규화 없이는 못 찾는다.
2) action_task_map은 pattern_map.csv가 대체해 더 이상 쓰지 않는다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..norm import norm


def _rows(path: Path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


@dataclass(frozen=True)
class TaskTemplate:
    type_group: str
    action_label: str  # task_catalog '행동' 컬럼
    plan_element: str  # Task | Set | If / Condition
    task_or_request_type: str
    pln: str  # 실제 S-expression 템플릿(placeholder 포함)
    params: str  # 교체할 파라미터 설명


class TaskCatalog:
    """(type_group, 행동) → TaskTemplate."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], TaskTemplate] = {}

    @classmethod
    def load(cls, path) -> "TaskCatalog":
        c = cls()
        for r in _rows(Path(path)):
            t = TaskTemplate(
                r["객체_타입_그룹"].strip(), r["행동"].strip(),
                r.get("Plan_요소", "").strip(),
                r.get("task_type_or_request_type", "").strip(),
                r.get("PLN_문법", ""), r.get("교체할_파라미터", ""),
            )
            c._by_key[(norm(t.type_group), norm(t.action_label))] = t
        return c

    def get(self, type_group: str, action_label: str) -> TaskTemplate | None:
        return self._by_key.get((norm(type_group), norm(action_label)))

    def labels_for(self, type_group: str) -> list[str]:
        key = norm(type_group)
        return [t.action_label for (g, _), t in self._by_key.items() if g == key]


class DisCatalog:
    """entity_class → DIS 7튜플(tuple[int,...]) 또는 None(미확정)."""

    def __init__(self) -> None:
        self._dis: dict[str, tuple[int, ...] | None] = {}
        self.domain: dict[str, str] = {}

    @classmethod
    def load(cls, path) -> "DisCatalog":
        c = cls()
        for r in _rows(Path(path)):
            cls_name = r["entity_class"].strip()
            raw = (r.get("dis") or "").strip()
            dis: tuple[int, ...] | None = None
            if raw:
                parts = [p for p in raw.replace(",", " ").split() if p]
                try:
                    dis = tuple(int(p) for p in parts)
                except ValueError:
                    dis = None
            c._dis[norm(cls_name)] = dis
            c.domain[norm(cls_name)] = (r.get("domain") or "").strip()
        return c

    def dis(self, entity_class: str) -> tuple[int, ...] | None:
        return self._dis.get(norm(entity_class))

    def known(self, entity_class: str) -> bool:
        return norm(entity_class) in self._dis
