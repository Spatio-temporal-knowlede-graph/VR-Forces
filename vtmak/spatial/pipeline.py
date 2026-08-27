"""시공간 CSV를 관계 구간·품질 리포트·매니페스트로 흘려보낸다."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from ..geometry import Coord, ground_distance
from .frame import judge_frame
from .interval import IntervalAccumulator, canonicalize
from .models import RelationStats
from .pair import Placement
from .profile import ProfileIndex
from .quality import MISSING_FORCE, QualityLog
from .thresholds import PREDICATES, SYMMETRIC_PREDICATES, Thresholds

INPUT_FIELDS = ["subject", "predicate", "object", "latitude", "longitude",
                "timestamp", "heading", "entity_type", "force"]
RELATION_FIELDS = ["subject", "predicate", "object", "t_start", "t_end",
                   "support_count", "evidence", "dataset_version",
                   "threshold_config_version"]
QUALITY_FIELDS = ["timestamp", "subjects", "code", "detail",
                  "dataset_version", "threshold_config_version"]


def _tmp(directory: Path) -> Path:
    fd, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(fd)
    return Path(name)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _seconds(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _frames(rows: Iterator[dict[str, str]]
            ) -> Iterator[tuple[str, list[dict[str, str]]]]:
    """같은 시각의 연속 행을 프레임으로 묶는다.

    입력이 이미 시각으로 묶여 있어야 한다. GT_ver1.0.csv로 확인했다 — 300,905행,
    시각 전환 943회, 고유 시각 943개, 되돌아감 0. 이게 깨지면 한 시각이 여러
    프레임으로 쪼개져 그 시각을 지나는 구간이 전부 부서지는데 산출물에는 아무
    흔적이 없다. 그래서 조용히 다시 묶지 않고 예외를 던진다. 정렬하면 파일
    전체를 메모리에 올려야 한다.
    """
    current: list[dict[str, str]] = []
    stamp: str | None = None
    seen: set[str] = set()
    for row in rows:
        if stamp is not None and row["timestamp"] != stamp:
            yield (stamp, current)
            seen.add(stamp)
            current = []
        stamp = row["timestamp"]
        if stamp in seen:
            raise ValueError(f"입력이 시각으로 묶여 있지 않다: {stamp!r}가 "
                             f"더 늦은 시각 뒤에 다시 나온다")
        current.append(row)
    if stamp is not None:
        yield (stamp, current)


def _build(timestamp: str, rows: list[dict[str, str]], index: ProfileIndex,
           log: QualityLog) -> tuple[list[Placement], set[frozenset[str]]]:
    """이 시각의 placements와 활성 Follow 쌍을 만든다.

    입력은 팩트 CSV라 한 엔티티가 한 시각에 여러 행을 갖는 게 정상이다 —
    `move to`, `Follow-Entity` 등 팩트마다 행이 하나다. 실측 평균 3.4행/엔티티다.
    쌍 판정은 subject 하나면 충분하므로 행마다 Placement를 새로 만들면 모든
    쌍이 그만큼 배로 평가된다(§4). Placement는 subject당 하나만 만들고(첫 행이
    이긴다), Follow-Entity 탐지만 모든 행을 계속 훑는다 — 그 팩트가 흔히 다른
    행에 있기 때문이다.
    """
    placements: list[Placement] = []
    seen_subjects: set[str] = set()
    follow: set[frozenset[str]] = set()
    for row in rows:
        if row["predicate"] == "Follow-Entity" and row["object"]:
            follow.add(frozenset({row["subject"], row["object"]}))
        if row["subject"] in seen_subjects:
            continue
        seen_subjects.add(row["subject"])
        heading = row["heading"].strip()
        force = row["force"].strip()
        if not force:
            log.record(timestamp, [row["subject"]], MISSING_FORCE,
                       "in_range_of 생략")
        placements.append(Placement(
            subject=row["subject"],
            coord=Coord(float(row["latitude"]), float(row["longitude"]), 0.0),
            heading_deg=float(heading) if heading else None,
            profile=index.of(row["entity_type"]),
            # 빈 문자열을 그대로 둔다. force가 없으면 in_range_of 자체를 만들지
            # 않는다(§3.3) — frame.py가 force 존재 여부로 건너뛴다. sentinel로
            # 서로 다르게 만들면 소속 미상끼리도 "다른 편"이 되어 관계가
            # 새로 생겨 버리는데, 이는 소속을 유추하는 것과 다르지 않다.
            force=force,
        ))
    return placements, follow


def _span(placements: list[Placement]) -> float:
    """이 프레임의 대각 폭. 격자가 쓸모 있는지의 경계다."""
    if len(placements) < 2:
        return 0.0
    lats = [p.coord.lat for p in placements]
    lons = [p.coord.lon for p in placements]
    return ground_distance(Coord(min(lats), min(lons), 0.0),
                           Coord(max(lats), max(lons), 0.0))


def process_csv(input_path: Path, relations_path: Path, quality_path: Path,
                manifest_path: Path, config_dir: Path, thresholds: Thresholds,
                dataset_version: str) -> RelationStats:
    """input_path에서 공간 관계 구간을 파생한다."""
    input_path, config_dir = Path(input_path), Path(config_dir)
    index = ProfileIndex.load(config_dir)
    log = QualityLog()
    acc = IntervalAccumulator(thresholds.max_merge_gap_s)
    input_rows = frames = 0
    prev_seconds: float | None = None

    with input_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != INPUT_FIELDS:
            raise ValueError(f"열이 {INPUT_FIELDS}여야 하는데 {reader.fieldnames}다")
        for timestamp, rows in _frames(reader):
            input_rows += len(rows)
            frames += 1
            seconds = _seconds(timestamp)
            # _frames는 같은 시각의 재등장만 잡는다. 08:00:05 다음에 08:00:02가
            # 오는 것처럼 새로운(재등장이 아닌) 시각이 더 이르게 오는 경우는
            # 여기서 걸러야 한다 — 안 그러면 t_end가 t_start보다 앞선 구간이
            # 조용히 만들어진다.
            if prev_seconds is not None and seconds < prev_seconds:
                raise ValueError(
                    f"입력이 시각순이 아니다: {timestamp!r}가 앞선 시각보다 이르다")
            prev_seconds = seconds
            placements, follow = _build(timestamp, rows, index, log)
            observations = judge_frame(timestamp, placements, follow, thresholds,
                                       _span(placements), log)
            acc.observe(timestamp, seconds,
                        canonicalize(observations, thresholds.symmetric_storage))

    intervals = acc.close()
    counts = {name: 0 for name in PREDICATES}
    for row in intervals:
        counts[row.predicate] = counts.get(row.predicate, 0) + 1

    _write_relations(relations_path, intervals, dataset_version, thresholds.version)
    _write_quality(quality_path, log, dataset_version, thresholds.version)
    _write_manifest(manifest_path, input_path, dataset_version, thresholds, counts)
    return RelationStats(input_rows=input_rows, timestamps=frames,
                         relation_counts=counts, quality_issues=log.count)


def _write_relations(path: Path, intervals, dataset_version: str,
                     config_version: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path.parent)
    with tmp.open("w", encoding="utf-8", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=RELATION_FIELDS)
        w.writeheader()
        for r in intervals:
            w.writerow({"subject": r.subject, "predicate": r.predicate,
                        "object": r.object, "t_start": r.t_start,
                        "t_end": r.t_end, "support_count": r.support_count,
                        "evidence": r.evidence,
                        "dataset_version": dataset_version,
                        "threshold_config_version": config_version})
    tmp.replace(path)


def _write_quality(path: Path, log: QualityLog, dataset_version: str,
                   config_version: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path.parent)
    with tmp.open("w", encoding="utf-8", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=QUALITY_FIELDS)
        w.writeheader()
        for i in log.issues():
            w.writerow({"timestamp": i.timestamp, "subjects": i.subjects,
                        "code": i.code, "detail": i.detail,
                        "dataset_version": dataset_version,
                        "threshold_config_version": config_version})
    tmp.replace(path)


def _write_manifest(path: Path, input_path: Path, dataset_version: str,
                    thresholds: Thresholds, counts: dict[str, int]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "dataset_version": dataset_version,
        "dataset_sha256": _sha256(input_path),
        "threshold_config_version": thresholds.version,
        # 내보내기가 시뮬레이션 시각을 주는지 아직 확인 못 했다(설계 §14).
        "time_base": "unverified",
        "symmetric": sorted(SYMMETRIC_PREDICATES),
        "symmetric_storage": thresholds.symmetric_storage,
        "generated_from": [input_path.name, "dis_catalog.csv",
                           "entity_class_map.csv", "weapon_ranges.csv"],
        "counts": counts,
    }, ensure_ascii=False, indent=2)
    tmp = _tmp(path.parent)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
