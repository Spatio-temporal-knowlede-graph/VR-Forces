# pre-made-input 교전 증량 (GT_ver2.0) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** STLogic 실험이 성립하도록 VR-Forces GT에 교전 관계를 증량한 6컬럼 CSV
`build/premade/GT_ver2.0.csv`를 결정론적으로 생성하고, 사전등록 합격검사 7항목으로 검증한다.

**Architecture:** 사람이 쓴 시나리오의 교전쌍 98개를 기반층으로 삼고, LLM이 쓴 국면별
교전 방침(`config/engagement_doctrine.json`)에 따라 코드가 표적을 재지정한다. 표적 선택은
**교리적 클래스 우선순위**로 하고 거리는 **가능/불가 판정에만** 쓴다 — 거리로 고르면
순환논증 검사에 걸린다. 실제 관측 궤적에서 물리 제약(대립 진영·무장·사거리·생존)을
강제하며, LLM은 좌표도 시각도 개체 쌍도 만들지 않는다.

**Tech Stack:** Python 3.10 (conda env `tlogic`), pytest, 표준 라이브러리 csv/json/dataclasses.
기존 `vtmak` 패키지 재사용.

**Spec:** `STLogic/STLogic/docs/superpowers/specs/2026-09-03-vrforces-stlogic-design.md`
(§2.1 관계 역할 분리, §2.2 증량 요건, §2.3 LLM 역할, §2.4 합격검사)

## Global Constraints

- 브랜치: `spatial-relations`에서 분기한다. `vtmak/spatial/profile.py`가 필요하며 main에는 없다.
- 출력 6컬럼 열 순서: `subject,predicate,object,latitude,longitude,timestamp` (좌표가 시각 앞).
  기존 `STKG/data/expansion_of_spatio-temporal_information/pre-made-input/GT_ver1.0.csv`와 동일.
- 출력 위치: `build/premade/` (STKG 모듈 입력과 분리된 실험 디렉터리).
- 인코딩: 모든 CSV 읽기/쓰기 `encoding="utf-8"`, BOM 있는 config는 `utf-8-sig`.
  줄바꿈은 `newline=""`로 csv 모듈에 맡긴다.
- 결정론: 같은 입력·같은 방침 파일이면 바이트 동일한 출력이 나와야 한다. 난수 금지.
  순서가 필요한 곳은 항상 명시적으로 `sorted()` 한다.
- LLM은 `config/engagement_doctrine.json`만 쓴다. 좌표·시각·개체 쌍을 생성하지 않는다.
- 표적 선택 기준은 **클래스 우선순위**다. 거리는 사거리 내/외 판정에만 쓴다.
- 콘솔 출력이 있는 스크립트는 기존 `scripts/08_spatial_relations.py`처럼
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`를 한다 (Windows cp949 대비).
- 새 모듈은 전부 `from __future__ import annotations`로 시작한다 (기존 관례).

## 합격검사 기준 (spec §2.4 — Task 7이 구현, Task 9가 통과시킨다)

| 검사 | 기준 |
|---|---|
| 고유 (사수, 표적) 쌍 | ≥ 300 |
| 고유 사수 수 | ≥ 60 |
| 사수당 평균 표적 수 | ≥ 3 |
| 타겟 엣지 총량 | ≥ 10,000 |
| 타겟 엣지 ts 범위 | ≥ 60% |
| train 구간(앞 80%) 타겟 엣지 | ≥ 6,000 |
| valid·test 구간 타겟 엣지 | 각 ≥ 700 |
| 최근접 적 베이스라인 MRR | < 0.20 |
| recency 베이스라인 MRR | < 0.30 |

---

## File Structure

**신규 패키지 `vtmak/premade/`** — 각 모듈이 하나의 책임만 진다.

| 파일 | 책임 |
|---|---|
| `vtmak/premade/__init__.py` | 빈 패키지 표식 |
| `vtmak/premade/phases.py` | 서사 5국면 정의와 `time_s → 국면` 조회 |
| `vtmak/premade/entities.py` | 관측 CSV → 진영·프로필·궤적 인덱스 |
| `vtmak/premade/base.py` | 시나리오 이벤트 → 기반 교전쌍 (GT 이름으로) |
| `vtmak/premade/doctrine.py` | 방침 파일 스키마·적재·검증 |
| `vtmak/premade/assign.py` | 표적 재지정 (교리 우선순위 + 물리 제약) |
| `vtmak/premade/emit.py` | 교전 → 시각별 엣지 → 6컬럼 CSV |
| `vtmak/premade/acceptance.py` | 합격검사 9항목과 리포트 |
| `vtmak/premade/pipeline.py` | 오케스트레이션 |
| `scripts/09_build_premade.py` | CLI 진입점 |
| `config/engagement_doctrine.json` | LLM 작성 방침 (Task 9) |

**테스트**: `tests/test_premade_<module>.py` — 기존 `tests/test_spatial_*.py` 관례를 따른다.

**출력**: `build/premade/GT_ver2.0.csv`, `build/premade/manifest.json`, `build/premade/acceptance.md`

---

## Task 1: 서사 국면 정의

**Files:**
- Create: `vtmak/premade/__init__.py`
- Create: `vtmak/premade/phases.py`
- Test: `tests/test_premade_phases.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `Phase(name: str, start_s: int, end_s: int)` 데이터클래스,
  `PHASES: tuple[Phase, ...]`, `phase_of(time_s: int) -> str | None`,
  `SCENARIO_END_S: int = 416`

**배경:** `build/events/battle.jsonl`의 술어별 `time_s` 범위를 실측한 결과
`approach` 60~74, `aimAt` 100~120, `indirectFireAt` 120~140, `directFireAt` 200~293,
전체 0~416이다. 이 전환점으로 5국면을 정의한다. 경계는 반열림 구간 `[start_s, end_s)`이고
마지막 국면만 `end_s`를 포함한다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_phases.py
from __future__ import annotations

from vtmak.premade.phases import PHASES, SCENARIO_END_S, Phase, phase_of


def test_phases_tile_the_whole_scenario_without_gaps():
    """국면은 0부터 시나리오 끝까지 빈틈도 겹침도 없이 덮는다."""
    assert PHASES[0].start_s == 0
    assert PHASES[-1].end_s == SCENARIO_END_S
    for earlier, later in zip(PHASES, PHASES[1:]):
        assert earlier.end_s == later.start_s


def test_phase_of_maps_scenario_landmarks_to_their_phase():
    """실측한 술어 시각이 의도한 국면에 떨어진다."""
    assert phase_of(65) == "접근"       # approach 60~74
    assert phase_of(110) == "조준"      # aimAt 100~120
    assert phase_of(130) == "간접사격"  # indirectFireAt 120~140
    assert phase_of(250) == "직접사격"  # directFireAt 200~293
    assert phase_of(400) == "철수"      # retreatTo 이후


def test_phase_of_includes_both_ends_of_the_scenario():
    assert phase_of(0) == PHASES[0].name
    assert phase_of(SCENARIO_END_S) == PHASES[-1].name


def test_phase_of_returns_none_outside_the_scenario():
    assert phase_of(-1) is None
    assert phase_of(SCENARIO_END_S + 1) is None


def test_every_phase_has_positive_length():
    for p in PHASES:
        assert p.end_s > p.start_s, f"{p.name}의 길이가 0 이하다"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_phases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/__init__.py
```

(빈 파일)

```python
# vtmak/premade/phases.py
"""전투 서사의 5국면.

경계는 build/events/battle.jsonl의 술어별 time_s 실측에서 왔다 —
approach 60~74, aimAt 100~120, indirectFireAt 120~140, directFireAt 200~293.
균등 분할이 아니라 서사 전환점을 쓰는 이유는, 표적 재지정이 전투의 실제
국면 전환과 맞물려야 합성 교전이 부자연스러워지지 않기 때문이다.
"""
from __future__ import annotations

from dataclasses import dataclass

SCENARIO_END_S = 416


@dataclass(frozen=True)
class Phase:
    name: str
    start_s: int
    end_s: int


PHASES: tuple[Phase, ...] = (
    Phase("접근", 0, 100),
    Phase("조준", 100, 120),
    Phase("간접사격", 120, 200),
    Phase("직접사격", 200, 294),
    Phase("철수", 294, SCENARIO_END_S),
)


