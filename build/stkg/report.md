# 시뮬레이터 CSV 후처리 보고

입력 파일 하나당 출력 파일 하나. 열은 내보내기가 준 8열 그대로다.
행은 시뮬레이터 인프라 객체만 지운다.

## ground_truth_20260803_dataset.csv

- 출력: `ground_truth_20260803_annotated.csv`
- 입력 행 126,718 = 출력 행 121,646 + 삭제 행 5,072 (맞음)
- object 채워진 행: 92,409
- 발사체 행 104 중 사수 확정 104

### 술어별 행수

- `move to`: 59,516
- `Follow-Entity`: 31,920
- `none`: 29,237
- `FFE-on-Location`: 868
- `fired_by`: 104
- `find_cover`: 1

### 삭제한 객체

- 2 Force (drop_infra): 862행
- 1 Force (drop_infra): 862행
- 3 Force (drop_infra): 862행
- GlobalEnv 1 (drop_infra): 862행
- Observer 1 (drop_infra): 857행
- Observer 2 (drop_infra): 767행

### 확정된 fired_by

- [GROUND_TRUTH] `M933HE 1` → `ENMORT001` (탄착 88.5m(2등 719.9m) · 포구 26.7m · FFE 종료 2026-08-03T08:09:21.000Z)
- [GROUND_TRUTH] `M933HE 2` → `ENMORT002` (탄착 49.0m(2등 708.7m) · 포구 28.8m · FFE 종료 2026-08-03T08:09:21.000Z)
- [GROUND_TRUTH] `M933HE 3` → `FRMORT003` (탄착 155.6m(2등 1005.5m) · 포구 47.7m · FFE 종료 2026-08-03T08:09:21.000Z)
- [GROUND_TRUTH] `M933HE 4` → `FRMORT001` (탄착 87.6m(2등 902.9m) · 포구 26.3m · FFE 종료 2026-08-03T08:09:21.000Z)

## UAV 1_20260803_dataset.csv

- 출력: `UAV 1_20260803_annotated.csv`
- 입력 행 1,227 = 출력 행 1,227 + 삭제 행 0 (맞음)
- object 채워진 행: 683
- 발사체 행 0 중 사수 확정 0

### 술어별 행수

- `move to`: 606
- `none`: 544
- `FFE-on-Location`: 77

## UAV 2_20260803_dataset.csv

- 출력: `UAV 2_20260803_annotated.csv`
- 입력 행 1,281 = 출력 행 1,281 + 삭제 행 0 (맞음)
- object 채워진 행: 800
- 발사체 행 9 중 사수 확정 0

### 술어별 행수

- `move to`: 722
- `none`: 472
- `FFE-on-Location`: 78
- `fired_by`: 9

### 확정하지 못한 발사체 (object 비움)

- [UAV 2] M933HE 1: 첫 관측(2026-08-03T22:00:12.372Z) 전에 FFE가 끝난 표적 하나짜리 사수 없음
- [UAV 2] M933HE 2: 첫 관측(2026-08-03T22:00:12.372Z) 전에 FFE가 끝난 표적 하나짜리 사수 없음
- [UAV 2] M933HE 3: 첫 관측(2026-08-03T22:00:36.720Z) 전에 FFE가 끝난 표적 하나짜리 사수 없음

## UAV 3_20260803_dataset.csv

- 출력: `UAV 3_20260803_annotated.csv`
- 입력 행 609 = 출력 행 609 + 삭제 행 0 (맞음)
- object 채워진 행: 576
- 발사체 행 0 중 사수 확정 0

### 술어별 행수

- `move to`: 571
- `none`: 33
- `FFE-on-Location`: 5

## UAV 4_20260803_dataset.csv

- 출력: `UAV 4_20260803_annotated.csv`
- 입력 행 688 = 출력 행 688 + 삭제 행 0 (맞음)
- object 채워진 행: 656
- 발사체 행 0 중 사수 확정 0

### 술어별 행수

- `move to`: 649
- `none`: 32
- `FFE-on-Location`: 7

