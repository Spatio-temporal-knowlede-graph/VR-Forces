"""17열 ver1.0 내보내기를 9열 ver2.0 계약으로 옮긴다.

ver2.0을 아직 안 모았으므로, 내보내기 변경이 들어오기 전에 네 관계를 실제
좌표·타입·소속으로 한 번 돌려 보려면 이게 필요하다. 17열 판에는 force와
entity_type이 있고 heading이 없으므로 방향 관계는 0건으로 나온다 — 그 없음이
확인 대상이다.

ver2.0이 생기면 지운다. 파이프라인의 일부가 아니라 발판이다.
"""
from __future__ import annotations

import csv
from pathlib import Path

LEGACY_FIELDS = ["subject", "predicate", "object", "timestamp", "latitude",
                 "longitude", "source", "force", "tracking_id", "uuid",
                 "entity_type", "damage", "smoke", "flaming", "mobility_kill",
                 "firepower_kill", "suppression_level"]
TARGET_FIELDS = ["subject", "predicate", "object", "latitude", "longitude",
                 "timestamp", "heading", "entity_type", "force"]


def adapt_legacy(source: Path, destination: Path, default_heading: str = "",
                 limit_timestamps: int | None = None) -> int:
    """옛 열을 새 계약에 투영한다. 쓴 행 수를 돌려준다.

    limit_timestamps는 앞쪽 시각 N개만 남긴다. 스모크가 알고 싶은 것은 실제
    데이터에서 관계가 나오느냐이지 100만 행 전수가 아니다 — 매번 전수를 훑으면
    테스트가 몇 분씩 걸려 아무도 안 돌린다.
    """
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    stamps: list[str] = []
    with (source.open(encoding="utf-8-sig", newline="") as src,
          destination.open("w", encoding="utf-8", newline="") as dst):
        reader = csv.DictReader(src)
        if reader.fieldnames != LEGACY_FIELDS:
            raise ValueError(f"열이 {LEGACY_FIELDS}여야 하는데 {reader.fieldnames}다")
        writer = csv.DictWriter(dst, fieldnames=TARGET_FIELDS)
        writer.writeheader()
        for row in reader:
            if limit_timestamps is not None:
                stamp = row["timestamp"]
                if not stamps or stamps[-1] != stamp:
                    stamps.append(stamp)
                if len(stamps) > limit_timestamps:
                    break
            writer.writerow({
                "subject": row["subject"], "predicate": row["predicate"],
                "object": row["object"], "latitude": row["latitude"],
                "longitude": row["longitude"], "timestamp": row["timestamp"],
                "heading": default_heading, "entity_type": row["entity_type"],
                "force": row["force"],
            })
            written += 1
    return written
