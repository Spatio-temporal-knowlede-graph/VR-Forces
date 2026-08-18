"""후처리 산출물 평가. 7개 항목을 각각 PASS/FAIL로 판정한다.

정본은 **시나리오 원문**이다(`vtmak.paths.SCENARIO`). 원문을 파싱해 만든
객체 사전·지명 목록을 기준으로, 내보내기 CSV(후처리 전)와 annotated CSV
(후처리 후)가 그 기준을 얼마나 지키는지 본다. 중간 산출물(timetable 등)은
보지 않는다 — 그것도 검사 대상이지 기준이 아니다.

  E1  원문 객체명 == CSV 객체명            (양쪽 차집합을 둘 다 낸다)
  E2  원문 객체 수 == 생성된 객체 수
  E4  모든 객체가 UAV 하나 이상에 관측되었는가
  E5  GT CSV에 모든 객체의 상태 변화가 기록되었는가
  E6  후처리 전후 행 수가 맞는가
  E7  후처리 후 object 열이 정상으로 채워졌는가

E3(원문 지명이 layout·CSV에 모두 있는가)은 뺐다. 지명은 `move to`/
`FFE-on-Location`의 목적지를 스냅해야 CSV에 들어오므로, 초기 배치에만 쓰이고
아무도 그리로 이동·사격하지 않는 지명은 원리상 안 나온다 — 산출물의 결함이
아니라 시나리오의 성질이라 판정 대상이 못 된다.

GT annotated가 200 MB급이라 CSV는 전부 스트리밍으로 읽는다. 행을 리스트에
담지 않는다.

도장은 `20260804`처럼 날짜만 있기도 하고 `20260809_175237`처럼 시각까지
붙기도 한다. 같은 날 두 번 돌린 것을 구분하려고 내보내기가 시각을 붙였다.

  python scripts/06_evaluate_dataset.py
  python scripts/06_evaluate_dataset.py --stamp 20260809_175237
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 기본 콘솔은 cp949라 보고의 '—' 같은 문자에서 죽는다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.geometry import BattlefieldLayout                      # noqa: E402
from vtmak.parser import PatternMap, parse_scenario               # noqa: E402
from vtmak.paths import SCENARIO                                  # noqa: E402
from vtmak.registry import ClassMap, build_registry               # noqa: E402
from vtmak.stkg.filter import classify, Disposition               # noqa: E402
from vtmak.stkg.firing import is_munition                         # noqa: E402
from vtmak.stkg.locate import is_place                            # noqa: E402
from vtmak.stkg.rewrite import _is_coord                          # noqa: E402
from vtmak.stkg.schema import standardize                         # noqa: E402

CONFIG = ROOT / "config"
CSV_DIR = ROOT / "build" / "csv"
STKG_DIR = ROOT / "build" / "stkg"

GT_SOURCE = "ground_truth"

# 도장은 날짜만(20260804) 또는 날짜_시각(20260809_175237)이다.
_STAMP = r"\d{8}(?:_\d{6})?"

# 대상이 반드시 있어야 하는 술어. 비어 있으면 E7 위반이다.
PRED_NEEDS_OBJECT = {"move to", "Follow-Entity", "FFE-on-Location",
                     "Fire-Weapon", "find_cover", "find_firing_position"}
# 대상이 반드시 비어야 하는 술어.
PRED_NEEDS_EMPTY = {"none", "Wait-Duration"}
# 확정했을 때만 채운다. 비어도 위반이 아니다(rewrite.py 참조).
PRED_OPTIONAL = {"fired_by"}

# 지명·통제점 판정은 vtmak.stkg.locate가 한다 — 05가 집계에 쓰는 것과 같은
# 규칙이라야 한다.
_RE_LOC = re.compile(r"^LOC_")


def marking_of(object_id: str) -> str:
    """객체 ID → .oob marking-text. writer._oob와 같은 규칙이라야 한다."""
    return object_id.replace("-", "")[:11]


class Check:
    """판정 하나. 통과 여부와 사람이 읽을 근거를 함께 들고 있는다."""

    def __init__(self, key: str, title: str) -> None:
        self.key = key
        self.title = title
        self.ok = True
        self.lines: list[str] = []

    def note(self, text: str) -> "Check":
        self.lines.append(text)
        return self

    def require(self, cond: bool, text: str) -> "Check":
        self.ok = self.ok and cond
        self.lines.append(("  OK   " if cond else "  FAIL ") + text)
        return self

    @property
    def verdict(self) -> str:
        return "PASS" if self.ok else "FAIL"


def _sample(names, limit: int = 12) -> str:
    names = sorted(names)
    head = ", ".join(names[:limit])
    return head + (f" … 외 {len(names) - limit}개" if len(names) > limit else "")


# ---------------------------------------------------------------- 원문 기준

class Reference:
    """시나리오 원문에서 뽑은 기준. 모든 판정이 이것과 대조한다."""

    def __init__(self) -> None:
        layout = BattlefieldLayout.load(CONFIG / "battlefield_layout.json")
        pmap = PatternMap.load(CONFIG / "pattern_map.csv")
        cmap = ClassMap.load(CONFIG / "entity_class_map.csv")
        result = parse_scenario(SCENARIO.read_text(encoding="utf-8"), pmap)

        self.layout = layout
        self.sentences = result.sentence_count
        self.events = result.events
        self.registry = build_registry(result.events, cmap, layout.static_ids())

        # 정적 객체는 지명에 이름을 붙인 바인딩이라 .scnx에 안 들어간다
        # (README '정적 객체 7개는 산출물에 들어가지 않는다'). CSV에 없는 게
        # 정상이므로 기준 집합에서 뺀다.
        self.taskable = {o for o, d in self.registry.items() if d.taskable}
        self.static = set(self.registry) - self.taskable

        self.marking = {marking_of(o): o for o in self.taskable}

        # 원문에 실제로 등장한 지명. 이벤트의 위치 자리 세 곳을 다 본다.
        locs: set[str] = set()
        for e in self.events:
            for v in (e.location, e.src, e.dst):
                if v and _RE_LOC.match(v):
                    locs.add(v)
        self.locations = locs


# ---------------------------------------------------------------- CSV 훑기

class Scan:
    """CSV 한 쌍(후처리 전/후)을 한 번씩 흘려 읽어 모은 것."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.raw_rows = 0
        self.raw_dropped_by_rule = 0     # filter.classify가 KEEP이 아닌 행
        self.out_rows = 0
        self.subjects: set[str] = set()          # 발사체·통제점 제외 주체
        self.munitions: set[str] = set()
        self.controls: set[str] = set()          # 주체로 나온 통제점
        self.object_entities: set[str] = set()   # 대상으로만 나온 이름
        self.object_locations: set[str] = set()
        self.object_coords: set[str] = set()     # 지명에 못 붙은 좌표 폴백
        self.predicates: Counter = Counter()
        self.changed: set[str] = set()           # none이 아닌 술어를 가진 주체
        self.missing_object: Counter = Counter()  # 채워야 하는데 빈 행
        self.spurious_object: Counter = Counter()  # 비어야 하는데 찬 행
        self.fired_by_blank = 0

    def read_raw(self, path: Path) -> None:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            # 05와 **같은** 규칙으로 표준 이름을 맞춘다(vtmak.stkg.schema).
            # 여기서 따로 어림짐작하면 판이 바뀔 때 05와 06이 다른 열을 주체로
            # 읽는다 — 20260809판은 object 열이 전 행 '-'라 실제로 그랬다.
            for row in reader:
                self.raw_rows += 1
                row = standardize(row)
                if classify(row.get("subject") or "",
                            row.get("timestamp") or "") is not Disposition.KEEP:
                    self.raw_dropped_by_rule += 1

    def read_annotated(self, path: Path) -> None:
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                self.out_rows += 1
                subject = row["subject"]
                pred = row["predicate"]
                obj = row["object"]
                self.predicates[pred] += 1
                if is_munition(subject):
                    self.munitions.add(subject)
                elif is_place(subject):
                    # 05가 주체로 나온 통제점을 지명으로 바꿔 내보낸다.
                    # `P\d+`만 통제점으로 보면 그 지명 11개가 전투 객체로
                    # 둔갑해 '못 맞춘 객체'로 남는다.
                    self.controls.add(subject)
                else:
                    self.subjects.add(subject)
                    if pred not in PRED_NEEDS_EMPTY:
                        self.changed.add(subject)
                if obj:
                    if is_place(obj):
                        self.object_locations.add(obj)
                    elif _is_coord(obj):
                        # locate.snap이 지명에 못 붙인 좌표다. 객체가 아니라
                        # 자리이므로 객체명 대조에 넣으면 안 된다.
                        self.object_coords.add(obj)
                    elif not is_munition(obj):
                        self.object_entities.add(obj)
                if pred in PRED_NEEDS_OBJECT and not obj:
                    self.missing_object[pred] += 1
                elif pred in PRED_NEEDS_EMPTY and obj:
                    self.spurious_object[pred] += 1
                elif pred in PRED_OPTIONAL and not obj:
                    self.fired_by_blank += 1

    @property
    def dropped(self) -> int:
        return self.raw_rows - self.out_rows

    @property
    def entities(self) -> set[str]:
        """이 CSV에 이름이 나온 전투 객체(발사체·지명 제외)."""
        return self.subjects | self.object_entities


