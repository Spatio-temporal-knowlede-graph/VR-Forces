"""고정 객체 — 원문 밖에서 가져와 모든 시나리오에 같은 배치로 넣는 객체.

UAV처럼 원문이 서술하지 않지만 어느 규모에서든 같은 자리에 있어야 하는
객체가 있다. 레코드를 손으로 적지 않고, 이미 정상 저작된 시나리오의 레코드를
복제한다. DIS·force·탑재 시스템이 통째로 따라오므로 새로 합성할 때 생기는
인스턴스화 실패 위험이 없다.

'고정'의 뜻은 **'움직이지 않는다'가 아니라 '원문 규모와 무관하게 같은 배치를
갖는다'** 이다. 명부를 줄여도 개수·순찰 중심·고도가 변하지 않는다.

UAV는 담당 중심 둘레의 순찰로를 `move-along`으로 돈다. 왜 정지가 아니라
비행인가는 `docs/superpowers/specs/2026-08-06-uav-placement-behavior-design.md`
§3.5에 있다 — 관측 방위가 계속 바뀌어야 지형 차폐가 풀린다.

**`orbit_object`는 쓰지 않는다.** campaign에서 수확해 넣었지만 실행에서 UAV가
전혀 움직이지 않았다(2026-08-06 실측). 그 태스크의 `target`은 데이터 타입이
`simulationobject`인데 우리는 통제점 uuid를 넣었고 VR-Forces가 받지 않는다.
대신 `battle/`에서 사람이 직접 저작해 돌려 본 `move-along` + Route를 복제한다 —
이 설치에서 실제로 도는 것이 확인된 방식이다.

라우트는 golden(`yewon_test`)에 템플릿이 없다(kind 17 레코드 0개). 그래서
`battle/`의 Route 레코드를 공여체로 삼아 uuid·좌표·정점만 갈아끼운다.

짐벌 각도는 플랜의 Set이 아니라 여기서 `.oob` raw 레코드에 직접 쓴다. Set으로
azimuth/elevation을 넘기는 문법은 정본을 확인하지 못했지만, PSR 필드명은
`campaign.oob`·`battle.oob`에서 직접 읽은 것이라 추측이 없다.
"""
from __future__ import annotations

import json
import math
import re
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path

from ..geometry import BattlefieldLayout, Coord, _deg_scales
from .golden import KIND_ROUTE, Golden
from .ids import NAMESPACE
from .pack import ensure_golden

_RE_LABEL = re.compile(r'\(object-label "([^"]*)"')
_RE_LABEL_SUB = re.compile(r'\(object-label "[^"]*"')
_RE_MARK_SUB = re.compile(r'\(marking-text "[^"]*"')
_RE_UUID_SUB = re.compile(r'\(uuid\s+"VRF_UUID:[^"]*"')
_RE_POS = re.compile(
    r"\(position\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*\)")
_RE_ORDERED_ALT = re.compile(r"\(ordered-altitude\s+-?\d[\d.eE+-]*\)")
_RE_ORDERED_ALT_RW = re.compile(
    r"\(DtRwReal\s+OrderedAltitude\s+-?\d[\d.eE+-]*((?:\s+publish)?)\)")
_RE_VERTS = re.compile(r"\(body-vertices\s*(?:\(vertex[^()]*\)\s*)*\)")

# 짐벌 PSR. 같은 이름의 필드가 무기·액추에이터 PSR에도 있으므로 이 블록
# 안에서만 갈아끼운다.
_GIMBAL_BLOCK = "sensor-gimbal-controller-process-state-repository-default"


@dataclass(frozen=True)
class FixedObject:
    marking: str
    label: str
    uuid: str
    dis: tuple[int, ...]
    coord: Coord
    raw: str            # .oob 레코드. object-identifier만 writer가 갈아끼운다.
    # 플랜에 넣을 행동. task_catalog의 (type_group, 행동) 키다. 비어 있으면
    # 플랜 자체를 만들지 않는다(순찰로 객체가 그렇다).
    type_group: str = ""
    plan_actions: tuple[str, ...] = ()
    # 순찰. patrol_center_loc이 비면 순찰 비행을 저작할 수 없다.
    patrol_center_loc: str = ""
    patrol_route_uuid: str = ""
    patrol_laps: int = 1

    @property
    def is_route(self) -> bool:
        return self.dis and str(self.dis[0]) == KIND_ROUTE


def _fmt_ecef(c: Coord) -> str:
    x, y, z = c.to_ecef()
    return f"{x:.6f} {y:.6f} {z:.6f}"


