# 운영 가이드 — 혼자 시나리오를 고치고 돌리기

시스템 설명은 [`README.md`](README.md), 설계 근거는
[`../docs/superpowers/specs/2026-08-02-new-vtmak-scnx-pipeline-design.md`](../docs/superpowers/specs/2026-08-02-new-vtmak-scnx-pipeline-design.md).
이 문서는 **손으로 무엇을 어디서 고치고 무엇을 다시 돌리는가**만 다룬다.

---

## 0. 준비

- Python 3.13 (설치·가상환경 필요 없음. `pytest`만 있으면 된다)
- 항상 `new_VTMAK/` 안에서 실행한다. 경로에 공백과 한글이 있어 `conftest.py`가
  `sys.path`를 대신 넣어준다.

```bash
cd "C:\Users\user\OneDrive\문서\Cybermarine system lab\STKG\STKG_Experiments\new_VTMAK"
```

---

## 1. 전체 실행

```bash
python scripts/01_harvest_layout.py     # golden 통제점 → 지명 좌표
python scripts/02_parse_events.py       # 원문 → 이벤트    (+G1 +G0)
python scripts/03_build_timetable.py    # 이벤트 → 타임테이블 (+G2)
python scripts/04_compile_scnx.py       # 스펙 → PLN → .scnx (+G0 +G3)
python scripts/06_stkg_export.py        # CSV → STKG 관계·위치 테이블 (A단계)
```

각 단계가 찍는 줄에서 **`차단 N건`의 N이 0**이어야 다음이 의미가 있다.
차단이 있으면 그 단계에서 멈추고 파일을 쓰지 않는다.

정상일 때 나오는 모습:

```
문장 3000 · 이벤트 2999 · 객체 335
명부 감축 → 객체 87 (35개 부대) · 이벤트 896
  task 가능 80 / 정적 7
위반 16건 (차단 0건)
셀 421 · 객체 87 · G2 0건 (차단 0건)
엔티티 80 · 통제점 23 · 플랜 보유 78 · 태스크 189
→ build/scnx/battle.scnx
```

산출은 전부 `build/` 아래에 생기고, 같은 입력이면 항상 같은 바이트가 나온다.

### 1-A. STKG A단계 (`06_stkg_export.py`)

재시뮬 없이 `build/csv/*.csv`만 읽어 `build/stkg/relations.csv` ·
`build/stkg/positions.csv` · `build/stkg/report.md`를 낸다.

```bash
python scripts/06_stkg_export.py   # CSV → STKG 관계·위치 테이블 (A단계)
```

2026-08-03 실측(`build/csv/` 5개 파일 · 130,523행):

```
입력 5개 파일 · 130,523행
관계 구간 345 (기여 행 95,020) · 위치 31,198 · 제외 4,305 · 격리 0
→ build/stkg
```

- 술어별: `moves_to` 285 · `follows` 38 · `fires_at` 17 · `fired_by` 4 ·
  `takes_cover_from` 1 (`engages`·`suppresses`는 이번 CSV에 재료 없음)
- 좌표 스냅: `location` 63,099건 (100.0%), `coord` 폴백 0건
- `relations.csv`의 `object` 빈 행 0건, `object_type=entity` 중 `.oob` marking에
  없는 것 0건(7종 전부 일치)
- `fired_by`: GROUND_TRUTH 4건 관계로 확정, UAV 2의 `M933HE 1/2/3` 3건 미확정
  (해당 시각에 정합하는 박격포가 없음)
- 파싱 실패 술어 0건

