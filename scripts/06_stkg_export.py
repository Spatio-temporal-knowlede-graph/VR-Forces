"""시뮬레이터 CSV → STKG 관계 테이블 + 위치 테이블 (A단계).

재시뮬이 필요 없다. build/csv/*.csv만 읽는다.
"""
from __future__ import annotations

import argparse
import csv
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 기본 콘솔은 cp949라 보고의 '—' 같은 문자에서 죽는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.geometry import BattlefieldLayout                 # noqa: E402
from vtmak.stkg.derive import load_munition_map              # noqa: E402
from vtmak.stkg.export import build, write_all               # noqa: E402
from vtmak.stkg.resolve import load_uuid_map                 # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", default=str(ROOT / "build" / "csv"))
    ap.add_argument("--out", default=str(ROOT / "build" / "stkg"))
    ap.add_argument("--oob", default="",
                    help="CSV와 짝이 되는 .oob. 없으면 uuid를 해석하지 않는다")
    args = ap.parse_args()

    paths = sorted(glob.glob(str(Path(args.csv_dir) / "*_dataset.csv")))
    if not paths:
        print(f"{args.csv_dir}에 *_dataset.csv 없음")
        return 1

    rows = []
    for p in paths:
        with open(p, encoding="utf-8", newline="") as fh:
            rows.extend(csv.DictReader(fh))
    print(f"입력 {len(paths)}개 파일 · {len(rows):,}행")

    layout = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    uuid_map = load_uuid_map(args.oob) if args.oob else {}
    if not uuid_map:
        print("  uuid 표 없음 — Move-To Waypoint / Target-entity task의 "
              "uuid는 원문을 유지한다(--oob로 짝이 되는 .oob를 줄 것)")
    munition_map = load_munition_map(ROOT / "config" / "munition_map.csv")

    relations, positions, tally, unresolved = build(
        rows, layout, uuid_map, munition_map)
    write_all(args.out, relations, positions, tally, unresolved)

    accounted = (tally.relation_rows + tally.position_rows
                 + tally.dropped + tally.quarantined)
    print(f"관계 구간 {len(relations):,} (기여 행 {tally.relation_rows:,}) · "
          f"위치 {tally.position_rows:,} · 제외 {tally.dropped:,} · "
          f"격리 {tally.quarantined:,}")
    if accounted != tally.total:
        print(f"회계 불일치: {accounted:,} != {tally.total:,} — 행이 "
              f"조용히 사라졌다")
        return 1
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