def phase_of(time_s: int) -> str | None:
    """시각이 속한 국면 이름. 시나리오 밖이면 None."""
    if time_s < 0 or time_s > SCENARIO_END_S:
        return None
    for p in PHASES:
        if p.start_s <= time_s < p.end_s:
            return p.name
    return PHASES[-1].name  # 마지막 국면만 end_s를 포함한다
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_premade_phases.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/__init__.py vtmak/premade/phases.py tests/test_premade_phases.py
git commit -m "feat(premade): 전투 서사 5국면을 실측 전환점으로 정의한다"
```

---

## Task 2: 엔티티 인덱스 (진영·프로필·궤적)

**Files:**
- Create: `vtmak/premade/entities.py`
- Test: `tests/test_premade_entities.py`

**Interfaces:**
- Consumes: `vtmak.geometry.Coord`, `vtmak.geometry.ground_distance`,
  `vtmak.spatial.profile.ProfileIndex` (`.load(config_dir)`, `.of(entity_type) -> EntityProfile | None`),
  `EntityProfile.direct: RangeSpec | None`, `RangeSpec.min_m`, `RangeSpec.max_m`
- Produces:
  - `EntityIndex.load(csv_path: Path, config_dir: Path) -> EntityIndex`
  - `.timestamps() -> list[str]` (정렬된 고유 ISO 시각)
  - `.force_of(name: str) -> str | None`
  - `.profile_of(name: str) -> EntityProfile | None`
  - `.pos(name: str, ts: str) -> Coord | None`
  - `.is_alive(name: str, ts: str) -> bool`
  - `.armed_subjects() -> list[str]` (직접사격 사거리를 가진 주체, 정렬)
  - `.in_direct_range(shooter: str, target: str, ts: str) -> bool`

**배경:** 입력은 17컬럼 `build/stkg/ground_truth_ver1.0.csv`다. 산출물은 6컬럼이지만
생성기는 `entity_type`(DIS)·`force`·`damage`를 쓸 수 있다. `force`는 `1`=아군, `2`=적군,
`3`=중립이다. 중립은 교전 대상이 아니다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_entities.py
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from vtmak.paths import CONFIG
from vtmak.premade.entities import EntityIndex

# GT에 실재하는 DIS 코드다 — dis_catalog에 매핑된 것으로 골랐다.
_M4 = "3:1:225:1:41:1:0"        # US Army M4, direct 0~500m
_T72 = "1:1:222:1:2:1:0"        # T-72 MBT, direct 0~2500m
_TRUCK = "1:1:225:7:12:8:0"     # 수송 트럭 — 무장 없음

_HEADER = ["subject", "predicate", "object", "timestamp", "latitude", "longitude",
           "source", "force", "tracking_id", "uuid", "entity_type", "damage",
           "smoke", "flaming", "mobility_kill", "firepower_kill", "suppression_level"]


def _row(subject, ts, lat, lon, force, etype, damage="0"):
    return {**{k: "" for k in _HEADER}, "subject": subject, "predicate": "none",
            "object": "", "timestamp": ts, "latitude": f"{lat}", "longitude": f"{lon}",
            "force": force, "entity_type": etype, "damage": damage}


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    p = tmp_path / "gt.csv"
    rows = [
        # 아군 소총수: 두 시각에 걸쳐 이동
        _row("FRINF001", "2026-08-09T08:53:22.000Z", 21.3860, -157.7390, "1", _M4),
        _row("FRINF001", "2026-08-09T08:53:23.000Z", 21.3861, -157.7390, "1", _M4),
        # 적 전차: 약 220m 북쪽
        _row("ENT72001", "2026-08-09T08:53:22.000Z", 21.3880, -157.7390, "2", _T72),
        _row("ENT72001", "2026-08-09T08:53:23.000Z", 21.3880, -157.7390, "2", _T72),
        # 적 전차 2: 약 5.5km 밖 (M4 사거리 500m 밖)
        _row("ENT72002", "2026-08-09T08:53:22.000Z", 21.4360, -157.7390, "2", _T72),
        # 파괴된 적
        _row("ENT72003", "2026-08-09T08:53:22.000Z", 21.3881, -157.7390, "2", _T72,
             damage="3"),
        # 비무장 수송차
        _row("FRTRK001", "2026-08-09T08:53:22.000Z", 21.3860, -157.7391, "1", _TRUCK),
    ]
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_HEADER)
        w.writeheader()
        w.writerows(rows)
    return p


def test_timestamps_are_sorted_and_deduplicated(csv_path):
    idx = EntityIndex.load(csv_path, CONFIG)
    assert idx.timestamps() == ["2026-08-09T08:53:22.000Z", "2026-08-09T08:53:23.000Z"]


def test_force_and_profile_are_resolved_from_the_observation_row(csv_path):
    idx = EntityIndex.load(csv_path, CONFIG)
    assert idx.force_of("FRINF001") == "1"
    assert idx.force_of("ENT72001") == "2"
    assert idx.profile_of("FRINF001").entity_class == "US Army M4"
    assert idx.profile_of("ENT72001").entity_class == "T-72 MBT"


def test_position_is_the_observation_at_that_timestamp(csv_path):
    idx = EntityIndex.load(csv_path, CONFIG)
    c = idx.pos("FRINF001", "2026-08-09T08:53:23.000Z")
    assert c.lat == pytest.approx(21.3861)
    assert idx.pos("FRINF001", "2026-08-09T09:00:00.000Z") is None


def test_armed_subjects_excludes_unarmed_classes(csv_path):
    idx = EntityIndex.load(csv_path, CONFIG)
    armed = idx.armed_subjects()
    assert "FRINF001" in armed
    assert "ENT72001" in armed
    assert "FRTRK001" not in armed, "비무장 수송차가 사수로 잡히면 안 된다"
    assert armed == sorted(armed), "결정론을 위해 정렬돼 있어야 한다"


def test_direct_range_check_uses_the_shooter_weapon_envelope(csv_path):
    idx = EntityIndex.load(csv_path, CONFIG)
    ts = "2026-08-09T08:53:22.000Z"
    # M4는 0~500m. 220m 표적은 안, 5.5km 표적은 밖.
    assert idx.in_direct_range("FRINF001", "ENT72001", ts) is True
    assert idx.in_direct_range("FRINF001", "ENT72002", ts) is False


def test_damaged_entities_are_not_alive(csv_path):
    idx = EntityIndex.load(csv_path, CONFIG)
    ts = "2026-08-09T08:53:22.000Z"
    assert idx.is_alive("ENT72001", ts) is True
    assert idx.is_alive("ENT72003", ts) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_entities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade.entities'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/entities.py
"""관측 CSV 하나에서 진영·무장 프로필·궤적을 뽑아 인덱스로 만든다.

산출물은 6컬럼이지만 생성기는 17컬럼 관측 CSV를 읽으므로 entity_type(DIS)·force·
damage를 쓸 수 있다. 이 세 열이 물리 제약 판정의 근거다.
"""
from __future__ import annotations

import csv
from pathlib import Path

from vtmak.geometry import Coord, ground_distance
from vtmak.spatial.profile import EntityProfile, ProfileIndex

# force 열의 교전 가능한 값. 3(중립)은 교전 대상이 아니다.
BELLIGERENT_FORCES = frozenset({"1", "2"})


class EntityIndex:
    """이름 → (진영, 프로필)과 (이름, 시각) → 좌표."""

    def __init__(self, force: dict[str, str], etype: dict[str, str],
                 traj: dict[tuple[str, str], Coord],
                 damaged: set[tuple[str, str]],
                 timestamps: list[str], profiles: ProfileIndex) -> None:
        self._force = force
        self._etype = etype
        self._traj = traj
        self._damaged = damaged
        self._timestamps = timestamps
        self._profiles = profiles

    @classmethod
    def load(cls, csv_path: Path, config_dir: Path) -> "EntityIndex":
        profiles = ProfileIndex.load(Path(config_dir))
        force: dict[str, str] = {}
        etype: dict[str, str] = {}
        traj: dict[tuple[str, str], Coord] = {}
        damaged: set[tuple[str, str]] = set()
        ts_set: set[str] = set()
        with Path(csv_path).open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                name = row["subject"]
                ts = row["timestamp"]
                ts_set.add(ts)
                # 같은 (이름, 시각)이 여러 번 와도 첫 관측을 쓴다 — 결정론.
                if row.get("force"):
                    force.setdefault(name, row["force"])
                if row.get("entity_type"):
                    etype.setdefault(name, row["entity_type"])
                key = (name, ts)
                if key not in traj:
                    try:
                        traj[key] = Coord(float(row["latitude"]),
                                          float(row["longitude"]), 0.0)
                    except (TypeError, ValueError):
                        pass
                if (row.get("damage") or "0").strip() not in ("", "0"):
                    damaged.add(key)
        return cls(force, etype, traj, damaged, sorted(ts_set), profiles)

    def timestamps(self) -> list[str]:
        return list(self._timestamps)

    def force_of(self, name: str) -> str | None:
        return self._force.get(name)

    def profile_of(self, name: str) -> EntityProfile | None:
        et = self._etype.get(name)
        return self._profiles.of(et) if et else None

    def pos(self, name: str, ts: str) -> Coord | None:
        return self._traj.get((name, ts))

    def is_alive(self, name: str, ts: str) -> bool:
        return (name, ts) not in self._damaged

    def armed_subjects(self) -> list[str]:
        """직접사격 사거리를 가진 주체. 간접사격만 되는 포병은 제외한다."""
        out = []
        for name in self._etype:
            p = self.profile_of(name)
            if p is not None and p.direct is not None:
                out.append(name)
        return sorted(out)

    def in_direct_range(self, shooter: str, target: str, ts: str) -> bool:
        p = self.profile_of(shooter)
        if p is None or p.direct is None:
            return False
        a, b = self.pos(shooter, ts), self.pos(target, ts)
        if a is None or b is None:
            return False
        d = ground_distance(a, b)
        return p.direct.min_m <= d <= p.direct.max_m
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_premade_entities.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/entities.py tests/test_premade_entities.py
git commit -m "feat(premade): 관측 CSV에서 진영·무장 프로필·궤적 인덱스를 만든다"
```

---

## Task 3: 기반 교전쌍 추출

**Files:**
- Create: `vtmak/premade/base.py`
- Test: `tests/test_premade_base.py`

**Interfaces:**
- Consumes: `vtmak.premade.phases.phase_of`
- Produces:
  - `BasePair(shooter: str, target: str, time_s: int, phase: str, event_ids: tuple[str, ...])`
  - `load_marking_map(objects_csv: Path) -> dict[str, str]` (`object_id` → `marking`)
  - `base_pairs(events_path: Path, objects_csv: Path) -> list[BasePair]`

**배경:** `build/events/battle.jsonl`은 `directFireAt` 77건 + `engagementPair` 118건을 갖고
있고 합집합은 고유 쌍 98개다. 이벤트의 이름은 `FR-INF-036` 꼴인데 GT 주체는 `FRINF027`
꼴이므로 `build/timetable/battle_scnx_objects.csv`의 `object_id ↔ marking`으로 옮긴다.
매핑이 없는 쌍은 조용히 버리지 않고 세어서 호출자가 알 수 있게 한다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_base.py
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from vtmak.premade.base import base_pairs, load_marking_map

_OBJ_HEADER = ["object_id", "name", "faction", "entity_class", "type_group",
               "marking", "initial_state", "n_tasks", "n_dropped",
               "t_first", "t_last", "kinds", "sequence"]


@pytest.fixture
def objects_csv(tmp_path: Path) -> Path:
    p = tmp_path / "objects.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_OBJ_HEADER)
        w.writeheader()
        for oid, marking in (("FR-INF-036", "FRINF036"),
                             ("EN-T72-001", "ENT72001"),
                             ("EN-T72-002", "ENT72002")):
            w.writerow({**{k: "" for k in _OBJ_HEADER},
                        "object_id": oid, "marking": marking})
    return p


