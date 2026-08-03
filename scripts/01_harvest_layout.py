"""golden 통제점 + layout_rules → battlefield_layout.json.

좌표의 정본은 golden(`yewon_test.oob`)에 사람이 찍은 통제점이다. 이 스크립트는
그 점들을 이름으로 수확하고, 원문에만 있고 golden에 없는 지명을 규칙으로
파생시켜 레이아웃을 만든다. 손으로 좌표를 적지 않는다.

파생 방위는 실제 나침반이 아니라 전장 축(아군 중심 → 적 중심)을 쓴다. golden의
동측능선이 실제 서쪽에, 서측능선이 실제 동쪽에 찍혀 있어 나침반으로 읽으면
전부 뒤집힌다. 근거는 layout_rules.json의 axis.note.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.geometry import Coord, _deg_scales                    # noqa: E402
from vtmak.norm import loc_id                                    # noqa: E402
from vtmak.scnx.golden import Golden                             # noqa: E402
from vtmak.scnx.pack import ensure_golden                        # noqa: E402

CONFIG = ROOT / "config"
RULES = CONFIG / "layout_rules.json"
OUT = CONFIG / "battlefield_layout.json"

# dir 값 → 전장 축 기준 단위벡터 계수 (축방향, 오른쪽방향)
_DIRS = {"북": (1.0, 0.0), "남": (-1.0, 0.0),
         "동": (0.0, 1.0), "서": (0.0, -1.0)}


def harvest_points(golden_dir: Path, aliases: dict[str, str]
                   ) -> dict[str, Coord]:
    """golden의 점·지역 객체 → {LOC_id: Coord}. alias는 먼저 적용한다."""
    g = Golden.load(ensure_golden(golden_dir))
    out: dict[str, Coord] = {}
    for o in g.points_and_areas():
        if o.position is None:
            continue
        lid = aliases.get(o.marking.strip()) or loc_id(o.marking)
        out.setdefault(lid, Coord.from_ecef(*o.position))
    return out


class _Frame:
    """전장 축 좌표계. 원점은 아군 중심, u = 적 방향, v = u의 오른쪽."""

    def __init__(self, pts: dict[str, Coord], friendly: list[str],
                 enemy: list[str]) -> None:
        self.lat0 = sum(c.lat for c in pts.values()) / len(pts)
        self.lon0 = sum(c.lon for c in pts.values()) / len(pts)
        self.m_lat, self.m_lon = _deg_scales(self.lat0)
        fc, ec = self._centroid(pts, friendly), self._centroid(pts, enemy)
        de, dn = ec[0] - fc[0], ec[1] - fc[1]
        n = math.hypot(de, dn)
        self.u = (de / n, dn / n)          # 시나리오 '북'
        self.v = (self.u[1], -self.u[0])   # 시나리오 '동'
        self.bearing_deg = math.degrees(math.atan2(*self.u)) % 360.0

    def _centroid(self, pts, ids):
        got = [self.to_en(pts[i]) for i in ids if i in pts]
        if not got:
            raise KeyError(f"axis 정의에 쓰인 지명이 golden에 없다: {ids}")
        return (sum(p[0] for p in got) / len(got),
                sum(p[1] for p in got) / len(got))

    def to_en(self, c: Coord) -> tuple[float, float]:
        return ((c.lon - self.lon0) * self.m_lon,
                (c.lat - self.lat0) * self.m_lat)

    def offset(self, c: Coord, east: float, north: float) -> Coord:
        return Coord(c.lat + north / self.m_lat,
                     c.lon + east / self.m_lon, c.alt)

    def push(self, c: Coord, direction: str, dist: float) -> Coord:
        """전장 축 방위로 dist 미터 민다."""
        du, dv = _DIRS[direction]
        east = (self.u[0] * du + self.v[0] * dv) * dist
        north = (self.u[1] * du + self.v[1] * dv) * dist
        return self.offset(c, east, north)

    def push_toward(self, c: Coord, target: Coord, dist: float) -> Coord:
        """다른 지점 방향으로 dist 미터 민다."""
        (e0, n0), (e1, n1) = self.to_en(c), self.to_en(target)
        de, dn = e1 - e0, n1 - n0
        n = math.hypot(de, dn)
        if n == 0.0:
            return c
        return self.offset(c, de / n * dist, dn / n * dist)


def derive(pts: dict[str, Coord], rules: dict, frame: _Frame
           ) -> dict[str, Coord]:
    out: dict[str, Coord] = {}
    for lid, spec in (rules.get("derived") or {}).items():
        base = pts.get(spec["base"])
        if base is None:
            raise KeyError(f"{lid}의 base가 golden에 없다: {spec['base']}")
        dist = float(spec["dist_m"])
        if "toward" in spec:
            tgt = pts.get(spec["toward"])
            if tgt is None:
                raise KeyError(f"{lid}의 toward가 golden에 없다: {spec['toward']}")
            out[lid] = frame.push_toward(base, tgt, dist)
        else:
            out[lid] = frame.push(base, spec["dir"], dist)
    return out


def main() -> int:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    golden = ROOT / rules["golden_dir"]
    pts = harvest_points(golden, rules.get("aliases") or {})
    print(f"golden 통제점 {len(pts)}개 수확 ({golden.name})")

    frame = _Frame(pts, rules["axis"]["friendly"], rules["axis"]["enemy"])
    print(f"전장 축: 아군→적 방위 {frame.bearing_deg:.1f}° "
          f"(시나리오 '북'). '동' = {(frame.bearing_deg + 90) % 360:.1f}°")

    derived = derive(pts, rules, frame)
    print(f"파생 지점 {len(derived)}개")

    locations = {}
    for lid, c in sorted(pts.items()):
        locations[lid] = {"lat": round(c.lat, 7), "lon": round(c.lon, 7),
                          "alt": round(c.alt, 1), "src": "golden"}
    for lid, c in sorted(derived.items()):
        locations[lid] = {"lat": round(c.lat, 7), "lon": round(c.lon, 7),
                          "alt": round(c.alt, 1), "src": "derived"}

    doc = {
        "layout_id": rules["layout_id"],
        "terrain": rules["terrain"],
        "generated_by": "scripts/01_harvest_layout.py",
        "generated_from": [f"{rules['golden_dir']}/*.oob",
                           "config/layout_rules.json"],
        "note": ("손으로 고치지 말 것. golden 통제점을 옮겼거나 규칙을 바꿨으면 "
                 "01_harvest_layout.py를 다시 돌린다. src=golden은 사람이 찍은 "
                 "지형점, src=derived는 규칙으로 민 점이다(지형 미확인)."),
        "axis_bearing_deg": round(frame.bearing_deg, 2),
        "locations": locations,
        "static_targets": rules["static_targets"],
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)} · 지명 {len(locations)}개 "
          f"(golden {len(pts)} + 파생 {len(derived)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
