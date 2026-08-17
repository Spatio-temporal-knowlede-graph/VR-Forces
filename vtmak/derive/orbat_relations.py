"""R8~R12 — 편제에서 부대 사실을 만든다.

시뮬레이터가 aggregate를 CSV로 내보내는지에 의존하지 않는다. 내보내기 판이
바뀌어도 같은 결과가 나와야 하고, 부대 fact가 관측 유무에 좌우되면 데이터셋의
관계 구성이 판마다 달라진다.

시간축: partOf·supports·reinforces는 t0에 한 번 낸다. 백마고지 데이터셋은
관계를 매 관측마다 복제해 test 20,210행 중 18,189행(90%)이 앞 시각 fact의
반복이었다 — '직전에 본 fact를 다시 낸다'는 규칙 하나로 90%를 맞춘다. 그 함정을
반복하지 않는다. 소속이 실제로 바뀌면 그 시점에 다시 낸다.
"""
from __future__ import annotations

from .relations import Relation, RuleResult

# 편제표가 선언한 값. 관측에서 파생한 relations.LAYER("derived")와 섞이면
# 어느 쪽이 만든 값인지 산출물에서 되물어야 한다.
LAYER_ORBAT = "orbat"

# R8·R9의 provenance. R1~R7은 event_id를 근거로 대 원문 문장까지 되짚을 수
# 있지만, 이 둘은 이벤트를 안 읽는다 — 근거가 될 event_id가 애초에 없다.
# 대신 그 값을 실제로 선언한 파일을 가리킨다. (u.unit_id,)나 (a, b)처럼
# 관계 자신의 subject/object를 provenance로 되풀이하면 "이 사실의 근거는
# 이 사실"이라는 동어반복이 되어 추적에 쓸모가 없다.
ORBAT_CONFIG_PATH = "config/orbat.json"


def r8_part_of(orbat) -> RuleResult:
    """partOf(엔티티, 소대) · partOf(소대, 중대) · partOf(중대, 대대).

    체인을 접어서 partOf(엔티티, 대대)까지 내지 않는다. 2단계 전이를 규칙이
    배울 재료를 남기는 것이 이 관계를 넣는 이유다.
    """
    rels = []
    for u in orbat.units():
        for oid in u.members:
            rels.append(Relation("R8", "partOf", oid, u.unit_id,
                                 (ORBAT_CONFIG_PATH,), LAYER_ORBAT))
        if u.parent:
            rels.append(Relation("R8", "partOf", u.unit_id, u.parent,
                                 (ORBAT_CONFIG_PATH,), LAYER_ORBAT))
    return RuleResult(tuple(rels))


def r9_task_organization(orbat) -> RuleResult:
    """supports·reinforces. 원문에 근거가 없어 편제표가 선언한 값이다."""
    rels = []
    for a, b in orbat.supports():
        rels.append(Relation("R9", "supports", a, b, (ORBAT_CONFIG_PATH,),
                             LAYER_ORBAT))
    for a, b in orbat.reinforces():
        rels.append(Relation("R9", "reinforces", a, b, (ORBAT_CONFIG_PATH,),
                             LAYER_ORBAT))
    return RuleResult(tuple(rels))
