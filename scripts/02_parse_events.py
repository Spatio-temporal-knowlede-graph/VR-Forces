"""원문 → 이벤트 JSONL (+G1 파싱, +G0 사거리 사전 점검)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vtmak.gates import blocking, check_g0, check_g1              # noqa: E402
from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import PatternMap, parse_scenario               # noqa: E402
from vtmak.ranges import WeaponRanges                             # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402

CONFIG = ROOT / "config"
SRC = ROOT / "scenario_original" / "scenario_v3.txt"
OUT = ROOT / "build" / "events"


def main() -> int:
    layout = BattlefieldLayout.load(CONFIG / "battlefield_layout.json")
    pmap = PatternMap.load(CONFIG / "pattern_map.csv")
    cmap = ClassMap.load(CONFIG / "entity_class_map.csv")
    ranges = WeaponRanges.load(CONFIG / "weapon_ranges.csv")

    result = parse_scenario(SRC.read_text(encoding="utf-8"), pmap)
    registry = build_registry(result.events, cmap, layout.static_ids())

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "battle.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for e in result.events:
            f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")

    taskable = sum(1 for d in registry.values() if d.taskable)
    print(f"문장 {result.sentence_count} · 이벤트 {len(result.events)} · "
          f"객체 {len(registry)} (task 가능 {taskable} / 정적 "
          f"{len(registry) - taskable})")

    violations = check_g1(result, layout, registry) + check_g0(
        result.events, registry, layout, ranges)
    for v in violations:
        print(f"  [{v.gate}/{v.code}/{v.severity}] {v.detail}")
    hard = blocking(violations)
    print(f"위반 {len(violations)}건 (차단 {len(hard)}건)")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
