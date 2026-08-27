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
from .plan import PLACEHOLDER_TOKENS, balanced
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


def validate_interaction_plan(spec: ScnxSpec,
                              config: EnrichmentConfig) -> list[Violation]:
    """G4 — 교전 슬롯과 큐 도달 가능성.

    G3가 '파일이 말이 되는가'라면 G4는 '이 큐가 VR-Forces에서 끝까지
    도는가'다. 여기서 잡히는 것들은 전부 실행 로그에서만 보이던 실패였다.

    C4.8(대기 초 미치환)은 두지 않는다 — Task 6 리뷰 라운드 1 finding 3.
    build_engagement_steps가 모든 슬롯 대기에 with_wait_seconds를
    무조건 부르고, 그 함수는 seconds-to-wait 자리가 없으면 예외를
    던진다(plan.py). 치환이 조용히 빠지는 경로가 애초에 없으므로 이
    검사가 잡겠다는 결함은 발생할 수 없다. 반대 방향은 실제로 위험하다 —
    wait_needed_for가 정당하게 60초를 돌려주면 치환 결과가 템플릿
    기본값과 바이트 단위로 같아져서, 옳게 계산된 빌드를 차단한다.
    저작 시점의 예외가 게이트보다 강한 강제이므로 그쪽에 맡긴다.
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
    # enabled=False는 '보강을 끈다'는 정상 설정이지, 결함이 아니다 — 그때는
    # added=0이 기대값이므로 하한·SPO 검사 둘 다 건너뛴다(Task 6 리뷰 라운드
    # 1 minor: 끄면 컴파일이 실패하던 회귀).
    if config.enabled:
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
            # 살아 있는 PLN에 자리표시자가 남으면 안 된다. 토큰 목록은
            # plan.py가 실제로 채우는 것과 같은 튜플이다(따로 두면 어긋난다
            # — Task 6 리뷰 라운드 1 finding 4: 다섯 개만 보다가
            # ENTITY_UUID·CONTROL_POINT_UUID 두 개를 놓쳤다). 어느 토큰이
            # 걸렸는지 메시지에 남겨 grep 없이 바로 보이게 한다.
            for tok in PLACEHOLDER_TOKENS:
                if tok in step.pln:
                    out.append(Violation(
                        "G4", "C4.9",
                        f"{oid}: 자리표시자 미치환 {tok} {step.event_id}"))
        # C4.4 — 사격 두 단계 인접. live 안의 **위치**로 비교한다(Task 6
        # 리뷰 라운드 1 finding 1). slot_id로 먼저 걸러낸 부분열끼리
        # kinds[-2:]를 비교하면, 그 사이에 낀 남의 task가 필터링 단계에서
        # 이미 사라져 있어 정작 이 검사가 이름으로 내건 '인접하지 않는다'는
        # 조건을 검사하지 못한다 — 부분열은 원소가 몇 개든 항상 자기 자신의
        # 마지막 두 원소로 끝나므로 kinds[-2:]는 절대 실패하지 않았다.
        pos = {id(s): i for i, s in enumerate(live)}
        for slot_id in sorted({s.slot_id for s in live if s.slot_id}):
            block = [s for s in live if s.slot_id == slot_id]
            fire = [s for s in block if s.task_kind == "fire_direct"]
            supp = [s for s in block if s.task_kind == "suppress"]
            if len(fire) != 1 or len(supp) != 1:
                out.append(Violation(
                    "G4", "C4.4",
                    f"{oid} {slot_id}: 사격 단계 수 이상 "
                    f"(fire {len(fire)}, suppress {len(supp)})"))
                continue
            if pos[id(supp[0])] != pos[id(fire[0])] + 1:
                between = [s.task_kind for s in
                          live[pos[id(fire[0])] + 1:pos[id(supp[0])]]]
                out.append(Violation(
                    "G4", "C4.4",
                    f"{oid} {slot_id}: 사격 두 단계 사이에 {between}"))
    return out
