"""시뮬레이터 CSV 후처리 — 술어를 정규형으로 바꾸고 object를 채운다.

**열을 늘리지 않는다.** 내보내기가 준 8열 그대로 낸다. 파생 정보를 열로
붙이면 원본과 대조가 안 되고, STKG 쪽에서 어느 열이 관측이고 어느 열이
우리가 만든 것인지 매번 되물어야 한다.

바꾸는 것은 두 열뿐이다.

  predicate   시뮬레이터 원문(`Move to {-5499107.729384, ...}`)을 정규형으로
  object      원문이 전 행 `-`라 비어 있던 자리를 대상으로 채운다

| 원문 | predicate | object |
|---|---|---|
| `Move to {좌표}` | `move to` | 좌표를 붙인 지명 |
| `Follow-Entity Entity: "X"` | `Follow-Entity` | `X` |
| `FFE-On-Location "Location={좌표}"` | `FFE-on-Location` | 좌표를 붙인 지명 |
| `find_cover: ... Threat=X; ...` | `find_cover` | `X` |
| `None` | `none` | 비움 |
| (발사체 행) | `fired_by` | 확정된 사수. 못 하면 비움 |

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
from .locate import snap
from .predicate import parse
from .resolve import to_marking

# 내보내기가 준 8열. 순서까지 그대로 둔다.
OUT_COLS = ["subject", "predicate", "object", "latitude", "longitude",
            "timestamp", "source", "CID"]

PRED_MOVE = "move to"
PRED_FOLLOW = "Follow-Entity"
PRED_FFE = "FFE-on-Location"
PRED_COVER = "find_cover"
PRED_FIRED_BY = "fired_by"
PRED_NONE = "none"

# predicate.parse의 정규화 이름 → 이 단계가 쓰는 정규형.
_NAME = {
    "moves_to": PRED_MOVE,
    "follows": PRED_FOLLOW,
    "fires_at": PRED_FFE,
    "takes_cover_from": PRED_COVER,
}

# object 열이 비었음을 뜻하는 값. 원문은 전 행 '-'였다.
EMPTY = ""


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


def ecef_of(row) -> tuple[float, float, float]:
    return Coord(float(row["latitude"]), float(row["longitude"]),
                 0.0).to_ecef()


def _snap_object(blob: str, layout, control_points) -> str:
    """'x,y,z' 문자열 → 지명. 못 붙이면 좌표 문자열을 그대로 남긴다."""
    x, y, z = (float(v) for v in blob.split(","))
    return snap((x, y, z), layout, control_points=control_points).object_id


def rewrite(rows, layout, uuid_map=None, control_points=None):
    """입력 행 목록 → 8열 출력 행 목록.

    인프라 행이 빠지므로 len(out) < len(rows)다. 얼마나 빠졌는지는
    Tally.dropped에 담기고, 호출부가 total == out + dropped를 확인한다.
    """
    uuid_map = uuid_map or {}
    tally = Tally()

    kept = []
    for row in rows:
        tally.total += 1
        verdict = classify(row["subject"], row["timestamp"])
        if verdict is Disposition.KEEP:
            kept.append(row)
        else:
            tally.dropped += 1
            tally.dropped_subjects[f"{row['subject']} ({verdict.value})"] += 1

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
        rec = {c: row.get(c, "") for c in OUT_COLS}
        rec["predicate"], rec["object"] = _fields(row, layout, uuid_map,
                                                  control_points, links, tally)
        if rec["object"]:
            tally.with_object += 1
        tally.predicates[rec["predicate"]] += 1
        out.append(rec)
        tally.out += 1

    return out, links, unresolved, tally


def _fields(row, layout, uuid_map, control_points, links, tally):
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

    if p.object_kind == "coord":
        return name, _snap_object(p.object_raw, layout, control_points)
    if p.object_kind == "uuid":
        marking = to_marking(p.object_raw, uuid_map)
        return name, marking if marking else p.object_raw
    return name, p.object_raw or EMPTY
