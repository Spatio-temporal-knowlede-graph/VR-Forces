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


@dataclass(frozen=True)
class TaskKind:
    task_kind: str
    ref_kind: str            # COORD | ENTITY | * (무관)
    ref_field: str           # Event의 필드 이름. 빈 값 = 참조 대상 없음
    fire_kind: str           # direct | indirect | 빈 값(사거리 검사 안 함)
    labels: tuple[str, ...]  # task_catalog '행동' 이름, 우선순위 순
    note: str
    # 이 task 앞뒤에 같이 붙는 행동(task_catalog '행동' 이름). 저속 보급 기동의
    # set-speed, 감시 이동의 방향 조준처럼 '한 문장이 두 블록을 낸다'는 사실을
    # 코드가 아니라 표에 둔다.
    pre_labels: tuple[str, ...] = ()
    post_labels: tuple[str, ...] = ()


class TaskKinds:
    """task_kind → 참조 필드 · 사거리 종류 · 행동 후보.

    예전에는 plan.py에 LABEL_CANDIDATES·REF_FIELD·FIRE_KIND 세 개의 dict로
    박혀 있었다. 그래서 매핑 하나를 늘리려면 CSV 두 장과 코드 세 곳을 같이
    고쳐야 했고, task_catalog에 템플릿이 있는 행동 33종 중 8종만 도달 가능했다.

    참조_필드와 사거리_종류는 task_kind 하나에 하나뿐이다(ref_kind별로 갈리지
    않는다). 여러 행에 다르게 적혀 있으면 어느 쪽이 맞는지 알 수 없으므로
    로드 시점에 예외로 세운다.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], TaskKind] = {}
        self._ref: dict[str, str] = {}
        self._fire: dict[str, str] = {}
        self._pre: dict[str, tuple[str, ...]] = {}
        self._post: dict[str, tuple[str, ...]] = {}

    @classmethod
    def load(cls, path) -> "TaskKinds":
        k = cls()
        for r in _rows(Path(path)):
            kind = r["task_kind"].strip()
            if not kind:
                continue
            split = lambda s: tuple(  # noqa: E731
                x.strip() for x in (s or "").split("|") if x.strip())
            t = TaskKind(
                kind,
                r["ref_kind"].strip() or "*",
                r["참조_필드"].strip(),
                r["사거리_종류"].strip(),
                split(r["행동_후보"]),
                (r.get("비고") or "").strip(),
                split(r.get("선행_행동")),
                split(r.get("후행_행동")),
            )
            for field, store in (("참조_필드", (t.ref_field, k._ref)),
                                 ("사거리_종류", (t.fire_kind, k._fire)),
                                 ("선행_행동", (t.pre_labels, k._pre)),
                                 ("후행_행동", (t.post_labels, k._post))):
                value, table = store
                if kind in table and table[kind] != value:
                    raise ValueError(
                        f"task_kinds.csv: {kind}의 {field}가 행마다 다르다 "
                        f"({table[kind]!r} vs {value!r})")
                table[kind] = value
            k._by_key[(kind, t.ref_kind)] = t
        return k

    def pre_labels(self, task_kind: str) -> tuple[str, ...]:
        return self._pre.get(task_kind, ())

    def post_labels(self, task_kind: str) -> tuple[str, ...]:
        return self._post.get(task_kind, ())

    def known(self, task_kind: str) -> bool:
        return task_kind in self._ref

    def get(self, task_kind: str, ref_kind: str) -> TaskKind | None:
        return (self._by_key.get((task_kind, ref_kind))
                or self._by_key.get((task_kind, "*")))

    def ref_field(self, task_kind: str) -> str:
        if task_kind not in self._ref:
            raise KeyError(f"task_kinds.csv에 없는 task_kind: {task_kind}")
        return self._ref[task_kind]

    def fire_kind(self, task_kind: str) -> str:
        if task_kind not in self._fire:
            raise KeyError(f"task_kinds.csv에 없는 task_kind: {task_kind}")
        return self._fire[task_kind]
