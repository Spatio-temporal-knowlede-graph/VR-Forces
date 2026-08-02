"""이벤트 → 객체별 타임테이블 CSV (+G2 커버리지)."""
from __future__ import annotations

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

from vtmak.gates import blocking                                  # noqa: E402
from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import Event                                    # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402
from vtmak.timetable import build_timetable, check_g2             # noqa: E402

CONFIG = ROOT / "config"
EVENTS = ROOT / "build" / "events" / "battle.jsonl"
OUT = ROOT / "build" / "timetable"


def main() -> int:
    if not EVENTS.exists():
        print("build/events/battle.jsonl 없음 — 02를 먼저 실행할 것")
        return 1
    events = [Event(**json.loads(line))
              for line in EVENTS.read_text(encoding="utf-8").splitlines() if line]

    layout = BattlefieldLayout.load(CONFIG / "battlefield_layout.json")
    cmap = ClassMap.load(CONFIG / "entity_class_map.csv")
    registry = build_registry(events, cmap, layout.static_ids())

    cells = build_timetable(events, registry)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "battle.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["object_id", "t0", "t1", "state", "location"])
        for c in cells:
            w.writerow([c.object_id, c.t0, c.t1, c.state, c.location])

    violations = check_g2(events, registry)
    for v in violations:
        print(f"  [{v.gate}/{v.code}/{v.severity}] {v.detail}")
    hard = blocking(violations)
    print(f"셀 {len(cells)} · 객체 {len(registry)} · "
          f"G2 {len(violations)}건 (차단 {len(hard)}건)")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
