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

시나리오 파일(`.scnx`)은 **01→04**에서 나온다. 05·06은 VR-Forces를 돌린
**뒤에** 그 산출 CSV를 처리하는 단계라, 시나리오만 다시 만들 때는 필요 없다.

```bash
python scripts/01_harvest_layout.py     # golden 통제점 → 지명 좌표
python scripts/02_parse_events.py       # 원문 → 이벤트    (+G1 +G0)
python scripts/03_build_timetable.py    # 이벤트 → 타임테이블 (+G2)
python scripts/04_compile_scnx.py       # 스펙 → PLN → .scnx (+G0 +G3)
python scripts/07_derive_relations.py   # 이벤트+편제 → 파생 관계 (R1~R12)
```

각 단계가 찍는 줄에서 **`차단 N건`의 N이 0**이어야 다음이 의미가 있다.
차단이 있으면 그 단계에서 멈추고 파일을 쓰지 않는다.

정상일 때 나오는 모습(2026-08-07 실측):

```
golden 통제점 23개 수확 (yewon_test)
→ config\battlefield_layout.json · 지명 29개 (golden 23 + 파생 6)
문장 3000 · 이벤트 3000 · 객체 335
명부 감축 없음 → 객체 335 (35개 부대) · 이벤트 3000
  task 가능 328 / 정적 7
위반 12건 (차단 0건)
셀 1600 · 객체 335 · G2 0건 (차단 0건)
엔티티 328 · 통제점 11 · 고정 객체 8 · 플랜 보유 322 · 태스크 956
  고정(규모 불변): UAV 1@405m↻적포병진지×8바퀴[관측 보고 켜기+순찰 비행] … · 순찰로 4
→ build/scnx/battle.scnx
```

**`명부 감축 없음`이 정상이다.** `roster.json`의 `quota`를 원문 구성과 같게
두어 감축이 아무것도 더 버리지 않게 해 뒀다 — 감축을 두 군데서 하면 어느 쪽이
줄인 건지 알 수 없기 때문이다. VR-Forces가 무거우면 §4-A로 내린다.

산출은 전부 `build/` 아래에 생기고, 같은 입력이면 항상 같은 바이트가 나온다.

### 1-A. VR-Forces를 돌린 뒤 (`05` · `06`)

시뮬레이터에서 뽑은 전역·UAV별 CSV를 `build/csv/`에 넣은 다음에 돈다.

```bash
python scripts/05_data_postprocessing.py   # CSV 후처리 → build/stkg/*_annotated.csv
python scripts/06_evaluate_dataset.py      # 후처리 산출물 평가 (E1·E2·E4~E7)
```

- **05**는 입력 파일 하나당 출력 파일 하나다. 전역(`ground_truth`)과 드론
  (`UAV n`)을 합치지 않는다 — 전역은 정답이고 드론은 관측이며 시각대도 다르다.
  열은 내보내기가 준 것을 순서까지 그대로 두고 `predicate`를 정규형으로 바꿔
  `object`를 채울 뿐이다. **행 회계가 안 맞으면 종료 코드 1로 실패한다.**
- **06**은 원문(`vtmak.paths.SCENARIO`)을 정본으로 삼아 7개 항목을 PASS/FAIL로
  낸다. 중간 산출물(timetable 등)은 기준이 아니라 검사 대상이다. 특정 빌드를
  보려면 `--stamp 20260809_175237`처럼 준다(05도 `--stamp`를 받는다).

**내보내기 열은 판마다 바뀐다.** 그래서 열 목록을 코드에 못박지 않는다 —
입력 헤더를 그대로 물려받아 낸다. 이름을 표준형으로 맞추는 규칙은
`vtmak/stkg/schema.py` 한 곳에 있고 05와 06이 같이 쓴다. 지금까지 본 판:

| 판 | 열 |
|---|---|
| 20260803 | 8열. 끝이 `CID` |
| 20260804 | 이름을 바꾸면서 `subject`와 `object`의 **뜻까지 맞바꿈** |
| 20260809 | `CID`가 빠지고 상태 열 10개가 붙어 17열 (`force`, `tracking_id`, `uuid`, `entity_type`, `damage`, `smoke`, `flaming`, `mobility_kill`, `firepower_kill`, `suppression_level`) |

