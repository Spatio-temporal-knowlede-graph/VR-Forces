# 데이터셋 평가 (20260809_175237)

- 원문: `scenario.txt` — 문장 3,000 · 이벤트 3,000 · 객체 335(task 가능 328 + 정적 7) · 지명 27
- 입력: `build/csv/*_20260809_175237_dataset.csv` → `build/stkg/*_20260809_175237_annotated.csv`

| 항목 | 판정 |
|---|---|
| E1 원문 객체명 == CSV 객체명 | **PASS** |
| E2 원문 객체 수 == 생성된 객체 수 | **PASS** |
| E4 모든 객체가 UAV 하나 이상에 관측되었는가 | **FAIL** |
| E5 GT CSV에 모든 객체의 상태 변화가 기록되었는가 | **FAIL** |
| E6 후처리 전후 행 수가 맞는가 | **PASS** |
| E7 후처리 후 object 열이 정상으로 채워졌는가 | **PASS** |

## E1 원문 객체명 == CSV 객체명 — PASS

```
원문 객체 328 · CSV 객체 328
  OK   CSV에만 있는 이름 0개
  OK   원문에만 있는 이름 0개
  참고 발사체 13종은 원문 객체가 아니다: M107 1, M107 2, M107 3, M107 4, M107 5, M933HE 1, M933HE 2, M933HE 3, M933HE 4, M933HE 5, M933HE 6, M933HE 7 … 외 1개
  참고 정적 객체 7개는 .scnx에 안 들어간다: EN-FP-001, EN-FP-002, EN-RT-001, FR-FP-001, FR-FP-002, FR-LN-001, OBJ-009
  참고 통제점 12개는 객체가 아니라 자리다: P1, P10, P11, P2, P3, P4, P5, P6, P7, P8, P9, Waypoint 1
```

## E2 원문 객체 수 == 생성된 객체 수 — PASS

```
원문 사전 335 = task 가능 328 + 정적 7
  OK   CSV 객체 328 vs 원문 task 가능 328
  파일별: UAV 1 115 · UAV 2 96 · UAV 3 126 · UAV 4 129 · ground_truth 328
```

## E4 모든 객체가 UAV 하나 이상에 관측되었는가 — FAIL

```
UAV 4대 · 관측된 객체 154 / 328 (47.0%)
  FAIL 어느 UAV도 못 본 객체 174개: ENCMD001, ENCMD002, ENINF001, ENINF002, ENINF003, ENINF004, ENINF005, ENINF006, ENINF007, ENINF008, ENINF009, ENINF010 … 외 162개
  관측 UAV 수별 객체: 1대 29개 · 2대 29개 · 3대 6개 · 4대 90개
```

## E5 GT CSV에 모든 객체의 상태 변화가 기록되었는가 — FAIL

```
GT 주체 328 · 상태 변화 있는 객체 320
  OK   GT에 아예 없는 객체 0개
  FAIL GT에 있으나 술어가 전부 none인 객체 8개: ENZPU001, ENZPU002, ENZPU003, FRM901001, FRMORT004, FRZPU001, FRZPU002, FRZPU003
  GT 술어별 행수: `none` 676,976 · `move to` 186,609 · `Follow-Entity` 149,499 · `Wait-Duration` 8,400 · `FFE-on-Location` 3,340 · `fired_by` 905 · `Fire-Weapon` 650 · `find_cover` 3
```

## E6 후처리 전후 행 수가 맞는가 — PASS

```
  OK   UAV 1          전    18,992 = 후    18,992 + 삭제       0 (규칙상 삭제 대상 0)
  OK   UAV 2          전    18,757 = 후    18,757 + 삭제       0 (규칙상 삭제 대상 0)
  OK   UAV 3          전    24,581 = 후    24,581 + 삭제       0 (규칙상 삭제 대상 0)
  OK   UAV 4          전    24,675 = 후    24,675 + 삭제       0 (규칙상 삭제 대상 0)
  OK   ground_truth   전 1,041,488 = 후 1,026,382 + 삭제  15,106 (규칙상 삭제 대상 15,106)
  행 수가 그대로인 파일 4개: UAV 1, UAV 2, UAV 3, UAV 4
  줄어든 파일: ground_truth -15,106 — 시뮬레이터 인프라 객체(N Force/Observer/GlobalEnv)와 일괄 스폰 효과(E숫자), 1970 타임스탬프 행이다
```

## E7 후처리 후 object 열이 정상으로 채워졌는가 — PASS

```
  OK   UAV 1          대상 필요    11,248행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   UAV 2          대상 필요    10,928행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   UAV 3          대상 필요    17,020행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   UAV 4          대상 필요    17,334행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   ground_truth   대상 필요   340,101행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  참고 fired_by 중 사수를 확정 못 해 비운 행 2,082개 — 억지로 채우지 않는 설계라 위반이 아니다
```

