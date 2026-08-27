## 프로젝트 개요

시간대별 전투 시나리오 원문을 구조화된 이벤트와 객체별 타임테이블로 변환하고, 이를 기반으로 VR-Forces에서 실행 가능한 `.scnx` 파일을 자동 생성하는 프로젝트임

시뮬레이션 실행 후에는 전역 및 UAV별 CSV를 후처리하여 비어 있는 `object` 정보를 보완하고 STKG 구축에 활용함

```text
시나리오 원문
→ 전장 좌표 준비
→ 이벤트 변환
→ 객체별 타임테이블 생성
→ VR-Forces .scnx 생성
→ 시뮬레이션 실행 및 CSV 추출
→ CSV 후처리
```

## 1. 시나리오 원문 준비

- 입력 파일: `scenario_original/scenario.txt`
- 원문에는 시각, 객체 ID, 모델, 역할, 위치, 행동, 대상, 상태 변화 정보가 포함됨

## 2. 전장 지명 좌표 준비

시나리오에 등장하는 장소를 VR-Forces 지형 위에 waypoint로 지정한 뒤 실제 위도·경도·고도를 추출함

Ala Moana 지형의 전술적 위치를 시스템이 자동으로 알 수 없으므로, 남측 제1방어선·중앙 킬존·적 포병진지 등 주요 장소의 중심점을 사람이 먼저 지정해야 함

```bash
python scripts/01_harvest_layout.py
```

출력:

```text
config/battlefield_layout.json
```

## 3. 원문 → 이벤트 변환

원문을 문장 단위로 읽고 시각, 주체, 위치, 대상, 행동, 상태 정보를 추출하여 구조화된 이벤트로 변환함

```bash
python scripts/02_parse_events.py
```

출력:

```text
build/events/battle.jsonl
```

예시:

```json
{
  "event_id": "E00001",
  "time_s": 0,
  "predicate": "locatedAt",
  "actor": "FR-INF-001",
  "actor_class": "US Army M4",
  "actor_role": "방어 보병 1",
  "location": "LOC_남측제1방어선"
}
```

이 단계에서 다음 작업도 함께 수행함.

- 원문에 등장하는 객체를 기반으로 객체 사전 자동 생성
- G0: `weapon_ranges.csv`를 이용한 무기 사거리 검증
- G1: 템플릿 미매칭 문장, 누락 객체·지명 검증

## 4. 객체별 타임테이블 생성

이벤트를 객체별·시간 구간별로 재구성하여 위치와 상태 변화를 확인할 수 있도록 함

```bash
python scripts/03_build_timetable.py
```

출력:

```text
build/timetable/battle.csv
```

G2에서는 task 수행이 가능한 객체가 실제 행동 이벤트를 하나 이상 가지는지 확인함

## 5. VR-Forces 시나리오 생성

이벤트, 객체 사전, 좌표, DIS 정보, task 카탈로그, golden 객체 레코드를 이용하여 VR-Forces용 시나리오를 생성함

```bash
python scripts/04_compile_scnx.py
```

출력:

```text
build/scnx/battle.scnx
```

G3에서는 다음 항목을 확인함.

- 모든 엔티티의 DIS 존재 여부
- golden에 동일 DIS 엔티티가 있는지
- 좌표·UUID·PLN 문법의 정상 여부
- task가 참조하는 객체와 템플릿의 존재 여부

## 6. 데이터 후처리

VR-Forces에서 추출한 전역 및 UAV별 CSV를 `build/csv/`에 저장한 뒤 후처리를 수행함

```bash
python scripts/05_data_postprocessing.py
```

출력:

```text
build/stkg/*_annotated.csv
build/stkg/report.md
```

전역과 UAV 데이터는 합치지 않고 입력 파일별로 따로 처리함. 원본 행은 유지하며, `predicate` 문자열에 포함된 대상 정보를 이용해 `object`를 채움

| 원본 | 후처리 |
|---|---|
| `Move to {좌표}` | `predicate=move to`, `object=지명` |
| `Follow-Entity Entity: "X"` | `predicate=Follow-Entity`, `object=X` |
| `FFE-On-Location` | `predicate=FFE-on-Location`, `object=목표 지명` |
| `find_cover ... Threat=X` | `predicate=find_cover`, `object=X` |
| `None` | `predicate=none`, `object` 비움 |
| 발사체 행 | `predicate=fired_by`, `object=확정된 사수` |

발사체의 사수를 확정할 수 없는 경우에는 잘못된 관계를 만들지 않고 `object`를 비워 둠

## 7. VR-Forces 런타임 인수 체크리스트 (수동)

`tests/test_spec.py::test_interaction_enrichment_static_acceptance`와 G4
(`validate_interaction_plan`)는 `.scnx`가 컴파일되고 슬롯·큐 계약을 지킨다는
것만 증명함. **정적 검사 통과는 VR-Forces 런타임 성공의 증거가 아니다** — 시나리오가
실제로 끝까지 도는지, 직접사격·제압사격이 관측으로 남는지는 시뮬레이터를 돌려
새 ground truth를 모아야만 판정할 수 있음. 아래는 그 인수 절차임.

1. `build/scnx/battle.scnx`를 VR-Forces에서 연다. **Ground Clamping**을 켜고
   Cutoff Distance Scale을 최대로 둔다(아래 실행 순서 절 참고).
2. 시나리오를 끝까지 실행하고, 추출한 새 ground-truth CSV를 기존 명명 규칙
   (`*_dataset.csv`)대로 `build/csv/` 아래에 저장한다.
3. `PYTHONIOENCODING=utf-8 python scripts/05_data_postprocessing.py`를
   실행한다. exit 0을 확인한다(0이 아니면 행 회계가 안 맞는 입력이 있다는
   뜻이라 원본 CSV를 먼저 의심한다).
4. `build/stkg/*_annotated.csv`에서 고유 `(subject, predicate, object)`
   삼중항 수를 predicate별로 센다.
5. **판정 기준(둘 다 충족해야 통과):**
   - 고유 `Fire-Weapon` SPO ≥ 70
   - 고유 `Provide-Suppressive-Fire-Loc` SPO ≥ 70
   - 이 두 문턱만이 이번 인수의 pass 조건이다. 다른 predicate 수는 참고용이다.
6. **반복 행 수와 고유 SPO 수를 반드시 따로 보고한다.** 같은 슬롯이 여러 틱에
   걸쳐 반복 관측되면 행 수는 쉽게 늘어난다 — 행 수 증가는 성공 지표가
   아니다. 5번의 판정은 오직 고유 SPO 수로만 한다.