@pytest.fixture
def events_path(tmp_path: Path) -> Path:
    p = tmp_path / "battle.jsonl"
    events = [
        {"event_id": "E1", "predicate": "directFireAt", "actor": "FR-INF-036",
         "target": "EN-T72-001", "time_s": 250},
        # 같은 쌍이 engagementPair로도 온다 — 합쳐지고 event_id는 둘 다 남아야 한다
        {"event_id": "E2", "predicate": "engagementPair", "actor": "FR-INF-036",
         "target": "EN-T72-001", "time_s": 240},
        {"event_id": "E3", "predicate": "engagementPair", "actor": "FR-INF-036",
         "target": "EN-T72-002", "time_s": 260},
        # 교전이 아닌 술어는 무시
        {"event_id": "E4", "predicate": "moveTo", "actor": "FR-INF-036",
         "target": "EN-T72-002", "time_s": 100},
        # marking이 없는 객체는 버려진다
        {"event_id": "E5", "predicate": "directFireAt", "actor": "FR-XX-999",
         "target": "EN-T72-001", "time_s": 250},
    ]
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events),
                 encoding="utf-8")
    return p


def test_marking_map_reads_object_id_to_marking(objects_csv):
    m = load_marking_map(objects_csv)
    assert m["FR-INF-036"] == "FRINF036"
    assert m["EN-T72-001"] == "ENT72001"


def test_base_pairs_uses_gt_names_not_event_ids(events_path, objects_csv):
    pairs = base_pairs(events_path, objects_csv)
    assert {(p.shooter, p.target) for p in pairs} == {
        ("FRINF036", "ENT72001"), ("FRINF036", "ENT72002")}


def test_duplicate_pairs_merge_and_keep_the_earliest_time(events_path, objects_csv):
    pairs = {(p.shooter, p.target): p for p in base_pairs(events_path, objects_csv)}
    merged = pairs[("FRINF036", "ENT72001")]
    assert merged.time_s == 240, "가장 이른 시각을 교전 시작으로 본다"
    assert set(merged.event_ids) == {"E1", "E2"}


def test_non_engagement_predicates_are_ignored(events_path, objects_csv):
    pairs = base_pairs(events_path, objects_csv)
    assert all(p.time_s != 100 for p in pairs), "moveTo가 교전으로 잡히면 안 된다"


def test_pairs_without_a_marking_are_dropped(events_path, objects_csv):
    pairs = base_pairs(events_path, objects_csv)
    assert all(not p.shooter.startswith("FR-XX") for p in pairs)


def test_result_is_sorted_for_determinism(events_path, objects_csv):
    pairs = base_pairs(events_path, objects_csv)
    keys = [(p.shooter, p.target) for p in pairs]
    assert keys == sorted(keys)


def test_phase_is_attached_from_the_engagement_time(events_path, objects_csv):
    pairs = {(p.shooter, p.target): p for p in base_pairs(events_path, objects_csv)}
    assert pairs[("FRINF036", "ENT72001")].phase == "직접사격"  # 240s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/base.py
"""시나리오 이벤트에서 기반 교전쌍을 뽑는다.

교전 구조를 지어내지 않는 것이 이 모듈의 존재 이유다 — 사람이 쓴 원문에 이미
directFireAt 77건과 engagementPair 118건(합집합 고유 98쌍)이 있다. 증량은 이
98쌍에 표적을 더하는 것이지 쌍을 발명하는 것이 아니다.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from vtmak.premade.phases import phase_of

# 교전으로 볼 술어. aimAt은 조준일 뿐 사격이 아니라 뺀다.
ENGAGEMENT_PREDICATES = frozenset({"directFireAt", "engagementPair"})


@dataclass(frozen=True)
class BasePair:
    shooter: str
    target: str
    time_s: int
    phase: str
    event_ids: tuple[str, ...]


def load_marking_map(objects_csv: Path) -> dict[str, str]:
    """object_id → marking. marking이 GT CSV의 subject 이름이다."""
    out: dict[str, str] = {}
    with Path(objects_csv).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            oid, marking = row.get("object_id"), row.get("marking")
            if oid and marking:
                out[oid] = marking
    return out


def base_pairs(events_path: Path, objects_csv: Path) -> list[BasePair]:
    """기반 교전쌍. 같은 쌍은 합치고 가장 이른 시각을 교전 시작으로 삼는다."""
    marking = load_marking_map(objects_csv)
    acc: dict[tuple[str, str], dict] = {}
    with Path(events_path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("predicate") not in ENGAGEMENT_PREDICATES:
                continue
            a, t = marking.get(e.get("actor")), marking.get(e.get("target"))
            if not a or not t:
                continue
            time_s = e.get("time_s")
            if time_s is None:
                continue
            slot = acc.setdefault((a, t), {"time_s": time_s, "ids": set()})
            slot["time_s"] = min(slot["time_s"], time_s)
            slot["ids"].add(e.get("event_id"))
    out = []
    for (a, t), slot in sorted(acc.items()):
        out.append(BasePair(shooter=a, target=t, time_s=slot["time_s"],
                            phase=phase_of(slot["time_s"]) or "",
                            event_ids=tuple(sorted(i for i in slot["ids"] if i))))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_premade_base.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/base.py tests/test_premade_base.py
git commit -m "feat(premade): 시나리오 이벤트에서 기반 교전쌍 98개를 뽑는다"
```

---

## Task 4: 교전 방침 스키마

**Files:**
- Create: `vtmak/premade/doctrine.py`
- Test: `tests/test_premade_doctrine.py`

**Interfaces:**
- Consumes: `vtmak.premade.phases.PHASES`
- Produces:
  - `PhaseRule(phase: str, target_priority: tuple[str, ...], dwell_s: int, engage: bool)`
  - `Doctrine.load(path: Path) -> Doctrine`
  - `Doctrine.rule_for(phase: str) -> PhaseRule | None`
  - `Doctrine.min_targets_per_shooter: int`
  - `DOCTRINE_SCHEMA_ERROR: str` (오류 메시지 접두사)

**배경:** LLM이 쓰는 유일한 파일의 스키마다. **`target_priority`는 type_group 이름의
목록이며 거리 개념이 들어가지 않는다** — 거리로 고르면 순환논증 검사에 걸린다.
알 수 없는 키는 조용히 넘기지 않고 거부한다(설정 오타가 조용히 무시되면 방침이
안 먹은 것을 나중에 발견하게 된다).

방침 파일 형식:

```json
{
  "version": "1.0",
  "min_targets_per_shooter": 3,
  "phases": {
    "접근": {"engage": true, "dwell_s": 40,
             "target_priority": ["차량/장갑차 - M2HB 계열", "포병 - 155mm 자주포"]},
    "조준": {"engage": false, "dwell_s": 0, "target_priority": []}
  }
}
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_doctrine.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vtmak.premade.doctrine import DOCTRINE_SCHEMA_ERROR, Doctrine
from vtmak.premade.phases import PHASES


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "doctrine.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _valid(**over) -> dict:
    base = {
        "version": "1.0",
        "min_targets_per_shooter": 3,
        "phases": {ph.name: {"engage": True, "dwell_s": 40,
                             "target_priority": ["차량/장갑차 - M2HB 계열"]}
                   for ph in PHASES},
    }
    base.update(over)
    return base


def test_loads_a_valid_doctrine(tmp_path):
    d = Doctrine.load(_write(tmp_path, _valid()))
    assert d.min_targets_per_shooter == 3
    rule = d.rule_for("직접사격")
    assert rule.engage is True
    assert rule.dwell_s == 40
    assert rule.target_priority == ("차량/장갑차 - M2HB 계열",)


def test_unknown_top_level_key_is_rejected(tmp_path):
    p = _write(tmp_path, _valid(nearest_first=True))
    with pytest.raises(ValueError, match=DOCTRINE_SCHEMA_ERROR):
        Doctrine.load(p)


def test_unknown_phase_name_is_rejected(tmp_path):
    payload = _valid()
    payload["phases"]["돌격"] = {"engage": True, "dwell_s": 10,
                                 "target_priority": []}
    with pytest.raises(ValueError, match=DOCTRINE_SCHEMA_ERROR):
        Doctrine.load(_write(tmp_path, payload))


def test_every_phase_must_be_present(tmp_path):
    payload = _valid()
    del payload["phases"]["철수"]
    with pytest.raises(ValueError, match=DOCTRINE_SCHEMA_ERROR):
        Doctrine.load(_write(tmp_path, payload))


def test_negative_dwell_is_rejected(tmp_path):
    payload = _valid()
    payload["phases"]["접근"]["dwell_s"] = -1
    with pytest.raises(ValueError, match=DOCTRINE_SCHEMA_ERROR):
        Doctrine.load(_write(tmp_path, payload))


def test_engaging_phase_needs_a_nonempty_priority(tmp_path):
    payload = _valid()
    payload["phases"]["접근"]["target_priority"] = []
    with pytest.raises(ValueError, match=DOCTRINE_SCHEMA_ERROR):
        Doctrine.load(_write(tmp_path, payload))


def test_rule_for_unknown_phase_is_none(tmp_path):
    d = Doctrine.load(_write(tmp_path, _valid()))
    assert d.rule_for("없는국면") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_doctrine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade.doctrine'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/doctrine.py
"""교전 방침 — LLM이 쓰는 유일한 파일의 스키마.

target_priority는 type_group 이름의 우선순위 목록이다. 거리 개념이 들어가지
않는 것이 핵심이다 — 표적을 거리로 고르면 최근접 베이스라인과 상관이 높아져
spec §2.4의 순환논증 검사에 걸린다. 방침은 "무엇을 먼저 치는가"(교리)를 정하고,
거리는 assign.py가 "칠 수 있는가"(물리)를 판정할 때만 쓴다.

알 수 없는 키를 거부하는 이유: 오타가 조용히 무시되면 방침이 안 먹은 것을
합격검사 실패로만 알게 되고, 원인을 찾는 데 시간이 든다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from vtmak.premade.phases import PHASES