20260809판에서 술어도 둘 늘었다. `Fire Weapon`은 **유일하게 내보내기가
`object` 열에 표적을 미리 채워 주는** 술어라(실측 GT 650행) 우리가 덮어쓰지
않고 그대로 통과시킨다. `Wait-Duration`은 대상이 없는 태스크다.

통제점(`P1`~`P11`, `Waypoint 1`)은 지우지 않되 **객체로 세지 않는다.**
시나리오 원문에 없고 물리 객체도 아닌, 태스크가 가리키는 자리다. 판정은
`vtmak/stkg/locate.py`의 `is_place`가 하고 05의 집계와 06의 대조가 같이 쓴다.

시뮬레이터 인프라 객체는 `vtmak/stkg/filter.py`의 `INFRA_SUBJECTS`가 지운다
(`1~3 Force` · `Observer 1` · `Observer 2` · `GlobalEnv 1`). `Observer 2`는
좌표가 변해 실제 객체처럼 보이지만 `predicate`가 항상 `None`인 위치 전용
관측 플랫폼이라 인프라로 넣었다.

---

## 2. 무엇을 고치면 무엇을 다시 돌리나

| 고친 것 | 다시 돌릴 것 |
|---|---|
| `yewon_test/` (골든 통제점·객체) | **01 → 02 → 03 → 04** |
| `config/layout_rules.json` | **01 → 02 → 03 → 04** |
| `scenario_original/scenario.txt` | 02 → 03 → 04 |
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
DEFAULT_SCENARIO = ROOT / "scenario_original" / "scenario.txt"
SCENARIO = Path(os.environ.get("VTMAK_SCENARIO") or DEFAULT_SCENARIO)
```

다른 원문으로 한 번만 돌려보려면 파일을 고칠 것 없이 환경변수를 준다 —
`VTMAK_SCENARIO=...` 가 `DEFAULT_SCENARIO`를 덮는다.

원문은 한 줄에 1~3문장을 `다. `로 이어 쓴다. **파서는 아래 16가지 문장 틀만 안다**
(`vtmak/parser.py`의 `TEMPLATES`). 틀을 벗어나면 G1이
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
"target_entities": 328,    // 현재값. 300, 200 … 로 내리면 된다
"min_per_type": 2,         // 엔티티 타입당 최소 보유. 52 밑으로 갈 땐 1로
"min_per_unit": 1,         // 부대당 최소 보유
```

정원표(`quota`)는 **상한**이라 이보다 많이 뽑지 않는다. 그 안에서 task를 가장
많이 살리는 조합을 자동으로 고른다. 02부터 다시 돌린다.

현재 `quota`의 합이 원문 구성과 같아서 감축이 아무것도 버리지 않는다(§1의
`명부 감축 없음`). `target_entities`를 내리는 순간 상한으로 동작하기 시작한다.

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

`config/weapon_ranges.csv`. `min_severity=REPORT`면 최소사거리 미달이 **G0를**
막지 않고 알리기만 한다(현재 155mm 3종 + MO-120RT-61 박격포). 심각도와 무관하게
**미달 사격은 `.pln`에 태스크로 나가지 않는다** — VR-Forces가 실제로 거부하는
것이 확인됐다(2026-08-04 `vrfSim.log`). 사격을 살리고 싶으면 표를 고칠 게 아니라
§F로 진지를 물려야 한다.

### F. 진지를 물려 최소사거리를 확보하기

`config/layout_rules.json`의 `relocate`에 지명·축 방위·거리를 적고
`python scripts/01_harvest_layout.py`를 다시 돌린다.

```json
"relocate": { "LOC_아군포병진지": { "dir": "남", "dist_m": 1000, "note": "..." } }
```

