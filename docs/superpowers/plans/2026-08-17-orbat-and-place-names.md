# 편제(ORBAT) 도입과 통제점 지명화 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 328개 객체에 소대→중대→대대 편제를 붙여 `.oob`와 STKG 양쪽에 부대를 실재화하고, 통제점이 `P1`~`P11`이 아니라 지명으로 나가게 한다.

**Architecture:** 편제는 `config/orbat.json`(기능 매핑·축약 정원)에서 `vtmak/orbat.py`가 결정적으로 도출한다. `.oob`에는 골든의 3계층 aggregate 레코드를 복제해 `parent-name` 체인을 잇고, 태스크는 지금처럼 개별 엔티티에만 준다. 부대 사실은 시뮬레이터 관측이 아니라 `vtmak/derive/`에서 파생한다. 지명은 `config/location_codes.csv`의 ASCII 코드를 marking으로 쓰고, 04가 내는 대조표로 후처리에서 `LOC_*`로 되돌린다.

**Tech Stack:** Python 3.13 (표준 라이브러리만), pytest. 가상환경 없음 — `VR-Forces/`에서 실행하고 `tests/conftest.py`가 `sys.path`를 넣는다.

**Spec:** [docs/superpowers/specs/2026-08-17-orbat-and-place-names-design.ko.md](../specs/2026-08-17-orbat-and-place-names-design.ko.md)

## Global Constraints

- **`roster.unit_of()`를 바꾸지 않는다.** 이 함수는 `roster.json`의 `quota` 키(`FR-INF`·`EN-T72`)를 만든다. 편제로 바꾸면 명부 감축이 전부 어긋난다. 스펙 §5의 "`unit_of()`가 주는 값을 바꾸면"은 이 계획에서 **별도 모듈 `vtmak/orbat.py` 신설**로 대체한다.
- **부대 단위 태스크를 만들지 않는다.** 328개 엔티티 개별 `.pln`이 그대로 간다.
- **설정 값을 코드에 박지 않는다.** 임계값·정원·코드표는 `config/`의 표에 두고 `note` 열에 근거를 남긴다 (`derive_rules.csv`의 기존 관례).
- **조회는 시끄럽게 실패한다.** 없는 키에 기본값을 돌려주지 않는다 (`derive/config.py`의 기존 관례).
- **결정적이어야 한다.** 난수·해시를 쓰지 않는다. 정렬된 목록의 순서가 결과를 정한다 (`placement.py`의 기존 관례).
- **DIS `marking-text`는 11바이트 ASCII 이하.** 한글은 `object-label`에 둔다.
- 테스트 실행: `python -m pytest -q`. 착수 시점 기준선은 **319 통과 · 1 실패**(`test_fixed_objects.py::test_gimbal_is_rewritten_in_the_cloned_record` — 이 계획과 무관한 기존 실패). 이 1건은 고치지 않는다.
- 커밋 메시지는 한국어. 무엇을 왜 바꿨는지와 근거 수치를 적는다.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `config/location_codes.csv` | 지명 → ASCII 코드 (신규) | 1 |
| `vtmak/scnx/places.py` | 코드표 로더 (신규) | 1 |
| `vtmak/scnx/writer.py` | 통제점 marking, 부대 레코드, `.omp` | 1·7 |
| `scripts/04_compile_scnx.py` | 통제점 대조표 출력 | 2 |
| `vtmak/stkg/rewrite.py` | 통제점 이름 → `LOC_*` | 2 |
| `scripts/05_data_postprocessing.py` | 대조표 인자 | 2 |
| `config/orbat.json` | 기능 매핑·축약 정원·지원관계 (신규) | 3 |
| `vtmak/orbat.py` | 편제 도출 (신규) | 3 |
| `vtmak/scnx/placement.py` | 블록 키를 편제 소대로 | 4 |
| `vtmak/scnx/spec.py` | 대형 추종 선두, `UnitSpec` | 4·6 |
| `vtmak/scnx/golden.py` | aggregate 템플릿 추출 | 5 |
| `vtmak/derive/orbat_relations.py` | 부대 관계 파생 (신규) | 8·9 |
| `vtmak/derive/relations.py` | R5·R6를 편제 기준으로 | 9 |
| `config/derive_rules.csv` | 부대 관계 임계값 | 9 |
| `scripts/07_derive_relations.py` | 파생 산출물 (신규) | 10 |

---

### Task 1: 지명 코드표와 통제점 marking

`P{k}`가 CSV로 새어 나가는 근원을 끊는다. 이 태스크만으로 VR-Forces 지도에도 의미 있는 이름이 보인다.

**Files:**
- Create: `config/location_codes.csv`
- Create: `vtmak/scnx/places.py`
- Modify: `vtmak/scnx/writer.py` (`TemplateScnxWriter.__init__`, `_oob`)
- Test: `tests/test_places.py`

**Interfaces:**
- Consumes: `config/battlefield_layout.json`의 지명 29개
- Produces: `places.PlaceCodes.load(path) -> PlaceCodes`, `.code(loc_id) -> str`, `.loc_id(code) -> str`, `.codes() -> dict[str, str]`; `TemplateScnxWriter(golden_path, emit_plans=True, ai_enabled=..., place_codes=None)`

- [ ] **Step 1: 코드표를 만든다**

`config/location_codes.csv`. 29곳 전부다. `battlefield_layout.json`의 지명과 1:1이어야 한다.

```csv
loc_id,code,note
LOC_남측고지관측소,S_OP,아군 관측소
LOC_남측제1방어선,S_DEF1,
LOC_남측제1방어선전방,S_DEF1_FWD,
LOC_남측제2방어선,S_DEF2,
LOC_동측능선,E_RIDGE,
LOC_동측측방접근로,E_AVE,
LOC_목표A,OBJ_A,
LOC_목표A남측,OBJ_A_S,
LOC_목표B,OBJ_B,
LOC_북측관측소,N_OP,적 관측소
LOC_북측예비방어선,N_DEF_RES,
LOC_북측전방방어선,N_DEF_FWD,
LOC_서측능선,W_RIDGE,
LOC_아군박격포진지,S_MORT,
LOC_아군포병진지,S_ARTY,relocate 규칙으로 옮긴 점
LOC_아군후방보급집결지,S_SUPPLY,
LOC_아군후방지휘소,S_CP,
LOC_적박격포진지,N_MORT,
LOC_적북측접근로,N_AVE,
LOC_적북측지휘소,N_CP,
LOC_적북측집결지,N_ASSY,
LOC_적전방방어선후방,N_DEF_RR,
LOC_적포병진지,N_ARTY,relocate 규칙으로 옮긴 점
LOC_적후방보급집결지,N_SUPPLY,
LOC_중앙계곡,C_VALLEY,
LOC_중앙계곡북측,C_VALLEY_N,
LOC_중앙킬존,C_KILLZONE,
LOC_중앙킬존남측,C_KZ_S,
LOC_포병진지또는방어선후방,RR_AREA,
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_places.py`:

```python
"""지명 코드표 — DIS marking(11byte ASCII)에 한글을 못 넣어 코드를 붙인다."""
import json
from pathlib import Path

import pytest

from vtmak.scnx.places import PlaceCodes

ROOT = Path(__file__).resolve().parents[1]
CODES = ROOT / "config" / "location_codes.csv"
LAYOUT = ROOT / "config" / "battlefield_layout.json"


@pytest.fixture(scope="module")
def codes():
    return PlaceCodes.load(CODES)


def test_covers_every_location(codes):
    """지명이 하나라도 빠지면 그 통제점이 다시 P{k}로 나간다."""
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    assert set(codes.codes()) == set(layout["locations"])


def test_codes_fit_dis_marking(codes):
    """marking-text는 11바이트 ASCII다. 넘으면 잘려서 유일성이 깨진다."""
    for loc_id, code in codes.codes().items():
        assert code.isascii(), loc_id
        assert 0 < len(code.encode("ascii")) <= 11, (loc_id, code)


def test_codes_are_unique(codes):
    values = list(codes.codes().values())
    assert len(values) == len(set(values))


def test_round_trip(codes):
    assert codes.code("LOC_중앙계곡") == "C_VALLEY"
    assert codes.loc_id("C_VALLEY") == "LOC_중앙계곡"


def test_unknown_key_is_loud(codes):
    """없는 지명에 기본값을 주면 P{k}가 조용히 되살아난다."""
    with pytest.raises(KeyError):
        codes.code("LOC_없는곳")
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_places.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtmak.scnx.places'`

- [ ] **Step 4: 로더를 구현한다**

`vtmak/scnx/places.py`:

```python
"""지명 → DIS marking 코드.

`marking-text`는 DIS 네트워크 이름이라 11바이트 ASCII다. 한글 지명이 안
들어가서 통제점 marking이 `P{k}` 순번이었고, 시뮬레이터가 그 순번을 CSV로
그대로 내보내 지명이 사라졌다(실측: `Move-To Waypoint: "P3"`).

코드는 사람이 정한다. 자동 약어는 `LOC_남측제1방어선`과
`LOC_남측제1방어선전방`처럼 접두가 겹치는 쌍에서 읽을 수 없는 값이 나온다.
"""
from __future__ import annotations

import csv
from pathlib import Path


class PlaceCodes:
    def __init__(self) -> None:
        self._by_loc: dict[str, str] = {}
        self._by_code: dict[str, str] = {}

    @classmethod
    def load(cls, path) -> "PlaceCodes":
        pc = cls()
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                loc_id = (row["loc_id"] or "").strip()
                code = (row["code"] or "").strip()
                if not loc_id:
                    continue
                if not code:
                    raise ValueError(f"location_codes.csv: {loc_id}의 code가 비었다")
                if code in pc._by_code:
                    raise ValueError(
                        f"location_codes.csv: 코드 중복 {code} "
                        f"({pc._by_code[code]}, {loc_id})")
                pc._by_loc[loc_id] = code
                pc._by_code[code] = loc_id
        return pc

    def codes(self) -> dict[str, str]:
        return dict(self._by_loc)

    def code(self, loc_id: str) -> str:
        if loc_id not in self._by_loc:
            raise KeyError(f"location_codes.csv에 없는 지명: {loc_id}")
        return self._by_loc[loc_id]

    def loc_id(self, code: str) -> str:
        if code not in self._by_code:
            raise KeyError(f"location_codes.csv에 없는 코드: {code}")
        return self._by_code[code]
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/test_places.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: writer가 코드를 쓰게 한다**

`vtmak/scnx/writer.py` — `TemplateScnxWriter.__init__`에 인자를 더한다.

```python
    def __init__(self, golden_path: str = "yewon_test.scnx",
                 emit_plans: bool = True, ai_enabled: bool | None = None,
                 place_codes=None) -> None:
```

생성자 본문 끝에:

```python
        # 통제점 marking. 없으면 옛 순번(P{k})으로 폴백한다 — 코드표 없이
        # 만든 .scnx도 로드는 되어야 한다.
        self.place_codes = place_codes
```

`_oob`의 통제점 루프를 바꾼다 (현재 [writer.py:264-266](../../../vtmak/scnx/writer.py#L264)):

```python
        for k, c in enumerate(spec.control_objects, 1):
            # marking이 CSV로 그대로 나간다. 순번(P{k})을 쓰면 지명이 사라진다.
            mark = (self.place_codes.code(c.ref_id) if self.place_codes
                    else f"P{k}")
            parts.append("  " + self._control_record(c, f"1:3001:{n}", mark))
            n += 1
```

`scripts/04_compile_scnx.py`에서 writer를 만드는 자리에 코드표를 넘긴다. 파일 안에서 `TemplateScnxWriter(` 를 찾아 인자를 더한다:

```python
from vtmak.scnx.places import PlaceCodes                     # noqa: E402
...
    place_codes = PlaceCodes.load(ROOT / "config" / "location_codes.csv")
    writer = TemplateScnxWriter(..., place_codes=place_codes)
```

- [ ] **Step 7: 회귀가 없는지 확인한다**

Run: `python -m pytest -q`
Expected: 324 passed, 1 failed (기존 gimbal 실패만)

- [ ] **Step 8: 커밋**

```bash
git add config/location_codes.csv vtmak/scnx/places.py vtmak/scnx/writer.py scripts/04_compile_scnx.py tests/test_places.py
git commit -m "feat(scnx): 통제점 marking을 순번에서 지명 코드로

marking이 CSV로 그대로 나가는데 P{k} 순번이라 지명이 사라졌다(실측
ground_truth 20260809: P2·P3·P4·P10·P11 약 10.7만 행). DIS marking이 11byte
ASCII라 한글이 못 들어가므로 지명 29곳에 코드를 붙인다. 코드표가 없으면
옛 순번으로 폴백해 기존 .scnx 저작은 깨지지 않는다."
```

---

### Task 2: 통제점 대조표와 후처리 복원

marking을 고쳐도 STKG 출력은 `C_VALLEY`가 된다. `LOC_중앙계곡`으로 되돌린다.

**Files:**
- Modify: `scripts/04_compile_scnx.py`
- Modify: `vtmak/stkg/rewrite.py` (`rewrite`, `_fields`)
- Modify: `scripts/05_data_postprocessing.py`
- Test: `tests/test_stkg_rewrite.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `PlaceCodes`
- Produces: `build/timetable/battle_control_points.csv` (열 `code,loc_id,uuid,lat,lon`); `rewrite(rows, layout, uuid_map=None, control_points=None, place_names=None)` — `place_names`는 `{marking: loc_id}`

- [ ] **Step 1: 04가 대조표를 내게 한다**

`scripts/04_compile_scnx.py`, `.scnx`를 쓴 뒤에:

```python
    cp_path = ROOT / "build" / "timetable" / "battle_control_points.csv"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cp_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "loc_id", "uuid", "lat", "lon"])
        for c in spec.control_objects:
            w.writerow([place_codes.code(c.ref_id), c.ref_id, c.uuid,
                        f"{c.coord.lat:.7f}" if c.coord else "",
                        f"{c.coord.lon:.7f}" if c.coord else ""])
    print(f"통제점 대조표 {len(spec.control_objects)}행 → {cp_path.name}")
```

`import csv`가 없으면 상단에 더한다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_stkg_rewrite.py` 끝에 붙인다:

```python
def test_control_point_name_becomes_place_name():
    """`Move-To Waypoint: "C_VALLEY"`가 지명으로 돌아온다.

    시뮬레이터는 uuid가 아니라 marking을 그대로 내보낸다(실측
    `Move-To Waypoint: "P3"`). 대조표가 없으면 그 이름이 산출물에 남는다.
    """
    rows = [{"subject": "FRINF001", "predicate": 'Move-To Waypoint: "C_VALLEY"',
             "object": "-", "latitude": "21.38", "longitude": "-157.74",
             "timestamp": "2026-08-09T08:53:44.000Z", "source": "UAV 1"}]
    out, _, _, _ = rewrite(rows, _layout(), place_names={"C_VALLEY": "LOC_중앙계곡"})
    assert (out[0]["predicate"], out[0]["object"]) == ("move to", "LOC_중앙계곡")


def test_unknown_control_point_name_survives():
    """표에 없는 이름은 버리지 않고 원문을 남긴다 — 옛 판 CSV가 그렇다."""
    rows = [{"subject": "FRINF001", "predicate": 'Move-To Waypoint: "P3"',
             "object": "-", "latitude": "21.38", "longitude": "-157.74",
             "timestamp": "2026-08-09T08:53:44.000Z", "source": "UAV 1"}]
    out, _, _, _ = rewrite(rows, _layout(), place_names={"C_VALLEY": "LOC_중앙계곡"})
    assert out[0]["object"] == "P3"
```

`_layout()` 헬퍼가 그 파일에 이미 있으면 재사용하고, 없으면 파일 상단에 더한다:

```python
def _layout():
    from vtmak.geometry import BattlefieldLayout
    return BattlefieldLayout.load(
        Path(__file__).resolve().parents[1] / "config" / "battlefield_layout.json")
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_stkg_rewrite.py -q -k control_point`
Expected: FAIL — `rewrite() got an unexpected keyword argument 'place_names'`

- [ ] **Step 4: rewrite가 대조표를 쓰게 한다**

`vtmak/stkg/rewrite.py` — `rewrite` 시그니처:

```python
def rewrite(rows, layout, uuid_map=None, control_points=None,
            place_names=None):
```

본문에서 `uuid_map = uuid_map or {}` 옆에 `place_names = place_names or {}` 를 더하고, `_fields(...)` 호출 인자에 `place_names` 를 `control_points` 뒤에 넣는다.

`_fields` 시그니처와 `uuid` 분기를 바꾼다:

```python
def _fields(row, layout, uuid_map, control_points, place_names, links, tally):
```

```python
    if p.object_kind == "uuid":
        # 통제점은 uuid가 아니라 marking으로 나온다(실측 `Move-To Waypoint:
        # "P3"`). 대조표가 정본이고, 없으면 .oob marking 표로, 그것도 없으면
        # 원문을 남긴다 — 버리면 그 행이 어디로 갔는지 알 수 없다.
        place = place_names.get(p.object_raw)
        if place:
            return name, place
        marking = to_marking(p.object_raw, uuid_map)
        return name, marking if marking else p.object_raw
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/test_stkg_rewrite.py -q`
Expected: PASS

- [ ] **Step 6: 05가 대조표를 받게 한다**

`scripts/05_data_postprocessing.py`:

```python
    ap.add_argument("--control-points", default=str(
        ROOT / "build" / "timetable" / "battle_control_points.csv"),
        help="04가 낸 통제점 대조표. 없으면 통제점 이름을 그대로 둔다")
```

`uuid_map` 을 만드는 자리 아래에:

```python
    place_names: dict[str, str] = {}
    cp = Path(args.control_points)
    if cp.exists():
        with open(cp, encoding="utf-8-sig", newline="") as fh:
            place_names = {r["code"]: r["loc_id"] for r in csv.DictReader(fh)}
        print(f"  통제점 대조표 {len(place_names)}행")
    else:
        print(f"  통제점 대조표 없음({cp.name}) — 통제점 이름을 그대로 둔다")
```

`rewrite(...)` 호출에 `place_names=place_names` 를 더한다.

- [ ] **Step 7: 산출물에 순번이 남지 않는지 본다**

`tests/test_stkg_rewrite.py`에 커버리지 검사를 더한다. 스펙 §7의 "지명 커버리지" 항목이다.

```python
def test_no_bare_control_point_numbers_survive():
    """산출 CSV에 P\\d+ 형태 object가 남으면 지명화가 반쪽이다.

    대조표가 있는 실행에서만 의미가 있다 — 없으면 원문을 남기는 것이 옳다.
    """
    import re
    rows = [{"subject": "FRINF001", "predicate": f'Move-To Waypoint: "{c}"',
             "object": "-", "latitude": "21.38", "longitude": "-157.74",
             "timestamp": "2026-08-09T08:53:44.000Z", "source": "UAV 1"}
            for c in ("C_VALLEY", "S_DEF1")]
    names = {"C_VALLEY": "LOC_중앙계곡", "S_DEF1": "LOC_남측제1방어선"}
    out, _, _, _ = rewrite(rows, _layout(), place_names=names)
    assert not [r for r in out if re.fullmatch(r"P\d+", r["object"])]
```

- [ ] **Step 8: 회귀 확인 후 커밋**

Run: `python -m pytest -q`
Expected: 327 passed, 1 failed (기존 gimbal)

```bash
git add scripts/04_compile_scnx.py scripts/05_data_postprocessing.py vtmak/stkg/rewrite.py tests/test_stkg_rewrite.py
git commit -m "feat(stkg): 통제점 대조표로 지명 복원

04가 (code, loc_id, uuid, 좌표) 대조표를 내고 05가 그걸로 CSV의 통제점
이름을 LOC_*로 되돌린다. uuid를 배정하는 코드가 표도 같이 내므로 어긋날 수
없다. 표에 없는 이름은 버리지 않고 원문을 남긴다 — 옛 판 CSV의 P3이 그렇다."
```

---

### Task 3: 편제 도출 — `config/orbat.json` + `vtmak/orbat.py`

순수 로직이다. 파일 I/O가 registry와 config뿐이라 테스트가 쉽다.

**Files:**
- Create: `config/orbat.json`
- Create: `vtmak/orbat.py`
- Test: `tests/test_orbat.py`

**Interfaces:**
- Consumes: `registry.EntityDef` (`object_id`, `role`, `faction`, `initial_location`, `taskable`)
- Produces:
  - `OrbatConfig.load(path) -> OrbatConfig`
  - `build_orbat(registry: dict[str, EntityDef], cfg: OrbatConfig) -> Orbat`
  - `Unit(unit_id, name, marking, echelon, faction, parent, members)` — `echelon`은 `"소대" | "중대" | "대대"`
  - `Orbat.units() -> list[Unit]`, `.get(unit_id) -> Unit`, `.platoon_of(object_id) -> str | None`, `.chain(unit_id) -> tuple[str, ...]`, `.supports() -> tuple[tuple[str, str], ...]`, `.reinforces() -> tuple[tuple[str, str], ...]`

- [ ] **Step 1: 편제표를 만든다**

`config/orbat.json`:

```json
{
  "note": "원문 1,294줄에 소대·중대·대대 언급이 0건이라 편제는 추출이 아니라 저작이다. doctrine과 simulation_abstraction을 섞지 말 것 — 축약 정원을 교리 정원으로 읽히게 두면 논문에서 근거 문제가 된다.",

  "doctrine": {
    "source": "ATP 7-100.2, Fig 3-9~3-11",
    "platoons_per_company": 3,
    "squads_per_platoon": 3,
    "basic_unit_of_action": "battalion",
    "apply_split_to": ["보병"],
    "apply_split_note": "ATP의 '중대=3소대'는 보병중대에 대한 서술이다. 화력중대(포대)·수송중대·군수중대에까지 3소대 규칙을 강제하는 것은 우리 모델링 선택이 아니라 과적용이라 보병에만 건다."
  },

  "simulation_abstraction": {
    "note": "정원이 아니라 축약 강도(abstraction strength)다. 교리가 규정한 값이 아니라 이 시나리오 객체 수(328)에 맞춘 값이고, 객체 수가 바뀌면 여기만 조정한다.",
    "platoon_capacity": {
      "보병": 20, "전차": 4, "기계화수송": 4, "화력": 2,
      "군수": 4, "대전차": 20, "정찰": 20, "방공": 3, "본부": 20
    },
    "platoon_capacity_override": {
      "휴대 대공화기조": 20
    },
    "platoon_capacity_override_note": "MANPADS(SA7 15기)는 보병이 휴대한다. 대공화기(ZPU) 3문 기준을 그대로 적용하면 15기가 5개 소대가 되어 방공중대가 생긴다."
  },

  "company_functions": ["보병", "전차", "기계화수송", "화력", "군수"],
  "company_split_by_location": ["전차"],
  "company_split_by_location_note": "전차는 능선·접근로별로 따로 배치되어 한 중대로 묶으면 2km 넘게 흩어진다.",

  "function_code": {
    "보병": "INF", "전차": "ARM", "기계화수송": "MEC", "화력": "FIRE",
    "군수": "LOG", "대전차": "AT", "정찰": "REC", "방공": "AD", "본부": "HQ"
  },

  "function_of_role": {
    "방어 보병": "보병", "제1제대 보병": "보병",
    "동측 전차": "전차", "서측 전차": "전차",
    "전방 전차": "전차", "예비 전차": "전차",
    "장갑 수송차": "기계화수송", "궤도 수송차": "기계화수송",
    "병력수송 장갑차": "기계화수송", "화력지원 장갑차": "기계화수송",
    "곡사포": "화력", "박격포": "화력", "장거리 자주포": "화력",
    "자주포": "화력", "로켓화력 대체 객체": "화력",
    "탄약 보급차": "군수", "포탄 보급차": "군수", "병력 수송 트럭": "군수",
    "대전차팀": "대전차", "근접화력팀": "대전차",
    "감시·저격조": "정찰", "정찰·저격조": "정찰",
    "대공화기": "방공", "전방 대공화기": "방공", "휴대 대공화기조": "방공",
    "지휘소 경계 보병": "본부"
  },

  "faction_code": { "BLUE": "FR", "RED": "EN" },
  "faction_name": { "BLUE": "아군", "RED": "적군" },
  "battalion_name": { "BLUE": "아군 전술대대", "RED": "적군 전술대대" },

  "task_organization_note": "원문에 근거가 없어 저작한 값이다. 관측에서 파생된 관계와 섞이지 않도록 파생 레이어가 layer 필드로 구분한다.",
  "supports": [
    ["UNIT-FR-FIRE-CO1", "UNIT-FR-INF-CO1"],
    ["UNIT-FR-AT-PL1", "UNIT-FR-INF-CO1"],
    ["UNIT-FR-LOG-CO1", "UNIT-FR-BN"],
    ["UNIT-EN-FIRE-CO1", "UNIT-EN-INF-CO1"],
    ["UNIT-EN-LOG-CO1", "UNIT-EN-BN"]
  ],
  "reinforces": [
    ["UNIT-FR-ARM-CO2", "UNIT-FR-INF-CO1"],
    ["UNIT-EN-ARM-CO1", "UNIT-EN-INF-CO1"],
    ["UNIT-EN-ARM-CO2", "UNIT-EN-INF-CO2"]
  ]
}
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_orbat.py`:

```python
"""편제 도출 — 원문에 편제 언급이 0건이라 (진영 × 역할 × 초기배치)에서 만든다.

실측 기대치는 2026-08-17 build/events/battle.jsonl(객체 335, task 가능 328)
기준이다. 숫자가 틀어지면 편제가 아니라 입력이 바뀐 것이니 둘 다 본다.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.parser import Event
from vtmak.registry import ClassMap, build_registry

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"


@pytest.fixture(scope="module")
def registry():
    evs = [Event(**{k: v for k, v in json.loads(l).items()
                    if k != "source_line"})
           for l in open(ROOT / "build" / "events" / "battle.jsonl",
                         encoding="utf-8")]
    cm = ClassMap.load(CFG / "entity_class_map.csv")
    return build_registry(evs, cm, static_ids=set())


@pytest.fixture(scope="module")
def orbat(registry):
    return build_orbat(registry, OrbatConfig.load(CFG / "orbat.json"))


def test_echelon_counts(orbat):
    """대대 2 · 중대 13 · 소대 52 = 부대 67. 설계가 약속한 수다."""
    got = Counter(u.echelon for u in orbat.units())
    assert got == {"소대": 52, "중대": 13, "대대": 2}


def test_every_taskable_entity_has_a_platoon(orbat, registry):
    """고아가 하나라도 있으면 .oob 조직 트리가 안 닫힌다."""
    taskable = [o for o, d in registry.items() if d.taskable]
    missing = [o for o in taskable if orbat.platoon_of(o) is None]
    assert missing == []


def test_chain_closes_at_battalion(orbat):
    """소대 → (중대) → 대대. 깊이는 2단과 3단이 섞인다."""
    for u in orbat.units():
        if u.echelon != "소대":
            continue
        chain = orbat.chain(u.unit_id)
        assert orbat.get(chain[-1]).echelon == "대대", u.unit_id
        assert len(chain) in (2, 3), (u.unit_id, chain)


def test_markings_fit_dis(orbat):
    marks = [u.marking for u in orbat.units()]
    assert len(marks) == len(set(marks))
    for m in marks:
        assert m.isascii() and 0 < len(m.encode("ascii")) <= 11, m


def test_deterministic(registry):
    cfg = OrbatConfig.load(CFG / "orbat.json")
    a = [(u.unit_id, u.members) for u in build_orbat(registry, cfg).units()]
    b = [(u.unit_id, u.members) for u in build_orbat(registry, cfg).units()]
    assert a == b


def test_unknown_role_is_loud(registry):
    """역할이 표에 없으면 조용히 빠지면 안 된다 — 그 객체가 고아가 된다."""
    cfg = OrbatConfig.load(CFG / "orbat.json")
    cfg.function_of_role.pop("방어 보병")
    with pytest.raises(KeyError):
        build_orbat(registry, cfg)


def test_task_organization_targets_exist(orbat):
    ids = {u.unit_id for u in orbat.units()}
    for a, b in orbat.supports() + orbat.reinforces():
        assert a in ids, a
        assert b in ids, b
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_orbat.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtmak.orbat'`

- [ ] **Step 4: 편제 도출을 구현한다**

`vtmak/orbat.py`:

```python
"""역할군 → 편제(소대·중대·대대).

원문 1,294줄에 소대·중대·대대 언급이 0건이라 편제는 추출이 아니라 저작이다.
그런데 (진영 × 역할 × 초기 배치 지명)으로 역할군 30개가 이미 깔끔하게 나오므로,
축약 정원만 얹어 결정적으로 분할한다. 난수도 해시도 쓰지 않는다 — 정렬된
목록의 순서가 편성을 정한다(placement.py와 같은 규칙).

roster.unit_of()는 건드리지 않는다. 그건 roster.json의 quota 키(FR-INF)라
편제로 바꾸면 명부 감축이 통째로 어긋난다. 편제는 여기서만 다룬다.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ECHELON_PL = "소대"
ECHELON_CO = "중대"
ECHELON_BN = "대대"

_ROLE_INDEX = re.compile(r"\s*\d+$")


def role_stem(role: str) -> str:
    """'방어 보병 12' → '방어 보병'. 역할은 객체마다 번호가 붙어 온다."""
    return _ROLE_INDEX.sub("", (role or "").strip())


@dataclass(frozen=True)
class Unit:
    unit_id: str
    name: str
    marking: str
    echelon: str
    faction: str
    parent: str                      # 상위 unit_id. 대대는 ""
    members: tuple[str, ...] = ()    # 엔티티 object_id. 소대만 채워진다


@dataclass
class OrbatConfig:
    platoons_per_company: int
    apply_split_to: set
    capacity: dict
    capacity_override: dict
    company_functions: set
    company_split_by_location: set
    function_code: dict
    function_of_role: dict
    faction_code: dict
    faction_name: dict
    battalion_name: dict
    supports: tuple = ()
    reinforces: tuple = ()

    @classmethod
    def load(cls, path) -> "OrbatConfig":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        doc, sim = d["doctrine"], d["simulation_abstraction"]
        return cls(
            platoons_per_company=int(doc["platoons_per_company"]),
            apply_split_to=set(doc["apply_split_to"]),
            capacity=dict(sim["platoon_capacity"]),
            capacity_override=dict(sim["platoon_capacity_override"]),
            company_functions=set(d["company_functions"]),
            company_split_by_location=set(d["company_split_by_location"]),
            function_code=dict(d["function_code"]),
            function_of_role=dict(d["function_of_role"]),
            faction_code=dict(d["faction_code"]),
            faction_name=dict(d["faction_name"]),
            battalion_name=dict(d["battalion_name"]),
            supports=tuple(tuple(p) for p in d.get("supports", [])),
            reinforces=tuple(tuple(p) for p in d.get("reinforces", [])),
        )

    def function(self, role: str) -> str:
        stem = role_stem(role)
        if stem not in self.function_of_role:
            raise KeyError(f"orbat.json의 function_of_role에 없는 역할: {stem!r}")
        return self.function_of_role[stem]

    def platoon_capacity(self, role: str, func: str) -> int:
        stem = role_stem(role)
        if stem in self.capacity_override:
            return int(self.capacity_override[stem])
        if func not in self.capacity:
            raise KeyError(f"orbat.json의 platoon_capacity에 없는 기능: {func}")
        return int(self.capacity[func])


class Orbat:
    def __init__(self, units: list[Unit], supports=(), reinforces=()) -> None:
        self._u = {u.unit_id: u for u in units}
        self._of: dict[str, str] = {}
        for u in units:
            for oid in u.members:
                self._of[oid] = u.unit_id
        self._supports = tuple(supports)
        self._reinforces = tuple(reinforces)

    def units(self) -> list[Unit]:
        return [self._u[k] for k in sorted(self._u)]

    def get(self, unit_id: str) -> Unit:
        if unit_id not in self._u:
            raise KeyError(f"없는 부대: {unit_id}")
        return self._u[unit_id]

    def platoon_of(self, object_id: str) -> str | None:
        return self._of.get(object_id)

    def chain(self, unit_id: str) -> tuple[str, ...]:
        """자기 → 상위 → ... → 대대."""
        out, cur, seen = [], unit_id, set()
        while cur:
            if cur in seen:
                raise ValueError(f"부대 트리에 사이클: {unit_id}")
            seen.add(cur)
            out.append(cur)
            cur = self.get(cur).parent
        return tuple(out)

    def supports(self) -> tuple:
        return self._supports

    def reinforces(self) -> tuple:
        return self._reinforces


def build_orbat(registry, cfg: OrbatConfig) -> Orbat:
    taskable = {o: d for o, d in registry.items() if d.taskable}

    # 역할군: (진영, 역할, 초기 배치). 정렬된 id 순서가 소대 배정을 정한다.
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for oid in sorted(taskable):
        d = taskable[oid]
        groups[(d.faction, role_stem(d.role), d.initial_location)].append(oid)

    units: list[Unit] = []
    for faction in sorted({f for f, _, _ in groups}):
        units += _build_faction(faction, groups, cfg, taskable)
    return Orbat(units, cfg.supports, cfg.reinforces)


def _build_faction(faction, groups, cfg, taskable) -> list[Unit]:
    fc = cfg.faction_code[faction]
    bn_id = f"UNIT-{fc}-BN"
    out = [Unit(bn_id, cfg.battalion_name[faction], f"{fc}BN",
                ECHELON_BN, faction, "")]

    # 기능 → [(역할, 지명, 소대멤버 리스트)]
    by_func: dict[str, list[tuple[str, str, list[list[str]]]]] = defaultdict(list)
    for (f, role, loc), members in sorted(groups.items()):
        if f != faction:
            continue
        func = cfg.function(role)
        cap = cfg.platoon_capacity(role, func)
        chunks = [members[i:i + cap] for i in range(0, len(members), cap)]
        by_func[func].append((role, loc, chunks))

    for func in sorted(by_func):
        code = cfg.function_code[func]
        if func in cfg.company_functions:
            out += _build_companies(faction, fc, code, func, by_func[func],
                                    bn_id, cfg)
        else:
            out += _build_direct(faction, fc, code, func, by_func[func], bn_id,
                                 cfg)
    return out


def _build_companies(faction, fc, code, func, entries, bn_id, cfg) -> list[Unit]:
    """중대를 만드는 기능. 전차는 지명별로, 보병은 3소대마다 나눈다."""
    buckets: dict[str, list[list[str]]] = defaultdict(list)
    for role, loc, chunks in entries:
        key = loc if func in cfg.company_split_by_location else ""
        buckets[key] += chunks

    out: list[Unit] = []
    co_no = 0
    for key in sorted(buckets):
        chunks = buckets[key]
        per = (cfg.platoons_per_company if func in cfg.apply_split_to
               else len(chunks))
        n_co = max(1, math.ceil(len(chunks) / per))
        for i in range(n_co):
            co_no += 1
            co_id = f"UNIT-{fc}-{code}-CO{co_no}"
            out.append(Unit(co_id, f"{cfg.faction_name[faction]} {func}중대 {co_no}",
                            f"{fc}{code}CO{co_no}", ECHELON_CO, faction, bn_id))
            for j, members in enumerate(chunks[i * per:(i + 1) * per], 1):
                out.append(Unit(
                    f"{co_id}-PL{j}",
                    f"{cfg.faction_name[faction]} {func}중대 {co_no} {j}소대",
                    f"{fc}{code}C{co_no}P{j}", ECHELON_PL, faction, co_id,
                    tuple(members)))
    return out


def _build_direct(faction, fc, code, func, entries, bn_id, cfg) -> list[Unit]:
    """중대를 만들지 않는 기능 — 대대 직할 소대로 단다."""
    out: list[Unit] = []
    pl_no = 0
    for role, loc, chunks in entries:
        for members in chunks:
            pl_no += 1
            out.append(Unit(
                f"UNIT-{fc}-{code}-PL{pl_no}",
                f"{cfg.faction_name[faction]} {func} {pl_no}소대",
                f"{fc}{code}PL{pl_no}", ECHELON_PL, faction, bn_id,
                tuple(members)))
    return out
```

- [ ] **Step 5: 실행해서 실제 수치를 본다**

Run: `python -m pytest tests/test_orbat.py -q`
Expected: 대부분 PASS. `test_echelon_counts`가 기대치와 다르면 **테스트를 고치지 말고** 실제 편성을 아래로 찍어 확인한다:

```bash
python - <<'EOF'
import json
from collections import Counter
from pathlib import Path
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.parser import Event
from vtmak.registry import ClassMap, build_registry
ROOT = Path('.')
evs=[Event(**{k:v for k,v in json.loads(l).items() if k!='source_line'})
     for l in open('build/events/battle.jsonl',encoding='utf-8')]
reg=build_registry(evs, ClassMap.load('config/entity_class_map.csv'), set())
ob=build_orbat(reg, OrbatConfig.load('config/orbat.json'))
print(Counter(u.echelon for u in ob.units()))
Path('C:/Users/user/AppData/Local/Temp/claude/orbat_built.txt').write_text(
    "\n".join(f"{u.echelon}\t{u.unit_id}\t{u.marking}\t{u.parent}\t{len(u.members)}"
              for u in ob.units()), encoding='utf-8')
EOF
```

`config/orbat.json`의 정원·기능 매핑을 고쳐 설계 수치(52/13/2)에 맞춘다. 어긋난 이유를 커밋 메시지에 적는다.

- [ ] **Step 6: 전체 테스트**

Run: `python -m pytest -q`
Expected: 333 passed, 1 failed (기존 gimbal)

- [ ] **Step 7: 커밋**

```bash
git add config/orbat.json vtmak/orbat.py tests/test_orbat.py
git commit -m "feat(orbat): 역할군에서 소대·중대·대대를 결정적으로 도출

원문에 편제 언급이 0건이라 (진영 × 역할 × 초기배치) 30개 역할군에 축약
정원을 얹어 만든다. 대대 2 · 중대 13 · 소대 52.

근거 수준을 파일에서 가른다 — doctrine(중대=3소대)과
simulation_abstraction(보병 20/소대)을 한 표에 두면 축약 정원이 교리 정원으로
읽힌다. roster.unit_of()는 그대로 둔다: roster.json의 quota 키라 편제로 바꾸면
명부 감축이 어긋난다."
```

---

### Task 4: 배치와 대형 추종을 편제 소대 기준으로

편제가 생겼으니 "같은 부대는 흩어지지 않는다"는 기존 규칙이 진짜 부대를 보게 한다.

**Files:**
- Modify: `vtmak/scnx/placement.py` (`_Item`, `plan_offsets`)
- Modify: `vtmak/scnx/spec.py` (`_Ctx.__init__`, `_Ctx.unit_leader`, `build_spec`)
- Test: `tests/test_placement.py` (추가)

**Interfaces:**
- Consumes: Task 3의 `Orbat.platoon_of`
- Produces: `plan_offsets(items, rules, axis_bearing_deg, headings=None, unit_of_object=None)` — `unit_of_object`는 `object_id -> str` 함수. 없으면 기존 `roster.unit_of`로 폴백

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_placement.py` 끝에:

```python
def test_blocks_follow_the_given_unit_function():
    """블록 키가 편제 소대면, 같은 타입이라도 다른 소대는 다른 블록이다."""
    from pathlib import Path

    from vtmak.scnx.placement import PlacementRules, _Item, plan_offsets

    rules = PlacementRules.load(
        Path(__file__).resolve().parents[1] / "config" / "placement_rules.csv")
    items = [_Item(f"FR-INF-{i:03d}", "보병 - 소총(M4 계열)", "BLUE",
                   "LOC_남측제1방어선") for i in range(1, 41)]
    one = plan_offsets(items, rules, 163.36, unit_of_object=lambda o: "PL1")
    two = plan_offsets(
        items, rules, 163.36,
        unit_of_object=lambda o: "PL1" if o < "FR-INF-021" else "PL2")
    # 소대를 둘로 가르면 블록이 갈려 배치가 달라진다.
    assert {k: (v.east_m, v.north_m) for k, v in one.items()} != \
           {k: (v.east_m, v.north_m) for k, v in two.items()}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_placement.py -q -k unit_function`
Expected: FAIL — `plan_offsets() got an unexpected keyword argument 'unit_of_object'`

- [ ] **Step 3: placement가 주입받게 한다**

`vtmak/scnx/placement.py`:

```python
def plan_offsets(items: list[_Item], rules: PlacementRules,
                 axis_bearing_deg: float,
                 headings: dict[str, float] | None = None,
                 unit_of_object=None) -> dict[str, Placed]:
```

docstring의 "(부대, 타입그룹)" 설명 아래에 한 줄 더한다:

```python
    `unit_of_object`가 부대를 정한다. 안 주면 roster.unit_of(타입 접두사)로
    폴백한다 — 편제표 없이도 배치는 돌아야 한다.
```

블록 키를 바꾼다 (현재 [placement.py:195](../../../vtmak/scnx/placement.py#L195)):

```python
    unit = unit_of_object or unit_of
    ...
        for it in group:
            blocks.setdefault((it.type_group, unit(it.object_id)),
                              []).append(it)
```

`unit = unit_of_object or unit_of` 는 `by_loc` 를 만들기 전, 함수 본문 맨 위에 둔다.

`build_positions`도 받아 넘긴다 (현재 [placement.py:253](../../../vtmak/scnx/placement.py#L253) — `axis_bearing_deg`는 인자가 아니라 `layout`에서 읽는다):

```python
def build_positions(defs, layout: BattlefieldLayout, rules: PlacementRules,
                    headings: dict[str, float] | None = None,
                    unit_of_object=None) -> dict[str, Coord]:
    """{object_id: EntityDef} → {object_id: 배치 좌표}."""
    items = [_Item(oid, d.type_group, d.faction, d.initial_location)
             for oid, d in sorted(defs.items())]
    offsets = plan_offsets(items, rules, layout.axis_bearing_deg, headings,
                           unit_of_object)
```

- [ ] **Step 4: spec이 편제를 쓰게 한다**

`vtmak/scnx/spec.py` — `_Ctx.__init__` 시그니처에 `orbat=None`을 더하고, 선두 계산을 바꾼다:

```python
        # 부대 선두 — 대형 추종 이동(follow-entity)의 추종 대상. 편제가 있으면
        # 소대 선두를, 없으면 타입 접두사 선두를 쓴다.
        self._orbat = orbat
        self._leader: dict[str, str] = {}
        for oid in sorted(entity_uuids):
            self._leader.setdefault(self._unit(oid), oid)

    def _unit(self, object_id: str) -> str:
        if self._orbat is not None:
            pl = self._orbat.platoon_of(object_id)
            if pl:
                return pl
        return unit_of(object_id)

    def unit_leader(self, object_id: str) -> str | None:
        lead = self._leader.get(self._unit(object_id))
        return None if lead == object_id else lead
```

`build_spec(...)`에 `orbat=None` 인자를 더하고 `_Ctx(layout, ids, registry, entity_uuids, orbat)`로 넘긴다. `build_positions` 호출에도 `unit_of_object=(orbat.platoon_of if orbat else None)`을 넘긴다.

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest -q`
Expected: 334 passed, 1 failed (기존 gimbal)

- [ ] **Step 6: 커밋**

```bash
git add vtmak/scnx/placement.py vtmak/scnx/spec.py tests/test_placement.py
git commit -m "refactor(scnx): 배치·대형추종의 부대 기준을 편제 소대로

블록 키와 follow-entity 선두가 타입 접두사(FR-INF)를 부대로 보고 있었다.
편제를 주면 소대를, 안 주면 예전대로 폴백한다."
```

---

### Task 5: 골든에서 aggregate 템플릿 뽑기

**Files:**
- Modify: `vtmak/scnx/golden.py`
- Test: `tests/test_golden.py` (추가)

**Interfaces:**
- Produces: `Golden.aggregate_templates() -> list[GoldenObject]` — `kind`가 `"aggregate"`인 레코드. 짧은 것부터 정렬

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_golden.py` 끝에:

```python
def test_aggregate_templates_are_found(golden):
    """골든에 대대·중대·소대 레코드가 7개 있다(2026-08-17 갱신분)."""
    aggs = golden.aggregate_templates()
    assert len(aggs) == 7
    for a in aggs:
        assert a.kind == "aggregate"
        assert a.uuid
        assert "(aggregate-state Disaggregated)" in a.raw


def test_aggregate_is_not_mistaken_for_an_entity(golden):
    """aggregate의 object-type 첫 값이 3(보병과 같다). 엔티티 템플릿으로
    새어 들어가면 보병 대신 부대 껍데기가 복제된다."""
    for o in golden.objects:
        assert o.kind != "aggregate"
```

`golden` 픽스처가 그 파일에 없으면 더한다:

```python
@pytest.fixture(scope="module")
def golden():
    from vtmak.scnx.golden import Golden
    return Golden.load(Path(__file__).resolve().parents[1] / "yewon_test.scnx")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_golden.py -q -k aggregate`
Expected: FAIL — `'Golden' object has no attribute 'aggregate_templates'`

- [ ] **Step 3: 파서를 확장한다**

`vtmak/scnx/golden.py` — 상수를 더한다:

```python
KIND_AGGREGATE = "aggregate"   # (aggregate ...) 레코드. object-type이 아니다
```

`Golden`에 필드와 메서드를 더한다:

```python
@dataclass
class Golden:
    files: dict[str, bytes] = field(default_factory=dict)
    objects: list[GoldenObject] = field(default_factory=list)
    aggregates: list[GoldenObject] = field(default_factory=list)
```

`load` 안에서:

```python
        g.objects = _parse_objects(oob)
        g.aggregates = _parse_aggregates(oob)
```

메서드:

```python
    def aggregate_templates(self) -> list[GoldenObject]:
        """부대 레코드. 제대는 DIS 타입이 아니라 트리로만 구분되므로
        (실측: 대대·중대·소대가 전부 object-type 3 (11 1 0 0 34 0 11))
        어느 것을 써도 같다. 짧은 것부터 준다."""
        return sorted(self.aggregates, key=lambda o: len(o.raw))
```

파서:

```python
def _parse_aggregates(oob: str) -> list[GoldenObject]:
    """`(aggregate ...)` 레코드. `_parse_objects`는 `(local-vrf-object`만 읽어
    이걸 못 본다. object-type 첫 값이 3이라 보병 템플릿으로 새면 안 된다."""
    out: list[GoldenObject] = []
    for raw in _balanced_records(oob, "(aggregate"):
        ot = _OT_RE.search(raw)
        if not ot:
            continue
        dis = tuple(int(x) for x in ot.group(1).split())
        uuid = _UUID_RE.search(raw)
        mark = _MARK_RE.search(raw)
        pos = _POS_RE.search(raw)
        out.append(GoldenObject(
            kind=KIND_AGGREGATE, dis=dis,
            marking=mark.group(1) if mark else "",
            uuid=uuid.group(1) if uuid else "",
            position=((float(pos.group(1)), float(pos.group(2)),
                       float(pos.group(3))) if pos else None),
            raw=raw))
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_golden.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add vtmak/scnx/golden.py tests/test_golden.py
git commit -m "feat(scnx): 골든에서 aggregate 레코드를 템플릿으로 뽑는다

_parse_objects가 (local-vrf-object만 읽어 부대 레코드 7개를 못 봤다.
object-type 첫 값이 3이라 보병 템플릿으로 새지 않게 목록을 따로 둔다."
```

---

### Task 6: `UnitSpec`과 부대 좌표

**Files:**
- Modify: `vtmak/scnx/spec.py`
- Test: `tests/test_spec.py` (추가)

**Interfaces:**
- Consumes: Task 3 `Orbat`, Task 4 `build_spec(..., orbat=None)`
- Produces: `UnitSpec(unit_id, name, marking, uuid, echelon, faction, parent_uuid, coord)`; `ScnxSpec.units: list[UnitSpec]`; `ScnxSpec.unit_of_entity: dict[str, str]` (object_id → 소대 uuid)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_spec.py` 끝에:

```python
def test_units_are_built_when_orbat_is_given(spec_with_orbat):
    spec = spec_with_orbat
    assert len(spec.units) == 67
    by_ech = {}
    for u in spec.units:
        by_ech[u.echelon] = by_ech.get(u.echelon, 0) + 1
    assert by_ech == {"소대": 52, "중대": 13, "대대": 2}


def test_unit_coord_is_the_member_centroid(spec_with_orbat):
    """부대 위치 = 구성원 배치 좌표의 중심점(연구내용 §3.2)."""
    spec = spec_with_orbat
    coords = {e.object_id: e.coord for e in spec.entities}
    pl = next(u for u in spec.units if u.echelon == "소대")
    members = [o for o, uu in spec.unit_of_entity.items() if uu == pl.uuid]
    assert members
    lat = sum(coords[o].lat for o in members) / len(members)
    lon = sum(coords[o].lon for o in members) / len(members)
    assert abs(pl.coord.lat - lat) < 1e-9
    assert abs(pl.coord.lon - lon) < 1e-9


def test_every_entity_maps_to_a_platoon_uuid(spec_with_orbat):
    spec = spec_with_orbat
    assert set(spec.unit_of_entity) == {e.object_id for e in spec.entities}
```

`spec_with_orbat` 픽스처는 그 파일의 기존 `spec` 픽스처를 복사해 `build_spec(..., orbat=build_orbat(registry, OrbatConfig.load(CFG / "orbat.json")))`로 만든다.

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_spec.py -q -k orbat`
Expected: FAIL — `AttributeError: 'ScnxSpec' object has no attribute 'units'`

- [ ] **Step 3: 구현한다**

`vtmak/scnx/spec.py`:

```python
@dataclass
class UnitSpec:
    unit_id: str
    name: str
    marking: str
    uuid: str
    echelon: str
    faction: str
    parent_uuid: str      # 상위 부대 uuid. 대대는 "" (force 루트에 건다)
    coord: Coord
```

`ScnxSpec`에 필드를 더한다:

```python
    units: list[UnitSpec] = field(default_factory=list)
    # 엔티티 object_id → 소속 소대 uuid. writer가 parent-name을 잇는다.
    unit_of_entity: dict[str, str] = field(default_factory=dict)
```

`build_spec` 끝(통제점 루프 뒤)에:

```python
    if orbat is not None:
        spec.units, spec.unit_of_entity = _build_units(orbat, spec, ids)
    return spec


def _centroid(coords: list[Coord]) -> Coord:
    """부대 좌표는 구성원 배치 좌표의 중심점이다(연구내용 §3.2).

    고도는 평균이 아니라 중심점에서 다시 지형을 읽어야 맞지만, 부대는 표시용
    노드라 지면에 박히지 않아도 된다. 평균으로 둔다.
    """
    n = len(coords)
    return Coord(sum(c.lat for c in coords) / n,
                 sum(c.lon for c in coords) / n,
                 sum(c.alt for c in coords) / n)


def _build_units(orbat, spec: ScnxSpec, ids: IdAllocator):
    coord_of = {e.object_id: e.coord for e in spec.entities}
    uuid_of = {u.unit_id: ids.alloc("unit", u.unit_id) for u in orbat.units()}

    # 소대부터 채워야 중대·대대 중심점을 구성원에서 다시 접을 수 있다.
    members: dict[str, list[Coord]] = {}
    for u in orbat.units():
        if u.echelon == "소대":
            members[u.unit_id] = [coord_of[o] for o in u.members
                                  if o in coord_of]
    for u in orbat.units():
        if u.echelon == "소대":
            continue
        kids = [x.unit_id for x in orbat.units() if x.parent == u.unit_id]
        members[u.unit_id] = [c for k in kids for c in members.get(k, [])]

    out: list[UnitSpec] = []
    for u in orbat.units():
        cs = members.get(u.unit_id) or []
        if not cs:
            raise ValueError(f"구성원이 없는 부대: {u.unit_id}")
        out.append(UnitSpec(
            unit_id=u.unit_id, name=u.name, marking=u.marking,
            uuid=uuid_of[u.unit_id], echelon=u.echelon, faction=u.faction,
            parent_uuid=uuid_of[u.parent] if u.parent else "",
            coord=_centroid(cs)))

    of_entity = {}
    for u in orbat.units():
        for oid in u.members:
            if oid in coord_of:
                of_entity[oid] = uuid_of[u.unit_id]
    return out, of_entity
```

`build_spec` 시그니처에 `orbat=None`이 이미 Task 4에서 더해졌는지 확인한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest -q`
Expected: 338 passed, 1 failed (기존 gimbal)

- [ ] **Step 5: 커밋**

```bash
git add vtmak/scnx/spec.py tests/test_spec.py
git commit -m "feat(scnx): UnitSpec과 부대 좌표(구성원 중심점)

부대 위치를 구성원 배치 좌표의 중심점으로 정한다 — STLogic 연구내용 §3.2가
'부대(구성원 중심점)'로 정의해 둔 것과 같은 값이라 STKG 쪽과 어긋나지 않는다.
중대·대대는 예하 소대의 구성원을 접어 올린다."
```

---

### Task 7: `.oob`에 부대 레코드와 parent 체인

무한 로딩이 났던 자리다. 게이트를 넉넉히 건다.

**Files:**
- Modify: `vtmak/scnx/writer.py` (`_unit_record`, `_entity_record`, `_oob`, `_omp`)
- Modify: `scripts/04_compile_scnx.py`
- Test: `tests/test_writer.py` (추가)

**Interfaces:**
- Consumes: Task 5 `Golden.aggregate_templates()`, Task 6 `ScnxSpec.units`·`unit_of_entity`
- Produces: 부대가 든 `.oob`/`.omp`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_writer.py` 끝에:

```python
def test_org_tree_closes_with_units(scnx_with_units):
    """parent-name이 전부 이 .oob 안에서 해석된다. 안 그러면 무한 로딩이다."""
    import re
    oob = scnx_with_units
    declared = set(re.findall(r'\(uuid\s+"VRF_UUID:([^"]*)"', oob)) | {
        "1 Force", "2 Force", "3 Force"}
    refs = re.findall(r'\(parent-name\s+(?:"VRF_UUID:([^"]*)"|(\S+?))\s*\)', oob)
    dangling = sorted({a for a, b in refs if a and a not in declared} |
                      {b for a, b in refs if b and b != "USE-DEFAULT"})
    assert dangling == []


def test_every_entity_hangs_under_a_platoon(scnx_with_units, spec_with_orbat):
    """고아 엔티티가 있으면 편제가 반쪽이다."""
    import re
    oob = scnx_with_units
    pl_uuids = {u.uuid for u in spec_with_orbat.units if u.echelon == "소대"}
    recs = re.findall(r'\(local-vrf-object.*?\n   \)', oob, re.S)
    hung = 0
    for r in recs:
        m = re.search(r'\(parent-name\s+"VRF_UUID:([^"]*)"', r)
        if m and m.group(1) in pl_uuids:
            hung += 1
    assert hung == len(spec_with_orbat.entities)


def test_omp_lists_every_object(scnx_with_units, omp_with_units, spec_with_orbat):
    import re
    oob_uuids = set(re.findall(r'\(uuid\s+"VRF_UUID:([^"]*)"', scnx_with_units))
    omp_uuids = set(re.findall(r'\(uuid\s+"VRF_UUID:([^"]*)"', omp_with_units))
    assert oob_uuids == omp_uuids
    assert len(omp_uuids) == (len(spec_with_orbat.entities)
                              + len(spec_with_orbat.units)
                              + len(spec_with_orbat.control_objects)
                              + len(spec_with_orbat.fixed_objects))
```

픽스처 두 개를 더한다 — `TemplateScnxWriter`의 `_oob`/`_omp`를 직접 부른다:

```python
@pytest.fixture(scope="module")
def scnx_with_units(spec_with_orbat, writer):
    return writer._oob(spec_with_orbat)


@pytest.fixture(scope="module")
def omp_with_units(spec_with_orbat, writer):
    return writer._omp(spec_with_orbat)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_writer.py -q -k units`
Expected: FAIL — 고아 엔티티 328개 (`hung == 0`)

- [ ] **Step 3: 부대 레코드를 쓴다**

`vtmak/scnx/writer.py`:

```python
_RE_FORMATION_NAME = re.compile(r'\(formation-name "[^"]*"')


    def _unit_record(self, u, oid: str) -> str:
        """골든 aggregate 레코드를 복제해 부대 하나를 만든다.

        제대는 DIS 타입이 아니라 트리로 구분된다(실측: 대대·중대·소대가 전부
        object-type 3 (11 1 0 0 34 0 11)). 대대만 force 루트에 걸고
        subordinate-of-force-level True를 준다 — 골든이 그렇게 되어 있다.
        """
        if self._agg is None:
            raise ValueError("골든에 aggregate 템플릿이 없다")
        force = _FORCE.get(u.faction, "ForceNeutral")
        r = self._agg.raw
        r = _RE_OID.sub(f'(object-identifier  "{oid}"', r, count=1)
        r = _RE_MARK.sub(f'(marking-text "{u.marking}"', r, count=1)
        r = _RE_LABEL.sub(f'(object-label "{u.name}"', r, count=1)
        r = _RE_UUID.sub(f'(uuid  "VRF_UUID:{u.uuid}"', r, count=1)
        r = _RE_FORCE.sub(f"(force {force})", r)
        r = _RE_FORMATION_NAME.sub(f'(formation-name "{u.name}"', r, count=1)
        if u.parent_uuid:
            r = _RE_PARENT.sub(f'(parent-name  "VRF_UUID:{u.parent_uuid}")',
                               r, count=1)
            r = _RE_SUBFL.sub("(subordinate-of-force-level False)", r, count=1)
        else:
            r = _RE_PARENT.sub(
                f'(parent-name  "VRF_UUID:{_FORCE_ROOT[force]}")', r, count=1)
            r = _RE_SUBFL.sub("(subordinate-of-force-level True)", r, count=1)
        r = _RE_POS.sub(f"(position  {_fmt_ecef(u.coord)})", r)
        return r
```

`__init__`에 템플릿을 잡는다:

```python
        aggs = self.golden.aggregate_templates()
        self._agg = aggs[0] if aggs else None
```

- [ ] **Step 4: 엔티티를 소대에 건다**

`_entity_record`에 `parent_uuid` 인자를 더한다:

```python
    def _entity_record(self, e: EntitySpec, oid: str, mark: str,
                       parent_uuid: str = "") -> str:
```

`_RE_PARENT.sub(...)` 부분(현재 force 루트 강제)을 바꾼다:

```python
        # 편제가 있으면 소속 소대 밑에, 없으면 force 루트에 건다. 골든 예하가
        # 아니라 우리가 선언한 부대라 dangling이 생기지 않는다.
        if parent_uuid:
            r = _RE_PARENT.sub(
                f'(parent-name  "VRF_UUID:{parent_uuid}")', r, count=1)
            r = _RE_SUBFL.sub("(subordinate-of-force-level False)", r, count=1)
        else:
            r = _RE_PARENT.sub(
                f'(parent-name  "VRF_UUID:{_FORCE_ROOT[force]}")', r, count=1)
            r = _RE_SUBFL.sub("(subordinate-of-force-level True)", r, count=1)
```

- [ ] **Step 5: `_oob`가 부대를 먼저 낸다**

`_oob`의 엔티티 루프 **앞**에:

```python
        # 대대 → 중대 → 소대 순으로 먼저 낸다. VR-Forces는 uuid로 트리를 닫아
        # 순서를 안 따지지만, 사람이 읽을 때 위에서 아래로 내려가는 편이 낫다.
        rank = {"대대": 0, "중대": 1, "소대": 2}
        for u in sorted(spec.units, key=lambda x: (rank[x.echelon], x.unit_id)):
            parts.append("  " + self._unit_record(u, f"1:3001:{n}"))
            n += 1
```

엔티티 루프에서 소속을 넘긴다:

```python
            parts.append("  " + self._entity_record(
                e, f"1:3001:{n}", e.object_id.replace("-", "")[:11],
                spec.unit_of_entity.get(e.object_id, "")))
```

- [ ] **Step 6: `.omp`에 부대를 넣는다**

`_omp`의 uuid 목록에 더한다:

```python
        for uid in ([e.uuid for e in spec.entities]
                    + [u.uuid for u in spec.units]
                    + [c.uuid for c in spec.control_objects]
                    + [f.uuid for f in spec.fixed_objects]):
```

- [ ] **Step 7: 04가 편제를 넘기게 한다**

`scripts/04_compile_scnx.py`:

```python
from vtmak.orbat import OrbatConfig, build_orbat                # noqa: E402
...
    orbat = build_orbat(registry, OrbatConfig.load(ROOT / "config" / "orbat.json"))
    spec = build_spec(..., orbat=orbat)
    print(f"부대 {len(spec.units)} (대대·중대·소대)")
```

- [ ] **Step 8: 통과를 확인하고 실물을 만든다**

Run: `python -m pytest -q`
Expected: 341 passed, 1 failed (기존 gimbal)

Run: `python scripts/04_compile_scnx.py`
Expected: `차단 0건`, `부대 67`, `통제점 대조표 N행`

- [ ] **Step 9: 커밋**

```bash
git add vtmak/scnx/writer.py scripts/04_compile_scnx.py tests/test_writer.py
git commit -m "feat(scnx): .oob에 부대 67개와 parent 체인

대대→중대→소대→엔티티를 잇는다. 골든(2026-08-17 갱신)에서 3계층이 실제로
닫히는 것을 확인했다 — dangling 0 · 사이클 없음 · .omp 60=60.

엔티티 parent-name을 force 루트로 강제하던 것을 소속 소대로 바꾼다. 우리가
같은 파일에 선언한 부대라 예전 무한 로딩(골든 '부대 1' 예하 참조)과 다르고,
_check_org_tree가 그대로 지킨다. 태스크는 개별 엔티티에만 준다."
```

---

### Task 8: 편제표에서 나오는 부대 사실 (R8·R9)

편제표만 보면 되는 관계다. 이벤트를 안 읽어 테스트가 빠르고, 관측 기반 규칙(Task 9)과 따로 판단할 수 있다.

**Files:**
- Create: `vtmak/derive/orbat_relations.py`
- Test: `tests/test_derive_orbat.py`

**Interfaces:**
- Consumes: Task 3 `Orbat`, `derive.relations.Relation(rule_id, predicate, subject, object, provenance, layer="derived")`, `derive.relations.RuleResult`
- Produces:
  - `LAYER_ORBAT = "orbat"`
  - `r8_part_of(orbat) -> RuleResult`
  - `r9_task_organization(orbat) -> RuleResult`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_derive_orbat.py`:

```python
"""R8~R12 — 편제와 이벤트에서 부대가 주어인 fact를 만든다.

백마고지 데이터셋은 주어가 부대인 fact가 0건이었다(변환 후 116,680행 전수).
여기서 그 자리를 메운다.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from vtmak.derive.orbat_relations import r8_part_of, r9_task_organization
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.parser import Event
from vtmak.registry import ClassMap, build_registry

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
EVENTS = ROOT / "build" / "events" / "battle.jsonl"


@pytest.fixture(scope="module")
def orbat():
    evs = [Event(**{k: v for k, v in json.loads(l).items()
                    if k != "source_line"})
           for l in open(EVENTS, encoding="utf-8")]
    reg = build_registry(evs, ClassMap.load(CFG / "entity_class_map.csv"), set())
    return build_orbat(reg, OrbatConfig.load(CFG / "orbat.json"))


def test_r8_covers_every_entity_and_child_unit(orbat):
    """엔티티 전원 + 상위가 있는 부대 전부. 대대만 상위가 없다."""
    rels = r8_part_of(orbat).relations
    assert all(r.predicate == "partOf" for r in rels)
    n_members = sum(len(u.members) for u in orbat.units())
    n_children = sum(1 for u in orbat.units() if u.parent)
    assert len(rels) == n_members + n_children


def test_r8_chain_reaches_the_battalion(orbat):
    """엔티티 → 소대 → (중대) → 대대로 닫힌다. 홉은 2단과 3단이 섞인다."""
    up = {r.subject: r.object for r in r8_part_of(orbat).relations}
    for u in orbat.units():
        for oid in u.members:
            cur, hops = oid, 0
            while cur in up:
                cur, hops = up[cur], hops + 1
            assert orbat.get(cur).echelon == "대대", oid
            assert hops in (2, 3), (oid, hops)


def test_r8_is_layered_as_orbat(orbat):
    """편제표가 선언한 값이지 관측에서 파생한 값이 아니다."""
    from vtmak.derive.orbat_relations import LAYER_ORBAT
    assert {r.layer for r in r8_part_of(orbat).relations} == {LAYER_ORBAT}


def test_r9_uses_only_declared_pairs(orbat):
    rels = r9_task_organization(orbat).relations
    assert Counter(r.predicate for r in rels) == {
        "supports": len(orbat.supports()),
        "reinforces": len(orbat.reinforces())}
    ids = {u.unit_id for u in orbat.units()}
    for r in rels:
        assert r.subject in ids and r.object in ids
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_derive_orbat.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtmak.derive.orbat_relations'`

- [ ] **Step 3: 구현한다**

`vtmak/derive/orbat_relations.py`:

```python
"""R8~R12 — 편제에서 부대 사실을 만든다.

시뮬레이터가 aggregate를 CSV로 내보내는지에 의존하지 않는다. 내보내기 판이
바뀌어도 같은 결과가 나와야 하고, 부대 fact가 관측 유무에 좌우되면 데이터셋의
관계 구성이 판마다 달라진다.

시간축: partOf·supports·reinforces는 t0에 한 번 낸다. 백마고지 데이터셋은
관계를 매 관측마다 복제해 test 20,210행 중 18,189행(90%)이 앞 시각 fact의
반복이었다 — '직전에 본 fact를 다시 낸다'는 규칙 하나로 90%를 맞춘다. 그 함정을
반복하지 않는다. 소속이 실제로 바뀌면 그 시점에 다시 낸다.
"""
from __future__ import annotations

from .relations import Relation, RuleResult

# 편제표가 선언한 값. 관측에서 파생한 relations.LAYER("derived")와 섞이면
# 어느 쪽이 만든 값인지 산출물에서 되물어야 한다.
LAYER_ORBAT = "orbat"


def r8_part_of(orbat) -> RuleResult:
    """partOf(엔티티, 소대) · partOf(소대, 중대) · partOf(중대, 대대).

    체인을 접어서 partOf(엔티티, 대대)까지 내지 않는다. 2단계 전이를 규칙이
    배울 재료를 남기는 것이 이 관계를 넣는 이유다.
    """
    rels = []
    for u in orbat.units():
        for oid in u.members:
            rels.append(Relation("R8", "partOf", oid, u.unit_id,
                                 (u.unit_id,), LAYER_ORBAT))
        if u.parent:
            rels.append(Relation("R8", "partOf", u.unit_id, u.parent,
                                 (u.parent,), LAYER_ORBAT))
    return RuleResult(tuple(rels))


def r9_task_organization(orbat) -> RuleResult:
    """supports·reinforces. 원문에 근거가 없어 편제표가 선언한 값이다."""
    rels = []
    for a, b in orbat.supports():
        rels.append(Relation("R9", "supports", a, b, (a, b), LAYER_ORBAT))
    for a, b in orbat.reinforces():
        rels.append(Relation("R9", "reinforces", a, b, (a, b), LAYER_ORBAT))
    return RuleResult(tuple(rels))
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_derive_orbat.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add vtmak/derive/orbat_relations.py tests/test_derive_orbat.py
git commit -m "feat(derive): R8·R9 — 편제표에서 partOf 체인과 지원관계

백마고지 데이터셋은 주어가 부대인 fact가 0건이었다(116,680행 전수). partOf를
엔티티→소대→중대→대대로 단계마다 내 2단계 전이 재료를 남긴다.

partOf는 t0에 한 번만 낸다. 그 데이터셋은 관계를 매 관측 복제해 test의 90%가
앞 시각 fact의 반복이었다. layer=orbat으로 관측 파생과 가른다."
```

---

### Task 9: 관측에서 나오는 부대 사실 (R10~R12) + R5·R6 편제 전환

**Files:**
- Modify: `vtmak/derive/orbat_relations.py`
- Modify: `vtmak/derive/relations.py` (`unit_members`, `r6_unit_suppressed`)
- Modify: `config/derive_rules.csv`
- Test: `tests/test_derive_orbat.py` (추가), `tests/test_derive_relations.py` (수정)

**Interfaces:**
- Consumes: Task 8의 `LAYER_ORBAT`, Task 3 `Orbat.platoon_of`
- Produces:
  - `r10_unit_moves(index, orbat, rules) -> RuleResult` — `movesToward(부대, 지명)`
  - `r11_unit_occupies(index, orbat, rules) -> RuleResult` — `occupies(부대, 지명)`
  - `r12_unit_fires(index, orbat, rules) -> RuleResult` — `firesUpon(부대, 대상)`
  - `unit_members(index, rules, orbat=None)` · `r6_unit_suppressed(index, rules, orbat=None)`

- [ ] **Step 1: 임계값을 표에 더한다**

`config/derive_rules.csv` 끝에 세 줄:

```csv
R10,threshold,unit_move_ratio,0.5,"부대가 '이동 중'이라고 볼 구성원 비율. 과반을 기본으로 둔다 — 내리면 한두 명의 이동이 부대 이동으로 읽히고, 올리면 소대가 나뉘어 움직이는 국면이 통째로 빠진다. 실측으로 조정할 것"
R11,threshold,unit_occupy_ratio,0.5,"부대가 그 지명을 '점령/잔류'한다고 볼 구성원 비율. moveTo와 같은 기준을 쓴다 — 이동과 점령에 다른 임계를 주면 부대가 이동 중도 점령 중도 아닌 구간이 생긴다"
R12,threshold,unit_fire_ratio,0.34,"부대가 '사격 중'이라고 볼 구성원 비율. 사격은 이동과 달리 소수가 수행한다(직사 77건·간접 21건이 328객체에 흩어져 있다). 과반을 걸면 0건이 되므로 1/3로 둔다"
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_derive_orbat.py`에 더한다:

```python
from vtmak.derive.config import DeriveRules
from vtmak.derive.events import EventIndex
from vtmak.derive.orbat_relations import (r10_unit_moves, r11_unit_occupies,
                                          r12_unit_fires)


@pytest.fixture(scope="module")
def idx():
    return EventIndex.load(EVENTS)


@pytest.fixture(scope="module")
def rules():
    return DeriveRules.load(CFG / "derive_rules.csv")


def _unit_subject(rels, orbat):
    ids = {u.unit_id for u in orbat.units()}
    return all(r.subject in ids for r in rels)


def test_r10_subject_is_a_unit(idx, orbat, rules):
    """부대가 주어인 fact를 만든다 — 백마고지에는 0건이었다."""
    rels = r10_unit_moves(idx, orbat, rules).relations
    assert rels, "0건이면 unit_move_ratio나 moveTo 이벤트를 본다"
    assert {r.predicate for r in rels} == {"movesToward"}
    assert _unit_subject(rels, orbat)


def test_r11_occupies_a_place(idx, orbat, rules):
    rels = r11_unit_occupies(idx, orbat, rules).relations
    assert rels, "0건이면 unit_occupy_ratio나 stopAt/stayAt 이벤트를 본다"
    assert {r.predicate for r in rels} == {"occupies"}
    assert _unit_subject(rels, orbat)
    assert all(r.object.startswith("LOC_") for r in rels)


def test_r12_fires_upon_something(idx, orbat, rules):
    rels = r12_unit_fires(idx, orbat, rules).relations
    assert rels, "0건이면 unit_fire_ratio를 본다(사격은 소수가 한다)"
    assert {r.predicate for r in rels} == {"firesUpon"}
    assert _unit_subject(rels, orbat)


def test_observed_unit_facts_are_not_layered_as_orbat(idx, orbat, rules):
    """관측에서 나온 값은 편제표 선언과 다른 레이어여야 한다."""
    from vtmak.derive.orbat_relations import LAYER_ORBAT
    for res in (r10_unit_moves(idx, orbat, rules),
                r11_unit_occupies(idx, orbat, rules),
                r12_unit_fires(idx, orbat, rules)):
        assert LAYER_ORBAT not in {r.layer for r in res.relations}


def test_r6_counts_by_platoon_when_orbat_is_given(idx, orbat, rules):
    """편제를 주면 R6의 분모가 타입 접두사가 아니라 소대가 된다."""
    from vtmak.derive.relations import r6_unit_suppressed
    ids = {u.unit_id for u in orbat.units()}
    for r in r6_unit_suppressed(idx, rules, orbat=orbat).relations:
        assert r.subject in ids
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_derive_orbat.py -q`
Expected: FAIL — `ImportError: cannot import name 'r10_unit_moves'`

- [ ] **Step 4: 관측 기반 규칙을 구현한다**

`vtmak/derive/orbat_relations.py`에 더한다. 이벤트 템플릿 이름은 실측이다
(`build/events/battle.jsonl` 3,000건: `moveTo` 571 · `stopAt` 102 · `stayAt` 77 ·
`directFireAt` 77 · `indirectFireAt` 21).

```python
from collections import defaultdict


def _by_platoon(index, orbat):
    """소대 → 이벤트에 등장한 구성원. 분모는 정원이 아니라 이 수다.

    정원으로 나누면 명부 감축이 비율을 바꾼다(R6가 같은 이유로 그렇게 한다).
    """
    seen: dict[str, set] = defaultdict(set)
    for e in index.events:
        pl = orbat.platoon_of(e.actor) if e.actor else None
        if pl:
            seen[pl].add(e.actor)
    return seen


def _fold(index, orbat, ratio, templates, target_of, rule_id, predicate):
    """구성원 과반이 같은 시각·같은 대상에 대해 같은 일을 하면 부대 사실이다.

    시각을 키에 넣는다. 넣지 않으면 전 구간의 행동이 한 건으로 접혀 시간축이
    사라지고, 그 순간 백마고지처럼 '안 변하는 관계'가 된다.
    """
    seen = _by_platoon(index, orbat)
    groups: dict[tuple[str, int, str], set] = defaultdict(set)
    for e in index.events:
        if e.template not in templates:
            continue
        pl = orbat.platoon_of(e.actor) if e.actor else None
        target = target_of(e)
        if not pl or not target:
            continue
        groups[(pl, e.time_s, target)].add(e.actor)

    rels = []
    for (pl, _t, target), actors in sorted(groups.items()):
        roster = seen.get(pl) or set()
        if not roster or len(actors) / len(roster) < ratio:
            continue
        rels.append(Relation(rule_id, predicate, pl, target,
                             tuple(sorted(actors))))
    return RuleResult(tuple(rels))


def r10_unit_moves(index, orbat, rules) -> RuleResult:
    """movesToward(부대, 지명) — 구성원 과반이 같은 곳으로 갈 때."""
    return _fold(index, orbat, rules.threshold("unit_move_ratio"),
                 {"moveTo"}, lambda e: e.dst, "R10", "movesToward")


def r11_unit_occupies(index, orbat, rules) -> RuleResult:
    """occupies(부대, 지명) — 구성원 과반이 그 자리에 멈춰 있을 때."""
    return _fold(index, orbat, rules.threshold("unit_occupy_ratio"),
                 {"stopAt", "stayAt"}, lambda e: e.location, "R11", "occupies")


def r12_unit_fires(index, orbat, rules) -> RuleResult:
    """firesUpon(부대, 대상) — 구성원 다수가 같은 대상을 쏠 때.

    대상은 엔티티일 수도 지역 표기 객체일 수도 있다. 가리지 않는다 — 무엇을
    쐈는지는 대상 id가 말한다.
    """
    return _fold(index, orbat, rules.threshold("unit_fire_ratio"),
                 {"directFireAt", "indirectFireAt"}, lambda e: e.target,
                 "R12", "firesUpon")
```

- [ ] **Step 5: R5·R6가 편제를 쓰게 한다**

`vtmak/derive/relations.py` — `unit_members`와 `r6_unit_suppressed`에 `orbat=None`을 더한다. 기존 호출부(`orbat` 없이)는 그대로 돌아야 한다.

```python
def unit_members(index: EventIndex, rules, orbat=None) -> dict[str, tuple[str, ...]]:
    """R5 — 부대 → 구성원.

    편제(orbat)를 주면 소대가 부대다. 안 주면 예전대로 id 접두사(FR-INF)를
    쓴다 — 그건 정원표(roster.json) 키라 편제가 아니지만, 편제표 없이도 R6가
    돌아야 한다.
    """
    if orbat is not None:
        members: dict[str, list[str]] = defaultdict(list)
        seen: set[str] = set()
        for e in index.events:
            for oid in (e.actor, e.target, e.source_obj):
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                pl = orbat.platoon_of(oid)
                if pl:
                    members[pl].append(oid)
        return {u: tuple(v) for u, v in sorted(members.items())}

    excluded = rules.excluded_unit_codes()
    members = defaultdict(list)
    seen = set()
    for e in index.events:
        for oid in (e.actor, e.target, e.source_obj):
            if not oid or oid in seen:
                continue
            seen.add(oid)
            unit = unit_of(oid)
            if unit.split("-")[-1] not in excluded:
                members[unit].append(oid)
    return {u: tuple(v) for u, v in sorted(members.items())}
```

`r6_unit_suppressed`도 `orbat=None`을 받아 `unit_members(index, rules, orbat)`로 넘긴다. 나머지 본문은 그대로다.

> `unit_of`로 만든 부대에는 `exclude_unit_code`(FP·RT·LN·OBJ)가 필요했다. 편제 경로에서는 `orbat.platoon_of`가 정적 객체에 `None`을 주므로 그 필터가 저절로 걸린다.

- [ ] **Step 6: 통과를 확인한다**

Run: `python -m pytest tests/test_derive_orbat.py tests/test_derive_relations.py -q`
Expected: PASS. 기존 `test_derive_relations.py`의 R5·R6 기대치는 `orbat` 없이 부르므로 바뀌지 않는다.

- [ ] **Step 7: 실제 건수를 본다**

```bash
python - <<'EOF'
import json
from pathlib import Path
from vtmak.derive.config import DeriveRules
from vtmak.derive.events import EventIndex
from vtmak.derive.orbat_relations import (r10_unit_moves, r11_unit_occupies,
                                          r12_unit_fires)
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.parser import Event
from vtmak.registry import ClassMap, build_registry
evs=[Event(**{k:v for k,v in json.loads(l).items() if k!='source_line'})
     for l in open('build/events/battle.jsonl',encoding='utf-8')]
reg=build_registry(evs, ClassMap.load('config/entity_class_map.csv'), set())
ob=build_orbat(reg, OrbatConfig.load('config/orbat.json'))
idx=EventIndex.load('build/events/battle.jsonl')
ru=DeriveRules.load('config/derive_rules.csv')
for n,f in (('R10 movesToward',r10_unit_moves),('R11 occupies',r11_unit_occupies),
            ('R12 firesUpon',r12_unit_fires)):
    print(n, len(f(idx,ob,ru).relations))
EOF
```

셋 중 하나라도 0건이면 `derive_rules.csv`의 임계값을 조정하고, **왜 그 값인지를 `note` 열에 실측 건수로 적는다.**

- [ ] **Step 8: 전체 테스트 후 커밋**

Run: `python -m pytest -q`
Expected: 351 passed, 1 failed (기존 gimbal)

```bash
git add vtmak/derive/orbat_relations.py vtmak/derive/relations.py config/derive_rules.csv tests/test_derive_orbat.py
git commit -m "feat(derive): R10~R12 — 관측에서 부대가 주어인 fact

movesToward·occupies·firesUpon을 구성원 비율로 접는다. 키에 시각을 넣어
시간축이 살아 있게 한다 — 시각을 빼면 전 구간이 한 건으로 접혀 백마고지처럼
'안 변하는 관계'가 된다.

R5·R6는 편제를 주면 소대를, 안 주면 예전대로 id 접두사를 쓴다. 사격 임계는
1/3이다 — 직사 77건·간접 21건이 328객체에 흩어져 있어 과반을 걸면 0건이다."
```

---

### Task 10: 파생 산출물 스크립트

`vtmak/derive/`가 지금 어느 스크립트도 호출하지 않는 라이브러리다. 산출물로 낸다.

**Files:**
- Create: `scripts/07_derive_relations.py`
- Modify: `RUNBOOK.md`
- Test: 없음 (로직은 Task 8·9가 덮는다. 이 저장소는 스크립트를 직접 테스트하지 않는다)

**Interfaces:**
- Consumes: R1~R12 전부
- Produces: `build/derive/relations.csv` (열 `rule_id,layer,predicate,subject,object,provenance`), `build/derive/report.md`

- [ ] **Step 1: 스크립트를 쓴다**

`scripts/07_derive_relations.py`:

```python
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
from vtmak.orbat import OrbatConfig, build_orbat               # noqa: E402
from vtmak.parser import Event                                 # noqa: E402
from vtmak.registry import ClassMap, build_registry            # noqa: E402

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
    reg = build_registry(evs, ClassMap.load(CFG / "entity_class_map.csv"), set())
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
```

- [ ] **Step 2: 돌린다**

Run: `python scripts/07_derive_relations.py`
Expected: 관계 수가 찍히고 `build/derive/relations.csv`·`report.md`가 생긴다. `partOf`가 **엔티티 수 + 상위가 있는 부대 수**(328 + 65 = 393) 근처여야 하고, **부대 주어 fact가 0이 아니어야 한다** — 0이면 이 계획 전체의 목적이 달성되지 않은 것이다.

- [ ] **Step 3: RUNBOOK을 고친다**

`RUNBOOK.md`의 "전체 실행" 블록에 한 줄 더한다:

```bash
python scripts/07_derive_relations.py  # 이벤트+편제 → 파생 관계 (R1~R12)
```

"무엇을 고치면 무엇을 다시 돌리나" 표에 두 줄 더한다:

```markdown
| `config/orbat.json` | **04 → 07** |
| `config/location_codes.csv` | **04 → 05** |
```

- [ ] **Step 4: 전체 테스트 후 커밋**

Run: `python -m pytest -q`
Expected: 351 passed, 1 failed (기존 gimbal)

```bash
git add scripts/07_derive_relations.py RUNBOOK.md
git commit -m "feat(derive): 파생 관계를 산출물로 낸다

vtmak/derive/가 테스트만 있는 라이브러리였다. R1~R12를 한 파일에 내되 layer
열로 추출 정본과 합성을 가른다. 보고에 '주어가 부대인 fact' 건수를 찍는다 —
백마고지 데이터셋이 0건이었던 그 수가 이 작업의 결과다."
```

---

## 마무리 — 소급 적용 확인

스펙 §6.2가 남긴 질문에 답한다. 계획의 마지막 단계다.

- [ ] **통제점 순번이 재현되는지 본다**

```bash
python scripts/04_compile_scnx.py
python - <<'EOF'
import csv
from pathlib import Path
rows = list(csv.DictReader(
    open('build/timetable/battle_control_points.csv', encoding='utf-8-sig')))
print(f"통제점 {len(rows)}개")
for i, r in enumerate(rows, 1):
    print(f"  P{i}\t{r['code']}\t{r['loc_id']}")
EOF
```

기존 20260809 CSV에 나온 것은 `P2·P3·P4·P10·P11`이다. 위 목록의 통제점 수가
**11개 이상이고 순서가 재현되면** 그 순번으로 `place_names`를 만들어 05를 다시
돌려 소급 적용한다.

개수나 순서가 다르면 **소급하지 않는다.** 억지로 맞추면 잘못된 지명이 붙고, 그건
`P3`이 남아 있는 것보다 나쁘다. 어느 쪽이든 결론과 근거(통제점 수)를 커밋
메시지에 적는다.

- [ ] **스펙의 남은 항목을 확인한다**

스펙 §8이 남긴 것 중 이 계획이 답하지 않는 것:

- **ATP 7-100.2 인용 페이지 대조** — 논문 반영 전 (연구자)
- **성능** — 부대 67개 추가 후 VR-Forces 로딩·프레임. 무거우면 소대만(52) 또는
  중대만(13) 실재화로 줄인다. `orbat.json`의 `company_functions`를 비우면 중대가
  사라지고 소대가 전부 대대 직할이 된다
- **`Observer 2`가 인프라인가** — RUNBOOK 미결, 767행이 위치 테이블로 샌다
- **A3(Data Logger가 aggregate를 내보내는가)** — 이 계획은 답에 의존하지 않지만,
  내보낸다면 R10~R12를 관측으로 교차검증할 수 있다