def _source_of(path: Path) -> str:
    """'UAV 2_20260809_175237_dataset.csv' → 'UAV 2'."""
    return re.sub(rf"_{_STAMP}_(dataset|annotated)$", "", path.stem)


def scan_all(stamp: str) -> dict[str, Scan]:
    raws = sorted(CSV_DIR.glob(f"*_{stamp}_dataset.csv"))
    if not raws:
        raise SystemExit(f"입력 CSV 없음: {CSV_DIR}/*_{stamp}_dataset.csv")
    scans: dict[str, Scan] = {}
    for raw in raws:
        ann = STKG_DIR / raw.name.replace("_dataset.csv", "_annotated.csv")
        if not ann.exists():
            raise SystemExit(f"후처리 산출 없음: {ann} — 05를 먼저 돌릴 것")
        s = Scan(_source_of(raw))
        s.read_raw(raw)
        s.read_annotated(ann)
        scans[s.source] = s
        print(f"  훑음 {s.source:14} 전 {s.raw_rows:9,}행 · 후 {s.out_rows:9,}행")
    return scans


# ---------------------------------------------------------------- 판정 7개

def e1_names(ref: Reference, scans: dict[str, Scan]) -> Check:
    c = Check("E1", "원문 객체명 == CSV 객체명")
    seen: set[str] = set()
    for s in scans.values():
        seen |= s.entities
    unknown = seen - set(ref.marking)
    unseen = set(ref.marking) - seen
    c.note(f"원문 객체 {len(ref.marking)} · CSV 객체 {len(seen)}")
    c.require(not unknown,
              f"CSV에만 있는 이름 {len(unknown)}개"
              + (f": {_sample(unknown)}" if unknown else ""))
    c.require(not unseen,
              f"원문에만 있는 이름 {len(unseen)}개"
              + (f": {_sample(unseen)}" if unseen else ""))
    muni: set[str] = set()
    for s in scans.values():
        muni |= s.munitions
    c.note(f"  참고 발사체 {len(muni)}종은 원문 객체가 아니다: {_sample(muni)}")
    c.note(f"  참고 정적 객체 {len(ref.static)}개는 .scnx에 안 들어간다: "
           f"{_sample(ref.static)}")
    ctrl: set[str] = set()
    for s in scans.values():
        ctrl |= s.controls
    if ctrl:
        c.note(f"  참고 통제점 {len(ctrl)}개는 객체가 아니라 자리다: "
               f"{_sample(ctrl)}")
    coords: set[str] = set()
    for s in scans.values():
        coords |= s.object_coords
    if coords:
        c.note(f"  참고 지명에 못 붙어 좌표로 남은 대상 {len(coords)}개 — "
               "객체명이 아니라 자리다")
    return c


