"""G3 — .scnx 정합성.

선행 프로젝트의 G3에 DIS 커버리지 검사를 더했다. golden에 DIS 완전일치
레코드가 없는 엔티티는 VR-Forces에서 실행 hang을 일으키므로, 파일을 쓰기
전에 잡는다.

PlanStep이 pln 없이 issue만 남긴 경우(C3.5)는 원인에 따라 심각도가 다르다.
무기체계 미확정으로 태스크를 못 만든 것은 설계가 인정한 사실이라 보고만
하고(설계 스펙 §8.3), 나머지는 차단한다.
"""
from __future__ import annotations

from ..gates import REPORT, Violation
from ..registry import UNCLASSIFIED
from .catalog import DisCatalog
from .golden import Golden
from .plan import balanced
from .spec import ScnxSpec


def check_g3(spec: ScnxSpec, golden: Golden,
             dis: DisCatalog) -> list[Violation]:
    out: list[Violation] = []
    uuids: set[str] = set()
    tg_by_id = {e.object_id: e.type_group for e in spec.entities}

    for e in spec.entities:
        if e.dis is None:
            out.append(Violation("G3", "C3.1",
                                 f"DIS 없음: {e.object_id} ({e.entity_class})"))
        elif golden.entity_by_dis(e.dis) is None:
            out.append(Violation("G3", "C3.2",
                                 f"golden 레코드 없음: {e.entity_class} {e.dis}"))
        if e.coord.is_zero():
            out.append(Violation("G3", "C3.3", f"좌표 미할당: {e.object_id}"))
        if e.uuid in uuids:
            out.append(Violation("G3", "C3.4", f"uuid 중복: {e.uuid}"))
        uuids.add(e.uuid)

    for c in spec.control_objects:
        if c.coord is not None and c.coord.is_zero():
            out.append(Violation("G3", "C3.3", f"좌표 미할당: {c.ref_id}"))
        if c.uuid in uuids:
            out.append(Violation("G3", "C3.4", f"uuid 중복: {c.uuid}"))
        uuids.add(c.uuid)

    for oid, steps in sorted(spec.entity_plans.items()):
        for s in steps:
            if s.pln is None:
                if not s.issues:
                    continue
                unclassified = tg_by_id.get(oid) == UNCLASSIFIED
                out.append(Violation(
                    "G3", "C3.5", f"{oid} {s.event_id}: {'; '.join(s.issues)}",
                    REPORT if unclassified else "BLOCK"))
                continue
            if not balanced(s.pln):
                out.append(Violation("G3", "C3.6",
                                     f"괄호 불균형: {oid} {s.event_id}"))
            for r in s.refs:
                if r not in uuids:
                    out.append(Violation("G3", "C3.7",
                                         f"참조 미해결: {oid} {s.event_id} → {r}"))
    return out
