"""이벤트 → 확정 스펙 → PLN → .scnx (+G0 사거리, +G3 정합성)."""
from __future__ import annotations

import argparse
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
from vtmak.scnx.fixed import load_fixed            # noqa: E402
from vtmak.scnx.gates import check_g3                             # noqa: E402
from vtmak.scnx.golden import Golden                              # noqa: E402
from vtmak.scnx.pack import ensure_golden                         # noqa: E402
from vtmak.scnx.places import PlaceCodes                          # noqa: E402
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
    spec = build_spec(events, registry, layout, pmap,
                      TaskCatalog.load(CFG / "task_catalog.csv"),
                      TaskKinds.load(CFG / "task_kinds.csv"),
                      dis, ranges,
                      scenario_id="battle", fixed=fixed)

    golden_path = ensure_golden(args.golden)
    if _report(check_g3(spec, Golden.load(golden_path), dis)):
        print("G3 차단 — .scnx를 쓰지 않는다")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    # 통제점 marking을 지명 코드로 낸다 — 순번(P{k})이면 CSV로 그대로 새어
    # 나가 지명이 사라진다.
    place_codes = PlaceCodes.load(CFG / "location_codes.csv")
    out = get_writer(args.writer, str(golden_path),
                      place_codes=place_codes).write(spec, OUT)
    planned = sum(1 for v in spec.entity_plans.values()
                  if any(s.pln for s in v))
    tasks = sum(1 for v in spec.entity_plans.values() for s in v if s.pln)
    print(f"엔티티 {len(spec.entities)} · 통제점 {len(spec.control_objects)} · "
          f"고정 객체 {len(spec.fixed_objects)} · "
          f"플랜 보유 {planned} · 태스크 {tasks}")
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