`dir`은 전장 축 기준이다(`북` = 적 방향, `남` = 아군 방향). 옮긴 점은
`src=relocated`가 되어 `C0.7`로 보고된다 — **golden이 주던 육지 보증이 없으니
GUI에서 물·급경사인지 반드시 눈으로 확인할 것.** 파생 지점의 `base`가 옮겨진
지명이면 파생 지점도 따라 움직인다.

### G. 어떤 모델이 어떤 task를 못 하는지 등록하기

VR-Forces가 `No controller or Controller is disabled, unable to carry out task X`를
찍으면 그 모델은 그 task의 컨트롤러가 없는 것이다. `config/entity_class_map.csv`의
**`unsupported_tasks`** 열에 task-type을 `;`로 나눠 적으면 그 모델에는 태스크를
만들지 않는다. 같은 `type_group`이라도 모델마다 다르므로(T-72는 `find_cover`
실패, T-80은 성공) 그룹이 아니라 모델에 적는다. `note`에 실패/보유 수를 같이
남길 것 — 근거 없는 항목이 쌓이면 시나리오가 소리 없이 비어 간다.

---

## 5. 게이트 읽는 법

`[게이트/코드/심각도] 내용` 형식으로 찍힌다. **`BLOCK`만 파이프라인을 멈춘다.**
`REPORT`는 사람이 알아야 하지만 산출을 막지 않는 사실이다.

| 코드 | 뜻 | 보통의 대처 |
|---|---|---|
| `C0.1` | 최소사거리 미달 | §4-F로 진지를 물린다. 그대로 두면 그 사격은 태스크가 안 나간다 |
| `C0.2` | 최대사거리 초과 | 진지를 가깝게 |
| `C0.3` | 무기체계 미확인 | Patriot 2종. 지상 간접사격은 불가로 확인됐다(§4-G) |
| `C0.4` | 사격 능력 없는 모델 | 원문에서 그 객체의 사격 문장을 뺀다 |
| `C0.7` | 파생·이동 지점 — 지형 미확인 | GUI에서 물·급경사인지 눈으로 확인 |
| `C1.1` | 문장 미매칭 | §3의 문장 틀과 대조 |
| `C1.2` | 레이아웃에 없는 지명 | §4-B |
| `C1.3` | 사전에 없는 객체 | 원문의 객체 표기 오타 |
| `C2.1` `C2.2` | 플랜 없는 객체 | `task_catalog`에 그 (type_group, 행동)이 없다 |
| `C3.1` `C3.2` | DIS 없음 / 골든 레코드 없음 | §4-C |
| `C3.3` | 좌표 미할당 | 지명이 레이아웃에 없다 |
| `C3.4` `C3.7` | uuid 중복 / 참조 미해소 | 코드 결함. 그대로 알려줄 것 |
| `C3.5` | 태스크 미저작 | `REPORT`면 일부러 뺀 것(§4-F·§4-G). `BLOCK`이면 결함 |
| `C3.6` | 괄호 불균형 | `task_catalog`의 S-expression 오타 |
| `C3.8` | 그 모델에 없는 무기 | §4-C |

---

## 6. VR-Forces에서 열기

1. `build/scnx/battle.scnx`를 VR-Forces가 시나리오를 읽는 폴더로 복사한다.
2. 지형은 **Ala Moana**여야 한다(`.scn`이 `..\userData\terrains\Ala Moana.mtf`를
   가리킨다).
3. **Ground Clamping을 켠다.** `Settings → Ground Clamping`, Cutoff Distance
   Scale을 최대로. 고도는 지명 지형점 값(1~95 m)이라 0은 아니지만, 대형으로
   흩은 자리까지 맞지는 않는다 — 지명 중심에서 최대 90 m대까지 벌어진다.

---

## 7. 점검 도구

```bash
python -m pytest -q                        # 297개. 고치기 전후로 항상
```

