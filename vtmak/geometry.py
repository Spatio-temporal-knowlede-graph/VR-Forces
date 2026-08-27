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


def deg_scales(lat_deg: float) -> tuple[float, float]:
    """위도 1도·경도 1도의 미터. _deg_scales의 공개 이름이다.

    격자 버킷을 도 단위로 나눌 때 필요하다. 이걸 안 내주면 호출부가 도-미터
    환산을 다시 짜게 되고, 그 순간 거리 기준이 두 벌이 된다.
    """
    return _deg_scales(lat_deg)


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


def _ned_basis(lat_deg: float, lon_deg: float
               ) -> tuple[tuple[float, float, float], ...]:
    """지점의 국지 NED 축을 ECEF 성분으로. (북, 동, 하) 순."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sla, cla = math.sin(lat), math.cos(lat)
    slo, clo = math.sin(lon), math.cos(lon)
    north = (-sla * clo, -sla * slo, cla)
    east = (-slo, clo, 0.0)
    down = (-cla * clo, -cla * slo, -sla)
    return north, east, down


def tait_bryan(c: Coord, heading_rad: float, pitch_rad: float = 0.0,
               roll_rad: float = 0.0) -> tuple[float, float, float]:
    """국지 방위·피치·롤 → `.oob`의 `(orientation-tait-bryan ψ θ φ)`.

    VR-Forces의 자세는 DIS 오일러각이다 — **ECEF 기준**이라 같은 방위라도
    위경도가 다르면 값이 달라진다. 그래서 방위각을 그대로 써 넣을 수 없다.

    DIS 정의에서 세계→동체 방향코사인 행렬은 R_x(φ)·R_y(θ)·R_z(ψ)이고, 그
    행들이 동체 축(전·우·하)을 ECEF 성분으로 적은 것이다. 따라서 전방 축 f와
    우현 축 r, 하방 축 d를 국지 NED에서 만들어 ECEF로 옮긴 뒤 되읽으면 된다.

        ψ = atan2(f_y, f_x)
        θ = -asin(f_z)
        φ = atan2(r_z, d_z)

    되읽기(`heading_from_tait_bryan`)로 왕복이 맞는지 테스트가 확인한다.
    """
    n, e, dn = _ned_basis(c.lat, c.lon)
    sh, ch = math.sin(heading_rad), math.cos(heading_rad)
    sp, cp = math.sin(pitch_rad), math.cos(pitch_rad)
    sr, cr = math.sin(roll_rad), math.cos(roll_rad)
    # 동체 축을 NED 성분으로
    fwd_ned = (ch * cp, sh * cp, -sp)
    rgt_ned = (ch * sp * sr - sh * cr, sh * sp * sr + ch * cr, cp * sr)
    dwn_ned = (ch * sp * cr + sh * sr, sh * sp * cr - ch * sr, cp * cr)

    def to_ecef(v):
        return tuple(v[0] * n[i] + v[1] * e[i] + v[2] * dn[i] for i in range(3))

    f, r, d = to_ecef(fwd_ned), to_ecef(rgt_ned), to_ecef(dwn_ned)
    psi = math.atan2(f[1], f[0])
    theta = -math.asin(max(-1.0, min(1.0, f[2])))
    phi = math.atan2(r[2], d[2])
    return (psi, theta, phi)


def heading_from_tait_bryan(c: Coord, psi: float, theta: float,
                            phi: float) -> tuple[float, float, float]:
    """`tait_bryan`의 역. (방위, 피치, 롤) 라디안. 방위는 0 이상 2π 미만."""
    n, e, dn = _ned_basis(c.lat, c.lon)
    cps, sps = math.cos(psi), math.sin(psi)
    cth, sth = math.cos(theta), math.sin(theta)
    cph, sph = math.cos(phi), math.sin(phi)
    f = (cth * cps, cth * sps, -sth)
    r = (sph * sth * cps - cph * sps, sph * sth * sps + cph * cps, sph * cth)

    def to_ned(v):
        return (sum(v[i] * n[i] for i in range(3)),
                sum(v[i] * e[i] for i in range(3)),
                sum(v[i] * dn[i] for i in range(3)))

    fn, rn = to_ned(f), to_ned(r)
    heading = math.atan2(fn[1], fn[0]) % (2 * math.pi)
    pitch = math.atan2(-fn[2], math.hypot(fn[0], fn[1]))
    roll = math.atan2(rn[2], math.hypot(rn[0], rn[1]) or 1e-12)
    return (heading, pitch, roll)


def bearing_elevation(a: Coord, b: Coord) -> tuple[float, float]:
    """a에서 b를 볼 때의 방위·고각(라디안).

    방위는 진북 0, 시계 방향으로 증가하며 0 이상 2π 미만이다. 고각은 수평이
    0이고 올려다보면 양수다.

    거리는 ground_distance(ECEF 직선거리)를 쓰지 않는다. 그건 고도차를
    포함하므로 고각 계산에 넣으면 자기 참조가 된다. 수평 성분만 _deg_scales로
    미터로 바꿔 쓴다 — 위도별 도-미터 환산이 이미 거기 있다.

    # VERIFY-ON-TARGET: VR-Forces의 aiming-azimuth가 진북 기준 시계 방향
    # 라디안이라는 것은 확인하지 못했다. 틀리면 포신 방향만 어긋나고
    # task 자체는 돈다.
    """
    lat_m, lon_m = _deg_scales((a.lat + b.lat) / 2.0)
    north = (b.lat - a.lat) * lat_m
    east = (b.lon - a.lon) * lon_m
    flat = math.hypot(north, east)
    if flat == 0.0 and b.alt == a.alt:
        return (0.0, 0.0)
    az = math.atan2(east, north) % (2 * math.pi)
    el = math.atan2(b.alt - a.alt, flat) if flat else math.copysign(
        math.pi / 2, b.alt - a.alt)
    return (az, el)


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
