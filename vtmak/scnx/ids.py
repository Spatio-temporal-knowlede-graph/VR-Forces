"""결정적 UUID 발급.

파일 직접 생성 방식에서 가장 까다로운 문제는 '파일 간 ID 일관성'이다
(entity를 참조하는 plan, plan이 참조하는 route/target 등이 모두 같은 uuid를
가리켜야 한다). 무작위 uuid4 대신 (seed, key)에서 uuid5로 결정론적으로
발급하면, 같은 스펙에서 항상 같은 uuid가 나와 재현·비교가 가능하다.

seed를 바꾸면 전혀 다른 uuid 집합이 나오므로, 여러 시나리오 변형 간
uuid 충돌을 피하려면 시나리오 id를 seed로 준다.
"""
from __future__ import annotations

import uuid

# 프로젝트 고정 네임스페이스(임의의 uuid4 1회 생성값을 상수로 박음).
# 이 값을 바꾸면 모든 발급 uuid가 달라진다.
NAMESPACE = uuid.UUID("6f3a9c2e-1b47-5d8a-9e10-7c4d2f6b8a01")


class IdAllocator:
    """(seed, key) → uuid5. 같은 인자는 항상 같은 uuid."""

    def __init__(self, seed: str = "") -> None:
        self.seed = seed
        self._cache: dict[str, str] = {}

    def alloc(self, kind: str, key: str) -> str:
        """kind는 네임스페이스 구분자(entity/route/control_point/point/scenario)."""
        ck = f"{kind}:{key}"
        if ck not in self._cache:
            self._cache[ck] = str(uuid.uuid5(NAMESPACE, f"{self.seed}|{ck}"))
        return self._cache[ck]
