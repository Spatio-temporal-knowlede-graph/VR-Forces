# new_VTMAK

`scenario_v3.txt` → VR-Forces 4.9 `.scnx` 자동 생성 파이프라인.

**혼자 고치고 돌리려면 → [`RUNBOOK.md`](RUNBOOK.md)** (문장 틀, 수정 레시피, 게이트 대처)

설계 근거: [`../docs/superpowers/specs/2026-08-02-new-vtmak-scnx-pipeline-design.md`](../docs/superpowers/specs/2026-08-02-new-vtmak-scnx-pipeline-design.md)

## 실행

```bash
python scripts/01_harvest_layout.py     # golden 통제점 → 레이아웃
python scripts/02_parse_events.py       # 원문 → 이벤트   (+G1, G0)
python scripts/03_build_timetable.py    # 이벤트 → 타임테이블 (+G2)
python scripts/04_compile_scnx.py       # 스펙 → PLN → .scnx (+G0, G3)
```

01은 golden 통제점을 옮겼거나 `layout_rules.json`을 고쳤을 때만 다시 돌리면 된다.

산출(명부 감축 후):

| 파일 | 내용 |
|---|---|
| `build/events/battle.jsonl` | 이벤트 710건 |
| `build/timetable/battle.csv` | 셀 366개 |
| `build/scnx/battle.scnx` | 엔티티 70 · 통제점 21 · 태스크 171 |

같은 입력이면 항상 같은 바이트가 나온다.

## VR-Forces에서 열 때 (필수)

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
| `layout_rules.json` | golden 이름 맞춤(alias) + 파생 지점 규칙 + 정적객체 바인딩 |
| `battlefield_layout.json` | **생성물.** 지명 29개 실좌표. 손으로 고치지 말 것 |
| `weapon_ranges.csv` | 모델 26종 → 직접/간접 사거리 |
| `pattern_map.csv` | 문장 템플릿·이동행동 → STKG 술어 + task_kind |
| `entity_class_map.csv` | 모델 → type_group + 무장 |
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
읽으면 전부 뒤집힌다(23곳 중 22곳이 축을 따른다). 파생 지점은 지형이 확인되지
않았으므로 G0가 `C0.7`로 알린다.

교전 거리는 초기 배치가 아니라 **교전 시점**의 위치로 잰다. 적 보병은 집결지에서
출발하지만 교전 시점에는 중앙 킬존까지 내려와 있다. 목표 위치는 원문의 피격
문장을 정본으로 쓴다.

**155mm 자주포 3종의 최소사거리 2 km는 지금 배치에서 만족되지 않는다.** golden
통제점이 만드는 범위가 2.5×2.5 km라 중앙 킬존에서 2 km 떨어진 자리가 없다.
`weapon_ranges.csv`의 `min_severity=REPORT`로 내려 산출은 내되 6건을 보고한다
(사용자 결정 2026-08-03). VR-Forces가 실제로 최소사거리 미달 사격을 거부하면
이 포병들은 사격하지 않는다 — 그때는 진지를 2 km 밖으로 다시 찍어야 한다.

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
| G0 | 모든 교전 쌍이 사거리 안 + 좌표 출처 | 차단 0 · 보고 16 |
| G1 | 3,000문장 전부 매칭 | 위반 0 |
| G2 | task 가능 객체 전원 플랜 보유 | 위반 0 |
| G3 | DIS·좌표·uuid·괄호·참조·**무기 실재** 정합성 | 차단 0 · 보고 4 |

`severity`가 `BLOCK`인 위반만 파이프라인을 멈춘다. `REPORT`는 사람이 알아야
하지만 산출을 막지 않는 사실이다.

G0 보고 16건의 내역: 155mm 최소사거리 미달 8(`C0.1`) · Patriot 미확인 2(`C0.3`)
· 파생 지점 지형 미확인 6(`C0.7`). **G3 보고 4건은 전부 Patriot 2종**(`FR-M901-001`, `EN-MIM-001`)이다. VR-Forces에서
이들의 지상 간접사격이 성립하는지 확인되지 않아 `미분류`로 두었고 태스크를
만들지 않는다. 확인되면 `entity_class_map.csv`의 `type_group`과
`weapon_ranges.csv`의 `unverified`를 고치면 된다. (참고: golden 실측으로 Patriot 2종의
무기 이름이 `Patriot Missile Launcher`인 것은 확인됐다. 남은 미확인은 지상 간접사격
성립 여부다.)

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

123개. `conftest.py`가 `sys.path`를 주입한다(경로에 공백·한글이 있어 설치 방식을
쓰지 않는다).
