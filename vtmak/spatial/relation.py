"""순수 판정. 파일도 상태도 시계도 없다.

이미 계산된 기하값과 임계값만 받아 한 가지 질문에 답한다. 순수하게 두는 이유는
경계값을 시뮬레이터 없이 손으로 짠 입력으로 찌를 수 있어야 하기 때문이다.

방출 정책(소속 필터·Follow 제외)은 여기 없다. frame.py가 맡는다.
"""
from __future__ import annotations

from .profile import EntityProfile
from .thresholds import Thresholds


def next_to_threshold(a: EntityProfile, b: EntityProfile,
                      thresholds: Thresholds) -> float:
    """이 쌍의 근접 컷. 큰 쪽 객체에 맞춰 늘린다."""
    return thresholds.next_to_multiplier * max(a.spacing_m, b.spacing_m)


def judge_next_to(distance: float, a: EntityProfile | None,
                  b: EntityProfile | None, thresholds: Thresholds) -> bool:
    """거리만 본다.

    방위를 보지 않으므로 '옆에 있다'가 좌우를 뜻하지 않는다. 좌우를 담으려면
    heading이 필요해지고, 그 순간 이 관계는 방향 관계가 된다 — 방향은
    in_front_of·behind가 이미 맡는다.

    하한은 없다. 좌표가 겹친 쌍도 next_to다. 겹침은 관계 정의가 아니라 데이터
    품질 문제라 따로 보고한다.
    """
    if a is None or b is None:
        return False
    return distance <= next_to_threshold(a, b, thresholds)


def relative_bearing_deg(heading_deg: float, bearing_deg: float) -> float:
    """bearing을 heading 기준으로 본 각도. (-180, 180].

    정반대는 -180이 아니라 +180이다. 두 값이 갈리면 behind 경계가 한쪽에서만
    성립한다.
    """
    value = (bearing_deg - heading_deg) % 360.0
    return value - 360.0 if value > 180.0 else value


def judge_direction(distance: float, relative_bearing: float | None,
                    thresholds: Thresholds) -> str | None:
    """'in_front_of' 또는 'behind' 또는 None.

    relative_bearing은 호출부가 목적어 기준으로 계산해 넘긴다:
    relative_bearing_deg(목적어 heading, bearing(목적어 → 주어)).
    (A, in_front_of, B)는 B의 프레임에서 판정한다. A의 방위는 쓰지 않는다.

    측면 90° 두 구간은 의도적으로 아무것도 내지 않는다. 좌우는 범위 밖이라
    빔 방향의 쌍은 방향 관계가 없다 — 가까운 쪽으로 우겨 넣으면 안 된다.

    좌표가 겹친 쌍도 아무것도 내지 않는다. 같은 자리에서는 방위가 정의되지
    않고, 부동소수 잔차가 사분면을 무작위로 고른다.
    """
    if relative_bearing is None:
        return None
    if distance < thresholds.min_bearing_distance_m:
        return None
    if distance > thresholds.interest_distance_m:
        return None
    offset = abs(relative_bearing)
    if offset <= thresholds.front_sector_deg:
        return "in_front_of"
    if offset > thresholds.behind_sector_deg:
        return "behind"
    return None
