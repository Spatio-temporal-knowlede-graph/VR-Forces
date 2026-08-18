"""시뮬레이터 CSV 후처리. 입력 파일 하나당 출력 파일 하나.

전역(ground_truth)과 드론(UAV n)을 합치지 않는다. 전역은 정답이고 드론은
관측이며 시각대도 다르다(실측: 전역 08:09~08:16, 드론 22:00~22:07).

열은 내보내기가 준 열을 순서까지 그대로 낸다. 판마다 열 수가 다르다 —
20260803은 8열(끝이 CID), 20260809는 CID 대신 상태 열 10개가 붙어 17열이다.
목록을 못박지 않고 입력 헤더를 물려받는다. 우리가 바꾸는 것은 predicate와
object 두 열뿐이다.

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
from vtmak.stkg.rewrite import out_columns, rewrite          # noqa: E402
from vtmak.stkg.schema import REQUIRED, standardize          # noqa: E402


def _out_name(path: Path) -> str:
    """'UAV 2_20260803_dataset.csv' → 'UAV 2_20260803_annotated.csv'."""
    return re.sub(r"_dataset$", "_annotated", path.stem) + ".csv"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="각 CSV를 따로 후처리한다. 열은 8열 그대로다.")
    ap.add_argument("csv", nargs="*",
                    help="입력 CSV. 안 주면 --csv-dir에서 찾는다")
    ap.add_argument("--stamp", default="",
                    help="날짜 도장으로 골라 받는다(예: 20260809_175237)")
    ap.add_argument("--csv-dir", default=str(ROOT / "build" / "csv"))
    ap.add_argument("--out", default=str(ROOT / "build" / "stkg"))
    ap.add_argument("--oob", default="",
                    help="CSV와 짝이 되는 .oob. 없으면 uuid를 해석하지 않는다")
    ap.add_argument("--control-points", default=str(
        ROOT / "build" / "timetable" / "battle_control_points.csv"),
        help="04가 낸 통제점 대조표. 없으면 통제점 이름을 그대로 둔다")
    args = ap.parse_args()

    pattern = f"*_{args.stamp}_dataset.csv" if args.stamp else "*_dataset.csv"
    paths = ([Path(p) for p in args.csv] if args.csv
             else sorted(Path(p) for p in
                         glob.glob(str(Path(args.csv_dir) / pattern))))
    if not paths:
        print(f"입력 CSV 없음 ({args.csv_dir}/{pattern})")
        return 1

    layout = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    uuid_map = load_uuid_map(args.oob) if args.oob else {}
    if not uuid_map:
        print("  uuid 표 없음 — uuid 대상은 원문을 유지한다(--oob로 줄 것)")

    place_names: dict[str, str] = {}
    cp = Path(args.control_points)
    if cp.exists():
        with open(cp, encoding="utf-8-sig", newline="") as fh:
            place_names = {r["marking"]: r["loc_id"] for r in csv.DictReader(fh)}
        print(f"  통제점 대조표 {len(place_names)}행")
    else:
        print(f"  통제점 대조표 없음({cp.name}) — 통제점 이름을 그대로 둔다")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    report: list[str] = [
        "# 시뮬레이터 CSV 후처리 보고", "",
        "입력 파일 하나당 출력 파일 하나. 열은 내보내기가 준 것 그대로다.",
        "행은 시뮬레이터 인프라 객체만 지운다.", ""]

    for path in paths:
        if not path.exists():
            print(f"  {path.name}: 없음 — 건너뜀")
            failed = True
            continue
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [standardize(r) for r in reader]
        missing = [c for c in REQUIRED if rows and c not in rows[0]]
        if missing:
            print(f"  {path.name}: 필수 열 없음 {missing} — 건너뜀")
            failed = True
            continue

        out_rows, links, unresolved, tally = rewrite(
            rows, layout, uuid_map, place_names=place_names)

        ok = (tally.total == len(rows)
              and tally.out == len(out_rows)
              and tally.total == tally.out + tally.dropped)
        failed = failed or not ok

        dest = out_dir / _out_name(path)
        with open(dest, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, out_columns(out_rows))
            w.writeheader()
            w.writerows(out_rows)

        mark = "" if ok else "  ← 행 회계 불일치"
        print(f"  {path.name:42} {len(rows):7,}행 → {len(out_rows):7,}행 "
              f"(삭제 {tally.dropped:,}) · object 채움 "
              f"{tally.with_object:7,}{mark}")
        print(f"  {'':42} 등장 객체 {tally.seen:3} "
              f"(주체 {len(tally.subjects):3} = 엔티티 {tally.entities:3} + "
              f"발사체 {len(tally.munition_subjects)} + "
              f"통제점 {len(tally.control_subjects)}"
              f"{f' , 대상에만 {len(tally.object_entities - tally.subjects)}'
                 if tally.object_entities - tally.subjects else ''}) · "
              f"지명 {len(tally.object_locations):2} · "
              f"삭제 객체 {len(tally.dropped_names)}")
        report += _section(path, dest, tally, links, unresolved,
                           out_columns(out_rows))

    (out_dir / "report.md").write_text("\n".join(report) + "\n",
                                       encoding="utf-8")
    print(f"→ {out_dir}")
    if failed:
        print("행 회계가 맞지 않는 입력이 있다")
        return 1
    return 0


def _section(src: Path, dest: Path, tally, links, unresolved,
             cols: list[str]) -> list[str]:
    lines = [f"## {src.name}", "",
             f"- 출력: `{dest.name}`",
             f"- 열 {len(cols)}개(내보내기가 준 그대로): "
             + ", ".join(f"`{c}`" for c in cols),
             f"- 입력 행 {tally.total:,} = 출력 행 {tally.out:,} + 삭제 행 "
             f"{tally.dropped:,} "
             f"({'맞음' if tally.total == tally.out + tally.dropped else '불일치'})",
             f"- object 채워진 행: {tally.with_object:,}",
             f"- 발사체 행 {tally.munitions:,} 중 사수 확정 "
             f"{tally.munitions_linked:,}", "",
             "### 등장 객체", "",
             f"- 객체 **{tally.seen}개** — 주체 {len(tally.subjects)} "
             f"(엔티티 {tally.entities} + 발사체 "
             f"{len(tally.munition_subjects)} + 통제점 "
             f"{len(tally.control_subjects)})",
             f"- 대상(object)에만 나오는 객체: "
             f"{len(tally.object_entities - tally.subjects)}",
             f"- 지명·통제점: {len(tally.object_locations)}개",
             f"- 지명에 못 붙은 좌표: {len(tally.object_coords)}개",
             f"- 삭제한 인프라 객체: {len(tally.dropped_names)}개", ""]
    if tally.object_locations:
        lines += ["등장 지명·통제점: "
                  + ", ".join(f"`{k}`" for k in sorted(tally.object_locations)),
                  ""]
    lines += ["### 술어별 행수", ""]
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
