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
<<<<<<< HEAD
| `Move to {좌표}` | `predicate=move to`, `object=지명` |
| `Follow-Entity Entity: "X"` | `predicate=Follow-Entity`, `object=X` |
| `FFE-On-Location` | `predicate=FFE-on-Location`, `object=목표 지명` |
| `find_cover ... Threat=X` | `predicate=find_cover`, `object=X` |
| `None` | `predicate=none`, `object` 비움 |
| 발사체 행 | `predicate=fired_by`, `object=확정된 사수` |
=======
| `build/events/battle.jsonl` | 이벤트 3,000건 |
| `build/timetable/battle.csv` | 셀 1,600개 |
| `build/scnx/battle.scnx` | 엔티티 328 · 고정 4 · 플랜 보유 320 · 태스크 702 |
>>>>>>> 06150cb (GT 시간대 안 맞음)

발사체의 사수를 확정할 수 없는 경우에는 잘못된 관계를 만들지 않고 `object`를 비워 둠

## 실행 순서

<<<<<<< HEAD
```bash
python scripts/01_harvest_layout.py
python scripts/02_parse_events.py
python scripts/03_build_timetable.py
python scripts/04_compile_scnx.py
python scripts/05_data_postprocessing.py
```
=======
**Ground Clamping을 반드시 켤 것.** 고도는 golden 지형점에서 가져오므로 이제
0이 아니지만(1~95 m), 지명 사이를 보간하거나 jitter로 흩은 자리의 고도까지
맞지는 않는다.

1. `Settings → Ground Clamping`
2. **Ground Clamping Cutoff Distance Scale을 최대로**

## 입력

파이프라인이 읽는 시나리오 입력은 `vtmak/paths.py`의 `SCENARIO`가 가리키는
파일 **단독**이다(현재 `scenario_original/scenario_ver70.txt`).
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

어휘를 코드에 하드코딩하지 않는다. 지명·모델·사거리·술어는 전부 여기서 온다.

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

ZPU-4와 M901은 이 시나리오에서 받은 태스크가 전부 실행 불가라 플랜이 빈다.
`test_spec.py`가 그 목록을 못 박아 둬서, 필터가 넓어지면 먼저 걸린다.

빠지는 것은 `.pln`의 태스크뿐이다. **`battle.jsonl`의 이벤트·원문 predicate·
subject-object 관계·`event_id`·`source_line`·STKG 관계는 그대로 남는다.**
어떤 태스크가 왜 빠졌는지는 감사표(`05_data_postprocessing.py`)의 `in_scnx`가
`False`인 행에 사유와 함께 남는다.

### AI Enabled = No 는 task를 막지 않는다

`AIEnabled False`로 둔 328객체 중 294객체가 오류 없이 태스크를 수행했다(같은
로그). 매뉴얼 34.3 그대로 **충돌회피·자동사격·피격반응만 꺼진다.** 계획에 없는
교전으로 시나리오가 일찍 끝나는 것을 막으려면 이대로 두면 된다. 생성기는
`AIEnabled True`로 쓰므로 VR-Forces에서 직접 끈다(사용자 결정 2026-08-04).

## 명부 감축

VR-Forces는 객체 수에서 먼저 막힌다(100개에서 렉으로 작동 불가 실측). 그래서
문제는 "몇 개를 남길까"가 아니라 **"이 수로 몇 개의 task를 살릴까"**다.

`roster.json`의 `target_entities`가 task 가능 객체 총수다(현재 **80**, 정적 7 별도).
그 수 안에서 `roster.py`가 **한계 이득**이 큰 객체부터 뽑는다 — 어떤 객체를 넣었을
때 그 객체 때문에 비로소 성립하는 task 이벤트 수다. 자기가 행위자인 이벤트뿐
아니라 이미 뽑힌 객체가 자기를 표적으로 삼은 이벤트도 함께 세는데, 사격은 쌍이라야
성립하기 때문이다(이 항이 없으면 표적 없는 사수만 남는다).

수확량보다 앞서는 것이 셋 있다. 구조를 지키는 몫이다.

| 제약 | 근거 |
|---|---|
| 교전 유형마다 최소 한 쌍 | STKG 관계 종류가 통째로 사라지지 않게 (라운드로빈) |
| `min_per_type` = 2 | 엔티티 타입 26종 유지 |
| `min_per_unit` = 1 | 이벤트가 적은 부대(지휘소 경계 보병 등)가 비지 않게 |
| `quota` | 사람이 정한 부대별 **상한**. 이보다 많이 뽑지 않는다 |

80개에서 실측: **task 이벤트 185 · 타입 26/26 · 부대 30/30 · 교전 유형 21/21**.
같은 80개를 정원 균등 축소(0.8배)로 뽑으면 task 176 · 교전 유형 17/21, 부대별
id 순으로 뽑으면 task 152 · 교전 유형 10/21이다. 테스트가 이 비교를 지킨다.

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
| G3 | DIS·좌표·uuid·괄호·참조·**무기 실재** 정합성 | 차단 0 · 보고 44 |

`severity`가 `BLOCK`인 위반만 파이프라인을 멈춘다. `REPORT`는 사람이 알아야
하지만 산출을 막지 않는 사실이다.

G0 보고 12건: 최소사거리 미달 2(`C0.1` — 155mm·박격포가 중앙 킬존을 치는
1건씩) · Patriot 미확인 2(`C0.3`) · 지형 미확인 8(`C0.7` — 파생 6 + 이동 2).

G3 보고 44건은 전부 `C3.5`, **일부러 저작하지 않은 태스크**다. 내역은 컨트롤러
없음 42 + 최소사거리 미달 2. `PlanStep.skip_reason`이 붙어 있으면
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
>>>>>>> 06150cb (GT 시간대 안 맞음)

## 테스트

```bash
python -m pytest tests/ -q
```
<<<<<<< HEAD
=======

204개. `conftest.py`가 `sys.path`를 주입한다(경로에 공백·한글이 있어 설치 방식을
쓰지 않는다).
>>>>>>> 06150cb (GT 시간대 안 맞음)