7. CSV에 나타나지 않은(관측되지 않은) `slot_id`가 있으면
   `build/engagements/audit.csv`(102 accepted · 80 rejected, 이 저장소
   기준값)와 대조한다.
   - 그 `slot_id`가 애초에 `audit.csv`에 없거나 `status=rejected`면 —
     컴파일 시점에 저작되지 않은 것이 정상이라 통과에 영향 없다.
   - `status=accepted`인데 CSV에 관측이 없으면 — 저작된 task가 VR-Forces에서
     실행되지 않았다는 뜻이다. `shooter_id`·`target_id`로 `build/engagements/slots.jsonl`을
     찾아 어느 predecessor task(이동·대기·직접사격·제압사격 중 어디)가 멈췄는지
     특정하고, 정확한 `vrfSim.log` 오류와 함께 보고한다. 필드나 값을 조용히
     완화하기 전에 반드시 이 로그부터 확보한다.
8. UAV 검출률(관측이 실제로 잡힌 슬롯의 비율)은 측정은 하되 **이번 인수의
   합격 판정에는 쓰지 않는다** — 합격 기준은 5번의 두 SPO 문턱뿐이다.

## 실행 순서

```bash
python scripts/01_harvest_layout.py
python scripts/02_parse_events.py
python scripts/03_build_timetable.py
python scripts/04_compile_scnx.py
python scripts/05_data_postprocessing.py
python scripts/06_evaluate_dataset.py
```

`.scnx`는 **01→04**에서 나온다. 05·06은 VR-Forces를 돌린 뒤 그 산출 CSV를
처리·평가하는 단계라, 시나리오만 다시 만들 때는 필요 없다.

**Ground Clamping을 반드시 켤 것.** 고도는 golden 지형점에서 가져오므로 이제
0이 아니지만(1~95 m), 지명 사이를 보간하거나 대형으로 흩은 자리의 고도까지
맞지는 않는다. 대형이 커지면서(남측 제1방어선 172 m 선, 적 북측 집결지
87 m 격자) 지명 중심에서 최대 90 m대까지 벌어지므로 예전보다 더 필요하다.

1. `Settings → Ground Clamping`
2. **Ground Clamping Cutoff Distance Scale을 최대로**

## 입력

파이프라인이 읽는 시나리오 입력은 `vtmak/paths.py`의 `SCENARIO`가 가리키는
파일 **단독**이다(기본값 `scenario_original/scenario.txt`. 환경변수
`VTMAK_SCENARIO`로 덮을 수 있다).
`시나리오_원문.md`와 배치도 PNG는 사람이 보는 참고 자료이며 코드가 참조하지 않는다.

golden은 `yewon_test/` 디렉터리다. `.scnx`(ZIP)는 저장소에 두지 않고
`vtmak.scnx.pack.ensure_golden`이 필요할 때 결정적으로 만든다.

golden은 세 가지를 준다: **지명 통제점 23개의 실좌표**, 엔티티 27종의 DIS 7튜플
(= `dis_catalog.csv` 26종 전부의 출처), 그리고 `.pln`의 task 문법·파라미터
(= `task_catalog.csv`의 절반). 어휘도 문법도 golden 실측이 정본이다.

## config

| 파일 | 내용 |
|---|---|
| `roster.json` | 명부 감축 — 엔티티 총수·부대별 상한·최소 보유 |
| `layout_rules.json` | golden 이름 맞춤(alias) + **통제점 이동(relocate)** + 파생 지점 규칙 + 정적객체 바인딩 |
| `battlefield_layout.json` | **생성물.** 지명 29개 실좌표. 손으로 고치지 말 것 |
| `weapon_ranges.csv` | 모델 26종 → 직접/간접 사거리 |
| `pattern_map.csv` | 문장 템플릿·이동행동 → STKG 술어 + task_kind |
| `entity_class_map.csv` | 모델 → type_group + 무장 + **실행 불가 task(unsupported_tasks)** |
| `dis_catalog.csv` | 모델 → DIS 7튜플 |
| `task_catalog.csv` | (type_group, 행동) → `.pln` S-expression 템플릿 |
| `derive_rules.csv` | 파생 관계 규칙 R2–R4·R7의 상태 매핑·플래그 |
| `placement_rules.csv` | **타입별 최소 이격거리 + 지명별 대형(선형·격자·종대)** |

어휘를 코드에 하드코딩하지 않는다. 지명·모델·사거리·술어는 전부 여기서 온다.

## 파생 관계 레이어 (R2–R4·R7)

`vtmak/derive/`는 `build/events/battle.jsonl`(추출 정본 3,000건)을 **읽기만**
하고, 원문에 문장으로는 없는 관계를 합성한다. 산출은 전부 `layer="derived"` ·
`rule_id` · `provenance`(근거 event_id)를 달고 나간다.

규칙이 쓰는 값은 코드가 아니라 `config/derive_rules.csv`에 있다. 표에는 `note`
열이 있어 왜 그 값인지가 값 옆에 남는다 — `pattern_map.csv`와 같은 원칙이고,
**이름과 값의 정본은 CSV다.** 설계 문서가 CSV와 어긋나면 문서를 고친다.

| 규칙 | 산출 | 실측(2026-08-07) |
|---|---|---:|
| R2 | `damages` — 피격 줄의 손상 전이 | 26 |
| R3 | `causes(directFireAt → hitBy)` | 77 |
| R4 | `firesUpon(공격자, 지역)` + `causes(indirectFireAt → 지역 전이)` | 21 + 21 |
| R7 | `precedes` — 같은 행위자의 시간 인접 쌍 | 2,368 |

옛 R1(`suppresses` — 피격 줄의 제압 전이, 실측 51건)은 2026-08-27에 뺐다.
위치 기반 제압 task에는 표적 UUID가 없고, 제압사격을 했다는 사실만으로
특정 객체가 실제로 제압됐다고 단정할 수 없다 — hitBy와 stateChange를 잇는
연결 규칙 자체가 관측 전용 GT 원칙을 벗어난다(설계 §9.2). 제압 전이 피격
51건은 지금은 R2 어느 쪽에도 잡히지 않고 미매칭으로도 안 남는다 — R2가
의도적으로 건너뛴다. GT 사격 보강은 관측 전용이다.

### 부대·편제가 주어인 관계는 내지 않는다

소대·중대·대대는 원문 1,294줄에 한 번도 나오지 않는 저작물이다. 그것을 주어로
삼은 fact(옛 R5·R6·R8~R12 — `unitSuppressed`·`partOf`·`supports`·`reinforces`·
부대 단위 `movesToward`·`occupies`·`firesUpon`)는 관측으로 확인할 길이 없어
2026-08-26에 전부 걷어냈다. 구성원 관측을 접어 만들던 값도 같이 뺀다 —
접는 기준인 소속 자체가 관측이 아니라 편제표의 선언이었다. 남은 규칙은 전부
`battle.jsonl`의 이벤트만 읽고, 주어는 원문에 등장한 객체·이벤트다. 그 제거
상태는 `tests/test_derive_relations.py::test_unit_and_formation_predicates_stay_removed`
가 회귀 테스트로 고정한다.