**주의 — 제외 건수가 계획서의 기대치(5,072행)와 767행 다르다.** 계획서는
`Observer 1 1,624` + `Force 2,586` + `GlobalEnv 862` = 5,072를 기대했지만,
실측 원인은 `GROUND_TRUTH` CSV에 `Observer 1`(857행)과 `Observer 2`(767행)
둘 다 있는데 `vtmak/stkg/filter.py`의 `INFRA_SUBJECTS`에는 `Observer 1`만
등록돼 있다는 것이다. `Observer 2`는 좌표가 변하는(665개 서로 다른 위치)
행이라 `1 Force`류의 고정 쓰레기값과는 다르게 보이지만, `predicate`가 항상
`None`이라 사실상 위치 전용 관측 플랫폼으로 추정된다. `export.py`는
`filter.classify`를 그대로 따르므로 `Observer 2`의 767행은 제외되지 않고
위치 테이블로 들어간다(제외 4,305 = 5,072 − 767, 위치 31,198 = 30,431 + 767 —
정확히 767행만큼 서로 반대로 어긋나 총합은 여전히 130,523과 맞는다).
`filter.py`는 읽기 전용 모듈이라 여기서 고치지 않았다 — `Observer 2`를
인프라로 볼지는 확인 후 `INFRA_SUBJECTS`에 추가할지 결정할 사안이다.

---

## 2. 무엇을 고치면 무엇을 다시 돌리나

| 고친 것 | 다시 돌릴 것 |
|---|---|
| `yewon_test/` (골든 통제점·객체) | **01 → 02 → 03 → 04** |
| `config/layout_rules.json` | **01 → 02 → 03 → 04** |
| `scenario_original/scenario_v3.txt` | 02 → 03 → 04 |
| `config/roster.json` (객체 수) | 02 → 03 → 04 |
| `config/pattern_map.csv` | 02 → 03 → 04 |
| `config/weapon_ranges.csv` | 02 → 03 → 04 |
| `config/entity_class_map.csv` | 02 → 03 → 04 |
| `config/task_catalog.csv` | 04 |
| `config/dis_catalog.csv` | 04 |

`config/battlefield_layout.json`은 **생성물이다. 손으로 고치지 말 것** — 01이
덮어쓰고, 어긋나면 테스트가 잡는다.

---

## 3. 시나리오 원문 고치기

`vtmak/paths.py`의 `SCENARIO`가 가리키는 파일 **하나**가 입력이다. 원문 파일을
바꾸면 **그 한 줄만** 고친다 — 스크립트와 테스트가 같은 상수를 본다.

```python
SCENARIO = ROOT / "scenario_original" / "scenario_ver70.txt"
``` 한 줄에 1~3문장을
`다. `로 이어 쓴다. **파서는 아래 20가지 문장 틀만 안다.** 틀을 벗어나면 G1이
`C1.1 미매칭 문장`으로 잡는다. 아래를 그대로 복사해서 값만 바꾸는 것이 안전하다.

### 배치·상태

```
00:00에 **US Army M4(FR-INF-001, 방어 보병 1)**은/는 남측 제1방어선에 위치한다
**US Army M4(FR-INF-001)**의 초기 상태는 대기 상태이다
**US Army M4(FR-INF-001)**은/는 대기 상태에서 기동 상태로 전환한다
**US Army M4(FR-INF-001)**은/는 제압 상태를 유지한다
06:50에 **US Army M4(FR-INF-017, 방어 보병 17)**은/는 남측 제1방어선에 정지한다
06:05에 **US Army M4(FR-INF-001, 방어 보병 1)**은/는 남측 제1방어선 전방에 잔류한다
이후 EN-INF-001에는 일반 이동·사격 task를 부여하지 않는다
```

### 이동 — 행동 이름 7종

```
01:00에 **Russian Soldier AK47(EN-INF-001, 제1제대 보병 1)**은/는 적 북측 집결지에서 적 북측 접근로을/를 향해 공격 대형 이동을 수행한다
```

`공격 대형 이동` 자리에 들어갈 수 있는 말:
`지상 이동` · `방어 위치 이동` · `방어선 재편성 이동` · `후퇴 이동` ·
`감시 위치 이동 및 관측 방향 유지` · `보급 이동 및 정차`

### 사격·피격

