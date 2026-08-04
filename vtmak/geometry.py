"""좌표 — golden 지형점 앵커 → WGS84 → ECEF.

v2까지는 시나리오 기하를 로컬 미터로 직접 선언했다. golden에 시나리오 지명이
하나도 없었기 때문이다. 이제 사람이 golden(`yewon_test.oob`)에 지명 통제점을
찍어 두었으므로 그 실좌표를 정본으로 쓴다. 선언 좌표·scale·해안선 모델은
사라졌다 — 지형점 자체가 육지 보증이다.

레이아웃 파일은 `scripts/01_harvest_layout.py`가 만든다. 여기서는 읽기만 한다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

ZERO = (0.0, 0.0, 0.0)

# 육지가 보증되지 않는 좌표 출처. golden은 사람이 지형 위에 찍은 점이라 안전하고,
# 규칙으로 민 점(derived)과 옮긴 점(relocated)은 지형이 확인되지 않았다.
UNVERIFIED_TERRAIN_SRC = ("derived", "relocated")

# WGS84 타원체 상수. .scnx의 (location X Y Z)는 ECEF geocentric 미터다.
_WGS84_A = 6378137.0
_WGS84_E2 = 6.69437999014e-3  # 이심률² = 2f - f²


def _deg_scales(lat_deg: float) -> tuple[float, float]:
    """주어진 위도에서 위도 1도·경도 1도가 각각 몇 미터인가.

    상수 110574/111320(적도 기준)을 쓰면 21°N에서 위도 방향이 0.13% 틀어진다.
    사거리 판정이 '선언한 미터 = 실제 미터'에 의존하므로 위도별로 계산한다.
    """
    phi = math.radians(lat_deg)
    s = math.sin(phi)
    w = 1.0 - _WGS84_E2 * s * s
    # 자오선 곡률반경 M, 묘유선 곡률반경 N
    m_rad = _WGS84_A * (1.0 - _WGS84_E2) / (w ** 1.5)
    n_rad = _WGS84_A / math.sqrt(w)
    return (m_rad * math.pi / 180.0,
            n_rad * math.cos(phi) * math.pi / 180.0)


@dataclass(frozen=True)
class Coord:
    lat: float
    lon: float
    alt: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.lat, self.lon, self.alt)

    def is_zero(self) -> bool:
        return self.as_tuple() == ZERO

    def to_ecef(self) -> tuple[float, float, float]:
        """WGS84 geodetic(도, m) → ECEF geocentric 미터."""
        lat, lon = math.radians(self.lat), math.radians(self.lon)
        sin_lat = math.sin(lat)
        n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
        x = (n + self.alt) * math.cos(lat) * math.cos(lon)
        y = (n + self.alt) * math.cos(lat) * math.sin(lon)
        z = (n * (1.0 - _WGS84_E2) + self.alt) * sin_lat
        return (x, y, z)

    @classmethod
    def from_ecef(cls, x: float, y: float, z: float) -> "Coord":
        """ECEF geocentric 미터 → WGS84 geodetic(도, m). Bowring 근사."""
        b = _WGS84_A * math.sqrt(1.0 - _WGS84_E2)
        ep2 = _WGS84_E2 / (1.0 - _WGS84_E2)
        p = math.hypot(x, y)
        if p == 0.0:  # 극점
            lat = math.copysign(math.pi / 2, z)
            return cls(math.degrees(lat), 0.0, abs(z) - b)
        th = math.atan2(z * _WGS84_A, p * b)
        lat = math.atan2(z + ep2 * b * math.sin(th) ** 3,
                         p - _WGS84_E2 * _WGS84_A * math.cos(th) ** 3)
        lon = math.atan2(y, x)
        n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * math.sin(lat) ** 2)
        alt = p / math.cos(lat) - n
        return cls(math.degrees(lat), math.degrees(lon), alt)


def ground_distance(a: Coord, b: Coord) -> float:
    """두 좌표 사이 거리(m). 사거리 판정의 유일한 거리 함수.

    ECEF 직선거리다. VR-Forces가 3차원 ECEF 공간에서 사거리를 재므로 같은
    기준을 쓴다. 7km 범위에서 현(弦)과 호(弧)의 차는 0.2mm 미만이라 무시한다.
    구형 지구 haversine을 쓰면 21°N에서 0.4% 커져 레이아웃 선언값과 어긋난다.
    """
    return math.dist(a.to_ecef(), b.to_ecef())


class BattlefieldLayout:
    """지명 → 좌표. golden 지형점의 실좌표를 그대로 쓴다.

    없는 지명은 예외 대신 ZERO를 돌려준다. 커버리지 리포트가 한 곳(G0/G3)에서
    나와야 어떤 지명이 비었는지 한 번에 보이기 때문이다.
    """

    def __init__(self, data: dict) -> None:
        self.layout_id: str = data.get("layout_id", "")
        self.terrain: str = data.get("terrain", "")
        self.axis_bearing_deg: float = float(data.get("axis_bearing_deg", 0.0))
        self._coord: dict[str, Coord] = {}
        self._src: dict[str, str] = {}
        for k, v in (data.get("locations") or {}).items():
            self._coord[k] = Coord(float(v["lat"]), float(v["lon"]),
                                   float(v.get("alt", 0.0)))
            self._src[k] = (v.get("src") or "golden").strip()
        self._static: dict[str, str] = dict(data.get("static_targets") or {})

    @classmethod
    def load(cls, path) -> "BattlefieldLayout":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def location_ids(self) -> list[str]:
        return sorted(self._coord)

    def has(self, location_id: str) -> bool:
        return location_id in self._coord

    def source_of(self, location_id: str) -> str:
        """golden = 사람이 찍은 지형점, derived = 규칙으로 민 점,
        relocated = golden 점을 relocate 규칙으로 옮긴 점(뒤 둘은 지형 미확인)."""
        return self._src.get(location_id, "")

    def derived_ids(self) -> list[str]:
        return sorted(k for k, v in self._src.items() if v == "derived")

    def unverified_terrain_ids(self) -> list[str]:
        """지형(물·급경사)이 확인되지 않은 지명. golden 지형점만 육지가 보증된다."""
        return sorted(k for k, v in self._src.items()
                      if v in UNVERIFIED_TERRAIN_SRC)

    def static_target(self, object_id: str) -> str | None:
        """정적 객체(포병진지·킬존 등) → 바인딩된 지명. 없으면 None."""
        return self._static.get(object_id)

    def static_ids(self) -> set[str]:
        """엔티티로 만들지 않는 정적 객체 id 집합."""
        return set(self._static)

    def coord(self, location_id: str) -> Coord:
        return self._coord.get(location_id) or Coord(*ZERO)

    def offset_coord(self, location_id: str, east_m: float,
                     north_m: float) -> Coord:
        """지명 기준 로컬 오프셋 좌표(동 +x, 북 +y 미터). jitter가 쓴다."""
        c = self._coord.get(location_id)
        if c is None:
            return Coord(*ZERO)
        m_lat, m_lon = _deg_scales(c.lat)
        return Coord(c.lat + north_m / m_lat, c.lon + east_m / m_lon, c.alt)

    def distance_m(self, a_id: str, b_id: str) -> float:
        return ground_distance(self.coord(a_id), self.coord(b_id))
