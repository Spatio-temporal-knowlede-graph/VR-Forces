"""저작된 .scnx → 객체별 태스크 타임테이블 CSV.

03(원문 이벤트 기준 상태·위치 타임테이블)과 짝이 되는 산출물이다. 이건
실제 build/scnx/battle.scnx를 되읽어 '이 객체가 시나리오 안에서 무슨 행동을
몇 시에 갖는가'를 표로 만든다. 저작 누락(이벤트는 있는데 태스크가 없음)도
같은 표에 in_scnx=N으로 남는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 기본 콘솔은 cp949라 리포트의 '×' 같은 문자에서 죽는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import Event, PatternMap                        # noqa: E402
from vtmak.ranges import WeaponRanges                             # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402
from vtmak.scnx.audit import build_rows, hhmmss, read_scnx        # noqa: E402
from vtmak.scnx.catalog import DisCatalog, TaskCatalog            # noqa: E402
from vtmak.scnx.spec import build_spec                            # noqa: E402

CFG = ROOT / "config"
EVENTS = ROOT / "build" / "events" / "battle.jsonl"
SCNX = ROOT / "build" / "scnx" / "battle.scnx"
OUT = ROOT / "build" / "timetable"

TASK_COLS = ["object_id", "name", "faction", "entity_class", "type_group",
             "marking", "seq", "time", "time_s", "event_id", "template",
             "task_kind", "action_label", "task_type", "script_id",
             "ref_id", "ref_kind", "in_scnx", "note"]
OBJ_COLS = ["object_id", "name", "faction", "entity_class", "type_group",
            "marking", "initial_state", "n_tasks", "n_dropped",
            "t_first", "t_last", "kinds", "sequence"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scnx", default=str(SCNX))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    scnx = Path(args.scnx)
    if not scnx.exists():
        print(f"{scnx} 없음 — 04를 먼저 실행할 것")
        return 1
    if not EVENTS.exists():
        print("build/events/battle.jsonl 없음 — 02를 먼저 실행할 것")
        return 1

    events = [Event(**json.loads(line))
              for line in EVENTS.read_text(encoding="utf-8").splitlines() if line]
    layout = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    cmap = ClassMap.load(CFG / "entity_class_map.csv")
    registry = build_registry(events, cmap, layout.static_ids())
    spec = build_spec(events, registry, layout,
                      PatternMap.load(CFG / "pattern_map.csv"),
                      TaskCatalog.load(CFG / "task_catalog.csv"),
                      DisCatalog.load(CFG / "dis_catalog.csv"),
                      WeaponRanges.load(CFG / "weapon_ranges.csv"),
                      scenario_id="battle")

    contents = read_scnx(scnx)
    tasks, objects, warnings = build_rows(spec, contents, events)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / "battle_scnx_tasks.csv", TASK_COLS, [
        {"object_id": r.object_id, "name": r.name, "faction": r.faction,
         "entity_class": r.entity_class, "type_group": r.type_group,
         "marking": r.marking, "seq": r.seq or "", "time": hhmmss(r.time_s),
         "time_s": r.time_s if r.time_s is not None else "",
         "event_id": r.event_id, "template": r.template,
         "task_kind": r.task_kind, "action_label": r.action_label,
         "task_type": r.task_type, "script_id": r.script_id,
         "ref_id": r.ref_id, "ref_kind": r.ref_kind,
         "in_scnx": "Y" if r.in_scnx else "N", "note": r.note}
        for r in tasks])
    _write(out_dir / "battle_scnx_objects.csv", OBJ_COLS, [
        {"object_id": o.object_id, "name": o.name, "faction": o.faction,
         "entity_class": o.entity_class, "type_group": o.type_group,
         "marking": o.marking, "initial_state": o.initial_state,
         "n_tasks": o.n_tasks, "n_dropped": o.n_dropped,
         "t_first": hhmmss(o.t_first), "t_last": hhmmss(o.t_last),
         "kinds": o.kinds, "sequence": o.sequence}
        for o in objects])

    for w in warnings:
        print(f"  [경고] {w}")
    live = [r for r in tasks if r.in_scnx]
    planned = sum(1 for o in objects if o.n_tasks)
    print(f"객체 {len(objects)} (플랜 보유 {planned}) · "
          f"태스크 {len(live)} · 미저작 이벤트 {len(tasks) - len(live)}")
    for k, n in Counter(r.task_kind for r in live).most_common():
        print(f"  {k:<14} {n}")
    print(f"→ {out_dir / 'battle_scnx_tasks.csv'}")
    print(f"→ {out_dir / 'battle_scnx_objects.csv'}")
    return 0


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
