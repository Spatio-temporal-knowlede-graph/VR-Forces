"""지명 → DIS marking 코드.

`marking-text`는 DIS 네트워크 이름이라 11바이트 ASCII다. 한글 지명이 안
들어가서 통제점 marking이 `P{k}` 순번이었고, 시뮬레이터가 그 순번을 CSV로
그대로 내보내 지명이 사라졌다(실측: `Move-To Waypoint: "P3"`).

코드는 사람이 정한다. 자동 약어는 `LOC_남측제1방어선`과
`LOC_남측제1방어선전방`처럼 접두가 겹치는 쌍에서 읽을 수 없는 값이 나온다.
"""
from __future__ import annotations

import csv
from pathlib import Path


class PlaceCodes:
    def __init__(self) -> None:
        self._by_loc: dict[str, str] = {}
        self._by_code: dict[str, str] = {}

    @classmethod
    def load(cls, path) -> "PlaceCodes":
        pc = cls()
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                loc_id = (row["loc_id"] or "").strip()
                code = (row["code"] or "").strip()
                if not loc_id:
                    continue
                if not code:
                    raise ValueError(f"location_codes.csv: {loc_id}의 code가 비었다")
                if code in pc._by_code:
                    raise ValueError(
                        f"location_codes.csv: 코드 중복 {code} "
                        f"({pc._by_code[code]}, {loc_id})")
                pc._by_loc[loc_id] = code
                pc._by_code[code] = loc_id
        return pc

    def codes(self) -> dict[str, str]:
        return dict(self._by_loc)

    def code(self, loc_id: str) -> str:
        if loc_id not in self._by_loc:
            raise KeyError(f"location_codes.csv에 없는 지명: {loc_id}")
        return self._by_loc[loc_id]

    def loc_id(self, code: str) -> str:
        if code not in self._by_code:
            raise KeyError(f"location_codes.csv에 없는 코드: {code}")
        return self._by_code[code]