### 짝짓기 순서가 계약이다

R3·R4는 소스 이벤트 하나가 싱크 하나를 고르고, 고른 싱크는 소진된다. 같은
피격을 두 발이 나눠 갖는 인과는 없기 때문이다. 그래서 **소비 순서가 산출을
정한다.** 순서는 `EventIndex`가 적재 때 `(time_s, event_id)`로 한 번만 정하고
규칙은 다시 정렬하지 않는다 — 규칙마다 정렬하면 R3의 '최근접'과 R7의 '인접'이
서로 다른 순서를 보고 조용히 다른 답을 낸다.

`derived.jsonl`은 GT 산출물이라 재실행·환경 간 바이트 안정성이 필요하다.
"두 번 실행 → 산출 동일", "입력 줄 순서를 섞어도 산출 동일"을 테스트가 단언한다
(`tests/test_derive_relations.py`).

### R2의 조인 조건은 셋이다

같은 `line_no` · 같은 `actor`(맞은 쪽) · **`template=="stateChange"`**. 앞의
둘만 걸면 `stateHold`가 같은 줄에 오는 순간 '유지'가 '전이'로 읽힌다. 현
데이터는 hold가 전부 다른 줄(잔류·occupy 라인)에 있어 우연히 안전하지만, 그건
데이터의 사실이지 규칙의 계약이 아니라 합성 네거티브 테스트로 못 박았다.

계약은 `hitBy` 77건 중 **손상 전이 26건만** damages가 되고, 나머지 51건(제압
전이)은 미매칭이 아니라 R2가 의도적으로 건너뛴다는 것이다 — `unmatched`는
항상 빈 튜플이다.

### R2와 R3는 서로를 봉인한다

두 레이어가 같은 피격을 각자 읽는다 — R2는 개체쌍
`(공격자, 피격자)`을, R3는 이벤트쌍 `(사격, 피격)`을 만든다. 그래서 모든
`damages(A, V)`에 대해 fire가 `directFireAt(actor=A, target=V)`인 R3 `causes`
엣지가 **정확히 하나** 있어야 한다. 어느 한쪽 규칙이 조용히 어긋나면 두
집합이 갈라져 이 교차 검증에서 걸린다.

### R3는 동반 술어를 요구하지 않는다

직접사격 77줄 중 76줄은 `engagementPair`·`hitArea`를 달고 있지만 1줄
(`E01494`, FR-INF-001→EN-INF-001, t=200)은 `directFireAt` 단독이다. 동반을
조건으로 걸면 조용히 76건이 된다. 키는 `(사격자, 대상)` 쌍뿐이다.

### R4의 Δt=+1은 필수가 아니라 예방이다

설계 초안은 "지역 7종에 21발이므로 쌍이 반복된다"를 시간 조건의 근거로 삼았다.
그건 **지역 카디널리티만 보고 공격자 카디널리티를 확인하지 않은 오류**였다.
실측은 21발의 공격자가 전부 다른 객체라 `(공격자, 지역)` 21쌍이 모두 유일하고,
현 데이터는 쌍 매칭만으로 결정된다.

조건 자체는 그대로 둔다 — 틀린 것은 조건이 아니라 필수성 주장이었다. Δt=+1은
동일 쌍이 반복 사격하는 데이터셋에 대비한 예방 장치이고, 실데이터가 그 경로를
덮지 못하므로 합성 이벤트 테스트로 고정한다.

### R7의 판별자는 `template`이지 빈 `state_from`이 아니다

초안 문구는 "hold류(`state_from==''`)"였는데, `state_from`이 빈 이벤트는 473건
이고 그중 **294건이 `stateInit`**이다. 공백으로 거르면 각 행위자의 출발점까지
사라진다(2,368 → 2,074). 상태 유지는 같은 상태의 재서술이지만 초기 상태는
체인의 첫 링크다. 판별자는 `template=="stateHold"`(179건)로 고정한다.

끄고 켜는 것은 `derive_rules.csv`의 `skip_state_hold` 플래그이며, **이 플래그는
R7 체인 구성에서만 소비한다.** 다른 규칙이 나중에 hold 처리를 원하게 되면 이
플래그를 재활용하지 말고 별도 플래그를 받는다.

행위자가 없는 이벤트는 체인에 끼지 않는다 — `targetArea`("목표 구역은 X이다")
118건이 그렇다. `targetArea`는 사격 라인의 속성(지역 지정)이지 어떤 개체의
행동이 아니라 체인에 낄 `actor` 자체가 없다. 이 118건을 키 `''` 하나로 묶으면
117엣지짜리 유사 체인이 생겨 각 수치가 117씩 부푼다 (2,664 / 2,485 / 2,191).

### precedes의 절반은 Δt=0이다 — 정의를 먼저 고정한다

2,368 엣지 중 **1,408(59%)이 `Δt=0`**이고, 그 1,408은 **동일 `line_no` 엣지
집합과 정확히 일치**한다. 원문 한 줄이 행동과 상태 전이를 같은 시각으로 함께
서술하기 때문이다(다중 이벤트 라인마다 하나씩).

그래서 `precedes`의 의미를 이렇게 고정한다:

> **`precedes`는 물리적 시간 선행이 아니라 같은 행위자의 서술 순서상 인접이다.**
> 같은 시각은 `event_id` 타이브레이크로 갈리고, `event_id`는 원문 등장 순서라
> 그 순서가 곧 문장 내 서술 순서다.

이 정의를 쓰는 한 현 구현이 맞다. `precedes`를 **엄밀한 시간 선행**으로 소비할
데이터셋이 나오면 Δt=0 엣지는 `precedes`가 아니라 동시 발생(`cooccursWith`)
이거나 제외 대상이다 — 그때는 규칙을 고치는 게 아니라 **관계를 하나 더 만드는**
쪽이다. 소비 측이 정의를 바꿔 읽는 것이 가장 조용한 실패다.

## 좌표

지명 좌표의 정본은 **golden(`yewon_test.oob`)에 사람이 찍은 통제점 23개**다.
`01_harvest_layout.py`가 이름으로 수확해 `battlefield_layout.json`을 만든다.
v2까지 쓰던 로컬 미터 선언·`scale`·해안선 모델은 사라졌다 — 지형점 자체가
육지 보증이라 더 필요 없다.

