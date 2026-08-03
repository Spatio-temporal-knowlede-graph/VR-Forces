"""시뮬레이터 CSV → STKG 관계·위치 테이블. **소스별로 나눠서** 낸다.

06_stkg_export.py는 전역(ground_truth)과 드론(UAV n) CSV를 합쳐 하나의
relations.csv로 낸다. 이 스크립트는 입력 파일 하나당 출력 디렉터리 하나를
만든다. 관측 주체가 다른 데이터를 섞지 않아야 하는 이유는 두 가지다.

1. 전역은 정답(ground truth), 드론은 관측이다. 둘을 한 파일에 담으면 관측
   성능을 재려는 쪽이 정답과 관측을 갈라내는 일부터 해야 한다.
2. 전역과 드론의 시각대가 다르다(실측: 전역 08:09~08:16, 드론 22:00~22:07).
   한 테이블에 담긴 t_start/t_end를 시간축으로 읽으면 사실이 아닌 순서가
   나온다.

관계 추출 자체는 06과 같은 vtmak.stkg.export.build를 쓴다. build가 이미
source별로 fired_by를 갈라 보고 collapse도 source를 묶음 키에 넣으므로,
파일을 나눠 돌린 결과와 합쳐 돌린 결과는 관계 내용이 같다 — 배치만 다르다.
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
from vtmak.stkg.derive import load_munition_map              # noqa: E402
from vtmak.stkg.export import build, write_all               # noqa: E402
from vtmak.stkg.resolve import load_uuid_map                 # noqa: E402


def _slug(path: Path) -> str:
    """'UAV 2_20260803_dataset.csv' → 'uav_2'. 날짜를 떼는 이유는 다시
    뽑을 때마다 디렉터리가 늘어나면 비교가 어려워지기 때문이다."""
    stem = re.sub(r"_\d{8}_dataset$", "", path.stem)
    return re.sub(r"[^0-9A-Za-z]+", "_", stem).strip("_").lower() or "unnamed"


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _discover(csv_dir: Path) -> tuple[list[Path], list[Path]]:
    """전역과 드론을 파일명으로 가른다. 이름 규칙이 바뀌면 --global/--uav로
    직접 준다."""
    everything = sorted(Path(p) for p in glob.glob(str(csv_dir / "*_dataset.csv")))
    gt = [p for p in everything if p.name.lower().startswith("ground_truth")]
    uav = [p for p in everything if p not in gt]
    return gt, uav


def main() -> int:
    ap = argparse.ArgumentParser(
        description="전역 CSV와 드론별 CSV를 각각 따로 후처리한다.")
    ap.add_argument("--csv-dir", default=str(ROOT / "build" / "csv"),
                    help="입력 디렉터리. --global/--uav를 주면 무시된다")
    ap.add_argument("--global", dest="global_paths", nargs="*", default=None,
                    metavar="CSV", help="전역(ground truth) CSV 경로")
    ap.add_argument("--uav", dest="uav_paths", nargs="*", default=None,
                    metavar="CSV", help="드론별 CSV 경로")
    ap.add_argument("--out", default=str(ROOT / "build" / "stkg_split"))
    ap.add_argument("--oob", default="",
                    help="CSV와 짝이 되는 .oob. 없으면 uuid를 해석하지 않는다")
    args = ap.parse_args()

    if args.global_paths is None and args.uav_paths is None:
        gt_paths, uav_paths = _discover(Path(args.csv_dir))
    else:
        gt_paths = [Path(p) for p in (args.global_paths or [])]
        uav_paths = [Path(p) for p in (args.uav_paths or [])]

    jobs = [("전역", p) for p in gt_paths] + [("드론", p) for p in uav_paths]
    if not jobs:
        print(f"입력 CSV 없음 ({args.csv_dir})")
        return 1

    layout = BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")
    uuid_map = load_uuid_map(args.oob) if args.oob else {}
    if not uuid_map:
        print("  uuid 표 없음 — uuid 대상은 원문을 유지한다(--oob로 줄 것)")
    munition_map = load_munition_map(ROOT / "config" / "munition_map.csv")

    out_root = Path(args.out)
    summary: list[dict] = []
    failed = False

    for kind, path in jobs:
        if not path.exists():
            print(f"  [{kind}] {path.name}: 없음 — 건너뜀")
            failed = True
            continue
        rows = _read(path)
        relations, positions, tally, unresolved = build(
            rows, layout, uuid_map, munition_map)
        slug = _slug(path)
        write_all(out_root / slug, relations, positions, tally, unresolved)

        accounted = (tally.relation_rows + tally.position_rows
                     + tally.dropped + tally.quarantined)
        ok = accounted == tally.total
        failed = failed or not ok
        preds: dict[str, int] = {}
        for r in relations:
            preds[r.predicate] = preds.get(r.predicate, 0) + 1
        summary.append({"kind": kind, "slug": slug, "file": path.name,
                        "total": tally.total, "relations": len(relations),
                        "positions": tally.position_rows,
                        "dropped": tally.dropped, "preds": preds,
                        "unresolved": len(unresolved), "ok": ok})
        mark = "" if ok else "  ← 회계 불일치"
        print(f"  [{kind}] {slug:14} 입력 {tally.total:7,} · 관계 "
              f"{len(relations):5,} · 위치 {tally.position_rows:7,} · 제외 "
              f"{tally.dropped:6,}{mark}")

    _write_summary(out_root, summary)
    print(f"→ {out_root}  ({len(summary)}개 디렉터리)")
    if failed:
        print("회계가 맞지 않는 입력이 있다 — 행이 조용히 사라졌다")
        return 1
    return 0


def _write_summary(out_root: Path, summary: list[dict]) -> None:
    """소스별 결과를 한눈에 비교하는 표. 드론 커버리지 차이를 보려면
    이 표가 있어야 한다 — 디렉터리를 하나씩 열어보게 만들지 않는다."""
    out_root.mkdir(parents=True, exist_ok=True)
    preds = sorted({p for s in summary for p in s["preds"]})
    head = ["구분", "출력", "입력행", "관계", "위치", "제외", "미확정"] + preds
    lines = ["# STKG 소스별 추출 요약", "",
             "| " + " | ".join(head) + " |",
             "|" + "|".join(["---"] * len(head)) + "|"]
    for s in summary:
        cells = [s["kind"], f'`{s["slug"]}/`', f'{s["total"]:,}',
                 f'{s["relations"]:,}', f'{s["positions"]:,}',
                 f'{s["dropped"]:,}', str(s["unresolved"])]
        cells += [str(s["preds"].get(p, 0)) for p in preds]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "각 디렉터리에 `relations.csv` · `positions.csv` · "
              "`report.md`가 들어 있다.", "",
              "전역(ground truth)과 드론(UAV)은 관측 시각대가 다르므로 "
              "한 테이블로 합치지 않는다.", ""]
    (out_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
