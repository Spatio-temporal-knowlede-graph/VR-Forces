"""derive_rules.csv 로더 — 규칙이 쓰는 값은 코드가 아니라 표에 있다.

임계값 0.25나 '제압→suppresses' 같은 것을 코드에 박으면, 왜 그 숫자인지가
diff에서 사라진다. 표에는 note 열이 있어 근거(실측 건수)가 값 옆에 남는다.

조회는 전부 시끄럽다. 없는 키에 기본값을 돌려주면 규칙이 0건을 낸 이유가
'표에 오타'인지 '데이터에 없음'인지 구분되지 않는다.
"""
from __future__ import annotations

import csv
from pathlib import Path

# 표가 쓸 수 있는 kind. 오타 하나가 규칙을 조용히 0건으로 만드는 걸 막는다.
_KINDS = {"hit_state", "area_state", "threshold", "flag"}

_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0"}


class DeriveRules:
    def __init__(self) -> None:
        self._hit_states: dict[str, tuple[str, str]] = {}
        self._area_state: tuple[str, str] | None = None
        self._thresholds: dict[str, float] = {}
        self._flags: dict[str, bool] = {}

    @classmethod
    def load(cls, path) -> "DeriveRules":
        c = cls()
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                kind = r["kind"].strip()
                key, value = r["key"].strip(), r["value"].strip()
                if kind not in _KINDS:
                    raise ValueError(
                        f"derive_rules.csv({r['rule_id']}): 모르는 kind {kind}")
                if kind == "hit_state":
                    c._hit_states[key] = (r["rule_id"].strip(), value)
                elif kind == "area_state":
                    before, _, after = key.partition(">")
                    c._area_state = (before.strip(), after.strip())
                elif kind == "threshold":
                    c._thresholds[key] = float(value)
                else:
                    c._flags[key] = _parse_flag(r["rule_id"], key, value)
        return c

    def hit_states(self) -> dict[str, tuple[str, str]]:
        """상태 이름 → (rule_id, 관계 이름). 제압 → ("R1", "suppresses").

        rule_id를 같이 돌려준다. 관계 이름만 주면 그게 R1인지 R2인지를 코드가
        다시 정해야 하고, 그 순간 표 밖에 두 번째 정본이 생긴다.
        """
        return dict(self._hit_states)

    def area_state(self) -> tuple[str, str]:
        """간접사격 탄착을 나타내는 지역 상태 전이 (이전, 이후)."""
        if self._area_state is None:
            raise KeyError("derive_rules.csv에 area_state 행이 없다")
        return self._area_state

    def threshold(self, key: str) -> float:
        if key not in self._thresholds:
            raise KeyError(f"derive_rules.csv에 없는 임계값: {key}")
        return self._thresholds[key]

    def flag(self, key: str) -> bool:
        if key not in self._flags:
            raise KeyError(f"derive_rules.csv에 없는 플래그: {key}")
        return self._flags[key]


def _parse_flag(rule_id: str, key: str, value: str) -> bool:
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(
        f"derive_rules.csv({rule_id}): {key}의 값 {value!r}이 true/false가 아니다")