```
03:20에 **US Army M4(FR-INF-001, 방어 보병 1)**은/는 중앙 킬존 남측에서 **Russian Soldier AK47(EN-INF-001, 제1제대 보병 1)**을/를 향해 직접사격을 수행한다
02:00에 **MO-120RT-61 Mortar(FR-MORT-001, 박격포 1)**은/는 아군 박격포진지에서 **포병진지(EN-FP-001, 적 자주포 사격진지)**을/를 향해 간접사격을 수행한다
01:40에 **MO-120RT-61 Mortar(FR-MORT-001, 박격포 1)**은/는 아군 박격포진지에서 **포병진지(EN-FP-001, 적 자주포 사격진지)**을/를 향해 포신 정렬 후 간접사격 준비을 수행한다
03:21에 **Russian Soldier AK47(EN-INF-001, 제1제대 보병 1)**은/는 중앙 킬존에서 **US Army M4(FR-INF-001, 방어 보병 1)**의 직접사격에 피격된다
02:01에 **포병진지(EN-FP-001, 적 자주포 사격진지)**은/는 **MO-120RT-61 Mortar(FR-MORT-001, 박격포 1)**의 사격으로 주변 탄착을 받는다
공격자 객체는 FR-MORT-001이고, 목표 객체는 EN-FP-001이다
피격 원천 객체는 FR-MORT-001이고, 피격 대상 객체는 EN-FP-001이다
목표 구역은 적 포병진지이다
```

### 지켜야 할 것

- **모델 이름은 VR-Forces 엔티티 이름이어야 한다.** `entity_class_map.csv`에 있는
  26종이 그 목록이고, 전부 `VR-Forces catalog/VRFEntityCatalog.pdf`의 번호 절
  (`1.4.x` / `1.5.x`)에 실린 이름과 일치한다. 카탈로그 뒤쪽 부록의 **3D 모델
  파일 이름**(`M109A5_SP_Howitzer`처럼 밑줄 표기)은 엔티티 이름이 아니다.
  2026-08-03 실측: `Russian Soldier AK74`(카탈로그에 없음), `M109A5 SP Howitzer`,
  `MIM-104 Patriot Remote Launcher`, `M1028 FMTV Cargo Truck`,
  `M1083A1 FMTV Cargo Truck` 다섯이 이 함정에 걸려 G3가 차단했다.
- **시각** `MM:SS`. 시각 없는 문장은 바로 앞 문장의 시각을 잇는다.
- **객체 표기** `**모델명(객체ID, 역할)**`. 모델명은 `config/entity_class_map.csv`에
  있는 이름과 **글자 그대로** 같아야 한다(공백·하이픈은 무시된다).
- **객체 ID** `진영-부대-번호` (예: `FR-INF-001`). 부대 이름이 `roster.json`의
  정원표 열쇠가 되므로, **새 부대를 만들면 정원표에도 넣어야 한다**.
- **지명**은 `config/battlefield_layout.json`에 있는 이름만 쓴다(공백 무시).
  새 지명은 §4-B 참고.
- 피격 문장의 지명이 **교전 거리의 정본**이다. 사수 위치는 사격 문장의
  `~에서`가, 표적 위치는 피격 문장의 `~에서`가 결정한다.

**교전을 새로 만들 때는 4문장이 한 벌이다** — 사격 · 피격 · `공격자 객체는…` ·
`피격 원천 객체는…`. 한 문장만 빼먹으면 사거리 판정이나 태스크 생성이 어긋난다.

---

## 4. 자주 하는 수정

### A. 객체 수 조절 (VR-Forces가 버벅일 때)

`config/roster.json`의 `target_entities` 하나만 바꾼다.

```json
"target_entities": 80,     // 60, 50 … 로 내리면 된다
"min_per_type": 2,         // 엔티티 타입당 최소 보유. 52 밑으로 갈 땐 1로
"min_per_unit": 1,         // 부대당 최소 보유
```

정원표(`quota`)는 **상한**이라 이보다 많이 뽑지 않는다. 그 안에서 task를 가장
많이 살리는 조합을 자동으로 고른다. 02부터 다시 돌린다.

