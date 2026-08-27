"""G3 — .scnx 정합성.

선행 프로젝트의 G3에 DIS 커버리지 검사를 더했다. golden에 DIS 완전일치
레코드가 없는 엔티티는 VR-Forces에서 실행 hang을 일으키므로, 파일을 쓰기
전에 잡는다.

C3.8은 무기 실재 검사다. 태스크가 지정한 무기 이름이 그 모델에 실제로 없으면
객체는 사격 태스크를 실행하지 못한다. 이름은 golden `.oob`의 display-name이
정본이다(실측: 적 보병에게 "M4 rifle"을 지정하고 있었다 — 그 모델의 무기는
"AK-47"이다).

PlanStep이 pln 없이 issue만 남긴 경우(C3.5)는 원인에 따라 심각도가 다르다.
무기체계 미확정으로 태스크를 못 만든 것은 설계가 인정한 사실이라 보고만
하고(설계 스펙 §8.3), 나머지는 차단한다.
"""
from __future__ import annotations

import re

from ..gates import REPORT, Violation
from ..registry import UNCLASSIFIED
from .catalog import DisCatalog
from .engagements import EnrichmentConfig, expected_suppress_spo
from .golden import Golden
from .plan import balanced
from .spec import ScnxSpec


# 태스크 안에서 무기 이름이 들어가는 자리. variable-data-types 블록의
# "direct fire weapon" 같은 자료형 문자열은 여기 걸리지 않는다(값이 아니다).
_RE_WEAPON_SLOT = re.compile(
    r'\((?:weapon-to-fire|weapon-name|weapon)\s+"([^"]+)"'
    r'|\(DtRw\w+\s+\((?:useGun|gunToUse)\s+"([^"]+)"')
_WEAPON_TYPE_WORDS = {"direct fire weapon", "indirect fire weapon"}


def weapons_in(pln: str) -> set[str]:
    """플랜 조각이 지정한 무기 이름."""
    out: set[str] = set()
    for a, b in _RE_WEAPON_SLOT.findall(pln):
        w = a or b
        if w and w not in _WEAPON_TYPE_WORDS:
            out.add(w)
    return out


def check_weapons(spec: ScnxSpec, golden: Golden) -> list[Violation]:
    """태스크가 지정한 무기를 그 객체가 실제로 갖고 있는가."""
    out: list[Violation] = []
    seen: set[tuple[str, str]] = set()
    dis_by_id = {e.object_id: e.dis for e in spec.entities}
    cls_by_id = {e.object_id: e.entity_class for e in spec.entities}
    for oid, steps in sorted(spec.entity_plans.items()):
        d = dis_by_id.get(oid)
        if d is None:
            continue
        have = golden.weapons_of(d)
        for s in steps:
            if not s.pln:
                continue
            for w in sorted(weapons_in(s.pln)):
                if w.split(":")[0] in have:
                    continue
                key = (cls_by_id.get(oid, ""), w)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Violation(
                    "G3", "C3.8",
                    f"{cls_by_id.get(oid, oid)}에 없는 무기로 사격: {w!r} "
                    f"— 이 모델의 무기는 {sorted(have) or '없음'}"))
    return out


def check_g3(spec: ScnxSpec, golden: Golden,
             dis: DisCatalog) -> list[Violation]:
    out: list[Violation] = check_weapons(spec, golden)
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

    # 고정 객체는 다른 시나리오에서 복제해 온 레코드다. uuid가 우리 할당기와
    # 겹치면 VR-Forces가 한쪽만 인스턴스화한다 — 여기서 잡는다.
    for f in spec.fixed_objects:
        if f.coord.is_zero():
            out.append(Violation("G3", "C3.3", f"좌표 미할당: {f.marking}"))
        if f.uuid in uuids:
            out.append(Violation("G3", "C3.4",
                                 f"uuid 중복(고정 객체): {f.marking} {f.uuid}"))
        uuids.add(f.uuid)

    for oid, steps in sorted(spec.entity_plans.items()):
        for s in steps:
            if s.pln is None:
                if not s.issues:
                    continue
                # 일부러 안 만든 것과 못 만든 것을 가른다. skip_reason이 붙은
                # 것은 VR-Forces가 실행을 거부함이 실측된 조합이라 저작하지
                # 않기로 한 사실이고, 무기체계 미확정(미분류)도 설계가 인정한
                # 사실이다(설계 스펙 §8.3). 나머지는 결함이라 차단한다.
                intended = bool(s.skip_reason) or tg_by_id.get(oid) == UNCLASSIFIED
                out.append(Violation(
                    "G3", "C3.5", f"{oid} {s.event_id}: {'; '.join(s.issues)}",
                    REPORT if intended else "BLOCK"))
                continue
            if not balanced(s.pln):
                out.append(Violation("G3", "C3.6",
                                     f"괄호 불균형: {oid} {s.event_id}"))
            for r in s.refs:
                if r not in uuids:
                    out.append(Violation("G3", "C3.7",
                                         f"참조 미해결: {oid} {s.event_id} → {r}"))
    return out


