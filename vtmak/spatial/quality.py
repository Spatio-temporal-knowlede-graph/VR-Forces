"""관계를 못 만든 이유를 모은다. 리포트가 산출물보다 커지지 않게 묶어서."""
from __future__ import annotations

from .models import QualityIssue

UNMAPPED_ENTITY_TYPE = "UNMAPPED_ENTITY_TYPE"
MISSING_HEADING = "MISSING_HEADING"
MISSING_FORCE = "MISSING_FORCE"
COORDINATE_COLLISION = "COORDINATE_COLLISION"
SAMPLING_GAP = "SAMPLING_GAP"
CLASS_JOIN_MISMATCH = "CLASS_JOIN_MISMATCH"


class QualityLog:
    """(시각, 코드)마다 객체 집합 하나로 묶는다.

    편대 추종이 좌표를 한 점으로 붕괴시키면 동일좌표 쌍이 시각당 약 4,945개
    나온다. 쌍마다 한 줄씩 내면 리포트가 관계 산출물보다 커진다.
    """

    def __init__(self) -> None:
        self._groups: dict[tuple[str, str], tuple[set[str], str]] = {}

    def record(self, timestamp: str, subjects: list[str], code: str,
               detail: str) -> None:
        key = (timestamp, code)
        names, kept = self._groups.setdefault(key, (set(), detail))
        names.update(subjects)
        if not kept and detail:
            self._groups[key] = (names, detail)

    def issues(self) -> list[QualityIssue]:
        return [
            QualityIssue(timestamp=ts, subjects=" ".join(sorted(names)),
                         code=code, detail=detail)
            for (ts, code), (names, detail) in sorted(self._groups.items())
        ]

    @property
    def count(self) -> int:
        return len(self._groups)