def _block_span(raw: str, name: str) -> tuple[int, int] | None:
    """`(name …)` 블록의 괄호 균형을 맞춘 [시작, 끝) 구간."""
    i = raw.find("(" + name)
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(raw)):
        if raw[j] == "(":
            depth += 1
        elif raw[j] == ")":
            depth -= 1
            if depth == 0:
                return (i, j + 1)
    raise ValueError(f"괄호가 안 닫힌 블록: {name}")


def _sub_in_block(raw: str, name: str, subs: dict[str, str]) -> str:
    """지정한 블록 안에서만 `(필드 값)`을 바꾼다.

    블록이나 필드가 없으면 예외다 — 조용히 넘기면 짐벌이 왜 안 도는지
    .scnx를 열어보기 전엔 알 수 없다(markings와 같은 규칙).
    """
    span = _block_span(raw, name)
    if span is None:
        raise KeyError(f"복제한 레코드에 없는 블록: {name}")
    a, b = span
    body = raw[a:b]
    for field, value in subs.items():
        pat = re.compile(rf"\({re.escape(field)}\s+[^()]*\)")
        if not pat.search(body):
            raise KeyError(f"{name}에 없는 필드: {field}")
        body = pat.sub(f"({field} {value})", body)
    return raw[:a] + body + raw[b:]


def _ring(radius_m: float, count: int,
          start_bearing_deg: float) -> list[tuple[float, float]]:
    """중심 둘레 등간격 방위의 로컬 오프셋(동 +x, 북 +y 미터).

    반시계로 돈다 — 짐벌을 기체 좌현(-90°)에 고정하면 안쪽을 본다. 그래서
    순찰 방향(traversal-direction)은 늘 0으로 두고 왕복시키지 않는다.
    """
    out = []
    for i in range(count):
        b = math.radians(start_bearing_deg - 360.0 * i / count)
        out.append((radius_m * math.sin(b), radius_m * math.cos(b)))
    return out


def _patrol_route(donor, marking: str, label: str, center: Coord,
                  radius_m: float, count: int, start_bearing_deg: float,
                  altitude_agl_m: float) -> FixedObject:
    """공여체 Route 레코드를 복제해 중심 둘레 순찰로 하나를 만든다.

    정점은 `(vertex dx dy dz)` 로컬 오프셋이고 레코드의 `position`이 원점이다
    (battle.oob 실측). dz는 지면 기준 비행고도가 된다.
    """
    ru = str(_uuid.uuid5(NAMESPACE, f"patrol_route|{marking}"))
    raw = donor.raw
    raw = _RE_UUID_SUB.sub(f'(uuid  "VRF_UUID:{ru}"', raw, count=1)
    raw = _RE_MARK_SUB.sub(f'(marking-text "{marking}"', raw, count=1)
    raw = _RE_LABEL_SUB.sub(f'(object-label "{label}"', raw, count=1)
    raw = _RE_POS.sub(f"(position  {_fmt_ecef(center)})", raw)
    if not _RE_VERTS.search(raw):
        raise KeyError(f"공여체 라우트에 body-vertices가 없다: {donor.marking}")
    verts = "".join(
        f"\n               (vertex  {dx:.6f} {dy:.6f} {altitude_agl_m:.6f})"
        for dx, dy in _ring(radius_m, count, start_bearing_deg))
    raw = _RE_VERTS.sub(f"(body-vertices{verts}\n            )", raw, count=1)
    return FixedObject(marking=marking, label=label, uuid=ru, dis=donor.dis,
                       coord=center, raw=raw)


