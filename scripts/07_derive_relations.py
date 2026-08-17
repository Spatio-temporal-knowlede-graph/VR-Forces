"""파생 관계 레이어를 산출물로 낸다.

vtmak/derive/는 지금까지 테스트만 있는 라이브러리였다. R1~R7은 원문 이벤트에서,
R8~R12는 편제에서 나온다. 둘을 한 파일에 내되 layer 열로 구분한다 — 추출 정본과
합성을 섞으면 어느 쪽이 만든 값인지 되물어야 한다.
"""
from __future__ import annotations

import csv
import json
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
from vtmak.derive.orbat_relations import (r8_part_of,          # noqa: E402
                                          r9_task_organization,
                                          r10_unit_moves, r11_unit_occupies,
                                          r12_unit_fires)
from vtmak.derive.relations import (r1r2_hit_state,            # noqa: E402
                                    r3_direct_fire, r4_indirect_fire,
                                    r6_unit_suppressed, r7_precedes)
from vtmak.geometry import BattlefieldLayout                   # noqa: E402
from vtmak.orbat import OrbatConfig, build_orbat               # noqa: E402
from vtmak.parser import Event                                 # noqa: E402
from vtmak.registry import ClassMap, build_registry             # noqa: E402

EVENTS = ROOT / "build" / "events" / "battle.jsonl"
CFG = ROOT / "config"
OUT = ROOT / "build" / "derive"


def main() -> int:
    if not EVENTS.exists():
        print(f"이벤트 없음({EVENTS}) — 02를 먼저 돌린다")
        return 1

    idx = EventIndex.load(EVENTS)
    rules = DeriveRules.load(CFG / "derive_rules.csv")
    evs = [Event(**{k: v for k, v in json.loads(l).items()
                    if k != "source_line"})
           for l in open(EVENTS, encoding="utf-8")]
    # 정적 객체(지명에 이름을 붙인 바인딩) 7개는 static_ids로 넘겨야
    # build_orbat이 역할 조회에서 KeyError 없이 넘어간다 — 02·03·04·06과
    # 같은 패턴이다.
    layout = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    cmap = ClassMap.load(CFG / "entity_class_map.csv")
    reg = build_registry(evs, cmap, layout.static_ids())
    orbat = build_orbat(reg, OrbatConfig.load(CFG / "orbat.json"))

    results = [
        ("R1·R2", r1r2_hit_state(idx, rules)),
        ("R3", r3_direct_fire(idx)),
        ("R4", r4_indirect_fire(idx, rules)),
        ("R6", r6_unit_suppressed(idx, rules, orbat=orbat)),
        ("R7", r7_precedes(idx, rules)),
        ("R8", r8_part_of(orbat)),
        ("R9", r9_task_organization(orbat)),
        ("R10", r10_unit_moves(idx, orbat, rules)),
        ("R11", r11_unit_occupies(idx, orbat, rules)),
        ("R12", r12_unit_fires(idx, orbat, rules)),
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
    unit_ids = {u.unit_id for u in orbat.units()}
    n_unit_subject = sum(1 for r in rows if r[3] in unit_ids)
    lines = ["# 파생 관계 보고", "",
             f"관계 {len(rows):,}건 · 미매칭 {len(unmatched):,}건",
             f"주어가 부대인 fact: {n_unit_subject:,}건", "",
             "## 술어별", ""]
    lines += [f"- `{k}`: {v:,}" for k, v in kinds.most_common()]
    lines += ["", "## 레이어별", ""]
    lines += [f"- `{k}`: {v:,}" for k, v in Counter(r[1] for r in rows).most_common()]

    # rule_id × predicate 분해. 술어별 집계만 보면 같은 사건이 두 규칙에서
    # 두 번 세어지는 것(R4의 firesUpon 21건과 R12가 소대 주어로 다시 쓴
    # 같은 21건)이 숨는다 — 42로만 보이면 사격 사건이 42건인 것처럼
    # 읽힌다(F5). rule_id별 내역을 나란히 두어 어느 건이 어느 규칙에서
    # 왔는지, 같은 사건이 다른 주어로 재기술됐을 뿐인지 보이게 한다.
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

    print(f"관계 {len(rows):,} · 미매칭 {len(unmatched):,} · "
          f"부대 주어 {n_unit_subject:,} → {OUT}")
    for k, v in kinds.most_common():
        print(f"  {k:24} {v:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