원문에만 있고 golden에 없는 지명 6곳은 `layout_rules.json`의 규칙으로 민다.
**방위는 실제 나침반이 아니라 전장 축(아군 중심 → 적 중심, 실측 163°)을 쓴다.**
golden 실측에서 동측능선이 실제 서쪽, 서측능선이 실제 동쪽에 찍혀 있어 나침반으로
읽으면 전부 뒤집힌다(23곳 중 22곳이 축을 따른다). 파생 지점과 `relocate`로
옮긴 지점은 지형이 확인되지 않았으므로 G0가 `C0.7`로 알린다.

교전 거리는 초기 배치가 아니라 **교전 시점**의 위치로 잰다. 적 보병은 집결지에서
출발하지만 교전 시점에는 중앙 킬존까지 내려와 있다. 목표 위치는 원문의 피격
문장을 정본으로 쓴다.

### 사격 좌표도 교전 시점의 위치다 (2026-08-09)

거리는 교전 시점으로 쟀는데 **`.pln`에 들어가는 좌표는 초기 배치**였다.
`spec._Ctx.coord_of`가 `initial_location`을 읽었기 때문이다. 그래서
제압사격(`provide_suppressive_fire_loc`) 51건 전부가 적이 이미 떠난 자리를
겨눴다 — 표적이 1.7 km를 이동해 중앙 킬존에 있는데 `targetLocation`은 적 북측
집결지를 가리켰다. G0는 통과한다. 거리는 맞게 쟀으니까.

해석기를 하나로 합쳤다. `coord_of(ref, time_s, actor)`가 G0와 **같은**
`gates.PositionTracker`·`engagement_locations`를 쓴다. 우선순위도 같다:
피격 문장이 적은 교전 지점 > 정적 바인딩 > 시각별 추적. 사수 위치는
`actor_coord(actor, time_s, src)`가 문장이 명시한 출발 지명을 먼저 본다.

추적된 지명이 그 객체의 **초기 배치 지명과 같으면** 대형 안의 실제 자리를
쓰고(아직 안 움직였다는 뜻), 움직였으면 지명 중심점을 쓴다. 목적지 안에서
어디에 서는지는 VR-Forces가 정하므로 아는 척하면 G0와 어긋난다.

`tests/test_placement.py::test_suppressive_fire_aims_where_the_target_is_when_fired`
이 51건 전부를 검사한다 — 옛 좌표가 하나라도 남으면 잡힌다.

### 포병진지는 golden 자리에서 1 km 물러나 있다

VR-Forces가 실제로 최소사거리 미달 사격을 거부하는 것이 확인됐다(2026-08-04
`vrfSim.log`: `Indirect fire target less than min range (2000 m)` — 155mm 10문
전원). `weapon_ranges.csv`의 2000 m가 VR-Forces의 실제 하한과 정확히 같았다.

golden 통제점이 만드는 범위가 2.5×2.5 km라 그 안에는 2 km 떨어진 표적이 없다
(최장 1,855 m). 그래서 `layout_rules.json`의 **`relocate`** 규칙으로 아군·적
포병진지를 전장 축을 따라 각각 1 km 뒤로 민다. 대포병 사거리는 1,186 → 3,186 m,
나머지 표적도 2,266~2,710 m가 된다. 남는 미달은 **아군포병진지 → 중앙 킬존
1,505 m 1건**뿐이고 그 사격은 태스크로 만들지 않는다.

박격포(MO-120RT-61)의 `indirect_min_m`도 교리값 1,100 → **1,200 m**로 올렸다.
같은 로그에서 1,154 m 사격이 `Could not find an allowable muzzle speed and
elevation angle to reach the target`로 실패했고 1,292 m는 정상이었다.

옮긴 두 지점은 golden이 주던 육지 보증이 없다. `src=relocated`가 되어 파생
지점과 함께 G0가 `C0.7`로 알린다 — **VR-Forces에서 물·급경사가 아닌지 눈으로
확인할 것.** 좌표는 아군포병진지 `21.395302, -157.737257`, 적포병진지
`21.367284, -157.731736`.

### 모델이 실행할 수 없는 task는 만들지 않는다

`entity_class_map.csv`의 **`unsupported_tasks`** 열이 모델별 실행 불가 task-type을
담는다. 없는 컨트롤러를 부르면 VR-Forces가 `No controller or Controller is
disabled, unable to carry out task ...`로 거절한다. 전부 2026-08-04 `vrfSim.log`
실측이다.

| 모델 | 못 하는 task | 실패/보유 |
|---|---|---|
| ZPU-4 AA Gun | `move-to-location-task` | 6/6 |
| MO-120RT-61 Mortar | `move-to-location-task` | 8/9 |
| M901 Patriot Launcher | `move-to-location-task`·`ffe-on-location` | 1/1 |
| MIM-104 Patriot Launcher | `ffe-on-location` | 1/1 |
| M1A2 Abrams MBT | `find_cover` | 5/5 |
| T-72 MBT | `find_cover` | 12/12 |
| BTR-60 APC | `find_cover` | 1/1 |

**`type_group`이 아니라 모델 단위인 이유**가 있다. `find_cover`는 T-72에서
12/12 실패하는데 같은 '차량/장갑차' 그룹의 T-69·T-80은 8/8 성공한다. 그룹으로
막으면 도는 태스크까지 같이 죽는다.

ZPU-4는 이 시나리오에서 받은 태스크가 전부 실행 불가라 플랜이 빈다.
`test_spec.py`가 그 목록을 못 박아 둬서, 필터가 넓어지면 먼저 걸린다.

**M901 Patriot Launcher는 더 이상 여기 없다(2026-08-05).** `unsupported_tasks`가
`move-to-location-task`·`ffe-on-location`뿐이라 `set-aiming-point`는 막히지
않고, `aim`이 방향 조준 task를 낸다 — aimAt이 noop이던 시절엔 이 모델의 유일한
이벤트가 aimAt이라 플랜이 통째로 비었지만, Task 4에서 aim이 실제 Set을 내면서
빠졌다. `test_spec.py::test_empty_plans_are_only_towed_equipment`가 빈 플랜
목록을 `{"ZPU-4 AA Gun"}` 하나로 못 박아 둔다.

빠지는 것은 `.pln`의 태스크뿐이다. **`battle.jsonl`의 이벤트·원문 predicate·
subject-object 관계·`event_id`·`source_line`·STKG 관계는 그대로 남는다.**
어떤 태스크가 왜 빠졌는지 보여주는 감사표(`vtmak/scnx/audit.py`의 `build_rows`,
행마다 `in_scnx`와 사유)는 있지만, 지금은 `tests/test_audit.py`만 부른다 —
파이프라인 스크립트 중에는 아직 이걸 쓰는 것이 없다(`05_data_postprocessing.py`
포함, `grep -rn "audit" scripts/`로 확인). CSV 후처리가 필요해지면 여기 붙이는
것이 다음 자리다.

### 매핑을 늘리는 자리는 CSV 두 줄이다

