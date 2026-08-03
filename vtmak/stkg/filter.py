"""입력 행을 네 갈래 중 하나로 판정한다.

제외 대상은 스펙 §6에서 확정했다. 판정을 코드 한 곳에 모아 두는 이유는
'어디선가 조용히 걸러졌다'가 생기지 않게 하기 위해서다. 모든 행은 여기서
꼬리표를 받고, export가 그 꼬리표대로 회계를 맞춘다.
"""
from __future__ import annotations

import re
from enum import Enum

# 시뮬레이터 인프라. 원문에 등장하지 않고 물리 객체도 아니다.
# Force 노드는 좌표가 (42.32429274, 45.00000000) 고정 쓰레기값이다.
#
# 이름을 그대로 나열하지 않고 번호를 패턴으로 받는다. VR-Forces가 몇 개를
# 만드는지는 시나리오·세션마다 다르다 — 실측에서 Observer가 1개인 줄 알고
# "Observer 1"만 적었더니 다음 내보내기에 Observer 2가 생겨 767행이 관측
# 데이터인 척 위치 테이블로 새어 들어갔다.
_RE_INFRA = re.compile(r"\d+ Force|Observer \d+|GlobalEnv \d+")

# 회귀 방지·문서용. 실측에서 실제로 본 이름들이다. 판정은 _RE_INFRA가 한다.
INFRA_SUBJECTS = frozenset({
    "1 Force", "2 Force", "3 Force",
    "Observer 1", "Observer 2", "GlobalEnv 1",
})

# E + 숫자만. 62종이 한 시각(07:13:22)에 동시 등장하고 정지하는 일괄 스폰이라
# 어떤 사격과도 짝지을 수 없다(스펙 §6.2). ENINF001 같은 엔티티가 여기 걸리면
# 적군이 통째로 사라지므로 fullmatch로 못박는다.
_RE_EFFECT = re.compile(r"E\d+")

# 초기화 안 된 타임스탬프. UAV 2에 182행, UAV 3에 15행.
_EPOCH_PREFIX = "1970-"


class Disposition(str, Enum):
    KEEP = "keep"
    DROP_INFRA = "drop_infra"
    DROP_EFFECT = "drop_effect"
    QUARANTINE_EPOCH = "quarantine_epoch"


def classify(subject: str, timestamp: str) -> Disposition:
    if _RE_INFRA.fullmatch(subject):
        return Disposition.DROP_INFRA
    if _RE_EFFECT.fullmatch(subject):
        return Disposition.DROP_EFFECT
    if timestamp.startswith(_EPOCH_PREFIX):
        return Disposition.QUARANTINE_EPOCH
    return Disposition.KEEP
