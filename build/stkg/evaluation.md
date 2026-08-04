# 데이터셋 평가 (20260804)

- 원문: `scenario.txt` — 문장 3,000 · 이벤트 3,000 · 객체 335(task 가능 328 + 정적 7) · 지명 27
- 입력: `build/csv/*_20260804_dataset.csv` → `build/stkg/*_20260804_annotated.csv`

| 항목 | 판정 |
|---|---|
| E1 원문 객체명 == CSV 객체명 | **FAIL** |
| E2 원문 객체 수 == 생성된 객체 수 | **FAIL** |
| E4 모든 객체가 UAV 하나 이상에 관측되었는가 | **FAIL** |
| E5 GT CSV에 모든 객체의 상태 변화가 기록되었는가 | **FAIL** |
| E6 후처리 전후 행 수가 맞는가 | **PASS** |
| E7 후처리 후 object 열이 정상으로 채워졌는가 | **PASS** |

## E1 원문 객체명 == CSV 객체명 — FAIL

```
원문 객체 328 · CSV 객체 329
  FAIL CSV에만 있는 이름 1개: Waypoint 1
  OK   원문에만 있는 이름 0개
  참고 발사체 15종은 원문 객체가 아니다: M107 1, M107 2, M107 3, M107 4, M107 5, M107 6, M107 7, M933HE 1, M933HE 2, M933HE 3, M933HE 4, M933HE 5 … 외 3개
  참고 정적 객체 7개는 .scnx에 안 들어간다: EN-FP-001, EN-FP-002, EN-RT-001, FR-FP-001, FR-FP-002, FR-LN-001, OBJ-009
  참고 지명에 못 붙어 좌표로 남은 대상 2개 — 객체명이 아니라 자리다
```

## E2 원문 객체 수 == 생성된 객체 수 — FAIL

```
원문 사전 335 = task 가능 328 + 정적 7
  FAIL CSV 객체 329 vs 원문 task 가능 328
  파일별: UAV 1 106 · UAV 2 90 · UAV 3 191 · UAV 4 132 · ground_truth 329
```

## E4 모든 객체가 UAV 하나 이상에 관측되었는가 — FAIL

```
UAV 4대 · 관측된 객체 208 / 328 (63.4%)
  FAIL 어느 UAV도 못 본 객체 120개: ENBTR80002, ENCMD001, ENCMD002, ENINF001, ENINF004, ENINF006, ENINF008, ENINF011, ENINF013, ENINF016, ENINF017, ENINF023 … 외 108개
  관측 UAV 수별 객체: 1대 63개 · 2대 47개 · 3대 32개 · 4대 66개
```

## E5 GT CSV에 모든 객체의 상태 변화가 기록되었는가 — FAIL

```
GT 주체 329 · 상태 변화 있는 객체 321
  OK   GT에 아예 없는 객체 0개
  FAIL GT에 있으나 술어가 전부 none인 객체 7개: ENZPU001, ENZPU002, ENZPU003, FRM901001, FRZPU001, FRZPU002, FRZPU003
  GT 술어별 행수: `none` 3,105,653 · `move to` 548,272 · `Follow-Entity` 366,346 · `fired_by` 12,948 · `FFE-on-Location` 9,861 · `find_cover` 5
```

## E6 후처리 전후 행 수가 맞는가 — PASS

```
  OK   UAV 1          전     5,501 = 후     5,501 + 삭제       0 (규칙상 삭제 대상 0)
  OK   UAV 2          전     1,581 = 후     1,581 + 삭제       0 (규칙상 삭제 대상 0)
  OK   UAV 3          전     3,400 = 후     3,400 + 삭제       0 (규칙상 삭제 대상 0)
  OK   UAV 4          전     3,339 = 후     3,339 + 삭제       0 (규칙상 삭제 대상 0)
  OK   ground_truth   전 4,107,509 = 후 4,043,085 + 삭제  64,424 (규칙상 삭제 대상 64,424)
  행 수가 그대로인 파일 4개: UAV 1, UAV 2, UAV 3, UAV 4
  줄어든 파일: ground_truth -64,424 — 시뮬레이터 인프라 객체(N Force/Observer/GlobalEnv)와 일괄 스폰 효과(E숫자), 1970 타임스탬프 행이다
```

## E7 후처리 후 object 열이 정상으로 채워졌는가 — PASS

```
  OK   UAV 1          대상 필요     4,424행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   UAV 2          대상 필요     1,466행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   UAV 3          대상 필요     3,197행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   UAV 4          대상 필요     3,136행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  OK   ground_truth   대상 필요   924,484행 · 빈 곳 0 · 비어야 하는데 찬 곳 0
  참고 fired_by 중 사수를 확정 못 해 비운 행 13,324개 — 억지로 채우지 않는 설계라 위반이 아니다
```