예전에는 task_kind 하나를 늘리려면 `pattern_map.csv`·`task_catalog.csv`와
`plan.py`의 표 세 개(`LABEL_CANDIDATES`·`REF_FIELD`·`FIRE_KIND`)를 같이
고쳐야 했다. 그래서 `task_catalog.csv`에 템플릿이 있는 행동 33종 중 8종만
도달 가능한 상태로 굳어 있었다.

세 표는 `config/task_kinds.csv`로 나왔다(2026-08-05). 이제 매핑 추가는
`pattern_map.csv` 한 줄 + `task_kinds.csv` 한 줄이다. 폴백은 없다 — 어느
쪽이 비면 G3가 막는다.

| 열 | 뜻 |
|---|---|
| `task_kind` | `pattern_map.csv`의 같은 이름 |
| `ref_kind` | `COORD` \| `ENTITY` \| `*` — 참조 대상 종류별로 후보가 갈린다 |
| `참조_필드` | Event의 어느 필드에서 대상을 가져오는가. 비면 참조 없음(`wait`) |
| `사거리_종류` | `direct` \| `indirect` \| 빈칸 |
| `행동_후보` | `task_catalog.csv`의 '행동', `\|`로 구분한 우선순위 순 |

`참조_필드`에 `next_fire_target`을 쓰면 그 객체가 곧이어 쏘는 표적을 가져온다
(`find_firing_position`의 위협 대상).

### 원문 어휘에서 뽑은 task 3종 (2026-08-05)

| 새 task | 원문 근거 | 원문 이벤트 | `.pln` 저작 |
|---|---|---:|---:|
| `wait-duration` | `stopAt` "…에 정지한다" · `stayAt` "…에 잔류한다" | 179 | 179 |
| `set-aiming-point` (방향 조준) | `aimAt` "포신 정렬 후 간접사격 준비" | 21 | 19(최소사거리 미달 2건은 저작하지 않는다) |
| `find_firing_position` | 상태전이 `사격 준비 대기 → 사격 준비` | 21 | 21 |

두 열이 다른 이유는 항목마다 다르다. `set-aiming-point`의 21은 원문 `aimAt`
이벤트 수, 19는 그중 실제로 `.pln`에 나간 수다(2026-08-05 실측,
`build_spec`의 결과 확인). `wait-duration`·`find_firing_position`은 사거리
검사가 없어 원문 건수와 저작 건수가 같다.

**`# VERIFY-ON-TARGET`** — 방향 조준(`aiming-azimuth`/`aiming-elevation`)의
기준이 진북인지 자북인지, 시계 방향인지도 실제 VR-Forces에서 확인하지
못했다(`vtmak/geometry.py`의 `bearing_elevation`이 진북 기준 시계 방향
라디안이라고 가정한다). CSV를 열어보지 않는 사람도 알아야 하는 사실이라
여기 적는다 — 틀리면 포신이 엉뚱한 방향을 보지만 task 자체는 정상적으로
돈다. GUI에서 눈으로 확인하기 전까지는 미확정으로 둔다.

### 종류보다 분포가 문제였다 (2026-08-09)

`.pln`의 task type은 **13종**이다(2026-08-09 컴파일 실측: `task-type` 10종 +
`set-data-request-type` 3종). 종류만 세면 12종에서 하나 늘었을 뿐이지만,
바뀐 것은 **편중**이다.

| task | 개편 전 | 개편 후 |
|---|---:|---:|
| `move-to-location-task` | **436 (45%)** | 238 (24%) |
| `move-to` (통제점) | 0 | 198 (20%) |
| `wait-duration` | 179 (18%) | 179 (18%) |
| `follow-entity` | 113 | 113 |
| `set-aiming-point` | 19 | 37 |
| 나머지 8종 | 227 | 227 |
| **총계 / 최대 점유율** | 974 / **45%** | 992 / **24%** |

한 종류가 전체의 45%를 먹으면 그 시뮬레이션에서 뽑은 STKG는 관계 하나가
머리를 다 차지하고 나머지가 롱테일이 된다. 원인은 원문이 이동 행동을 일곱
가지로 구분해 서술하는데 그중 넷이 전부 `move-to-location-task` 하나로
합쳐지고 있었다는 것이다.

원문 어휘를 늘리지 않고 **이미 구분돼 있는 것을 구분해서 받았다.**

| 원문 이동 행동 | 개편 전 | 개편 후 | 근거 |
|---|---|---|---|
| 방어선 재편성 이동 · 방어 위치 이동 | `move` | **`move_cp`** → `move-to` | 둘 다 '지정된 방어 위치로 간다'는 서술이라 좌표가 아니라 자리를 가리킨다. 통제점으로 찍히면 사람이 지도에서 방어 배치를 확인할 수 있다 |
| 감시 위치 이동 및 관측 방향 유지 | `move` | **`move_watch`** → 이동 + 방향 조준 | 원문이 '관측 방향 유지'를 말하는데 이동만 저작하면 그 절이 산출에서 사라졌다 |
| 후퇴 이동 · 지상 이동 | `move` | 그대로 | |

`test_no_single_task_type_dominates`가 최대 점유율 1/3 미만을 못 박는다.

**한 문장이 두 블록을 내는 규칙은 코드가 아니라 표에 있다.** 예전에는
`plan.py`가 `if kind == "move_slow"`로 set-speed를 앞에 붙였다. 지금은
`task_kinds.csv`의 `선행_행동`·`후행_행동` 열이 정하고, 템플릿이 없으면
예외로 멈춘다(조용히 빠지면 보급 차량이 왜 전속력으로 달리는지 `.scnx`를
열어보기 전엔 알 수 없다).

**`move-to`도 컨트롤러가 필요하다.** `move-to-location-task`가 '컨트롤러 없음'
으로 거절되는 견인 장비(ZPU-4 · MO-120RT-61 · M901)는 이동 컨트롤러 자체가
없다는 뜻이라 `unsupported_tasks`에 `move-to`를 같이 넣었다. **이건 실측이
아니라 추론이다** — VR-Forces에서 확인되면 `entity_class_map.csv`의 그 비고를
지운다. 막지 않으면 실행되지 않을 태스크가 저작된다.

아직 안 쓰는 것이 남아 있다. 팀이 고른 21종 task 중 미사용 8종은
`animated-movement-task` · `engage_from_cover` · `ffe-on-entity` ·
`ffe-on-target` · `place_ied` · `throwgrenade` · `embark`/`disembark` ·
`set-target`이다. **이것들은 매핑이 아니라 원문 어휘가 없어서 못 쓴다** —
`task_catalog.csv`에는 템플릿이 이미 있다. 늘리려면 원문에 그 행동을 서술하는
문장을 넣어야 한다.