DOCTRINE_SCHEMA_ERROR = "DOCTRINE_SCHEMA_ERROR"

_TOP_KEYS = frozenset({"version", "min_targets_per_shooter", "phases"})
_PHASE_KEYS = frozenset({"engage", "dwell_s", "target_priority"})


@dataclass(frozen=True)
class PhaseRule:
    phase: str
    target_priority: tuple[str, ...]
    dwell_s: int
    engage: bool


class Doctrine:
    def __init__(self, version: str, min_targets_per_shooter: int,
                 rules: dict[str, PhaseRule]) -> None:
        self.version = version
        self.min_targets_per_shooter = min_targets_per_shooter
        self._rules = rules

    @classmethod
    def load(cls, path: Path) -> "Doctrine":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        unknown = set(payload) - _TOP_KEYS
        if unknown:
            raise ValueError(f"{DOCTRINE_SCHEMA_ERROR}: 모르는 키 {sorted(unknown)}")
        missing = _TOP_KEYS - set(payload)
        if missing:
            raise ValueError(f"{DOCTRINE_SCHEMA_ERROR}: 빠진 키 {sorted(missing)}")

        mtps = payload["min_targets_per_shooter"]
        if not isinstance(mtps, int) or mtps < 1:
            raise ValueError(
                f"{DOCTRINE_SCHEMA_ERROR}: min_targets_per_shooter는 1 이상 정수여야 한다")

        phases = payload["phases"]
        expected = {p.name for p in PHASES}
        if set(phases) != expected:
            raise ValueError(
                f"{DOCTRINE_SCHEMA_ERROR}: 국면 집합이 다르다 — "
                f"넘침 {sorted(set(phases) - expected)}, 빠짐 {sorted(expected - set(phases))}")

        rules: dict[str, PhaseRule] = {}
        for name, spec in phases.items():
            bad = set(spec) - _PHASE_KEYS
            if bad:
                raise ValueError(
                    f"{DOCTRINE_SCHEMA_ERROR}: 국면 {name!r}에 모르는 키 {sorted(bad)}")
            gone = _PHASE_KEYS - set(spec)
            if gone:
                raise ValueError(
                    f"{DOCTRINE_SCHEMA_ERROR}: 국면 {name!r}에 빠진 키 {sorted(gone)}")
            dwell = spec["dwell_s"]
            if not isinstance(dwell, int) or dwell < 0:
                raise ValueError(
                    f"{DOCTRINE_SCHEMA_ERROR}: 국면 {name!r}의 dwell_s는 0 이상 정수여야 한다")
            priority = tuple(spec["target_priority"])
            if spec["engage"] and not priority:
                raise ValueError(
                    f"{DOCTRINE_SCHEMA_ERROR}: 교전하는 국면 {name!r}에 "
                    f"target_priority가 비어 있다")
            rules[name] = PhaseRule(phase=name, target_priority=priority,
                                    dwell_s=dwell, engage=bool(spec["engage"]))
        return cls(str(payload["version"]), mtps, rules)

    def rule_for(self, phase: str) -> PhaseRule | None:
        return self._rules.get(phase)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_premade_doctrine.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/doctrine.py tests/test_premade_doctrine.py
git commit -m "feat(premade): 교전 방침 스키마 — 거리가 아니라 교리로 표적을 정한다"
```

---

## Task 5: 표적 재지정

**Files:**
- Create: `vtmak/premade/assign.py`
- Test: `tests/test_premade_assign.py`

**Interfaces:**
- Consumes: `EntityIndex` (Task 2), `BasePair` (Task 3), `Doctrine`/`PhaseRule` (Task 4),
  `PHASES`, `phase_of` (Task 1)
- Produces:
  - `Engagement(shooter: str, target: str, phase: str, start_ts: str, end_ts: str, origin: str)`
    — `origin`은 `"scenario"` 또는 `"doctrine"`
  - `assign(index, pairs, doctrine, sim_start_ts, seconds_per_ts) -> list[Engagement]`
  - `feasible_targets(index, shooter, ts) -> list[str]`

**핵심 알고리즘.** 각 기반 사수마다:

1. 시나리오 쌍을 `origin="scenario"` 교전으로 그대로 둔다.
2. 사수가 `min_targets_per_shooter`에 못 미치면, `engage=True`인 국면을 국면 순서대로 돌며
   표적을 하나씩 더한다.
3. 각 국면에서 **가용 표적**(`feasible_targets`)을 구한다 — 대립 진영 · 생존 · 사거리 내 ·
   좌표 존재 · 이미 이 사수에게 배정되지 않음.
4. 가용 표적을 **방침의 `target_priority` 순서**로 정렬한다. 같은 우선순위 안에서는
   **이름 오름차순**으로 깬다. **거리로 정렬하지 않는다.**
5. 우선순위 목록에 없는 type_group은 목록 끝에 붙인다(우선순위 미지정 = 최하위).
6. 고른 표적으로 `dwell_s` 길이의 교전을 만든다. 한 사수의 교전 구간은 겹치지 않는다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_assign.py
from __future__ import annotations

from dataclasses import dataclass

import pytest

from vtmak.premade.assign import Engagement, assign, feasible_targets
from vtmak.premade.base import BasePair
from vtmak.premade.doctrine import Doctrine, PhaseRule


@dataclass(frozen=True)
class _Range:
    min_m: float
    max_m: float


@dataclass(frozen=True)
class _Profile:
    entity_class: str
    type_group: str
    direct: object


class _FakeIndex:
    """EntityIndex 대역. 사거리·생존·진영을 표로 준다."""

    def __init__(self, force, group, in_range, alive=(), ts=None):
        self._force = force
        self._group = group
        self._in_range = set(in_range)
        self._dead = set(alive)
        self._ts = ts or [f"T{i:04d}" for i in range(400)]

    def timestamps(self):
        return list(self._ts)

    def force_of(self, name):
        return self._force.get(name)

    def profile_of(self, name):
        g = self._group.get(name)
        return None if g is None else _Profile(name, g, _Range(0, 3000))

    def pos(self, name, ts):
        return object() if name in self._force else None

    def is_alive(self, name, ts):
        return name not in self._dead

    def armed_subjects(self):
        return sorted(self._group)

    def in_direct_range(self, shooter, target, ts):
        return (shooter, target) in self._in_range


_GROUPS = {
    "FRINF001": "보병 - 소총(M4 계열)",
    "ENT72001": "차량/장갑차 - M2HB 계열",
    "ENT72002": "차량/장갑차 - M2HB 계열",
    "ENINF001": "보병 - 소총(M4 계열)",
    "ENINF002": "보병 - 소총(M4 계열)",
}
_FORCE = {"FRINF001": "1", "ENT72001": "2", "ENT72002": "2",
          "ENINF001": "2", "ENINF002": "2"}
_ALL_IN_RANGE = {("FRINF001", t) for t in
                 ("ENT72001", "ENT72002", "ENINF001", "ENINF002")}


def _doctrine(min_targets=3, priority=("차량/장갑차 - M2HB 계열",
                                       "보병 - 소총(M4 계열)")):
    rules = {}
    from vtmak.premade.phases import PHASES
    for ph in PHASES:
        rules[ph.name] = PhaseRule(ph.name, priority, 40, True)
    return Doctrine("test", min_targets, rules)


def test_feasible_targets_excludes_same_force():
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE)
    out = feasible_targets(idx, "FRINF001", "T0100")
    assert "FRINF001" not in out
    assert set(out) == {"ENT72001", "ENT72002", "ENINF001", "ENINF002"}


def test_feasible_targets_excludes_out_of_range():
    idx = _FakeIndex(_FORCE, _GROUPS, {("FRINF001", "ENT72001")})
    assert feasible_targets(idx, "FRINF001", "T0100") == ["ENT72001"]


def test_feasible_targets_excludes_the_dead():
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE, alive={"ENT72001"})
    assert "ENT72001" not in feasible_targets(idx, "FRINF001", "T0100")


def test_assignment_reaches_the_minimum_target_count():
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE)
    base = [BasePair("FRINF001", "ENT72001", 250, "직접사격", ("E1",))]
    out = assign(idx, base, _doctrine(min_targets=3),
                 sim_start_ts="T0000", seconds_per_ts=1)
    targets = {e.target for e in out if e.shooter == "FRINF001"}
    assert len(targets) >= 3


def test_scenario_pairs_are_preserved_and_labelled():
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE)
    base = [BasePair("FRINF001", "ENT72001", 250, "직접사격", ("E1",))]
    out = assign(idx, base, _doctrine(), sim_start_ts="T0000", seconds_per_ts=1)
    scen = [e for e in out if e.origin == "scenario"]
    assert len(scen) == 1
    assert (scen[0].shooter, scen[0].target) == ("FRINF001", "ENT72001")


def test_targets_are_ordered_by_doctrine_priority_not_by_name():
    """우선순위가 기갑 우선이면, 이름이 뒤여도 기갑을 먼저 고른다."""
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE)
    base = [BasePair("FRINF001", "ENINF001", 250, "직접사격", ("E1",))]
    out = assign(idx, base, _doctrine(min_targets=2,
                                      priority=("차량/장갑차 - M2HB 계열",
                                                "보병 - 소총(M4 계열)")),
                 sim_start_ts="T0000", seconds_per_ts=1)
    added = [e for e in out if e.origin == "doctrine"]
    assert added[0].target.startswith("ENT72"), \
        "이름 오름차순이면 ENINF002가 먼저다 — 교리 우선순위가 이겨야 한다"


def test_a_shooter_never_has_overlapping_engagements():
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE)
    base = [BasePair("FRINF001", "ENT72001", 250, "직접사격", ("E1",))]
    mine = [e for e in assign(idx, base, _doctrine(),
                              sim_start_ts="T0000", seconds_per_ts=1)
            if e.shooter == "FRINF001"]
    mine.sort(key=lambda e: e.start_ts)
    for a, b in zip(mine, mine[1:]):
        assert a.end_ts <= b.start_ts, f"{a} 와 {b} 가 겹친다"


def test_assignment_is_deterministic():
    idx = _FakeIndex(_FORCE, _GROUPS, _ALL_IN_RANGE)
    base = [BasePair("FRINF001", "ENT72001", 250, "직접사격", ("E1",))]
    a = assign(idx, base, _doctrine(), sim_start_ts="T0000", seconds_per_ts=1)
    b = assign(idx, base, _doctrine(), sim_start_ts="T0000", seconds_per_ts=1)
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_assign.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade.assign'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/assign.py
"""표적 재지정 — 방침(교리)이 무엇을 고를지 정하고, 물리가 무엇이 가능한지 정한다.

거리는 feasible_targets의 사거리 판정에만 쓴다. 고를 때는 쓰지 않는다.
이 분리가 spec §2.4의 최근접 베이스라인 검사를 통과시키는 장치다.
"""
from __future__ import annotations

from dataclasses import dataclass

from vtmak.premade.base import BasePair
from vtmak.premade.doctrine import Doctrine
from vtmak.premade.entities import BELLIGERENT_FORCES
from vtmak.premade.phases import PHASES


@dataclass(frozen=True)
class Engagement:
    shooter: str
    target: str
    phase: str
    start_ts: str
    end_ts: str
    origin: str  # "scenario" | "doctrine"


def feasible_targets(index, shooter: str, ts: str) -> list[str]:
    """이 시각에 이 사수가 실제로 칠 수 있는 표적. 이름 오름차순."""
    my_force = index.force_of(shooter)
    if my_force not in BELLIGERENT_FORCES:
        return []
    out = []
    for name in index.armed_subjects_or_all():
        if name == shooter:
            continue
        f = index.force_of(name)
        if f not in BELLIGERENT_FORCES or f == my_force:
            continue
        if not index.is_alive(name, ts):
            continue
        if index.pos(name, ts) is None:
            continue
        if not index.in_direct_range(shooter, name, ts):
            continue
        out.append(name)
    return sorted(out)


def _priority_key(index, priority: tuple[str, ...]):
    """교리 우선순위 → 정렬 키. 목록에 없는 type_group은 맨 뒤."""
    rank = {g: i for i, g in enumerate(priority)}

    def key(name: str):
        p = index.profile_of(name)
        group = p.type_group if p is not None else ""
        return (rank.get(group, len(rank)), name)

    return key


def _ts_at(timestamps: list[str], sim_start_ts: str, time_s: int,
           seconds_per_ts: int) -> str | None:
    """시나리오 초 → 관측 시각 문자열. 범위를 벗어나면 None."""
    try:
        base = timestamps.index(sim_start_ts)
    except ValueError:
        return None
    i = base + int(time_s // max(1, seconds_per_ts))
    return timestamps[i] if 0 <= i < len(timestamps) else None


def assign(index, pairs: list[BasePair], doctrine: Doctrine,
           sim_start_ts: str, seconds_per_ts: int) -> list[Engagement]:
    """기반 쌍을 보존하고, 방침에 따라 사수마다 표적을 채운다."""
    timestamps = index.timestamps()
    by_shooter: dict[str, list[BasePair]] = {}
    for p in pairs:
        by_shooter.setdefault(p.shooter, []).append(p)

    out: list[Engagement] = []
    for shooter in sorted(by_shooter):
        assigned: set[str] = set()
        busy: list[tuple[int, int]] = []   # timestamps 인덱스 구간

        for p in sorted(by_shooter[shooter], key=lambda x: (x.time_s, x.target)):
            s = _ts_at(timestamps, sim_start_ts, p.time_s, seconds_per_ts)
            if s is None:
                continue
            rule = doctrine.rule_for(p.phase)
            dwell = rule.dwell_s if rule else 0
            i = timestamps.index(s)
            j = min(len(timestamps) - 1, i + dwell // max(1, seconds_per_ts))
            out.append(Engagement(shooter, p.target, p.phase,
                                  timestamps[i], timestamps[j], "scenario"))
            assigned.add(p.target)
            busy.append((i, j))

        for ph in PHASES:
            if len(assigned) >= doctrine.min_targets_per_shooter:
                break
            rule = doctrine.rule_for(ph.name)
            if rule is None or not rule.engage:
                continue
            s = _ts_at(timestamps, sim_start_ts, ph.start_s, seconds_per_ts)
            if s is None:
                continue
            i = timestamps.index(s)
            span = rule.dwell_s // max(1, seconds_per_ts)
            while any(i <= b and a <= i + span for a, b in busy):
                i += span + 1
                if i + span >= len(timestamps):
                    break
            if i + span >= len(timestamps):
                continue
            ts = timestamps[i]
            cands = [c for c in feasible_targets(index, shooter, ts)
                     if c not in assigned]
            if not cands:
                continue
            cands.sort(key=_priority_key(index, rule.target_priority))
            chosen = cands[0]
            j = i + span
            out.append(Engagement(shooter, chosen, ph.name,
                                  timestamps[i], timestamps[j], "doctrine"))
            assigned.add(chosen)
            busy.append((i, j))

    return sorted(out, key=lambda e: (e.shooter, e.start_ts, e.target))
```

