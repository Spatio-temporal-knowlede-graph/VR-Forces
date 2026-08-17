"""시뮬레이터 CSV 후처리 — 술어를 정규형으로 바꾸고 object를 채운다.

**열을 늘리지 않는다.** 내보내기가 준 열을 순서까지 그대로 낸다. 판마다
열이 다르므로(20260803은 8열 끝이 CID, 20260809는 CID 대신 상태 열 10개)
목록을 못박지 않고 입력 헤더를 그대로 물려받는다. 파생 정보를 열로 붙이면
원본과 대조가 안 되고, STKG 쪽에서 어느 열이 관측이고 어느 열이 우리가
만든 것인지 매번 되물어야 한다.

바꾸는 것은 두 열뿐이다.

  predicate   시뮬레이터 원문(`Move to {-5499107.729384, ...}`)을 정규형으로
  object      원문이 대개 `-`라 비어 있던 자리를 대상으로 채운다

| 원문 | predicate | object |
|---|---|---|
| `Move to {좌표}` | `move to` | 좌표를 붙인 지명 |
| `Move-To Waypoint: "P10"` | `move to` | `P10` (통제점) |
| `Follow-Entity Entity: "X"` | `Follow-Entity` | `X` |
| `FFE-On-Location "Location={좌표}"` | `FFE-on-Location` | 좌표를 붙인 지명 |
| `Fire Weapon` | `Fire-Weapon` | 내보내기가 준 object 열 그대로 |
| `Wait-Duration Seconds-To-Wait:60` | `Wait-Duration` | 비움 |
| `find_cover: ... Threat=X; ...` | `find_cover` | `X` |
| `find_firing_position: ... Threat=X; ...` | `find_firing_position` | `X` |
| `None` | `none` | 비움 |
| (발사체 행) | `fired_by` | 확정된 사수. 못 하면 비움 |

`Fire Weapon`은 20260809판에서 새로 나왔고, 유일하게 내보내기가 대상을
미리 채워 준다(실측 ground_truth 650행). 우리가 만든 값이 아니라 관측이므로
덮어쓰지 않고 그대로 통과시킨다.

행은 지운다. 시뮬레이터 인프라 객체(`N Force`, `Observer N`, `GlobalEnv N`)는
원문 시나리오에 없고 물리 객체도 아니다. `Force` 노드는 좌표까지
(42.32429274, 45.0) 고정 쓰레기값이다. 실측 ground_truth 5,072행.

발사체 행의 `fired_by`는 `firing.link`가 확정한 것만 쓴다. 확정 못 하면
술어는 `fired_by`로 두되 object는 비운다 — 억지로 채우지 않는다.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

from ..geometry import Coord
from . import firing
from .filter import Disposition, classify
from .locate import is_control_point, is_place, snap
from .predicate import parse
from .resolve import to_marking
from .schema import object_of

# 20260803판이 준 8열. 이제는 입력에 헤더가 없을 때만 쓰는 기본값이다 —
# 실제 출력 열은 out_columns()가 입력에서 물려받는다.
OUT_COLS = ["subject", "predicate", "object", "latitude", "longitude",
            "timestamp", "source", "CID"]

PRED_MOVE = "move to"
PRED_FOLLOW = "Follow-Entity"
PRED_FFE = "FFE-on-Location"
PRED_FIRE = "Fire-Weapon"
PRED_WAIT = "Wait-Duration"
PRED_COVER = "find_cover"
PRED_FIRING_POS = "find_firing_position"
PRED_FIRED_BY = "fired_by"
PRED_NONE = "none"

# predicate.parse의 정규화 이름 → 이 단계가 쓰는 정규형.
_NAME = {
    "moves_to": PRED_MOVE,
    "follows": PRED_FOLLOW,
    "fires_at": PRED_FFE,
    "fires_weapon_at": PRED_FIRE,
    "waits": PRED_WAIT,
    "takes_cover_from": PRED_COVER,
    "takes_firing_position_against": PRED_FIRING_POS,
}

# object 열이 비었음을 뜻하는 값. 원문은 대개 '-'다.
EMPTY = ""


def out_columns(rows) -> list[str]:
    """출력 열 = 입력이 준 열, 순서까지 그대로. 입력이 비면 기본 8열."""
    for row in rows:
        return list(row)
    return list(OUT_COLS)


@dataclass
class Tally:
    total: int = 0
    out: int = 0
    dropped: int = 0
    with_object: int = 0
    predicates: dict = field(default_factory=lambda: collections.Counter())
    dropped_subjects: dict = field(default_factory=lambda: collections.Counter())
    unmapped: dict = field(default_factory=lambda: collections.Counter())
    unparsed: dict = field(default_factory=lambda: collections.Counter())
    munitions: int = 0
    munitions_linked: int = 0

    # 등장 객체. 행 수와 달리 '몇 개가 나오는가'를 센다.
    subjects: set = field(default_factory=set)          # 남은 주체 전부
    munition_subjects: set = field(default_factory=set)  # 그중 발사체
    control_subjects: set = field(default_factory=set)   # 그중 통제점(자리)
    dropped_names: set = field(default_factory=set)      # 지운 인프라 객체
    object_entities: set = field(default_factory=set)    # object로 등장한 객체
    object_locations: set = field(default_factory=set)   # object로 등장한 지명
    object_coords: set = field(default_factory=set)      # 지명에 못 붙은 좌표

    @property
    def entities(self) -> int:
        """발사체와 통제점을 뺀 주체 수. 실제 전투 객체다."""
        return (len(self.subjects) - len(self.munition_subjects)
                - len(self.control_subjects))

    @property
    def seen(self) -> int:
        """주체든 대상이든 한 번이라도 이름이 나온 객체 수. 자리는 뺀다."""
        return len((self.subjects - self.control_subjects)
                   | self.object_entities)


def _is_coord(value: str) -> bool:
    """'x,y,z' 좌표 폴백인가. locate.snap이 지명에 못 붙였을 때 나온다."""
    parts = value.split(",")
    if len(parts) != 3:
        return False
    try:
        [float(p) for p in parts]
    except ValueError:
        return False
    return True


def ecef_of(row) -> tuple[float, float, float]:
    return Coord(float(row["latitude"]), float(row["longitude"]),
                 0.0).to_ecef()


def _snap_object(blob: str, layout, control_points) -> str:
    """'x,y,z' 문자열 → 지명. 못 붙이면 좌표 문자열을 그대로 남긴다."""
    x, y, z = (float(v) for v in blob.split(","))
    return snap((x, y, z), layout, control_points=control_points).object_id


def rewrite(rows, layout, uuid_map=None, control_points=None,
            place_names=None):
    """입력 행 목록 → 8열 출력 행 목록.

    인프라 행이 빠지므로 len(out) < len(rows)다. 얼마나 빠졌는지는
    Tally.dropped에 담기고, 호출부가 total == out + dropped를 확인한다.
    """
    uuid_map = uuid_map or {}
    place_names = place_names or {}
    tally = Tally()
    cols = out_columns(rows)

    kept = []
    for row in rows:
        tally.total += 1
        verdict = classify(row["subject"], row["timestamp"])
        if verdict is Disposition.KEEP:
            kept.append(row)
        else:
            tally.dropped += 1
            tally.dropped_subjects[f"{row['subject']} ({verdict.value})"] += 1
            tally.dropped_names.add(row["subject"])

    # 발사체 짝짓기는 관측자별로 따로 돈다. 섞으면 다른 시각대의 관측이
    # 하나로 이어진다(실측: M933HE 1이 GROUND_TRUTH와 UAV 2 양쪽에 있다).
    links: dict[str, firing.Link] = {}
    unresolved: list[str] = []
    by_source = collections.defaultdict(list)
    for row in kept:
        by_source[row["source"]].append(row)
    for source, group in sorted(by_source.items()):
        found, reasons = firing.link(group, ecef_of)
        links.update({(source, k): v for k, v in found.items()})
        unresolved += [f"[{source}] {r}" for r in reasons]

    out = []
    for row in kept:
        rec = {c: row.get(c, "") for c in cols}
        rec["predicate"], rec["object"] = _fields(row, layout, uuid_map,
                                                  control_points, place_names,
                                                  links, tally)
        if rec["object"]:
            tally.with_object += 1
            if is_place(rec["object"]):
                tally.object_locations.add(rec["object"])
            elif _is_coord(rec["object"]):
                # 지명에 못 붙은 좌표 폴백. 객체가 아니라 자리다.
                tally.object_coords.add(rec["object"])
            else:
                tally.object_entities.add(rec["object"])
        tally.predicates[rec["predicate"]] += 1
        tally.subjects.add(rec["subject"])
        if firing.is_munition(rec["subject"]):
            tally.munition_subjects.add(rec["subject"])
        elif is_control_point(rec["subject"]):
            tally.control_subjects.add(rec["subject"])
        out.append(rec)
        tally.out += 1

    return out, links, unresolved, tally


def _fields(row, layout, uuid_map, control_points, place_names, links, tally):
    """행 하나의 (predicate, object)를 정한다."""
    subject = row["subject"]

    if firing.is_munition(subject):
        tally.munitions += 1
        link = links.get((row["source"], subject))
        if link is None:
            return PRED_FIRED_BY, EMPTY
        tally.munitions_linked += 1
        return PRED_FIRED_BY, link.shooter

    raw = row["predicate"]
    p = parse(raw)
    if p is None:
        tally.unparsed[raw] += 1
        return raw, EMPTY                     # 모르는 술어는 원문을 남긴다
    if not p.predicate:
        return PRED_NONE, EMPTY

    name = _NAME.get(p.predicate)
    if name is None:
        tally.unmapped[p.predicate] += 1
        return raw, EMPTY

    if p.object_kind == "given":
        # 대상이 predicate가 아니라 object 열에 있다(`Fire Weapon`). 내보내기가
        # 준 관측이므로 그대로 통과시킨다.
        return name, object_of(row)
    if p.object_kind == "coord":
        return name, _snap_object(p.object_raw, layout, control_points)
    if p.object_kind == "uuid":
        # 통제점은 uuid가 아니라 marking으로 나온다(실측 `Move-To Waypoint:
        # "P3"`). 대조표가 정본이고, 없으면 .oob marking 표로, 그것도 없으면
        # 원문을 남긴다 — 버리면 그 행이 어디로 갔는지 알 수 없다.
        place = place_names.get(p.object_raw)
        if place:
            return name, place
        marking = to_marking(p.object_raw, uuid_map)
        return name, marking if marking else p.object_raw
    return name, p.object_raw or EMPTY