**상태전이를 대부분 쓰지 않는 이유가 있다.** `stateChange` 계열(`stateInit`·
`stateChange`·`stateHold` 세 템플릿) 1,294건 중 745건은 이미 task를 내는
이벤트와 **같은 시각·같은 객체**에 붙어 있다 — 서사가 같은 순간을 상태로
한 번 더 말하는 것이라 task를 또 붙이면 중복이다(2026-08-05 재실측,
`git show b6aab56:new_VTMAK/config/pattern_map.csv` 기준으로 재현 가능).
나머지 549건 중 473건은 `stateInit`·`stateHold`처럼 애초에 전이가 아니라
초기·유지 상태 서술이다(`이전 상태`가 없다). 진짜 전이(`이전→다음`이 둘 다
있는) 중 짝이 없는 것은 4종 76건이다 — `대기→사격 준비 대기`(21) ·
`사격 준비 대기→사격 준비`(21) · `정상→피격 지역`(21) · `대기→적재 대기`
(13). 예전 문서는 이 합을 68로 잘못 적었다(21+21+21+13=76).

**`사격 준비 대기 → 사격 준비`는 예외다 — 사실은 짝이 있다.** 같은 시각·
같은 객체·같은 원문 줄의 `aimAt` 이벤트와 21/21 전부 짝을 이룬다(2026-08-05
실측). `aimAt`이 `noop`이던 시절에는 이 전이도 짝 없는 전이로 셌지만,
`aimAt`이 `set-aiming-point`를 내게 되면서 짝이 생겼다. 짝이 생겼다고 이
전이를 다시 버리지는 않는다 — 포신을 정렬하는 것과 사격위치를 잡는 것은
**같은 순간을 말하지만 서로 다른 행위**이기 때문이다(포병이 조준한 뒤
자리를 옮기는 것은 실제로도 그렇다). 알려진 부작용: 조준이 재배치보다 먼저
일어나 재배치 반경(100m) 안에서 조준각이 몇 도 어긋난다 — 받아들인다.

**`set-target`은 일부러 뺐다.** `engAttacker` 118건이 근거가 되지만, 이
요청은 "이걸 교전하라"고 지정만 하고 실제 사격은 자동교전 로직이 한다.
`AIEnabled`가 끄는 것이 바로 그 자동사격이므로 AI Off에서는 지정만 되고
아무 일도 일어나지 않을 가능성이 크다(실측 없음, 구조상의 판단).

**통제점은 11개다(2026-08-09).** `find_firing_position`의 위협 대상 7곳에
방어 배치 이동(`move_cp`)의 목적지 4곳이 더해졌다. 2026-08-03에 통제점을 뺀
것은 배치 지명 29개를 전부 찍어 로딩이 느려졌기 때문이고, 이 11개는 실제로
조준·사격 대상이거나 부대가 실제로 가는 자리뿐이다. 로딩 영향은 측정하지 않았다.

### AI Enabled = No 는 task를 막지 않는다

`AIEnabled False`로 둔 328객체 중 294객체가 오류 없이 태스크를 수행했다(같은
로그). 매뉴얼 34.3 그대로 **충돌회피·자동사격·피격반응만 꺼진다.** 계획에 없는
교전으로 시나리오가 일찍 끝나는 것을 막으려면 이대로 두면 된다(사용자 결정
2026-08-04).

**생성기가 끈다(2026-08-05).** golden·campaign 레코드는 `AIEnabled True`로
저장돼 있어서 예전에는 VR-Forces에서 손으로 328개를 껐다. 이제
`writer._ai_switch`가 `.oob`를 쓰기 직전에 엔티티·통제점·고정 객체를 한 번에
`False`로 맞춘다. state-data가 없는 객체(통제점·라우트)에는 스위치를 만들어
넣지 않는다 — golden에 없는 형태가 되기 때문이다. 다시 켜고 싶으면
`writer.AI_ENABLED_DEFAULT`(또는 `TemplateScnxWriter(ai_enabled=True)`)
한 곳만 바꾼다. `test_writer.py`가 산출물에 `AIEnabled True`가 하나도 없음을
못 박는다.

### 고정 객체(UAV)에서 '고정'은 '안 움직인다'가 아니다

UAV 4기는 `campaign`에서 레코드를 복제해 넣는 고정 객체다(→ "고정 객체").
여기서 **고정은 '원문 규모와 무관하게 같은 배치를 갖는다'** 는 뜻이다. 명부를
줄여도 개수·선회 중심·고도가 변하지 않는다. 복제한 레코드에서 우리가 덮어쓰는
것은 좌표·고도·짐벌 셋뿐이고, 그 값은 전부 `fixed_objects.json`이 정한다.

2026-08-05까지는 '이동 태스크를 붙이지 않는다'가 원칙이었고
`spec.build_fixed_plans`가 `Set` 외의 Plan 요소를 예외로 막았다. 측정 결과 정지
관측으로는 지형 차폐가 안 풀린다는 것이 드러나 원칙을 개정했다
([설계 스펙](../docs/superpowers/specs/2026-08-06-uav-placement-behavior-design.md)).
`FIXED_PLAN_ELEMENTS`는 이제 `{Set, Task}`이고, 붙일 수 있는 행동은 여전히
`task_catalog`에 있는 것만이다.

지금 붙는 것은 둘이다. 무엇을 붙일지는 `fixed_objects.json`의 `plan`이 선언하고
S-expression은 `task_catalog.csv`에 있다 — 문법을 코드에 박지 않는다.

| 행동 | Plan 요소 | 하는 일 |
|---|---|---|
| `관측 보고 켜기` | `Set` (`set-spot-reporting-request`) | 탐지한 것을 보고하게 켠다 |
| `순찰 비행` | `Task` (`move-along`) | 담당 통제점 둘레 반경 1,000 m의 순찰로를 8바퀴 돈다 |

관측 보고 Set은 `campaign.pln`의 UAV 플랜에서 **리터럴 그대로 수확했다.** 그래서
문법에 추측이 없다. 관측 보고 Set은 생성기가 빼먹고 있던 것이다 — 개편 전
`build/scnx/battle.scnx` 안의 `.pln`에는 0건, `campaign.pln`에는 4건이었다.

짐벌은 플랜 Set이 아니라 `fixed.load_fixed`가 `.oob` raw 레코드의
`sensor-gimbal-controller` PSR에 직접 쓴다. Set으로 azimuth/elevation을 넘기는
문법은 정본을 확인하지 못했지만 PSR 필드명은 `campaign.oob`·`battle.oob`에서
직접 읽은 것이라 추측이 없다. 하방각은 config에 적지 않고
`-atan(altitude_agl_m / radius_m)`으로 계산한다.

