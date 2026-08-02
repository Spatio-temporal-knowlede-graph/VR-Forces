"""무기 사거리 표와 판정.

선행 프로젝트는 사거리 미달 간접사격을 조용히 스킵했다. 그 결과 '의도한
스킵'과 '레이아웃이 잘못됨'이 구분되지 않았다. 여기서는 판정 결과를
문자열로 돌려주고, 판단은 G0가 한다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .norm import norm

OK = "OK"
TOO_CLOSE = "TOO_CLOSE"
TOO_FAR = "TOO_FAR"
NO_WEAPON = "NO_WEAPON"
UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class RangeSpec:
    min_m: float
    max_m: float


def _num(s: str | None) -> float | None:
    s = (s or "").strip()
    return float(s) if s else None


class WeaponRanges:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], RangeSpec] = {}
        self._unverified: set[str] = set()
        self._classes: list[str] = []

    @classmethod
    def load(cls, path) -> "WeaponRanges":
        wr = cls()
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                ecls = (row["entity_class"] or "").strip()
                if not ecls:
                    continue
                wr._classes.append(ecls)
                key = norm(ecls)
                if (row.get("unverified") or "").strip() == "1":
                    wr._unverified.add(key)
                for kind, lo_col, hi_col in (
                    ("direct", "direct_min_m", "direct_max_m"),
                    ("indirect", "indirect_min_m", "indirect_max_m"),
                ):
                    lo, hi = _num(row.get(lo_col)), _num(row.get(hi_col))
                    if lo is not None and hi is not None:
                        wr._by_key[(key, kind)] = RangeSpec(lo, hi)
        return wr

    def classes(self) -> list[str]:
        return list(self._classes)

    def spec(self, entity_class: str, fire_kind: str) -> RangeSpec | None:
        return self._by_key.get((norm(entity_class), fire_kind))

    def check(self, entity_class: str, fire_kind: str,
              distance_m: float) -> str:
        key = norm(entity_class)
        if key in self._unverified:
            return UNVERIFIED
        rs = self._by_key.get((key, fire_kind))
        if rs is None:
            return NO_WEAPON
        if distance_m < rs.min_m:
            return TOO_CLOSE
        if distance_m > rs.max_m:
            return TOO_FAR
        return OK