def e2_count(ref: Reference, scans: dict[str, Scan]) -> Check:
    c = Check("E2", "원문 객체 수 == 생성된 객체 수")
    seen: set[str] = set()
    for s in scans.values():
        seen |= s.entities
    c.note(f"원문 사전 {len(ref.registry)} = task 가능 {len(ref.taskable)} "
           f"+ 정적 {len(ref.static)}")
    c.require(len(seen) == len(ref.marking),
              f"CSV 객체 {len(seen)} vs 원문 task 가능 {len(ref.marking)}")
    per = " · ".join(f"{k} {len(v.entities)}" for k, v in sorted(scans.items()))
    c.note(f"  파일별: {per}")
    return c


def e4_uav(ref: Reference, scans: dict[str, Scan]) -> Check:
    c = Check("E4", "모든 객체가 UAV 하나 이상에 관측되었는가")
    uavs = {k: v for k, v in scans.items() if k != GT_SOURCE}
    seen: set[str] = set()
    by_object: dict[str, list[str]] = defaultdict(list)
    for name, s in sorted(uavs.items()):
        seen |= s.subjects
        for o in s.subjects:
            by_object[o].append(name)
    unseen = set(ref.marking) - seen
    c.note(f"UAV {len(uavs)}대 · 관측된 객체 {len(seen)} / "
           f"{len(ref.marking)} ({len(seen) / max(len(ref.marking), 1):.1%})")
    c.require(not unseen,
              f"어느 UAV도 못 본 객체 {len(unseen)}개"
              + (f": {_sample(unseen)}" if unseen else ""))
    hist = Counter(len(v) for v in by_object.values())
    c.note("  관측 UAV 수별 객체: "
           + " · ".join(f"{n}대 {cnt}개" for n, cnt in sorted(hist.items())))
    return c


