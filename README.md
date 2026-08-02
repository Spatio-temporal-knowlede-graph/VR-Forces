# new_VTMAK

`scenario_v3.txt` → VR-Forces 4.9 `.scnx` 자동 생성 파이프라인.

설계 근거: [`../docs/superpowers/specs/2026-08-02-new-vtmak-scnx-pipeline-design.md`](../docs/superpowers/specs/2026-08-02-new-vtmak-scnx-pipeline-design.md)

## 실행

```bash
python scripts/02_parse_events.py       # 원문 → 이벤트   (+G1, G0)
python scripts/03_build_timetable.py    # 이벤트 → 타임테이블 (+G2)
python scripts/04_compile_scnx.py       # 스펙 → PLN → .scnx (+G0, G3)
```

산출:

| 파일 | 내용 |
|---|---|
| `build/events/battle.jsonl` | 이벤트 2,999건 |
| `build/timetable/battle.csv` | 셀 1,600개 |
| `build/scnx/battle.scnx` | 약 7분, 엔티티 328 · 통제점 23 · 태스크 665 |

같은 입력이면 항상 같은 바이트가 나온다.

## VR-Forces에서 열 때 (필수)

**Ground Clamping을 반드시 켤 것.** 객체 좌표는 위경도만 결정적이고 고도는
0이라, 켜지 않으면 지형에 따라 땅속이나 공중에 배치된다.

1. `Settings → Ground Clamping`
2. **Ground Clamping Cutoff Distance Scale을 최대로**

## 입력

파이프라인이 읽는 시나리오 입력은 `scenario_original/scenario_v3.txt` **단독**이다.
`시나리오_원문.md`와 배치도 PNG는 사람이 보는 참고 자료이며 코드가 참조하지 않는다.

golden은 `yewon_test/` 디렉터리다. `.scnx`(ZIP)는 저장소에 두지 않고
`vtmak.scnx.pack.ensure_golden`이 필요할 때 결정적으로 만든다.

## config

| 파일 | 내용 |
|---|---|
| `battlefield_layout.json` | 지명 27개 로컬 미터 좌표 + 정적객체 7개 바인딩 |
| `weapon_ranges.csv` | 모델 26종 → 직접/간접 사거리 |
| `pattern_map.csv` | 문장 템플릿·이동행동 → STKG 술어 + task_kind |
| `entity_class_map.csv` | 모델 → type_group + 무장 |
| `dis_catalog.csv` | 모델 → DIS 7튜플 |
| `task_catalog.csv` | (type_group, 행동) → `.pln` S-expression 템플릿 |

어휘를 코드에 하드코딩하지 않는다. 지명·모델·사거리·술어는 전부 여기서 온다.

## 좌표

지명 좌표는 golden 지형점 앵커링이 아니라 시나리오 기하를 로컬 미터로 선언한
`battlefield_layout.json`에서 나온다(북 = +y, 동 = +x). 이유는 설계 스펙 §3에 있다.

**지형이 좁아 배치가 안 들어가면** `scale`을 낮춘다. 다만 **0.71 미만으로 내리면**
M109 최소사거리 2 km가 깨져 G0가 차단한다. 그게 축소 하한이다(테스트로 확인:
0.75 통과 / 0.70 차단).

교전 거리는 초기 배치가 아니라 **교전 시점**의 위치로 잰다. 적 보병은 집결지에서
출발하지만 교전 시점에는 중앙 킬존까지 내려와 있다. 목표 위치는 원문의 피격
문장을 정본으로 쓴다.

## 검증 게이트

| 게이트 | 조건 | 현재 |
|---|---|---|
| G0 | 모든 교전 쌍이 사거리 안 | 차단 0 · 보고 2 |
| G1 | 3,000문장 전부 매칭 | 위반 0 |
| G2 | task 가능 328객체 전원 플랜 보유 | 위반 0 |
| G3 | DIS·좌표·uuid·괄호·참조 정합성 | 차단 0 · 보고 4 |

`severity`가 `BLOCK`인 위반만 파이프라인을 멈춘다. `REPORT`는 사람이 알아야
하지만 산출을 막지 않는 사실이다.

**현재 보고 6건은 전부 Patriot 2종**(`FR-M901-001`, `EN-MIM-001`)이다. VR-Forces에서
이들의 지상 간접사격이 성립하는지 확인되지 않아 `미분류`로 두었고 태스크를
만들지 않는다. 확인되면 `entity_class_map.csv`의 `type_group`과
`weapon_ranges.csv`의 `unverified`를 고치면 된다.

## 테스트

```bash
python -m pytest tests/ -q
```

92개. `conftest.py`가 `sys.path`를 주입한다(경로에 공백·한글이 있어 설치 방식을
쓰지 않는다).