- [ ] **Step 4: Add the helper the fake index needs and re-run**

`feasible_targets`가 후보 풀을 얻는 통로가 필요하다. `EntityIndex`에 한 줄 추가한다.

```python
# vtmak/premade/entities.py 의 EntityIndex 안에 추가
    def armed_subjects_or_all(self) -> list[str]:
        """표적 후보 풀 — 무장 여부와 무관하게 관측된 모든 주체."""
        return sorted(self._etype)
```

`_FakeIndex`에도 같은 메서드를 더한다.

```python
# tests/test_premade_assign.py 의 _FakeIndex 안에 추가
    def armed_subjects_or_all(self):
        return sorted(self._force)
```

Run: `pytest tests/test_premade_assign.py tests/test_premade_entities.py -v`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/assign.py vtmak/premade/entities.py tests/test_premade_assign.py
git commit -m "feat(premade): 교리 우선순위로 표적을 재지정한다 — 거리는 가부 판정만"
```

---

## Task 6: 엣지 방출과 CSV 쓰기

**Files:**
- Create: `vtmak/premade/emit.py`
- Test: `tests/test_premade_emit.py`

**Interfaces:**
- Consumes: `Engagement` (Task 5), `EntityIndex` (Task 2)
- Produces:
  - `PREMADE_COLUMNS: tuple[str, ...]` = `("subject","predicate","object","latitude","longitude","timestamp")`
  - `FIRE_PREDICATE: str` = `"Fire-Weapon"`
  - `engagement_edges(index, engagements, stride_ts) -> list[dict]`
  - `context_rows(source_csv) -> list[dict]` (ver1.0의 맥락 행을 6컬럼으로)
  - `write_premade(rows, out_path) -> int` (쓴 행 수)

**배경:** 한 교전은 `start_ts`~`end_ts` 사이의 관측 시각마다 `stride_ts` 간격으로
`Fire-Weapon` 엣지를 낸다. 좌표는 **사수의 관측 좌표**를 쓴다(ver1.0에서 주체 행의
좌표가 주체 것이었던 것과 같다). 맥락 행(`move to`·`Follow-Entity`·`FFE-on-Location`)은
ver1.0에서 그대로 가져오되, 기존 `Fire-Weapon` 338행은 **버린다** — 새 교전 집합으로
대체되며 남겨 두면 사수 4명이 이중 계산된다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_emit.py
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from vtmak.premade.assign import Engagement
from vtmak.premade.emit import (FIRE_PREDICATE, PREMADE_COLUMNS, context_rows,
                                engagement_edges, write_premade)


class _Idx:
    def __init__(self):
        self._ts = [f"2026-08-09T09:00:{i:02d}.000Z" for i in range(10)]

    def timestamps(self):
        return list(self._ts)

    def pos(self, name, ts):
        class C:
            lat, lon = 21.38, -157.74
        return C() if name == "FRINF001" else C()


def test_edges_cover_the_engagement_window_at_the_given_stride():
    eng = [Engagement("FRINF001", "ENT72001", "직접사격",
                      "2026-08-09T09:00:00.000Z", "2026-08-09T09:00:06.000Z",
                      "scenario")]
    rows = engagement_edges(_Idx(), eng, stride_ts=2)
    assert [r["timestamp"] for r in rows] == [
        "2026-08-09T09:00:00.000Z", "2026-08-09T09:00:02.000Z",
        "2026-08-09T09:00:04.000Z", "2026-08-09T09:00:06.000Z"]
    assert all(r["predicate"] == FIRE_PREDICATE for r in rows)
    assert all(r["subject"] == "FRINF001" and r["object"] == "ENT72001"
               for r in rows)


def test_edges_use_the_shooter_coordinate():
    eng = [Engagement("FRINF001", "ENT72001", "직접사격",
                      "2026-08-09T09:00:00.000Z", "2026-08-09T09:00:00.000Z",
                      "scenario")]
    rows = engagement_edges(_Idx(), eng, stride_ts=1)
    assert rows[0]["latitude"] == "21.38"


def test_context_rows_keep_the_six_columns_and_drop_old_fire(tmp_path):
    src = tmp_path / "gt.csv"
    header = ["subject", "predicate", "object", "timestamp", "latitude",
              "longitude", "source", "force", "tracking_id", "uuid",
              "entity_type", "damage", "smoke", "flaming", "mobility_kill",
              "firepower_kill", "suppression_level"]
    with src.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        base = {k: "" for k in header}
        w.writerow({**base, "subject": "A", "predicate": "move to",
                    "object": "LOC_중앙킬존", "timestamp": "T1",
                    "latitude": "21.1", "longitude": "-157.1"})
        w.writerow({**base, "subject": "B", "predicate": "none", "object": "",
                    "timestamp": "T1", "latitude": "21.2", "longitude": "-157.2"})
        w.writerow({**base, "subject": "C", "predicate": "Fire-Weapon",
                    "object": "D", "timestamp": "T1",
                    "latitude": "21.3", "longitude": "-157.3"})
    rows = context_rows(src)
    assert [r["predicate"] for r in rows] == ["move to"]
    assert list(rows[0]) == list(PREMADE_COLUMNS)


def test_write_premade_emits_the_header_in_the_agreed_order(tmp_path):
    out = tmp_path / "GT_ver2.0.csv"
    n = write_premade([{"subject": "A", "predicate": "move to", "object": "L",
                        "latitude": "21.1", "longitude": "-157.1",
                        "timestamp": "T1"}], out)
    assert n == 1
    first = out.read_text(encoding="utf-8").splitlines()[0]
    assert first == "subject,predicate,object,latitude,longitude,timestamp"


def test_rows_are_written_in_timestamp_then_subject_order(tmp_path):
    out = tmp_path / "o.csv"
    rows = [
        {"subject": "B", "predicate": "p", "object": "o", "latitude": "1",
         "longitude": "2", "timestamp": "T2"},
        {"subject": "A", "predicate": "p", "object": "o", "latitude": "1",
         "longitude": "2", "timestamp": "T1"},
        {"subject": "A", "predicate": "p", "object": "o", "latitude": "1",
         "longitude": "2", "timestamp": "T2"},
    ]
    write_premade(rows, out)
    got = [(r["timestamp"], r["subject"])
           for r in csv.DictReader(out.open(encoding="utf-8", newline=""))]
    assert got == [("T1", "A"), ("T2", "A"), ("T2", "B")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_emit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade.emit'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/emit.py
"""교전 → 시각별 엣지 → 6컬럼 CSV.

기존 Fire-Weapon 338행을 버리는 이유: 새 교전 집합이 시나리오 쌍을 이미
포함하므로(assign이 origin="scenario"로 보존한다) 남겨 두면 같은 사격이
두 번 센다. 합격검사의 '고유 쌍'과 '엣지 총량'이 둘 다 왜곡된다.
"""
from __future__ import annotations

import csv
from pathlib import Path

PREMADE_COLUMNS = ("subject", "predicate", "object",
                   "latitude", "longitude", "timestamp")
FIRE_PREDICATE = "Fire-Weapon"

# 맥락으로 남길 술어. spec §2.1의 역할 분리표를 그대로 옮긴 것이다.
CONTEXT_PREDICATES = frozenset({"move to", "Follow-Entity", "FFE-on-Location"})


def _fmt(v: float) -> str:
    return f"{v}"


def engagement_edges(index, engagements, stride_ts: int) -> list[dict]:
    """교전 구간의 관측 시각마다 Fire-Weapon 엣지를 낸다."""
    timestamps = index.timestamps()
    pos_of = {t: i for i, t in enumerate(timestamps)}
    rows: list[dict] = []
    for e in engagements:
        i, j = pos_of.get(e.start_ts), pos_of.get(e.end_ts)
        if i is None or j is None or j < i:
            continue
        for k in range(i, j + 1, max(1, stride_ts)):
            ts = timestamps[k]
            c = index.pos(e.shooter, ts)
            if c is None:
                continue
            rows.append({"subject": e.shooter, "predicate": FIRE_PREDICATE,
                         "object": e.target, "latitude": _fmt(c.lat),
                         "longitude": _fmt(c.lon), "timestamp": ts})
    return rows


def context_rows(source_csv: Path) -> list[dict]:
    """ver1.0 관측 CSV에서 맥락 엣지만 6컬럼으로 추린다."""
    out: list[dict] = []
    with Path(source_csv).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("predicate") not in CONTEXT_PREDICATES:
                continue
            if not (row.get("object") or "").strip():
                continue
            out.append({"subject": row["subject"], "predicate": row["predicate"],
                        "object": row["object"], "latitude": row["latitude"],
                        "longitude": row["longitude"],
                        "timestamp": row["timestamp"]})
    return out


def write_premade(rows: list[dict], out_path: Path) -> int:
    """시각·주체·대상 순으로 정렬해 쓴다. 같은 입력이면 바이트가 같다."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r["timestamp"], r["subject"],
                                          r["predicate"], r["object"]))
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(PREMADE_COLUMNS))
        w.writeheader()
        w.writerows(ordered)
    return len(ordered)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_premade_emit.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/emit.py tests/test_premade_emit.py
git commit -m "feat(premade): 교전을 시각별 엣지로 펴고 6컬럼 CSV로 쓴다"
```

