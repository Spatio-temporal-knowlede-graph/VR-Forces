"""원문 → 이벤트 JSONL (+G1 파싱, +G0 사거리 사전 점검)."""
from __future__ import annotations

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

from vtmak.gates import blocking, check_g0, check_g1              # noqa: E402
from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import PatternMap, parse_scenario               # noqa: E402
from vtmak.paths import SCENARIO                                   # noqa: E402
from vtmak.ranges import WeaponRanges                             # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402
from vtmak.roster import unit_of                                  # noqa: E402

CONFIG = ROOT / "config"
SRC = SCENARIO
OUT = ROOT / "build" / "events"


def main() -> int:
    layout = BattlefieldLayout.load(CONFIG / "battlefield_layout.json")
    pmap = PatternMap.load(CONFIG / "pattern_map.csv")
    cmap = ClassMap.load(CONFIG / "entity_class_map.csv")
    ranges = WeaponRanges.load(CONFIG / "weapon_ranges.csv")

    result = parse_scenario(SRC.read_text(encoding="utf-8"), pmap)
    full_registry = build_registry(result.events, cmap, layout.static_ids())
    print(f"문장 {result.sentence_count} · 이벤트 {len(result.events)} · "
          f"객체 {len(full_registry)}")

    # 명부 감축을 하지 않는다. 원문의 객체를 하나도 빼지 않고 그대로 쓴다.
    # VR-Forces 성능 때문에 부대별로 솎던 단계였는데, 객체가 줄면 원문과
    # 대조가 안 되고 STKG에서도 빠진 객체를 되살릴 방법이 없다.
    registry = full_registry
    units = len({unit_of(o) for o in registry})
    print(f"명부 감축 없음 → 객체 {len(registry)} ({units}개 부대) · "
          f"이벤트 {len(result.events)}")

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "battle.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for e in result.events:
            f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")

    taskable = sum(1 for d in registry.values() if d.taskable)
    print(f"  task 가능 {taskable} / 정적 {len(registry) - taskable}")

    violations = check_g1(result, layout, registry) + check_g0(
        result.events, registry, layout, ranges)
    for v in violations:
        print(f"  [{v.gate}/{v.code}/{v.severity}] {v.detail}")
    hard = blocking(violations)
    print(f"위반 {len(violations)}건 (차단 {len(hard)}건)")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