def e5_ground_truth(ref: Reference, scans: dict[str, Scan]) -> Check:
    c = Check("E5", "GT CSV에 모든 객체의 상태 변화가 기록되었는가")
    gt = scans.get(GT_SOURCE)
    if gt is None:
        c.require(False, f"GT CSV가 없다 (source '{GT_SOURCE}')")
        return c
    absent = set(ref.marking) - gt.subjects
    still = set(ref.marking) & gt.subjects - gt.changed
    c.note(f"GT 주체 {len(gt.subjects)} · 상태 변화 있는 객체 {len(gt.changed)}")
    c.require(not absent,
              f"GT에 아예 없는 객체 {len(absent)}개"
              + (f": {_sample(absent)}" if absent else ""))
    c.require(not still,
              f"GT에 있으나 술어가 전부 none인 객체 {len(still)}개"
              + (f": {_sample(still)}" if still else ""))
    c.note("  GT 술어별 행수: "
           + " · ".join(f"`{k}` {v:,}" for k, v in gt.predicates.most_common()))
    return c


def e6_rows(ref: Reference, scans: dict[str, Scan]) -> Check:
    c = Check("E6", "후처리 전후 행 수가 맞는가")
    for name, s in sorted(scans.items()):
        c.require(s.dropped == s.raw_dropped_by_rule,
                  f"{name:14} 전 {s.raw_rows:9,} = 후 {s.out_rows:9,} + 삭제 "
                  f"{s.dropped:7,} (규칙상 삭제 대상 {s.raw_dropped_by_rule:,})")
    kept = [n for n, s in scans.items() if s.dropped == 0]
    cut = {n: s.dropped for n, s in scans.items() if s.dropped}
    c.note(f"  행 수가 그대로인 파일 {len(kept)}개: {_sample(kept)}")
    if cut:
        c.note("  줄어든 파일: "
               + " · ".join(f"{n} -{d:,}" for n, d in sorted(cut.items()))
               + " — 시뮬레이터 인프라 객체(N Force/Observer/GlobalEnv)와 "
                 "일괄 스폰 효과(E숫자), 1970 타임스탬프 행이다")
    return c