`.scnx`를 되읽어 객체별 행동표를 내던 `05_scnx_timetable.py`는 없어졌다.
산출물을 직접 확인하려면 §8 끝의 스니펫처럼 `.scnx`(ZIP)에서 `battle.pln` ·
`battle.oob`를 열어 센다 — **스펙이 아니라 산출물을 믿는 것이 요점이다.**

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
| 객체가 가만히 있다 | 04 출력의 `플랜 보유` 수와 `.pln`을 직접 열어(§8 스니펫) 그 객체에 태스크가 있는지, 무기 이름이 맞는지 |
| 객체가 땅속·공중 | Ground Clamping이 꺼져 있다 |
| 객체가 물 위에 있다 | 그 지명이 파생·이동 지점인지 확인(`C0.7`), 골든에서 다시 찍는다 |
| `No controller ...` 오류 | 그 (모델, task) 조합을 §4-G에 등록한다 |
| `less than min range` 오류 | §4-F로 진지를 물린다 |

**AI Enabled = No로 두는 것이 정상이다.** 매뉴얼 34.3대로 충돌회피·자동사격·
피격반응만 꺼지고 task는 그대로 돈다(2026-08-04 실측: 328객체 중 294객체가
AI Off 상태로 오류 없이 수행). 켜면 계획에 없는 교전이 일어나 시나리오가 일찍
끝난다. **2026-08-05부터 생성기가 끈다** — 손으로 끌 필요가 없다. 다시 켜려면
`vtmak/scnx/writer.py`의 `AI_ENABLED_DEFAULT`를 바꾼다.

**새 task를 매핑하려면 CSV 두 줄이다.** `config/pattern_map.csv`에 원문
문장 종류 → `task_kind` 한 줄, `config/task_kinds.csv`에 그 `task_kind`의
참조 필드·사거리 종류·행동 후보 한 줄. 행동 이름은 `config/task_catalog.csv`에
있어야 한다 — 없으면 G3의 C3.5가 `BLOCK`으로 막는다(조용히 안 빠진다).

상태전이로 매핑하려면 `pattern_map.csv`의 `kind`를 `state_transition`으로,
`key`를 `<이전 상태>><다음 상태>`로 쓴다. 다만 상태전이 대부분은 같은 시각
같은 객체의 task 이벤트와 중복이다 — 붙이기 전에 짝이 있는지 확인한다.

**짝이 있다고 자동으로 탈락은 아니다.** 확인할 질문은 "짝이 있는가"가 아니라
"그 둘이 같은 행위를 말하는가, 서로 다른 두 행위를 말하는가"다. 짝이 진짜
같은 행위의 중복 서술일 때만 버린다. 실제 예: `사격 준비 대기 → 사격 준비`는
같은 시각·같은 객체·같은 원문 줄의 `aimAt`과 21/21 전부 짝이 있지만, 포신
정렬(`aimAt`)과 사격위치 확보(이 전이)는 서로 다른 행위라 둘 다 task로
남겼다(2026-08-05, 근거는 `config/pattern_map.csv`의 해당 행 `note`).

**새 task 종류를 넣은 다음에는 측정 라운드를 돈다.** 1차 저작 → VR-Forces
실행 → `vrfSim.log`에서 `No controller`가 난 (모델, task) 조합을 모아
`config/entity_class_map.csv`의 `unsupported_tasks`에 적는다 → 재저작.
1차 런은 오류가 많은 것이 정상이다. 실패 후보는 견인 박격포·ZPU 계열의
`find_firing_position`과 Patriot 계열이다.

**`wait-duration`의 60초는 값을 고를 수 있다.** `config/task_catalog.csv`의
`대기` 행(보병-소총·보병-RPG·차량/장갑차) `PLN_문법`에 박힌
`seconds-to-wait` 리터럴이 정본이다 — 코드가 아니라 그 칸을 고친다. 60초가
안전한 이유는 측정으로 확인했다: 179건의 대기가 객체마다 최대 1개씩만
붙어(2026-08-05 실측, `spec.entity_plans` 기준 엔티티당 wait 최댓값 1) 같은
객체 안에서 대기가 겹쳐 쌓이지 않는다.

**통제점이 7개 생겼다(2026-08-05).** 로딩이 눈에 띄게 느려지면
`config/pattern_map.csv`의 `사격 준비 대기>사격 준비` 행을 `noop`으로 되돌리면
통제점도 같이 사라진다.

