"""이벤트 → 확정 스펙 → PLN → .scnx (+G0 사거리, +G3 정합성)."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 기본 콘솔은 cp949라 리포트의 '—' 같은 문자에서 죽는다.
# 사용자가 PYTHONIOENCODING을 걸어야 하는 상황을 만들지 않는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.gates import blocking, check_g0                        # noqa: E402
from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import Event, PatternMap                        # noqa: E402
from vtmak.ranges import WeaponRanges                             # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.engagements import (                               # noqa: E402
    AUDIT_COLUMNS, EnrichmentConfig, expected_suppress_spo, slot_audit_rows)
from vtmak.scnx.fixed import load_fixed            # noqa: E402
from vtmak.scnx.gates import check_g3, validate_interaction_plan  # noqa: E402
from vtmak.scnx.golden import Golden                              # noqa: E402
from vtmak.scnx.pack import ensure_golden                         # noqa: E402
from vtmak.scnx.spec import build_spec                            # noqa: E402
from vtmak.scnx.writer import get_writer                          # noqa: E402

CFG = ROOT / "config"
EVENTS = ROOT / "build" / "events" / "battle.jsonl"
OUT = ROOT / "build" / "scnx"


def _report(violations) -> int:
    for v in violations:
        print(f"  [{v.gate}/{v.code}/{v.severity}] {v.detail}")
    return len(blocking(violations))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(ROOT / "yewon_test"),
                    help="golden .scnx 또는 그 내용이 든 디렉터리")
    ap.add_argument("--writer", choices=["template", "dir"], default="template")
    args = ap.parse_args()

    if not EVENTS.exists():
        print("build/events/battle.jsonl 없음 — 02를 먼저 실행할 것")
        return 1
    events = [Event(**json.loads(line))
              for line in EVENTS.read_text(encoding="utf-8").splitlines() if line]

    layout = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    pmap = PatternMap.load(CFG / "pattern_map.csv")
    cmap = ClassMap.load(CFG / "entity_class_map.csv")
    ranges = WeaponRanges.load(CFG / "weapon_ranges.csv")
    dis = DisCatalog.load(CFG / "dis_catalog.csv")
    registry = build_registry(events, cmap, layout.static_ids())

    if _report(check_g0(events, registry, layout, ranges)):
        print("G0 차단 — 레이아웃을 고칠 것 (config/battlefield_layout.json)")
        return 1

    fixed = load_fixed(CFG / "fixed_objects.json", ROOT, layout)
    enrichment_config = EnrichmentConfig.load(
        CFG / "engagement_enrichment.json")
    spec = build_spec(events, registry, layout, pmap,
                      TaskCatalog.load(CFG / "task_catalog.csv"),
                      TaskKinds.load(CFG / "task_kinds.csv"),
                      dis, ranges,
                      scenario_id="battle", fixed=fixed,
                      enrichment_config=enrichment_config)

    golden_path = ensure_golden(args.golden)
    if _report(check_g3(spec, Golden.load(golden_path), dis)):
        print("G3 차단 — .scnx를 쓰지 않는다")
        return 1

    if _report(validate_interaction_plan(spec, enrichment_config)):
        print("G4 차단 — .scnx를 쓰지 않는다")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    out = get_writer(args.writer, str(golden_path)).write(spec, OUT)

    # 교전 슬롯 산출물. G4까지 통과한 뒤에만 쓴다 — 차단된 빌드의 슬롯이
    # 다음 단계(05)에 흘러들어가지 않게 한다.
    engagement_dir = ROOT / "build" / "engagements"
    engagement_dir.mkdir(parents=True, exist_ok=True)
    (engagement_dir / "slots.jsonl").write_text(
        "".join(json.dumps(s.to_json(), ensure_ascii=False, sort_keys=True)
                + "\n" for s in spec.engagement_slots), encoding="utf-8")
    with open(engagement_dir / "audit.csv", "w", encoding="utf-8",
              newline="") as fh:
        w = csv.writer(fh)
        w.writerow(AUDIT_COLUMNS)
        w.writerows(slot_audit_rows(spec))

    # 통제점 대조표. `.scnx`에는 안 들어가고 후처리(05)가 쓴다.
    # 시뮬레이터가 통제점을 marking으로 내보내는데 그 marking이 순번(P{k})이라
    # 지명이 사라진다(실측 `Move-To Waypoint: "P3"`). 순번을 매기는 코드가
    # 표도 같이 내므로 어긋날 수 없다 — writer._oob의 enumerate와 같은 순서다.
    cp_path = ROOT / "build" / "timetable" / "battle_control_points.csv"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cp_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["marking", "loc_id", "uuid", "lat", "lon"])
        for k, c in enumerate(spec.control_objects, 1):
            w.writerow([f"P{k}", c.ref_id, c.uuid,
                        f"{c.coord.lat:.7f}" if c.coord else "",
                        f"{c.coord.lon:.7f}" if c.coord else ""])
    print(f"통제점 대조표 {len(spec.control_objects)}행 → {cp_path.name}")
    planned = sum(1 for v in spec.entity_plans.values()
                  if any(s.pln for s in v))
    tasks = sum(1 for v in spec.entity_plans.values() for s in v if s.pln)
    print(f"엔티티 {len(spec.entities)} · 통제점 {len(spec.control_objects)} · "
          f"고정 객체 {len(spec.fixed_objects)} · "
          f"플랜 보유 {planned} · 태스크 {tasks}")
    n_source = sum(1 for s in spec.engagement_slots if s.origin == "source")
    n_added = sum(1 for s in spec.engagement_slots if s.origin == "enrichment")
    n_spo = len(expected_suppress_spo(tuple(spec.engagement_slots)))
    print(f"원문 교전 {n_source} · 신규 교전 {n_added} · 예상 제압 SPO {n_spo}")
    uavs = [f for f in spec.fixed_objects if not f.is_route]
    routes = [f for f in spec.fixed_objects if f.is_route]
    if uavs:
        # 고정 객체는 명부 규모와 무관하게 같은 배치를 갖는다. 순찰 중심과
        # 고도, 그리고 몇 바퀴 도는지가 여기서 바로 보여야 한다.
        print("  고정(규모 불변): "
              + ", ".join(
                  f"{f.marking}@{f.coord.alt:.0f}m"
                  + (f"↻{f.patrol_center_loc.removeprefix('LOC_')}"
                     f"×{f.patrol_laps}바퀴" if f.patrol_center_loc else "")
                  + (f"[{'+'.join(f.plan_actions)}]" if f.plan_actions else "")
                  for f in uavs)
              + (f" · 순찰로 {len(routes)}" if routes else ""))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
