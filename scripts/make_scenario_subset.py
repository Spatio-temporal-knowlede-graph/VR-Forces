"""원문 → 객체 수를 줄인 원문. 파이프라인 단계가 아니라 저작 도구다.

원문은 한 줄이 한 이벤트 묶음이다(사격 문장 + 공격자/목표 선언 + 상태 전환).
그래서 감축을 '문장 편집'이 아니라 **줄 걸러내기**로 한다 — 빠진 객체를
언급하는 줄을 통째로 버리면 사수만 남고 표적이 사라지는 일이 구조적으로 없다.

객체 고르는 순서
1. 부대별 정원을 전체 비율대로 나눈다(최대잔여법, 부대당 최소 1).
   부대 유형이 사라지면 규모 비교가 성립하지 않으므로 바닥을 1로 둔다.
2. 정원 안에서 **교전 쌍을 통째로** 집는다. 한쪽만 남기면 그 사격 문장이
   통째로 버려져 교전 수가 정원보다 훨씬 빨리 준다.
3. 남은 정원을 번호 순으로 채운다.

정적 객체(포병진지·킬존 등)는 엔티티가 아니라 표적 지역이라 항상 남기고
객체 수에도 세지 않는다.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import PatternMap, parse_scenario               # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402
from vtmak.roster import engagement_pairs_of, unit_of             # noqa: E402

CONFIG = ROOT / "config"
_ID = re.compile(r"\b(?:FR|EN|OBJ)-[A-Z0-9]+-\d+\b")


def ids_in(line: str) -> set[str]:
    return set(_ID.findall(line))


def quotas(units: dict[str, list[str]], target: int) -> dict[str, int]:
    """부대별 정원 — 비율 배분 + 최대잔여법. 바닥 1, 천장 실제 보유 수."""
    total = sum(len(v) for v in units.values())
    ratio = target / total
    want: dict[str, float] = {u: len(v) * ratio for u, v in units.items()}
    out = {u: min(len(units[u]), max(1, int(w))) for u, w in want.items()}
    # 바닥·천장 때문에 어긋난 만큼을 잔여가 큰 부대부터 ±1 한다.
    order = sorted(units, key=lambda u: (-(want[u] - int(want[u])), u))
    while sum(out.values()) < target:
        moved = False
        for u in order:
            if out[u] < len(units[u]):
                out[u] += 1
                moved = True
                if sum(out.values()) == target:
                    break
        if not moved:
            break
    while sum(out.values()) > target:
        moved = False
        for u in reversed(order):
            if out[u] > 1:
                out[u] -= 1
                moved = True
                if sum(out.values()) == target:
                    break
        if not moved:
            break
    return out


def choose(units: dict[str, list[str]], quota: dict[str, int],
           pairs: list[tuple[str, str]]) -> set[str]:
    keep: set[str] = set()
    room = dict(quota)

    def take(oid: str) -> bool:
        u = unit_of(oid)
        if oid in keep:
            return True
        if room.get(u, 0) <= 0:
            return False
        keep.add(oid)
        room[u] -= 1
        return True

    # 2) 교전 쌍 우선. 양쪽 다 들어갈 수 있을 때만 집는다.
    for a, t in pairs:
        if a in keep and t in keep:
            continue
        need = collections.Counter(
            unit_of(o) for o in (a, t) if o not in keep)
        if any(room.get(u, 0) < n for u, n in need.items()):
            continue
        take(a)
        take(t)
    # 3) 남은 정원은 번호 순으로.
    for u in sorted(units):
        for oid in units[u]:
            if room[u] <= 0:
                break
            take(oid)
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "scenario_original"
                                         / "scenario.txt"))
    ap.add_argument("--objects", type=int, required=True,
                    help="목표 task 가능 객체 수(정적 객체는 세지 않는다)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.src)
    pmap = PatternMap.load(CONFIG / "pattern_map.csv")
    layout = BattlefieldLayout.load(CONFIG / "battlefield_layout.json")
    cmap = ClassMap.load(CONFIG / "entity_class_map.csv")
    text = src.read_text(encoding="utf-8")
    res = parse_scenario(text, pmap)
    reg = build_registry(res.events, cmap, layout.static_ids())

    static = {o for o, d in reg.items() if not d.taskable}
    units: dict[str, list[str]] = collections.defaultdict(list)
    for o, d in reg.items():
        if d.taskable:
            units[unit_of(o)].append(o)
    for v in units.values():
        v.sort()
    total = sum(len(v) for v in units.values())
    print(f"{src.name}: 줄 {len(text.splitlines())} · "
          f"task 가능 {total} ({len(units)}개 부대) · 정적 {len(static)}")

    q = quotas(units, args.objects)
    pairs = sorted(engagement_pairs_of(res.events))
    keep = choose(units, q, pairs) | static

    lines = [ln for ln in text.splitlines()
             if not (ids_in(ln) - static) - keep]
    got = set()
    for ln in lines:
        got |= ids_in(ln)
    kept_task = sorted(got - static)

    out = Path(args.out)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    live = sum(1 for a, t in pairs if a in got and t in got)
    print(f"→ {out.name}: 줄 {len(lines)} · task 가능 {len(kept_task)} "
          f"({len({unit_of(o) for o in kept_task})}개 부대) · "
          f"교전 쌍 {live}/{len(pairs)}")
    if len(kept_task) != args.objects:
        print(f"  ← 목표 {args.objects}과 다르다")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