---

## Task 7: 합격검사

**Files:**
- Create: `vtmak/premade/acceptance.py`
- Test: `tests/test_premade_acceptance.py`

**Interfaces:**
- Consumes: `FIRE_PREDICATE` (Task 6), `vtmak.geometry.Coord`, `ground_distance`
- Produces:
  - `Check(name: str, value: float, threshold: float, direction: str, passed: bool)`
    — `direction`은 `"min"`(이상) 또는 `"max"`(미만)
  - `run_checks(premade_csv: Path, index) -> list[Check]`
  - `report(checks: list[Check]) -> str` (마크다운)
  - `all_passed(checks) -> bool`

**검사 정의.** `Fire-Weapon` 엣지만 대상으로 한다.

| 이름 | 계산 | 방향 | 기준 |
|---|---|---|---|
| `unique_pairs` | 고유 (subject, object) 수 | min | 300 |
| `unique_shooters` | 고유 subject 수 | min | 60 |
| `targets_per_shooter` | 고유쌍 ÷ 고유사수 | min | 3.0 |
| `total_edges` | 엣지 행 수 | min | 10000 |
| `ts_span_ratio` | (마지막ts − 첫ts) ÷ 전체 ts 수 | min | 0.60 |
| `train_edges` | 앞 80% ts 구간의 엣지 수 | min | 6000 |
| `valid_edges` / `test_edges` | 80~90% / 90~100% 구간 | min | 700 |
| `nearest_enemy_mrr` | 사거리 내 적을 거리순 정렬했을 때 정답 순위의 MRR | max | 0.20 |
| `recency_mrr` | (subject) 직전 표적을 1등으로 놨을 때 MRR | max | 0.30 |

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_acceptance.py
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from vtmak.premade.acceptance import all_passed, report, run_checks
from vtmak.premade.emit import PREMADE_COLUMNS, FIRE_PREDICATE


class _Idx:
    def __init__(self, n_ts=100):
        self._ts = [f"T{i:04d}" for i in range(n_ts)]
        self._force = {}

    def timestamps(self):
        return list(self._ts)

    def force_of(self, name):
        return "1" if name.startswith("FR") else "2"

    def is_alive(self, name, ts):
        return True

    def pos(self, name, ts):
        class C:
            lat, lon = 21.38, -157.74
        return C()

    def in_direct_range(self, s, t, ts):
        return True

    def armed_subjects_or_all(self):
        return ["FRINF001", "ENT72001", "ENT72002"]

    def profile_of(self, name):
        return None


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "premade.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(PREMADE_COLUMNS))
        w.writeheader()
        w.writerows(rows)
    return p


def _fire(subject, obj, ts):
    return {"subject": subject, "predicate": FIRE_PREDICATE, "object": obj,
            "latitude": "21.38", "longitude": "-157.74", "timestamp": ts}


def test_checks_are_named_and_complete(tmp_path):
    p = _write(tmp_path, [_fire("FRINF001", "ENT72001", "T0001")])
    names = {c.name for c in run_checks(p, _Idx())}
    assert names == {"unique_pairs", "unique_shooters", "targets_per_shooter",
                     "total_edges", "ts_span_ratio", "train_edges",
                     "valid_edges", "test_edges", "nearest_enemy_mrr",
                     "recency_mrr"}


def test_a_thin_dataset_fails_the_volume_checks(tmp_path):
    p = _write(tmp_path, [_fire("FRINF001", "ENT72001", "T0001")])
    checks = {c.name: c for c in run_checks(p, _Idx())}
    assert checks["unique_pairs"].passed is False
    assert checks["total_edges"].passed is False
    assert all_passed(run_checks(p, _Idx())) is False


def test_recency_mrr_is_one_when_the_shooter_never_switches(tmp_path):
    """한 사수가 같은 표적만 쏘면 recency가 1.0이 되어 검사에 걸려야 한다."""
    rows = [_fire("FRINF001", "ENT72001", f"T{i:04d}") for i in range(1, 40)]
    p = _write(tmp_path, rows)
    checks = {c.name: c for c in run_checks(p, _Idx())}
    assert checks["recency_mrr"].value == pytest.approx(1.0)
    assert checks["recency_mrr"].passed is False


def test_ts_span_ratio_reflects_how_widely_edges_are_spread(tmp_path):
    rows = [_fire("FRINF001", "ENT72001", "T0000"),
            _fire("FRINF001", "ENT72002", "T0099")]
    p = _write(tmp_path, rows)
    checks = {c.name: c for c in run_checks(p, _Idx(n_ts=100))}
    assert checks["ts_span_ratio"].value == pytest.approx(0.99, abs=0.02)
    assert checks["ts_span_ratio"].passed is True