def e7_object_column(ref: Reference, scans: dict[str, Scan]) -> Check:
    c = Check("E7", "후처리 후 object 열이 정상으로 채워졌는가")
    for name, s in sorted(scans.items()):
        bad = sum(s.missing_object.values()) + sum(s.spurious_object.values())
        filled = sum(v for k, v in s.predicates.items()
                     if k in PRED_NEEDS_OBJECT)
        c.require(bad == 0,
                  f"{name:14} 대상 필요 {filled:9,}행 · 빈 곳 "
                  f"{sum(s.missing_object.values()):,} · 비어야 하는데 찬 곳 "
                  f"{sum(s.spurious_object.values()):,}")
        if s.missing_object:
            c.note("    빈 곳 내역: "
                   + " · ".join(f"`{k}` {v:,}"
                                for k, v in s.missing_object.most_common()))
    blank = sum(s.fired_by_blank for s in scans.values())
    if blank:
        c.note(f"  참고 fired_by 중 사수를 확정 못 해 비운 행 {blank:,}개 — "
               "억지로 채우지 않는 설계라 위반이 아니다")
    unknown = Counter()
    for s in scans.values():
        for k, v in s.predicates.items():
            if k not in (PRED_NEEDS_OBJECT | PRED_NEEDS_EMPTY | PRED_OPTIONAL):
                unknown[k] += v
    if unknown:
        c.note("  참고 정규형이 없어 원문을 남긴 술어: "
               + " · ".join(f"`{k[:60]}` {v:,}"
                            for k, v in unknown.most_common(10)))
    return c


CHECKS = (e1_names, e2_count, e4_uav, e5_ground_truth, e6_rows,
          e7_object_column)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stamp", default="",
                    help="날짜 도장(예: 20260804). 안 주면 가장 최근 것")
    ap.add_argument("--out", default=str(STKG_DIR / "evaluation.md"))
    args = ap.parse_args()

    stamp = args.stamp
    if not stamp:
        stamps = sorted({m.group(1) for p in CSV_DIR.glob("*_dataset.csv")
                         if (m := re.search(rf"_({_STAMP})_dataset$", p.stem))})
        if not stamps:
            raise SystemExit(f"입력 CSV 없음: {CSV_DIR}")
        stamp = stamps[-1]

    print(f"원문 {SCENARIO.name} · 도장 {stamp}")
    ref = Reference()
    print(f"  문장 {ref.sentences:,} · 이벤트 {len(ref.events):,} · "
          f"객체 {len(ref.registry)} (task 가능 {len(ref.taskable)}) · "
          f"지명 {len(ref.locations)}")
    scans = scan_all(stamp)

    results = [fn(ref, scans) for fn in CHECKS]

    print()
    for c in results:
        print(f"[{c.verdict}] {c.key} {c.title}")
        for line in c.lines:
            print(line)
    failed = [c for c in results if not c.ok]
    print()
    print(f"통과 {len(results) - len(failed)}/{len(results)}"
          + (f" · 실패 {', '.join(c.key for c in failed)}" if failed else ""))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    md = [f"# 데이터셋 평가 ({stamp})", "",
          f"- 원문: `{SCENARIO.name}` — 문장 {ref.sentences:,} · "
          f"이벤트 {len(ref.events):,} · 객체 {len(ref.registry)}"
          f"(task 가능 {len(ref.taskable)} + 정적 {len(ref.static)}) · "
          f"지명 {len(ref.locations)}",
          f"- 입력: `build/csv/*_{stamp}_dataset.csv` "
          f"→ `build/stkg/*_{stamp}_annotated.csv`", "",
          "| 항목 | 판정 |", "|---|---|"]
    md += [f"| {c.key} {c.title} | **{c.verdict}** |" for c in results]
    md.append("")
    for c in results:
        md += [f"## {c.key} {c.title} — {c.verdict}", "", "```"]
        md += c.lines
        md += ["```", ""]
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"→ {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
