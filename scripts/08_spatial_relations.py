"""STKG CSV → 공간 관계 구간 (+품질 리포트, +매니페스트)."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 기본 콘솔은 cp949라 리포트의 '—' 같은 문자에서 죽는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.paths import CONFIG                                    # noqa: E402
from vtmak.spatial.pipeline import process_csv                    # noqa: E402
from vtmak.spatial.thresholds import Thresholds                   # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="공간 관계 구간을 파생한다.")
    p.add_argument("input", type=Path, help="9열 STKG CSV")
    p.add_argument("--relations", type=Path, required=True, help="관계 구간 CSV")
    p.add_argument("--quality", type=Path, required=True, help="품질 리포트 CSV")
    p.add_argument("--manifest", type=Path, required=True, help="매니페스트 JSON")
    p.add_argument("--config-dir", type=Path, default=CONFIG,
                   help="dis_catalog·entity_class_map·weapon_ranges가 있는 곳")
    p.add_argument("--thresholds", type=Path, default=None, help="임계값 덮어쓰기 JSON")
    p.add_argument("--dataset-version", default="unversioned",
                   help="모든 산출 행에 찍을 판 이름")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        stats = process_csv(
            args.input, args.relations, args.quality, args.manifest,
            config_dir=args.config_dir,
            thresholds=Thresholds.load(args.thresholds),
            dataset_version=args.dataset_version)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(asdict(stats), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