### B. 지명 추가·이동

**정확한 자리를 아는 지명**은 VR-Forces에서 `yewon_test`를 열고 **통제점을 찍고
원문 표기 그대로 이름을 준다**(예: `중앙 킬존`). 저장한 뒤 `01`을 돌리면 좌표가
따라온다. 공백은 무시되므로 `중앙 킬존` = `LOC_중앙킬존`이다.

**다른 지점 기준으로 밀면 되는 지명**은 `config/layout_rules.json`의 `derived`에
규칙을 쓴다.

```json
"LOC_새지명": { "base": "LOC_중앙킬존", "dir": "북", "dist_m": 300 }
"LOC_새지명": { "base": "LOC_중앙계곡", "toward": "LOC_남측제1방어선", "dist_m": 250 }
```

`dir`는 **전장 축 기준**이다(`북` = 적 방향). 실제 나침반이 아니다 — 골든에서
동측능선이 실제 서쪽에 찍혀 있다. 01부터 다시 돌린다.

골든 이름과 원문 표기가 다르면 `aliases`에 한 줄 넣는다.

### C. 새 엔티티 모델 추가

**골든에 그 모델 객체를 1개 놓는 것이 먼저다.** DIS와 레코드 원본을 거기서
가져오기 때문에, 골든에 없는 모델은 G3 `C3.2`가 차단한다. 그다음 세 파일:

| 파일 | 넣을 것 |
|---|---|
| `dis_catalog.csv` | 모델명, DIS 7튜플(골든 실측) |
| `entity_class_map.csv` | 모델명, type_group, **무기 이름** |
| `weapon_ranges.csv` | 모델명, 직접/간접 최소·최대 사거리 |

무기 이름은 골든 `.oob`의 `(display-name ...)` 값이다. 확인하는 법:

```bash
python -c "import sys;sys.path.insert(0,'.');from pathlib import Path;from vtmak.scnx.golden import Golden;from vtmak.scnx.pack import ensure_golden;g=Golden.load(ensure_golden(Path('yewon_test')));print(sorted(g.weapons_of((1,1,225,4,3,6,0))), sorted(g.munitions_of((1,1,225,4,3,6,0))))"
```

간접사격은 `<display-name>:<탄약>` 형식이다(`Indirect-Fire-Gun:M107-155mm`).
틀리면 G3 `C3.8`이 차단한다 — **그 무기가 없는 객체는 사격을 실행하지 못한다.**

### D. 새 행동(태스크) 추가

- **이동 행동 이름만 추가**: `pattern_map.csv`에 `kind=move_action` 한 줄.
- **`.pln` 태스크 종류 추가**: `task_catalog.csv`에 `(type_group, 행동)` 행을 넣고
  S-expression은 **골든 `.pln`에서 그대로 수확**해 값만 자리표시자로 바꾼다
  (`X Y Z`, `TARGET_UUID`, `ROUTE_UUID`). 골든에 없는 문법은 쓰지 않는다.
- **문장 틀 자체를 새로 만들기**: `vtmak/parser.py`의 `TEMPLATES`를 고쳐야 한다
  (코드 수정). 여기까지 오면 테스트를 먼저 쓰는 편이 빠르다.

### E. 사거리 조정

`config/weapon_ranges.csv`. `min_severity=REPORT`면 최소사거리 미달을 막지 않고
알리기만 한다(현재 155mm 3종이 그렇다).

---

## 5. 게이트 읽는 법

`[게이트/코드/심각도] 내용` 형식으로 찍힌다. **`BLOCK`만 파이프라인을 멈춘다.**
`REPORT`는 사람이 알아야 하지만 산출을 막지 않는 사실이다.