`orbit_object`는 폐기했다(2026-08-07). 그 태스크의 `target`은 데이터 타입이
`simulationobject`인데 우리는 통제점 uuid를 넣고 있었고, 결국 UAV가 실제로
움직이지 않았다. 중립 앵커 엔티티를 만들어 맞추는 대신, 통제점 둘레에 순찰로를
찍고 `move-along`으로 도는 쪽으로 바꿨다 — 골든에 이미 있는 문법이라 확인할
것이 남지 않는다. 산출에는 `UAV<n>RTE` 표식의 순찰로 4개가 들어간다.

## 초기 배치 (2026-08-09 개편)

`vtmak/scnx/placement.py`. 값은 `config/placement_rules.csv`에 있다.

예전에는 `object_id` 해시로 지명 둘레 ±25 m 정사각형에 흩었다. 개수도 객체
크기도 보지 않는 방식이라 실측이 이랬다.

| | 개편 전 | 개편 후 |
|---|---:|---:|
| 최근접 이웃 거리 중앙값 | 3.2 m | 2.0 m(보병 규정 간격) |
| 2 m 미만인 객체 | 103 / 343 | **0** |
| 차량급끼리 8 m 미만 | 있음(최소 1.24 m) | **0** |
| 방어선 대형 | ±25 m 덩어리 | 172 m 선(장/단축 비 ∞) |
| heading | 343객체 전부 0°(진북) | 12개 방위 구간에 분산 |

T-72가 6.9 m, BTR-60이 7.6 m다. 중심 간격 1.24 m는 전차 두 대가 서로를
관통한 채 서 있었다는 뜻이다. 원인은 적 북측 집결지 한 곳에 130객체가
50×50 m 안에 들어간 것이었다.

**세 가지가 바뀌었다.**

1. **최소 이격거리를 타입별로 보장한다.** 보병 2 m · 차량/전차 10 m ·
   박격포 12 m · 155mm/Patriot 15 m. 같은 지명의 객체를 (부대, 타입그룹)별
   블록으로 묶고 블록을 선반(shelf)처럼 늘어놓는다. 블록 사이·선반 사이
   간격은 **양쪽 이격거리 중 큰 값**이라 서로 다른 타입이 붙어도 큰 쪽 규칙을
   지킨다.
2. **대형이 지명마다 다르다.** 방어선·능선은 `선형`(부대별로 한 열씩), 집결지·
   포진지는 `격자`, 접근로는 `종대`(2열)다.
3. **결정적이다.** 난수도 해시도 쓰지 않는다 — 정렬된 목록의 순서가 자리를
   정한다. `test_placement_is_deterministic`이 두 번 만든 좌표가 같음을 단언한다.

### 대형이 눕는 방향은 전장 축이 아니다

`axis_bearing_deg`(163°)는 아군 중심 → 적 중심의 **평균**이다. 남측 제1방어선에서
목표 A·중앙 킬존을 보는 실제 방위는 238° 부근이라 75°가 어긋난다. 그 값으로
방어선을 세우면 적을 가로막는 대신 적을 향해 세로로 늘어선다.

그래서 대형은 그 지명에 있는 객체들의 **평균 방위(= 적을 보는 쪽)에 수직**으로
눕는다. 깊이 축은 후방을 가리켜 뒷열이 적에서 멀어진다. 전장 축은 방위를
하나도 못 구했을 때의 폴백으로만 남는다.

### heading — 예전에는 전원이 진북을 봤다

`orientation-tait-bryan`을 공여체 레코드에서 복사만 하고 덮어쓰지 않았다.
되읽어 보면 343객체가 전부 heading 0° · pitch 0° · roll 0°였다. 아군과 적이
같은 쪽을 보고 서 있었다.

방위 기준은 둘이다.

1. **첫 이동 목적지.** 그 객체가 처음 가는 곳이 처음 보는 쪽이다. 시작하자마자
   제자리에서 180° 도는 일이 없어진다.
2. 이동이 없으면 **상대 진영 초기 배치의 무게중심.** 정지한 방어부대·포병이
   여기 해당한다.

VR-Forces의 자세는 **ECEF 기준 DIS 오일러각**이라 같은 방위라도 위경도가
다르면 값이 달라진다. 방위각을 그대로 써 넣을 수 없다.
`geometry.tait_bryan`이 국지 NED 축으로 동체 축을 만들어 ECEF로 옮긴 뒤 되읽고,
`heading_from_tait_bryan`이 그 역이다. 왕복이 맞는지를 네 위도에서 테스트가
확인한다. 피치·롤은 0으로 둔다 — 지면 경사는 Ground Clamping이 잡는다.

방위 계산의 기준점은 배치 좌표가 아니라 **지명 중심**이다. 배치가 방위에
의존하므로(대형이 방위에 수직으로 눕는다) 반대로도 의존하면 순환이 된다.
대형 반경은 최대 90 m대이고 겨냥 거리는 700~2,000 m라 각도 차이는 몇 도다.

## 명부 감축

VR-Forces는 객체 수에서 먼저 막힌다(100개에서 렉으로 작동 불가 실측). 그래서
문제는 "몇 개를 남길까"가 아니라 **"이 수로 몇 개의 task를 살릴까"**다.

`roster.json`의 `target_entities`가 task 가능 객체 총수다(현재 **328**, 정적 7 별도).
그 수 안에서 `roster.py`가 **한계 이득**이 큰 객체부터 뽑는다 — 어떤 객체를 넣었을
때 그 객체 때문에 비로소 성립하는 task 이벤트 수다. 자기가 행위자인 이벤트뿐
아니라 이미 뽑힌 객체가 자기를 표적으로 삼은 이벤트도 함께 세는데, 사격은 쌍이라야
성립하기 때문이다(이 항이 없으면 표적 없는 사수만 남는다).

수확량보다 앞서는 것이 셋 있다. 구조를 지키는 몫이다.

| 제약 | 근거 |
|---|---|
| 교전 유형마다 최소 한 쌍 | STKG 관계 종류가 통째로 사라지지 않게 (라운드로빈) |
| `min_per_type` = 2 | 엔티티 타입 31종 유지 |
| `min_per_unit` = 1 | 이벤트가 적은 부대(지휘소 경계 보병 등)가 비지 않게 |
| `quota` | 사람이 정한 부대별 **상한**. 이보다 많이 뽑지 않는다 |

**지금은 아무것도 버리지 않는다.** `target_entities` 328은 원문이 이미
추려 놓은 수와 같고 `quota`도 그 구성과 같아서, 감축기는 전원을 통과시킨다
(2026-08-09 실측: 엔티티 328 · 타입 31/31 · 부대 35/35). 감축을 두 군데서
하면 어느 쪽이 줄인 건지 알 수 없기 때문이다.