def load_fixed(config_path, root, layout: BattlefieldLayout | None = None
               ) -> list[FixedObject]:
    """config/fixed_objects.json → 배치까지 확정한 복제 레코드들.

    markings 순서대로 UAV가 먼저, 그 뒤에 순찰로 객체가 온다. 하나라도 못
    찾으면 예외다 — 조용히 빠지면 '있는 줄 알았는데 없는' 상태가 되고,
    .scnx를 열어보기 전엔 모른다.

    `layout`은 순찰 중심 지명을 좌표로 푸는 데 쓴다. `patrol_centers`를 선언한
    config에서 layout을 안 주면 예외다.
    """
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        return []
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    markings = list(cfg.get("markings") or [])
    if not markings:
        return []

    plan = cfg.get("plan") or {}
    type_group = str(plan.get("type_group") or "")
    actions = tuple(plan.get("actions") or ())
    if actions and not type_group:
        raise ValueError(
            "fixed_objects.json: plan.actions를 쓰려면 plan.type_group도 "
            "있어야 한다 — task_catalog는 (type_group, 행동)으로 찾는다")

    centers = dict(cfg.get("patrol_centers") or {})
    patrol = cfg.get("patrol") or {}
    gimbal = cfg.get("gimbal") or {}
    radius_m = float(patrol.get("radius_m") or 0.0)
    vertices = int(patrol.get("vertices") or 0)
    bearing = float(patrol.get("start_bearing_deg") or 0.0)
    alt_agl = float(patrol.get("altitude_agl_m") or 0.0)
    laps = max(1, int(patrol.get("laps") or 1))
    if centers and layout is None:
        raise ValueError(
            "fixed_objects.json이 patrol_centers를 선언했으면 load_fixed에 "
            "BattlefieldLayout을 줘야 한다 — 지명을 좌표로 풀 수 없다")
    if centers and (radius_m <= 0.0 or vertices < 3):
        raise ValueError(
            "fixed_objects.json: patrol.radius_m과 patrol.vertices(3 이상)가 "
            "있어야 순찰로를 그린다")
    missing_center = [m for m in markings if m not in centers] if centers else []
    if missing_center:
        raise KeyError(f"patrol_centers에 없는 고정 객체: {missing_center}")

    src = Path(root) / cfg["source_dir"]
    by_marking = {o.marking: o for o in Golden.load(ensure_golden(src)).objects}
    missing = [m for m in markings if m not in by_marking]
    if missing:
        raise KeyError(f"{src.name}에 없는 고정 객체: {missing}")

    donor = None
    if centers:
        dcfg = patrol.get("route_donor") or {}
        dsrc = Path(root) / str(dcfg.get("source_dir") or cfg["source_dir"])
        dmark = str(dcfg.get("marking") or "")
        donor = next((o for o in Golden.load(ensure_golden(dsrc)).objects
                      if o.marking == dmark and o.kind == KIND_ROUTE), None)
        if donor is None:
            raise KeyError(
                f"{dsrc.name}에 라우트 공여체가 없다: {dmark!r} "
                f"(kind {KIND_ROUTE}) — golden에는 라우트 템플릿이 없으므로 "
                "실제로 저작된 시나리오에서 가져와야 한다")

    # 짐벌 하방각은 config에 적지 않는다 — 고도와 반경에서 나오므로 둘 중
    # 하나를 고치면 각도가 저절로 따라와야 한다.
    elevation = -math.atan2(alt_agl, radius_m) if radius_m > 0.0 else 0.0

    uavs: list[FixedObject] = []
    routes: list[FixedObject] = []
    for n, m in enumerate(markings, 1):
        o = by_marking[m]
        if o.position is None:
            raise ValueError(f"고정 객체에 좌표가 없다: {m}")
        label = _RE_LABEL.search(o.raw)
        raw = o.raw
        center_loc = centers.get(m, "")
        route_uuid = ""
        if center_loc:
            c = layout.coord(center_loc)
            if c.is_zero():
                raise KeyError(
                    f"battlefield_layout에 없는 순찰 중심: {center_loc}")
            # 순찰로 첫 정점 위에서 출발한다 — 결정론.
            m_lat, m_lon = _deg_scales(c.lat)
            b = math.radians(bearing)
            coord = Coord(c.lat + radius_m * math.cos(b) / m_lat,
                          c.lon + radius_m * math.sin(b) / m_lon,
                          c.alt + alt_agl)
            route = _patrol_route(donor, f"UAV{n}RTE", f"{m} 순찰로", c,
                                  radius_m, vertices, bearing, alt_agl)
            routes.append(route)
            route_uuid = route.uuid
            raw = _RE_POS.sub(f"(position  {_fmt_ecef(coord)})", raw)
            raw = _RE_ORDERED_ALT.sub(
                f"(ordered-altitude {coord.alt:.6f})", raw)
            raw = _RE_ORDERED_ALT_RW.sub(
                lambda mo: (f"(DtRwReal OrderedAltitude "
                            f"{coord.alt:.6f}{mo.group(1)})"), raw)
            raw = _sub_in_block(raw, _GIMBAL_BLOCK, {
                "aiming-azimuth": f"{float(gimbal.get('azimuth_rad', 0.0)):.6f}",
                "aiming-elevation": f"{elevation:.6f}",
                "scanning-left": str(bool(gimbal.get("scanning_left"))),
                "aiming-mode": str(int(gimbal.get("aiming_mode", 0))),
            })
        else:
            coord = Coord.from_ecef(*o.position)
        uavs.append(FixedObject(
            marking=o.marking,
            label=label.group(1) if label else o.marking,
            uuid=o.uuid,
            dis=o.dis,
            coord=coord,
            raw=raw,
            type_group=type_group,
            plan_actions=actions,
            patrol_center_loc=center_loc,
            patrol_route_uuid=route_uuid,
            patrol_laps=laps,
        ))
    return uavs + routes
