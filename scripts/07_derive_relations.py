"""파생 관계 레이어를 산출물로 낸다.

규칙은 전부 `build/events/battle.jsonl`의 이벤트만 읽는다. 부대·편제가 주어인
fact는 내지 않는다 — 소대·중대·대대는 원문에 없는 저작물이라 관측으로 확인할
길이 없다. layer 열은 그대로 둔다: 추출 정본과 합성을 섞으면 어느 쪽이 만든
값인지 되물어야 한다.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.derive.config import DeriveRules                    # noqa: E402
from vtmak.derive.events import EventIndex                     # noqa: E402
from vtmak.derive.relations import (r1r2_hit_state,            # noqa: E402
                                    r3_direct_fire, r4_indirect_fire,
                                    r7_precedes)

EVENTS = ROOT / "build" / "events" / "battle.jsonl"
CFG = ROOT / "config"
OUT = ROOT / "build" / "derive"


def main() -> int:
    if not EVENTS.exists():
        print(f"이벤트 없음({EVENTS}) — 02를 먼저 돌린다")
        return 1

    idx = EventIndex.load(EVENTS)
    rules = DeriveRules.load(CFG / "derive_rules.csv")

    results = [
        ("R1·R2", r1r2_hit_state(idx, rules)),
        ("R3", r3_direct_fire(idx)),
        ("R4", r4_indirect_fire(idx, rules)),
        ("R7", r7_precedes(idx, rules)),
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    rows, unmatched = [], []
    for name, res in results:
        for r in res.relations:
            rows.append([r.rule_id, r.layer, r.predicate, r.subject, r.object,
                         "|".join(r.provenance)])
        unmatched += [(name, u) for u in res.unmatched]

    with open(OUT / "relations.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rule_id", "layer", "predicate", "subject", "object",
                    "provenance"])
        w.writerows(rows)

    kinds = Counter(r[2] for r in rows)
    lines = ["# 파생 관계 보고", "",
             f"관계 {len(rows):,}건 · 미매칭 {len(unmatched):,}건", "",
             "## 술어별", ""]
    lines += [f"- `{k}`: {v:,}" for k, v in kinds.most_common()]
    lines += ["", "## 레이어별", ""]
    lines += [f"- `{k}`: {v:,}" for k, v in Counter(r[1] for r in rows).most_common()]

    # rule_id × predicate 분해. 술어별 집계만 보면 같은 술어를 두 규칙이
    # 나눠 내는 경우(R1·R2가 같은 hitBy를 상태별로 가르는 것처럼)가 숨는다.
    # rule_id별 내역을 나란히 두어 어느 건이 어느 규칙에서 왔는지 보이게 한다.
    rule_predicate = Counter((r[0], r[2]) for r in rows)
    lines += ["", "## rule_id × 술어", ""]
    lines += ["| rule_id | 술어 | 건수 |", "| --- | --- | --- |"]

    def _rule_sort_key(rule_id: str):
        digits = "".join(c for c in rule_id if c.isdigit())
        return (int(digits) if digits else 0, rule_id)

    for (rid, pred), n in sorted(rule_predicate.items(),
                                  key=lambda kv: (_rule_sort_key(kv[0][0]),
                                                  kv[0][1])):
        lines.append(f"| `{rid}` | `{pred}` | {n:,} |")

    if unmatched:
        lines += ["", "## 미매칭 (앞 50건)", ""]
        lines += [f"- {n}: {u}" for n, u in unmatched[:50]]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"관계 {len(rows):,} · 미매칭 {len(unmatched):,} → {OUT}")
    for k, v in kinds.most_common():
        print(f"  {k:24} {v:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