VR-Forces가 무거우면 `target_entities`만 내린다. 그때 `quota`는 상한으로
동작하고 한계 이득 방식이 살아난다 — 80으로 내린 측정에서는 정원 균등
축소(0.8배)보다 task 185 대 176, 교전 유형 21/21 대 17/21로 앞섰다. 테스트가
이 비교를 지킨다.

`target_entities`를 비우면 정원표를 정확히 맞추는 방식, 정원표까지 비우면 예전
예산 방식(`target_objects`)으로 돌아간다.

### 정적 객체 7개는 산출물에 들어가지 않는다

`FR/EN-FP-001~002`(사격진지) · `FR-LN-001`(방어선) · `EN-RT-001`(도로) ·
`OBJ-009`(킬존)는 `.scnx`에 객체로 쓰이지 않는다. 지명 좌표에 이름을 붙여 둔
바인딩일 뿐이고(`layout_rules.json`의 `static_targets`), 그 좌표가 간접사격
목표로 들어간다. 포병 태스크는 전부 `ffe-on-location`이라 객체가 아니라 좌표를
쏘므로 프롭이 없어도 사격은 성립한다. 지휘소·관측소·보급소 프롭은 사람이
VR-Forces에서 직접 얹는다(2026-08-03 결정).

## 검증 게이트

| 게이트 | 조건 | 현재 |
|---|---|---|
| G0 | 모든 교전 쌍이 사거리 안 + 좌표 출처 | 차단 0 · 보고 12 |
| G1 | 3,000문장 전부 매칭 | 위반 0 |
| G2 | task 가능 객체 전원 플랜 보유 | 위반 0 |
| G3 | DIS·좌표·uuid·괄호·참조·**무기 실재** 정합성 | 차단 0 · 보고 46 |

`severity`가 `BLOCK`인 위반만 파이프라인을 멈춘다. `REPORT`는 사람이 알아야
하지만 산출을 막지 않는 사실이다.

G0 보고 12건: 최소사거리 미달 2(`C0.1` — 155mm·박격포가 중앙 킬존을 치는
1건씩) · Patriot 미확인 2(`C0.3`) · 지형 미확인 8(`C0.7` — 파생 6 + 이동 2).

G3 보고 46건(2026-08-09 실측)은 전부 `C3.5`, **일부러 저작하지 않은 태스크**다.
내역은 컨트롤러 없음 42 + 최소사거리 미달 4. 옛 문서의 44는 최소사거리 미달을
2로 적었는데 실제로는 155mm 1쌍·박격포 1쌍으로 4건이다(조준·사격 각각). `PlanStep.skip_reason`이 붙어 있으면
'실행 불가가 실측된 조합'이라 `REPORT`, 없으면 저작 결함이라 `BLOCK`이다.

### 무기 이름은 모델마다 다르다 (C3.8)

`task_catalog`의 템플릿은 type_group 단위라 무기 이름이 하나로 박혀 있다. 그런데
같은 그룹 안에 다른 무기를 든 모델이 있다 — '보병 - 소총(M4 계열)'에는 M4를 든
미군과 **AK-47을 든 적군**이 같이 있다. 박힌 이름을 그대로 쓰면 적 보병이
`"M4 rifle"`로 쏘라는 태스크를 받고, 그 무기가 없어 사격을 실행하지 못한다
(2026-08-03 실측: 80객체 중 23객체가 이 상태였다).

무기 이름의 정본은 golden `.oob`의 `(display-name ...)`이고 `entity_class_map.csv`가
그 사본이다. 간접사격은 `<display-name>:<munition resource>` 형식이다
(`Indirect-Fire-Gun:M107-155mm`). `plan.py`가 템플릿의 무기 자리를 객체의 무기로
바꾸고, G3 `C3.8`이 "그 모델이 실제로 가진 무기인가"를 검사해 차단한다.

## 테스트

```bash
python -m pytest tests/ -q
```

297개. `conftest.py`가 `sys.path`를 주입한다(경로에 공백·한글이 있어 설치 방식을
쓰지 않는다).

## 공간 관계 확장

엔티티 쌍의 정성적 공간 관계 네 개를 파생해 시간 구간으로 낸다.

```powershell
python scripts/08_spatial_relations.py `
  "build\stkg\adapted_ver2.0.csv" `
  --relations "build\stkg\relations_ver2.0.csv" `
  --quality   "build\stkg\relation_quality_ver2.0.csv" `
  --manifest  "build\stkg\relations_ver2.0.manifest.json" `
  --dataset-version "ver2.0"
```

### 입력 계약

```text
subject,predicate,object,latitude,longitude,timestamp,heading,entity_type,force
```

`heading`은 진북 0, 시계 방향 도(度). `timestamp`는 벽시계가 아니라 VR-Forces
시뮬레이션 시각이어야 한다. `force`는 `entity_type`에서 유추할 수 없다 — DIS
국가코드는 제작국이고, 시나리오에는 미제 장비를 쓰는 적이 있다.

### 관계

| 관계 | 뜻 | 대칭 |
|---|---|---|
| `next_to` | 타입별 이격거리 컷 안의 거리 | 예 |
| `in_front_of` | 주어가 목적어 방위 ±45° 안, 관심거리 이내 | 아니오 |
| `behind` | 주어가 목적어 방위에서 135° 밖, 관심거리 이내 | 아니오 |
| `in_range_of` | 목적어가 주어의 명목 사거리 안, 소속이 다를 때만 | 아니오 |

측면 90° 두 구간은 의도적으로 아무 방향 관계도 갖지 않는다. 좌우는 범위 밖이다.

`in_range_of`는 쏠 수 있다는 뜻이 아니다. 명목 사거리표만 본다 — 탑재 무장,
탄약, 가시선, 센서 탐지, 교전규칙은 확인하지 않는다.

**`approach`는 설계돼 있지만 구현하지 않았다.** 거리 변화율이 필요한데 그 율은
내보내기가 시뮬레이션 시각을 줄 때에만 뜻이 있다. 설계 문서 §14를 보라.

### 출력 계약

```text
subject,predicate,object,t_start,t_end,support_count,evidence,dataset_version,threshold_config_version
```

시각마다 한 줄이 아니라 구간으로 낸다 — 매초 방출은 원본의 15~63배가 된다.
`support_count`는 그 구간을 뒷받침한 관측 수라, 근거가 얇은 구간을 걸러낼 수 있다.

대칭 관계는 기본적으로 한 방향만 저장한다(임계값 설정의 `symmetric_storage`).
매니페스트가 어느 술어가 대칭이고 어떻게 저장했는지 남긴다.

### 거리·방위의 출처

거리는 전부 `vtmak.geometry.ground_distance`, 방위는 `bearing_elevation`이다.
평면 투영을 따로 두면 `in_range_of`가 G0 사거리 게이트와 경계에서 어긋난다.
