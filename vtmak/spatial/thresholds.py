"""조절 가능한 값은 전부 여기 있다. 다른 모듈에 숫자 상수를 두지 않는다.

설계 문서가 임시값으로 표시한 것들은 ver2.0 재수집 뒤에 다시 잡는다. 한 파일에
모아 두는 이유가 그것이다 — 재보정이 코드 수정이 아니라 설정 수정이어야 한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path

# type_group → 최소 이격 거리(m). VR-Forces 배치 규칙에서 그대로 가져왔다.
SPACING_BY_TYPE_GROUP: dict[str, float] = {
    "보병 - 소총(M4 계열)": 2.0,
    "보병 - RPG 계열": 2.0,
    "차량/장갑차 - M2HB 계열": 10.0,
    "포병 - 박격포(m9333he 계열)": 12.0,
    "포병 - 155mm 자주포": 15.0,
    "미사일 발사대 - Patriot": 15.0,
}

# 대칭 술어. approach는 아직 안 만들지만 의미는 지금 확정돼 있으므로 여기 둔다.
SYMMETRIC_PREDICATES: frozenset[str] = frozenset({"next_to", "approach"})

# 설계 §10이 "임시값"으로 표시한 필드 이름. ver2.0 재수집 뒤 재보정 대상이다.
# max_merge_gap_s는 여기 없다 — 관측된 정상 간격의 최댓값이라는 실측 근거가
# 있어(§2.3) 임시값이 아니다(§10 말미). 매니페스트가 이 목록을 그대로 노출해
# 소비자가 다섯 값 중 어느 것이 아직 근거가 얇은지 알 수 있게 한다.
PROVISIONAL: frozenset[str] = frozenset({
    "interest_distance_m", "closing_rate_mps", "next_to_multiplier",
    "window_s", "min_bearing_distance_m",
})

# 이번 범위가 실제로 내는 술어. approach는 시뮬레이션 시각이 확인되면 붙인다.
PREDICATES: tuple[str, ...] = ("next_to", "in_front_of", "behind", "in_range_of")

_STORAGE_CHOICES = frozenset({"canonical", "both"})


@dataclass(frozen=True)
class Thresholds:
    interest_distance_m: float = 500.0
    next_to_multiplier: float = 3.0
    max_merge_gap_s: float = 3.0
    min_bearing_distance_m: float = 0.5
    front_sector_deg: float = 45.0
    behind_sector_deg: float = 135.0
    symmetric_storage: str = "canonical"
    # approach 전용. 지금은 아무도 읽지 않는다 — 자리만 잡아 둔다.
    closing_rate_mps: float = 1.0
    window_s: float = 10.0
    version: str = "2026-08-26.1"

    @classmethod
    def load(cls, path: Path | None) -> "Thresholds":
        """JSON에서 덮어쓴다. 없는 키는 기본값을 유지한다."""
        base = cls()
        if path is None:
            return base
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        unknown = set(payload) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"모르는 임계값 키: {sorted(unknown)}")
        out = replace(base, **payload)
        if out.symmetric_storage not in _STORAGE_CHOICES:
            raise ValueError(
                f"symmetric_storage는 {sorted(_STORAGE_CHOICES)} 중 하나여야 한다")
        return out