**UAV는 담당 지명 둘레의 순찰로를 돈다(2026-08-06 개편 → 2026-08-07 교체).**
`orbit_object`는 폐기했다 — 그 태스크로는 실제로 움직이지 않아 지명 둘레에
찍은 **순찰로를 `move-along`으로 도는** 방식으로 바꿨다(UAV당 8바퀴).
무엇을 어떻게 볼지는
전부 `config/fixed_objects.json` 한 장이 정한다 — 선회 중심 지명(`orbit_centers`)
· 반경과 회전 방향(`orbit`) · 고도(`flight`) · 짐벌(`gimbal`). 근거와 실측은
[설계 스펙](../docs/superpowers/specs/2026-08-06-uav-placement-behavior-design.md).

| UAV | 선회 중심 | 왜 거기인가 |
|---|---|---|
| 1 | `LOC_적포병진지` | `fired_by` 78%(2,303행)의 최대밀집에서 14 m |
| 2 | `LOC_아군포병진지` | `FFE-on-Location` 69%(1,500행)에서 22 m |
| 3 | `LOC_적북측접근로` | `Follow-Entity` 56%(40,788행) + `find_cover`에서 4 m |
| 4 | `LOC_중앙킬존` | 광역 보완 |

바꾸면 04만 다시 돌리면 된다. 짐벌 하방각은 적지 않는다 —
`-atan(altitude_agl_m / radius_m)`으로 나오므로 고도나 반경을 고치면 따라온다.
기본값(400 m / 1,000 m)에서 -21.80°다.

저작 결과를 눈으로 확인하는 법:

```bash
python - <<'PY'
import re, zipfile
z = zipfile.ZipFile("build/scnx/battle.scnx")
pln = z.read("battle.pln").decode("utf-8", "replace")
oob = z.read("battle.oob").decode("utf-8", "replace")
print("관측보고 Set", pln.count("set-spot-reporting-request"), "(4여야 함)")
print("순찰로      ", len(re.findall(r'marking-text "UAV\dRTE"', oob)), "(4여야 함)")
print("폐기 Task   ", pln.count('task-type "orbit_object"'), "(0이어야 함)")
print("치환 누락   ", pln.count("ORBIT_TARGET_UUID"), pln.count("ROUTE_UUID"), "(둘 다 0)")
print("짐벌 하방각 ", sorted(set(re.findall(r"\(aiming-elevation (-?[\d.]+)\)", oob))))
PY
```

2026-08-07 실측: 관측보고 4 · 순찰로 4 · 폐기 Task 0 · 치환 누락 0 0 ·
하방각 `-0.380506`(= -21.80°) 4기. `move-along`은 UAV 전용이 아니므로
(전체 32건) 그 수를 UAV 확인에 쓰지 말 것 — 순찰로는 `UAV<n>RTE` 표식으로 센다.

**막히면 여기부터 의심한다.**

- UAV가 안 움직인다 → 먼저 `순찰로 4`와 `폐기 Task 0`을 확인한다. `orbit_object`가
  0이 아니면 옛 저작이 남은 것이다. 순찰로는 있는데 안 돌면 `vrfSim.log`에서
  `move-along` 컨트롤러 오류를 본다.
- 관측이 여전히 드물다 → 순서대로 `orbit.radius_m`(순찰로 반경) →
  `flight.altitude_agl_m` → `gimbal.azimuth_rad`를 조정한다. 셋 다 config 한
  줄이고 코드는 안 고친다.
- UAV 1이 안 뜬다 → 종전 자리에서 2,629 m 남하했다. 지형 경계를 벗어났으면
  `orbit_centers`의 UAV 1을 안쪽 지명으로 바꾼다.

미해결로 남아 있는 것은 README의 "좌표" 절과 "검증 게이트" 절에 적혀 있다 —
최소사거리 미달 2건(중앙 킬존), 지형 미확인 8건(파생 6 + 이동 2).