| 코드 | 뜻 | 보통의 대처 |
|---|---|---|
| `C0.1` | 최소사거리 미달 | 진지를 멀리 옮기거나 `min_severity` |
| `C0.2` | 최대사거리 초과 | 진지를 가깝게 |
| `C0.3` | 무기체계 미확인 | Patriot 2종. 확인되면 `unverified` 해제 |
| `C0.4` | 사격 능력 없는 모델 | 원문에서 그 객체의 사격 문장을 뺀다 |
| `C0.7` | 파생 지점 — 지형 미확인 | GUI에서 물·급경사인지 눈으로 확인 |
| `C1.1` | 문장 미매칭 | §3의 문장 틀과 대조 |
| `C1.2` | 레이아웃에 없는 지명 | §4-B |
| `C1.3` | 사전에 없는 객체 | 원문의 객체 표기 오타 |
| `C2.1` `C2.2` | 플랜 없는 객체 | `task_catalog`에 그 (type_group, 행동)이 없다 |
| `C3.1` `C3.2` | DIS 없음 / 골든 레코드 없음 | §4-C |
| `C3.3` | 좌표 미할당 | 지명이 레이아웃에 없다 |
| `C3.4` `C3.7` | uuid 중복 / 참조 미해소 | 코드 결함. 그대로 알려줄 것 |
| `C3.5` | 태스크 생성 실패 | 대개 미분류(Patriot) |
| `C3.6` | 괄호 불균형 | `task_catalog`의 S-expression 오타 |
| `C3.8` | 그 모델에 없는 무기 | §4-C |

---

## 6. VR-Forces에서 열기

1. `build/scnx/battle.scnx`를 VR-Forces가 시나리오를 읽는 폴더로 복사한다.
2. 지형은 **Ala Moana**여야 한다(`.scn`이 `..\userData\terrains\Ala Moana.mtf`를
   가리킨다).
3. **Ground Clamping을 켠다.** `Settings → Ground Clamping`, Cutoff Distance
   Scale을 최대로. 고도는 지명 지형점 값(1~95 m)이라 0은 아니지만, jitter로
   흩은 자리까지 맞지는 않는다.

---

## 7. 점검 도구

```bash
python -m pytest tests/ -q                 # 123개. 고치기 전후로 항상
python scripts/05_scnx_timetable.py        # 실제 .scnx를 되읽어 객체별 행동표
```

`05`는 **스펙이 아니라 산출물을 믿는 표**다. `in_scnx=N`인 줄이 있으면
"이벤트는 있는데 태스크가 안 만들어진" 객체다.

---

## 8. 막혔을 때

| 증상 | 먼저 볼 곳 |
|---|---|
| 고쳤는데 결과가 그대로 | **차단된 실행은 파일을 안 쓴다.** `build/`에 이전 산출물이 남아 있다. `ls -l build/scnx/battle.scnx`로 시각 확인, 확실히 하려면 `rm -rf build` 후 재실행 |
| `사격 능력 없는 모델`(C0.4) | 모델 이름이 `weapon_ranges.csv`에 없다. 대개 원문 모델명이 카탈로그 이름이 아니다 |
| `G1 차단` | 방금 고친 문장. §3의 틀과 글자 단위로 대조 |
| `G0 차단` | 두 지명 사이 거리. `01` 출력의 좌표와 `weapon_ranges.csv` |
| `G3 차단` | 대개 `C3.2`(골든에 없는 모델) 또는 `C3.8`(없는 무기) |
| VR-Forces가 무겁다 | `roster.json`의 `target_entities`를 내린다 |
| 객체가 가만히 있다 | `05`로 그 객체에 태스크가 있는지, 무기 이름이 맞는지 |
| 객체가 땅속·공중 | Ground Clamping이 꺼져 있다 |
| 객체가 물 위에 있다 | 그 지명이 파생 지점인지 확인(`C0.7`), 골든에서 다시 찍는다 |

미해결로 남아 있는 것 두 가지는 README의 "좌표" 절과 "검증 게이트" 절에 적혀
있다 — 155mm 최소사거리 미달 8건, 파생 지점 지형 미확인 6건.
