"""시뮬레이터 CSV 후처리. 입력 파일 하나당 출력 파일 하나.

전역(ground_truth)과 드론(UAV n)을 합치지 않는다. 전역은 정답이고 드론은
관측이며 시각대도 다르다(실측: 전역 08:09~08:16, 드론 22:00~22:07).

열은 내보내기가 준 8열 그대로 낸다 — subject, predicate, object, latitude,
longitude, timestamp, source, CID. predicate를 정규형으로 바꾸고 object를
채울 뿐이다.

행은 시뮬레이터 인프라 객체만 지운다. 입력 행 수 != 출력 행 수 + 삭제 행
수이면 종료 코드 1로 실패한다.
"""
from __future__ import annotations

import argparse
import csv
import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 기본 콘솔은 cp949라 보고의 '—' 같은 문자에서 죽는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.geometry import BattlefieldLayout                 # noqa: E402
from vtmak.stkg.resolve import load_uuid_map                 # noqa: E402
from vtmak.stkg.rewrite import OUT_COLS, rewrite             # noqa: E402

REQUIRED = ("subject", "predicate", "timestamp", "source", "latitude",
            "longitude")


def _out_name(path: Path) -> str:
    """'UAV 2_20260803_dataset.csv' → 'UAV 2_20260803_annotated.csv'."""
    return re.sub(r"_dataset$", "_annotated", path.stem) + ".csv"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="각 CSV를 따로 후처리한다. 열은 8열 그대로다.")
    ap.add_argument("csv", nargs="*",
                    help="입력 CSV. 안 주면 --csv-dir에서 찾는다")
    ap.add_argument("--csv-dir", default=str(ROOT / "build" / "csv"))
    ap.add_argument("--out", default=str(ROOT / "build" / "stkg"))
    ap.add_argument("--oob", default="",
                    help="CSV와 짝이 되는 .oob. 없으면 uuid를 해석하지 않는다")
    args = ap.parse_args()

    paths = ([Path(p) for p in args.csv] if args.csv
             else sorted(Path(p) for p in
                         glob.glob(str(Path(args.csv_dir) / "*_dataset.csv"))))
    if not paths:
        print(f"입력 CSV 없음 ({args.csv_dir})")
        return 1

    layout = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    uuid_map = load_uuid_map(args.oob) if args.oob else {}
    if not uuid_map:
        print("  uuid 표 없음 — uuid 대상은 원문을 유지한다(--oob로 줄 것)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    report: list[str] = [
        "# 시뮬레이터 CSV 후처리 보고", "",
        "입력 파일 하나당 출력 파일 하나. 열은 내보내기가 준 8열 그대로다.",
        "행은 시뮬레이터 인프라 객체만 지운다.", ""]

    for path in paths:
        if not path.exists():
            print(f"  {path.name}: 없음 — 건너뜀")
            failed = True
            continue
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                print(f"  {path.name}: 필수 열 없음 {missing} — 건너뜀")
                failed = True
                continue
            rows = list(reader)

        out_rows, links, unresolved, tally = rewrite(rows, layout, uuid_map)

        ok = (tally.total == len(rows)
              and tally.out == len(out_rows)
              and tally.total == tally.out + tally.dropped)
        failed = failed or not ok

        dest = out_dir / _out_name(path)
        with open(dest, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, OUT_COLS)
            w.writeheader()
            w.writerows(out_rows)

        mark = "" if ok else "  ← 행 회계 불일치"
        print(f"  {path.name:42} {len(rows):7,}행 → {len(out_rows):7,}행 "
              f"(삭제 {tally.dropped:,}) · object 채움 "
              f"{tally.with_object:7,}{mark}")
        report += _section(path, dest, tally, links, unresolved)

    (out_dir / "report.md").write_text("\n".join(report) + "\n",
                                       encoding="utf-8")
    print(f"→ {out_dir}")
    if failed:
        print("행 회계가 맞지 않는 입력이 있다")
        return 1
    return 0


def _section(src: Path, dest: Path, tally, links, unresolved) -> list[str]:
    lines = [f"## {src.name}", "",
             f"- 출력: `{dest.name}`",
             f"- 입력 행 {tally.total:,} = 출력 행 {tally.out:,} + 삭제 행 "
             f"{tally.dropped:,} "
             f"({'맞음' if tally.total == tally.out + tally.dropped else '불일치'})",
             f"- object 채워진 행: {tally.with_object:,}",
             f"- 발사체 행 {tally.munitions:,} 중 사수 확정 "
             f"{tally.munitions_linked:,}", "",
             "### 술어별 행수", ""]
    for k, v in tally.predicates.most_common():
        lines.append(f"- `{k}`: {v:,}")

    if tally.dropped_subjects:
        lines += ["", "### 삭제한 객체", ""]
        lines += [f"- {k}: {v:,}행"
                  for k, v in tally.dropped_subjects.most_common()]
    if links:
        lines += ["", "### 확정된 fired_by", ""]
        for (source, munition), link in sorted(links.items()):
            lines.append(f"- [{source}] `{munition}` → `{link.shooter}` "
                         f"({link.evidence})")
    if unresolved:
        lines += ["", "### 확정하지 못한 발사체 (object 비움)", ""]
        lines += [f"- {u}" for u in unresolved]
    if tally.unmapped:
        lines += ["", "### 정규형이 없는 술어 (원문 유지)", ""]
        lines += [f"- {k}: {v:,}행" for k, v in tally.unmapped.most_common()]
    if tally.unparsed:
        lines += ["", "### 파싱 실패 술어 (원문 유지)", ""]
        lines += [f"- {v:,}행  `{k[:120]}`"
                  for k, v in tally.unparsed.most_common()]
    return lines + [""]


if __name__ == "__main__":
    raise SystemExit(main())