# _fill(plan.py)·with_wait_seconds가 채우지 못하고 살아 있는 PLN에 남길 수
# 있는 자리표시자. 괄호 불균형은 C3.6(위)이 이미 잡으므로 여기서 다시
# 검사하지 않는다(설계 §12).
_PLACEHOLDERS = ("TARGET_UUID", "X Y Z", "SX SY SZ", "AZIMUTH_RAD",
                "ELEVATION_RAD")


def validate_interaction_plan(spec: ScnxSpec,
                              config: EnrichmentConfig) -> list[Violation]:
    """G4 — 교전 슬롯과 큐 도달 가능성.

    G3가 '파일이 말이 되는가'라면 G4는 '이 큐가 VR-Forces에서 끝까지
    도는가'다. 여기서 잡히는 것들은 전부 실행 로그에서만 보이던 실패였다.
    """
    out: list[Violation] = []
    seen_slot_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    factions = {e.object_id: e.faction for e in spec.entities}

    for slot in spec.engagement_slots:
        if slot.slot_id in seen_slot_ids:
            out.append(Violation("G4", "C4.1", f"slot_id 중복: {slot.slot_id}"))
        seen_slot_ids.add(slot.slot_id)
        pair = (slot.shooter_id, slot.target_id)
        if slot.origin == "enrichment":
            if pair in seen_pairs:
                out.append(Violation("G4", "C4.1", f"중복 신규 교전: {pair}"))
            seen_pairs.add(pair)
        if factions.get(slot.shooter_id) == factions.get(slot.target_id):
            out.append(Violation("G4", "C4.5",
                                 f"같은 진영 교전: {slot.slot_id} {pair}"))

    source = [s for s in spec.engagement_slots if s.origin == "source"]
    added = [s for s in spec.engagement_slots if s.origin == "enrichment"]
    if len(source) != 77:
        out.append(Violation("G4", "C4.6", f"원문 교전 슬롯 {len(source)}개 (77 기대)"))
    if not (config.min_new_unique_pairs <= len(added)
            <= config.max_new_unique_pairs):
        out.append(Violation("G4", "C4.6", f"신규 교전 슬롯 {len(added)}개"))
    spo = expected_suppress_spo(tuple(spec.engagement_slots))
    if len(spo) < config.min_expected_suppress_spo:
        out.append(Violation("G4", "C4.7",
                             f"예상 고유 제압사격 SPO {len(spo)}개 "
                             f"({config.min_expected_suppress_spo} 미만)"))

    for oid, steps in sorted(spec.entity_plans.items()):
        live = [s for s in steps if s.pln]
        for i, step in enumerate(live):
            if 'task-type "follow-entity"' in step.pln and i + 1 < len(live):
                out.append(Violation(
                    "G4", "C4.2",
                    f"{oid}: 무기한 follow 뒤 후속 task "
                    f"({step.event_id} → {live[i + 1].event_id})"))
            if 'task-type "find_firing_position"' in step.pln or \
                    'task-type "find_cover"' in step.pln:
                out.append(Violation("G4", "C4.3",
                                     f"{oid}: 실패 task 잔존 {step.event_id}"))
            # C4.8은 slot_id가 붙은 대기 단계만 본다 — stopAt/stayAt 원문
            # 대기는 task_kind=wait이지만 slot_id가 없고, 수확된 기본
            # 60초를 그대로 쓰는 게 정상이다(전역 제약은 '유한하고 양수'만
            # 요구하고 60.0은 그 조건을 만족한다). slot 대기만 실제로
            # with_wait_seconds가 치환해야 하는 합성 값이라, 60.000000이
            # 남아 있으면 그 치환이 빠졌다는 결함 신호다.
            if step.slot_id and 'task-type "wait-duration"' in step.pln and \
                    "(seconds-to-wait 60.000000)" in step.pln:
                out.append(Violation("G4", "C4.8",
                                     f"{oid}: 대기 초 미치환 {step.event_id}"))
            if any(tok in step.pln for tok in _PLACEHOLDERS):
                out.append(Violation("G4", "C4.9",
                                     f"{oid}: 자리표시자 미치환 {step.event_id}"))
        for slot_id in sorted({s.slot_id for s in live if s.slot_id}):
            block = [s for s in live if s.slot_id == slot_id]
            kinds = [s.task_kind for s in block]
            if kinds[-2:] != ["fire_direct", "suppress"]:
                out.append(Violation("G4", "C4.4",
                                     f"{oid} {slot_id}: 사격 두 단계가 인접하지 "
                                     f"않는다 {kinds}"))
    return out