def test_report_marks_each_check_with_pass_or_fail(tmp_path):
    p = _write(tmp_path, [_fire("FRINF001", "ENT72001", "T0001")])
    text = report(run_checks(p, _Idx()))
    assert "unique_pairs" in text
    assert "FAIL" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_acceptance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtmak.premade.acceptance'`

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/acceptance.py
"""spec §2.4의 사전등록 합격검사.

nearest_enemy_mrr가 이 파일의 존재 이유다 — LLM 방침이 표적을 사실상 거리로
골랐다면 이 값이 실데이터 실측치 0.108에서 크게 벗어난다. 순환논증을 주장이
아니라 숫자로 판정한다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from vtmak.geometry import ground_distance
from vtmak.premade.emit import FIRE_PREDICATE

THRESHOLDS: dict[str, tuple[float, str]] = {
    "unique_pairs": (300, "min"),
    "unique_shooters": (60, "min"),
    "targets_per_shooter": (3.0, "min"),
    "total_edges": (10000, "min"),
    "ts_span_ratio": (0.60, "min"),
    "train_edges": (6000, "min"),
    "valid_edges": (700, "min"),
    "test_edges": (700, "min"),
    "nearest_enemy_mrr": (0.20, "max"),
    "recency_mrr": (0.30, "max"),
}


@dataclass(frozen=True)
class Check:
    name: str
    value: float
    threshold: float
    direction: str
    passed: bool


def _check(name: str, value: float) -> Check:
    threshold, direction = THRESHOLDS[name]
    passed = value >= threshold if direction == "min" else value < threshold
    return Check(name, float(value), float(threshold), direction, passed)


def _rr(ranked: list[str], gold: str) -> float:
    try:
        return 1.0 / (ranked.index(gold) + 1)
    except ValueError:
        return 0.0


def run_checks(premade_csv: Path, index) -> list[Check]:
    fires: list[tuple[str, str, str]] = []   # (ts, subject, object)
    with Path(premade_csv).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["predicate"] == FIRE_PREDICATE:
                fires.append((row["timestamp"], row["subject"], row["object"]))
    fires.sort()

    pairs = {(s, o) for _, s, o in fires}
    shooters = {s for _, s, _ in fires}
    timestamps = index.timestamps()
    n_ts = max(1, len(timestamps))
    pos_of = {t: i for i, t in enumerate(timestamps)}

    idxs = [pos_of[t] for t, _, _ in fires if t in pos_of]
    span = ((max(idxs) - min(idxs)) / n_ts) if idxs else 0.0
    cut1, cut2 = int(n_ts * 0.8), int(n_ts * 0.9)
    train = sum(1 for i in idxs if i < cut1)
    valid = sum(1 for i in idxs if cut1 <= i < cut2)
    test = sum(1 for i in idxs if i >= cut2)

    # 최근접 적 베이스라인
    near_rr, near_n = 0.0, 0
    for ts, s, gold in fires:
        cands = []
        my = index.force_of(s)
        for c in index.armed_subjects_or_all():
            if c == s or index.force_of(c) == my:
                continue
            if not index.is_alive(c, ts) or not index.in_direct_range(s, c, ts):
                continue
            a, b = index.pos(s, ts), index.pos(c, ts)
            if a is None or b is None:
                continue
            cands.append((ground_distance(a, b), c))
        if not cands:
            continue
        cands.sort()
        near_rr += _rr([c for _, c in cands], gold)
        near_n += 1

    # recency 베이스라인
    last: dict[str, str] = {}
    rec_rr, rec_n = 0.0, 0
    all_targets = sorted({o for _, _, o in fires})
    for _, s, gold in fires:
        prev = last.get(s)
        if prev is not None:
            ranked = [prev] + [t for t in all_targets if t != prev]
            rec_rr += _rr(ranked, gold)
            rec_n += 1
        last[s] = gold

    return [
        _check("unique_pairs", len(pairs)),
        _check("unique_shooters", len(shooters)),
        _check("targets_per_shooter", len(pairs) / max(1, len(shooters))),
        _check("total_edges", len(fires)),
        _check("ts_span_ratio", span),
        _check("train_edges", train),
        _check("valid_edges", valid),
        _check("test_edges", test),
        _check("nearest_enemy_mrr", near_rr / near_n if near_n else 0.0),
        _check("recency_mrr", rec_rr / rec_n if rec_n else 0.0),
    ]


def all_passed(checks: list[Check]) -> bool:
    return all(c.passed for c in checks)


def report(checks: list[Check]) -> str:
    lines = ["# pre-made-input 합격검사", "",
             "| 검사 | 값 | 기준 | 판정 |", "| --- | ---: | --- | --- |"]
    for c in checks:
        op = "≥" if c.direction == "min" else "<"
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"| `{c.name}` | {c.value:.4g} | {op} {c.threshold:g} | **{mark}** |")
    lines += ["", f"전체: **{'PASS' if all_passed(checks) else 'FAIL'}**"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_premade_acceptance.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/acceptance.py tests/test_premade_acceptance.py
git commit -m "feat(premade): 합격검사 10항목 — 순환논증을 숫자로 판정한다"
```

---

## Task 8: 파이프라인과 CLI

**Files:**
- Create: `vtmak/premade/pipeline.py`
- Create: `scripts/09_build_premade.py`
- Test: `tests/test_premade_pipeline.py`

**Interfaces:**
- Consumes: Task 1~7 전부
- Produces: `build_premade(gt_csv, events, objects_csv, doctrine_path, config_dir, out_dir, stride_ts, sim_start_ts, seconds_per_ts) -> dict`
  (매니페스트 딕셔너리를 돌려주고 `GT_ver2.0.csv`·`manifest.json`·`acceptance.md`를 쓴다)

**배경:** `sim_start_ts`는 시나리오 `time_s=0`에 대응하는 관측 시각이다. GT의 첫 시각은
`2026-08-09T08:53:22.000Z`이고 관측은 1초 간격이므로 기본값은 그 값, `seconds_per_ts=1`이다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_premade_pipeline.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vtmak.paths import BUILD, CONFIG, ROOT
from vtmak.premade.pipeline import build_premade

GT = BUILD / "stkg" / "ground_truth_ver1.0.csv"
EVENTS = BUILD / "events" / "battle.jsonl"
OBJECTS = BUILD / "timetable" / "battle_scnx_objects.csv"
DOCTRINE = CONFIG / "engagement_doctrine.json"

pytestmark = pytest.mark.skipif(
    not (GT.exists() and EVENTS.exists() and OBJECTS.exists()),
    reason="빌드 산출물이 없다")


def test_pipeline_writes_the_three_artifacts(tmp_path):
    out = tmp_path / "premade"
    manifest = build_premade(GT, EVENTS, OBJECTS, DOCTRINE, CONFIG, out,
                             stride_ts=1,
                             sim_start_ts="2026-08-09T08:53:22.000Z",
                             seconds_per_ts=1)
    assert (out / "GT_ver2.0.csv").exists()
    assert (out / "manifest.json").exists()
    assert (out / "acceptance.md").exists()
    assert manifest["rows"] > 0
    assert "checks" in manifest


def test_output_is_byte_stable_across_two_runs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        build_premade(GT, EVENTS, OBJECTS, DOCTRINE, CONFIG, d, stride_ts=1,
                      sim_start_ts="2026-08-09T08:53:22.000Z", seconds_per_ts=1)
    assert (a / "GT_ver2.0.csv").read_bytes() == (b / "GT_ver2.0.csv").read_bytes()


def test_manifest_records_provenance(tmp_path):
    out = tmp_path / "premade"
    m = build_premade(GT, EVENTS, OBJECTS, DOCTRINE, CONFIG, out, stride_ts=1,
                      sim_start_ts="2026-08-09T08:53:22.000Z", seconds_per_ts=1)
    assert m["doctrine_version"]
    assert m["base_pairs"] >= 1
    assert set(m["engagements_by_origin"]) == {"scenario", "doctrine"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_premade_pipeline.py -v`
Expected: FAIL (모듈 없음, 또는 `engagement_doctrine.json`이 없어 skip/에러)

- [ ] **Step 3: Write minimal implementation**

```python
# vtmak/premade/pipeline.py
"""증량 파이프라인 오케스트레이션."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from vtmak.premade.acceptance import all_passed, report, run_checks
from vtmak.premade.assign import assign
from vtmak.premade.base import base_pairs
from vtmak.premade.doctrine import Doctrine
from vtmak.premade.emit import context_rows, engagement_edges, write_premade
from vtmak.premade.entities import EntityIndex


