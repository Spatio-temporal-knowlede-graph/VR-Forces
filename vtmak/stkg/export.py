"""입력 행을 관계·위치 두 테이블로 가르고 회계를 맞춘다.

회계가 이 모듈의 핵심이다. 모든 입력 행은 관계·위치·제외·격리 중 정확히 한
갈래로 간다. 합이 안 맞으면 어딘가에서 조용히 사라진 것이므로 실패시킨다.

파싱 실패는 행을 버리는 사유가 아니다. 관계를 못 만들 뿐 위치는 살리고,
원문을 report에 적는다.
"""
from __future__ import annotations

import collections
import csv
from dataclasses import dataclass, field
from pathlib import Path

from ..geometry import Coord
from .collapse import Relation, collapse
from .derive import Obs, fired_by
from .filter import Disposition, classify
from .locate import snap
from .predicate import parse
from .resolve import to_marking

_MUNITION_HINT = ("M107 ", "M933HE ", "PAC-3 ")


@dataclass
class Tally:
    total: int = 0
    relation_rows: int = 0        # 관계에 기여한 행 (축약 전)
    position_rows: int = 0
    dropped: int = 0
    quarantined: int = 0
    unparsed: dict[str, int] = field(default_factory=dict)
    snap_hits: dict[str, int] = field(default_factory=dict)


def _ecef(blob: str) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in blob.split(","))
    return x, y, z


def _is_munition(subject: str) -> bool:
    return subject.startswith(_MUNITION_HINT)


def build(rows, layout, uuid_map, munition_map, control_points=None):
    tally = Tally()
    obs: list[Obs] = []
    positions: list[dict] = []
    first_seen: dict[str, tuple[str, tuple[float, float, float], str]] = {}
    candidates: dict[str, list] = collections.defaultdict(list)

    for row in rows:
        tally.total += 1
        subject, ts = row["subject"], row["timestamp"]
        verdict = classify(subject, ts)
        if verdict in (Disposition.DROP_INFRA, Disposition.DROP_EFFECT):
            tally.dropped += 1
            continue
        if verdict is Disposition.QUARANTINE_EPOCH:
            tally.quarantined += 1
            continue

        kind = "projectile" if _is_munition(subject) else "entity"
        ecef = _ecef_of(row)
        source = row["source"]

        # fired_by 재료. 관계·위치 어느 갈래로 가든 필요하므로 먼저 모은다.
        # 키에 source를 넣는다 — 같은 발사체가 GT와 UAV 양쪽에 나오고,
        # 섞으면 UAV가 본 발사체가 GT가 본 박격포에 붙는다.
        # setdefault가 아니라 이른 시각으로 갱신한다. 입력 순서가 시각
        # 순서라는 보장이 없다(파일이 UAV → ground_truth 순으로 읽힌다).
        if kind == "projectile":
            key = (source, subject)
            if key not in first_seen or ts < first_seen[key][0]:
                first_seen[key] = (ts, ecef)
        else:
            candidates[(source, ts)].append((subject, ecef))

        raw = row["predicate"]
        p = parse(raw)
        if p is None:
            tally.unparsed[raw] = tally.unparsed.get(raw, 0) + 1
        elif p.predicate:
            obj, obj_type, evidence = _object_of(p, layout, uuid_map,
                                                 control_points, tally)
            obs.append(Obs(subject, p.predicate, obj, obj_type, ts,
                           row["source"], "observed", evidence))
            tally.relation_rows += 1
            continue          # 관계가 된 행은 위치 테이블로 가지 않는다

        positions.append({"subject": subject, "kind": kind,
                          "latitude": row["latitude"],
                          "longitude": row["longitude"],
                          "timestamp": ts, "source": row["source"]})
        tally.position_rows += 1

    derived, unresolved = fired_by(first_seen, candidates, munition_map) \
        if munition_map else ([], [])
    return collapse(obs + derived), positions, tally, unresolved


def _ecef_of(row) -> tuple[float, float, float]:
    """위경도를 ECEF 미터로. fired_by가 math.dist로 거리를 재므로 도 단위를
    그대로 넘기면 200m 임계가 아무 의미가 없어진다."""
    return Coord(float(row["latitude"]), float(row["longitude"]),
                 0.0).to_ecef()


def _object_of(p, layout, uuid_map, control_points, tally):
    if p.object_kind == "coord":
        result = snap(_ecef(p.object_raw), layout,
                      control_points=control_points)
        tally.snap_hits[result.object_type] = \
            tally.snap_hits.get(result.object_type, 0) + 1
        return (result.object_id, result.object_type,
                f"snap {result.distance_m:.1f}m")
    if p.object_kind == "uuid":
        marking = to_marking(p.object_raw, uuid_map)
        if marking is None:
            return p.object_raw, "uuid", "uuid 미해석"
        kind = "waypoint" if p.predicate == "moves_to" else "entity"
        return marking, kind, "uuid 해석"
    return p.object_raw, "entity", "predicate 원문"


def write_all(out_dir, relations, positions, tally, unresolved) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "relations.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["subject", "predicate", "object", "object_type",
                    "t_start", "t_end", "source", "confidence", "evidence"])
        for r in relations:
            w.writerow([r.subject, r.predicate, r.object, r.object_type,
                        r.t_start, r.t_end, r.source, r.confidence,
                        r.evidence])

    with open(out / "positions.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["subject", "kind", "latitude", "longitude",
                                "timestamp", "source"])
        w.writeheader()
        w.writerows(positions)

    lines = [
        "# STKG A단계 추출 보고", "",
        f"- 입력 행: {tally.total:,}",
        f"- 관계 기여 행(축약 전): {tally.relation_rows:,}",
        f"- 관계 구간: {len(relations):,}",
        f"- 위치 행: {tally.position_rows:,}",
        f"- 제외: {tally.dropped:,}",
        f"- 격리(1970 epoch): {tally.quarantined:,}", "",
        "## 좌표 스냅", "",
    ]
    total_snap = sum(tally.snap_hits.values()) or 1
    for kind, n in sorted(tally.snap_hits.items()):
        lines.append(f"- {kind}: {n:,} ({n / total_snap:.1%})")
    lines += ["", "## 미확정 fired_by", ""]
    lines += [f"- {u}" for u in unresolved] or ["- 없음"]
    lines += ["", "## 파싱 실패 술어", ""]
    lines += [f"- {n:,}행  `{raw[:120]}`"
              for raw, n in sorted(tally.unparsed.items(),
                                   key=lambda x: -x[1])] or ["- 없음"]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