def build_premade(gt_csv: Path, events: Path, objects_csv: Path,
                  doctrine_path: Path, config_dir: Path, out_dir: Path,
                  stride_ts: int, sim_start_ts: str,
                  seconds_per_ts: int) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = EntityIndex.load(gt_csv, config_dir)
    doctrine = Doctrine.load(doctrine_path)
    pairs = base_pairs(events, objects_csv)
    engagements = assign(index, pairs, doctrine, sim_start_ts, seconds_per_ts)

    rows = context_rows(gt_csv) + engagement_edges(index, engagements, stride_ts)
    premade = out_dir / "GT_ver2.0.csv"
    n = write_premade(rows, premade)

    checks = run_checks(premade, index)
    (out_dir / "acceptance.md").write_text(report(checks), encoding="utf-8")

    by_origin = collections.Counter(e.origin for e in engagements)
    manifest = {
        "doctrine_version": doctrine.version,
        "base_pairs": len(pairs),
        "engagements": len(engagements),
        "engagements_by_origin": {"scenario": by_origin.get("scenario", 0),
                                  "doctrine": by_origin.get("doctrine", 0)},
        "rows": n,
        "stride_ts": stride_ts,
        "sim_start_ts": sim_start_ts,
        "seconds_per_ts": seconds_per_ts,
        "accepted": all_passed(checks),
        "checks": [{"name": c.name, "value": c.value, "threshold": c.threshold,
                    "direction": c.direction, "passed": c.passed}
                   for c in checks],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
```

```python
# scripts/09_build_premade.py
"""시나리오 교전쌍 + 교전 방침 → 증량된 pre-made-input CSV."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from vtmak.paths import BUILD, CONFIG                       # noqa: E402
from vtmak.premade.pipeline import build_premade            # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="pre-made-input 교전 증량")
    p.add_argument("--gt", type=Path,
                   default=BUILD / "stkg" / "ground_truth_ver1.0.csv")
    p.add_argument("--events", type=Path, default=BUILD / "events" / "battle.jsonl")
    p.add_argument("--objects", type=Path,
                   default=BUILD / "timetable" / "battle_scnx_objects.csv")
    p.add_argument("--doctrine", type=Path,
                   default=CONFIG / "engagement_doctrine.json")
    p.add_argument("--config-dir", type=Path, default=CONFIG)
    p.add_argument("--out-dir", type=Path, default=BUILD / "premade")
    p.add_argument("--stride-ts", type=int, default=1)
    p.add_argument("--sim-start-ts", default="2026-08-09T08:53:22.000Z")
    p.add_argument("--seconds-per-ts", type=int, default=1)
    return p


def main() -> int:
    a = build_parser().parse_args()
    m = build_premade(a.gt, a.events, a.objects, a.doctrine, a.config_dir,
                      a.out_dir, a.stride_ts, a.sim_start_ts, a.seconds_per_ts)
    print(f"행 {m['rows']:,} · 교전 {m['engagements']:,} "
          f"(시나리오 {m['engagements_by_origin']['scenario']:,} / "
          f"방침 {m['engagements_by_origin']['doctrine']:,})")
    for c in m["checks"]:
        mark = "PASS" if c["passed"] else "FAIL"
        op = "≥" if c["direction"] == "min" else "<"
        print(f"  [{mark}] {c['name']:22s} {c['value']:.4g} {op} {c['threshold']:g}")
    print("합격" if m["accepted"] else "불합격 — 방침을 고쳐 다시 생성한다")
    return 0 if m["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Task 9에서 `engagement_doctrine.json`을 만들기 전까지는 파이프라인 테스트가
파일 없음으로 실패한다. 임시로 최소 방침을 만들어 배관만 확인한다.

```bash
python - <<'PY'
import json, pathlib
from vtmak.premade.phases import PHASES
d = {"version": "0.0-smoke", "min_targets_per_shooter": 3,
     "phases": {p.name: {"engage": True, "dwell_s": 30,
                         "target_priority": ["차량/장갑차 - M2HB 계열"]}
                for p in PHASES}}
pathlib.Path("config/engagement_doctrine.json").write_text(
    json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
PY
pytest tests/test_premade_pipeline.py -v
```

Expected: 3 passed (합격검사는 아직 불합격이어도 된다 — 이 테스트는 산출·결정론만 본다)

- [ ] **Step 5: Commit**

```bash
git add vtmak/premade/pipeline.py scripts/09_build_premade.py tests/test_premade_pipeline.py
git commit -m "feat(premade): 파이프라인과 CLI — 산출물 3종과 결정론 보증"
```

---

## Task 9: 교전 방침 작성과 합격검사 통과

**Files:**
- Modify: `config/engagement_doctrine.json` (Task 8의 스모크용 파일을 실제 방침으로 대체)
- Create: `build/premade/GT_ver2.0.csv`, `manifest.json`, `acceptance.md` (생성물)
- Modify: `README.md` (9단계 추가)

**Interfaces:**
- Consumes: `scripts/09_build_premade.py` (Task 8)
- Produces: 합격검사 10항목을 모두 통과한 `build/premade/GT_ver2.0.csv`

**이 태스크가 유일하게 LLM이 내용을 쓰는 곳이다.** 방침은 교리적 판단이며,
`target_priority`에 거리 개념을 넣지 않는다.

- [ ] **Step 1: 실제 방침을 쓴다**

`config/entity_class_map.csv`의 `type_group` 6종을 우선순위 재료로 쓴다:
`보병 - 소총(M4 계열)`, `보병 - RPG 계열`, `차량/장갑차 - M2HB 계열`,
`포병 - 박격포(m9333he 계열)`, `포병 - 155mm 자주포`, `미사일 발사대 - Patriot`.

국면별 교리 의도:

| 국면 | 교전 | 우선순위 의도 |
|---|---|---|
| 접근 | 예 | 원거리 화력을 먼저 무력화 — 포병·미사일 발사대 |
| 조준 | 아니오 | 조준 국면은 사격이 아니다 |
| 간접사격 | 예 | 대포병 — 포병 계열 |
| 직접사격 | 예 | 기갑 우선, 다음 대전차 보병 |
| 철수 | 예 | 추격 저지 — 기갑·차량 |

```bash
cat > config/engagement_doctrine.json <<'JSON'
{
  "version": "1.0",
  "min_targets_per_shooter": 3,
  "phases": {
    "접근": {
      "engage": true,
      "dwell_s": 40,
      "target_priority": ["포병 - 155mm 자주포", "포병 - 박격포(m9333he 계열)",
                          "미사일 발사대 - Patriot", "차량/장갑차 - M2HB 계열"]
    },
    "조준": {
      "engage": false,
      "dwell_s": 0,
      "target_priority": []
    },
    "간접사격": {
      "engage": true,
      "dwell_s": 40,
      "target_priority": ["포병 - 박격포(m9333he 계열)", "포병 - 155mm 자주포",
                          "차량/장갑차 - M2HB 계열"]
    },
    "직접사격": {
      "engage": true,
      "dwell_s": 40,
      "target_priority": ["차량/장갑차 - M2HB 계열", "보병 - RPG 계열",
                          "보병 - 소총(M4 계열)"]
    },
    "철수": {
      "engage": true,
      "dwell_s": 40,
      "target_priority": ["차량/장갑차 - M2HB 계열", "보병 - RPG 계열"]
    }
  }
}
JSON
```

- [ ] **Step 2: 생성하고 합격검사를 본다**

Run: `python scripts/09_build_premade.py`
Expected: 검사 10항목의 PASS/FAIL이 출력된다.

- [ ] **Step 3: 불합격 항목을 방침으로 고친다**

각 실패에 대응하는 조정 손잡이는 다음과 같다. **코드를 고치지 않는다** — 방침과
CLI 인자만 만진다. 코드를 고쳐야 한다면 그것은 이 태스크가 아니라 결함이다.

| 실패 검사 | 조정 |
|---|---|
| `unique_pairs`·`targets_per_shooter` 미달 | `min_targets_per_shooter`를 올린다 |
| `total_edges`·`train_edges` 미달 | `dwell_s`를 늘리거나 `--stride-ts 1`을 확인한다 |
| `ts_span_ratio` 미달 | `접근`·`철수` 국면의 `engage`가 true인지 확인한다 |
| `valid_edges`·`test_edges` 미달 | `철수` 국면 `dwell_s`를 늘린다 (뒤 20% 구간) |
| `nearest_enemy_mrr` 초과 | ⚠️ 우선순위가 사실상 거리와 정렬된 것이다. 근거리 클래스(보병)를 우선순위 앞에서 뒤로 옮긴다 |
| `recency_mrr` 초과 | 국면마다 우선순위 1위 클래스를 서로 다르게 한다 |

- [ ] **Step 4: 통과를 확인하고 README를 갱신한다**

Run: `python scripts/09_build_premade.py`
Expected: 모든 검사 PASS, 종료코드 0

Run: `pytest tests/ -v`
Expected: `test_gimbal_is_rewritten_in_the_cloned_record` 하나만 실패
(이 작업 이전부터 실패하던 기존 결함이다), 나머지 전부 통과

`README.md`에 9단계를 더한다:

```markdown
## 9. pre-made-input 교전 증량

시나리오의 교전쌍 98개를 기반으로, 국면별 교전 방침에 따라 표적을 재지정해
STLogic 실험용 6컬럼 CSV를 만든다. 방침은 교리적 우선순위만 정하고 좌표·시각·
개체 쌍은 코드가 실제 관측 궤적에서 고른다.

```bash
python scripts/09_build_premade.py
```

출력:

```text
build/premade/GT_ver2.0.csv     6컬럼 (subject,predicate,object,latitude,longitude,timestamp)
build/premade/manifest.json     출처·개수·합격검사 결과
build/premade/acceptance.md     합격검사 리포트
```

합격검사가 하나라도 불합격이면 종료코드 1이다. 기준은
`vtmak/premade/acceptance.py`의 `THRESHOLDS`에 있고 근거는 실험 설계 스펙
§2.4에 있다.
```

- [ ] **Step 5: Commit**

```bash
git add config/engagement_doctrine.json build/premade/ README.md
git commit -m "feat(premade): 교전 방침 1.0과 합격검사를 통과한 GT_ver2.0"
```

---

## Self-Review

**Spec coverage:**

| spec 절 | 구현 태스크 |
|---|---|
| §2.1 관계 역할 분리 (맥락/타겟) | Task 6 `CONTEXT_PREDICATES`, 기존 Fire-Weapon 폐기 |
| §2.2 (가) 사수당 표적 ≥3 | Task 4 `min_targets_per_shooter`, Task 5 재지정 루프, Task 7 검사 |
| §2.2 (나) 시간축 분산 | Task 1 5국면, Task 5 국면별 배치, Task 7 `ts_span_ratio`·`train_edges` |
| §2.3 LLM은 방침만 | Task 4 스키마, Task 9 방침 작성. 좌표·시각·쌍은 Task 5가 궤적에서 고름 |
| §2.4 합격검사 | Task 7 전체 |
| §2.5 6컬럼 열 순서 | Task 6 `PREMADE_COLUMNS` |
| §2.6 시간 분할 80/10/10 | Task 7 `train/valid/test_edges` |

**미구현으로 남기는 spec 항목**: §2.5 좌표 투영(ENU)과 §2.6 유출 차단은 STLogic
변환기·추론기의 일이지 pre-made-input의 일이 아니다. 이 계획의 범위 밖이며 별도
계획에서 다룬다.

**Type consistency 확인:**
- `EntityIndex`가 `armed_subjects()`(Task 2)와 `armed_subjects_or_all()`(Task 5 Step 4)
  둘 다 갖는다. 전자는 사수 후보(무장 필수), 후자는 표적 후보(무장 무관)다. 이름이
  역할을 드러내므로 유지한다.
- `Check.direction`은 `"min"`/`"max"` 두 값만 쓴다 — Task 7 정의와 Task 9 조정표가 일치.
- `Engagement.origin`은 `"scenario"`/`"doctrine"` 두 값 — Task 5 생성과 Task 8 매니페스트 집계 일치.
- `FIRE_PREDICATE`는 Task 6에서 정의하고 Task 7이 import 한다. 값은 `"Fire-Weapon"`으로
  기존 GT 표기와 같다.

**알려진 위험**: Task 5의 `_ts_at`은 시나리오 초와 관측 시각이 1:1 대응한다고 본다.
GT의 고유 시각이 1,325개이고 시나리오가 0~416초이므로 실제로는 관측이 더 길다.
`--seconds-per-ts`로 조절 가능하게 뒀으나, Task 9에서 국면 배치가 의도대로 안 되면
이 대응부터 확인한다.
