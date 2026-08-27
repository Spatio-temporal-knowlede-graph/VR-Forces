# VR-Forces 상호작용 task 보강 설계

## 1. 목적

현재 시나리오는 원문의 사건을 객체별 PLN으로 변환하지만, 실제 VR-Forces 실행에서는 직접사격과 엄폐 같은 상호작용 task의 실행률이 낮다. 특히 같은 행의 반복 기록이 많아도 고유한 `(subject, predicate, object)` 조합은 적다.

이번 변경의 목적은 객체 수를 늘리지 않고 다음을 달성하는 것이다.

1. VR-Forces에서 끝까지 실행 가능한 객체별 task 큐를 만든다.
2. 직접사격과 제압사격을 한 교전 안의 연속된 두 단계로 유지한다.
3. task가 적은 기존 무장 객체를 신규 직접사격의 표적으로 활용한다.
4. GT에서 고유 `Fire-Weapon` 및 `Provide-Suppressive-Fire-Loc` 관계를 충분히 확보한다.
5. 사격 GT에는 시뮬레이터에서 직접 보이는 task 관계만 저장한다.

행 수를 늘리는 것 자체는 성공으로 보지 않는다. 주 성공 지표는 서로 다른 공격자와 표적이 만드는 **고유 SPO 수**다.

## 2. 확인된 현황

현재 입력 이벤트에는 `directFireAt`이 77건 있다. 그러나 `vtmak/scnx/spec.py::suppression_events`와 `vtmak/scnx/plan.py::build_entity_plan`은 이 중 표적이 제압 상태가 되는 51건을 `fire-at-target`에서 `provide_suppressive_fire_loc`으로 **대체**한다. 결과적으로 PLN에는 `fire-at-target` 26건과 제압사격 51건이 서로 배타적으로 생성된다.

실행 결과에서는 다음 문제가 확인됐다.

- 계획된 `fire-at-target` 26개 객체 중 GT에서 `Fire-Weapon`이 확인된 주체는 4개다.
- `provide_suppressive_fire_loc`은 `vtmak/stkg/predicate.py`에서 파싱되지만 `vtmak/stkg/rewrite.py::_NAME`에 정규형 매핑이 없어 최종 술어로 정상 저장되지 않는다.
- `find_firing_position`은 계획 21건 전부 컨트롤러 비활성 오류로 실패했다.
- `find_cover`는 계획 59건 중 GT에서 한 객체만 확인됐고, 다수 모델에서 컨트롤러 비활성 오류가 발생했다.
- `follow-entity`는 실행되면 계속 유지되어 뒤에 배치된 사격·엄폐 task가 도달 불가능해질 수 있다.
- PLN에는 절대 시각 트리거가 없고 객체별 task가 즉시 순차 실행되므로, 원문 사건 시각과 실제 task 시작 시각이 크게 어긋날 수 있다.

부대·편제 기반 파생 관계는 이미 제거됐다. 현재 `vtmak/derive/`는 객체·이벤트 수준의 R1–R4·R7만 유지하며, 옛 `partOf`, `supports`, `reinforces`, `unitSuppressed`, 부대 수준 `movesToward`, `occupies`, `firesUpon`은 생성하지 않는다. 이번 변경은 이 상태를 유지하는 회귀 검증을 추가하고, 피격과 상태 전환을 합성하던 R1 `suppresses`는 최종 관계 산출에서 제외한다.

## 3. 범위

### 포함

- 기존 직접사격 77건을 교전 슬롯으로 변환
- `fire-at-target` 뒤에 유한한 `provide_suppressive_fire_loc`을 배치
- 저-task 무장 객체를 표적으로 하는 신규 교전 슬롯 20~30건 생성
- 종료되지 않는 `follow-entity` 뒤에 상호작용 task가 놓이지 않도록 큐 재작성
- `find_firing_position` 및 `find_cover`을 사전 계산 좌표로 향하는 `move-to` 계열 task로 대체
- 제압사격 술어 정규화
- 정적 감사 보고서와 시뮬레이션 후 GT 평가 항목 추가

### 제외

- 신규 객체 생성
- UAV 위치, 순찰 경로, 계획 또는 관측 로직 변경
- 간접사격 `FFE-on-Location` 제거 또는 직접사격으로 대체
- VR-Forces 런타임 플러그인이나 새로운 트리거 시스템 도입
- 공간 관계 확장 모듈 변경
- 원문 이벤트 정본 `build/events/battle.jsonl`에 보강 사건을 원문 사건인 것처럼 삽입
- GT 또는 최종 STKG에 객체 간 `suppresses` 관계 생성

UAV CSV는 이번 변경으로 인해 우연히 달라질 수 있으나 합격 기준에 포함하지 않는다. 고정 UAV 계획과 관련 설정은 바이트 수준 회귀 검증 대상으로 둔다.

## 4. 핵심 구조: 교전 슬롯

원문 이벤트를 바로 PLN 블록으로 내리지 않고, 직접사격에 한해 중간 표현인 `EngagementSlot`을 만든다.

```text
EngagementSlot
  slot_id
  origin                 source | enrichment
  source_event_ids
  scheduled_time_s
  shooter_id
  target_id
  shooter_position
  target_position
  firing_position
  direct_fire_rounds
  suppress_duration_s
  suppress_ammo_limit
  target_task_count
  provenance
```

`origin=source`는 기존 `directFireAt` 77건을 나타낸다. `origin=enrichment`는 새로 만든 20~30개 교전이다. 보강 슬롯은 원문 사건이 아니므로 원문 이벤트 JSONL에 섞지 않고, 별도 산출물 `build/engagements/slots.jsonl`에 기록한다.

`slot_id`는 입력과 설정으로부터 결정적으로 생성한다. 후보 순회와 동률 해소는 객체 ID와 사건 ID의 정렬 순서를 사용하여 같은 입력에서 같은 PLN과 슬롯 파일이 나오게 한다.

## 5. 기존 교전 변환

현재의 “직접사격 또는 제압사격” 변환을 없애고 모든 직접사격 슬롯을 다음 두 단계로 내린다.

```text
필요 시 사전 계산된 사격 지점으로 move-to
→ 사건 시각을 맞추기 위한 유한 wait-duration
→ fire-at-target(max-rounds-to-fire=1)
→ provide_suppressive_fire_loc(durationTotal 제한, ammoLimit 제한)
→ 다음 task
```

`fire-at-target`은 표적 객체 UUID를 사용한다. 제압사격은 같은 슬롯의 표적이 해당 시각에 있던 좌표를 사용한다. 직접사격 뒤 표적이 파괴되더라도 제압사격은 마지막으로 계산된 표적 위치를 향하므로 두 번째 단계가 표적 생존에 의존하지 않는다.

기존 task 템플릿에 있는 `max-rounds-to-fire=1`은 유지한다. 제압사격의 현재 기본값인 60초·100발은 큐 정체와 표적 과잉 피해를 유발할 수 있으므로 `durationRapid=5초`, `durationTotal=10초`, `ammoLimit=10발`로 낮춘다. 세 값은 이미 수확된 템플릿에 존재하는 필드만 치환한다.

## 6. 신규 교전 생성

### 6.1 공격자 후보

공격자는 다음 조건을 모두 만족해야 한다.

- taskable 전투 객체이며 UAV·통제점·발사체가 아님
- 실제 직접사격 무기가 `entity_class_map.csv`에 등록됨
- `weapon_ranges.csv`에서 직접사격 사거리를 확인할 수 있음
- `fire-at-target`과 제압사격 템플릿을 해당 `type_group`에서 생성할 수 있음
- 슬롯 이전에 `noTask`가 선언되지 않음
- 슬롯 시점까지 선행 task가 유한하게 종료 가능함
- 이미 배정된 신규 슬롯 수가 공격자별 상한을 넘지 않음

### 6.2 표적 후보

표적은 다음 조건을 모두 만족해야 한다.

- 공격자와 반대 진영인 기존 무장 객체
- 원문에서 부여된 실행 가능 task 수가 적은 객체를 우선함
- UAV·통제점·발사체가 아님
- 기존 task가 남아 있다면 마지막 task 이후에 교전하도록 예약 가능함
- 해당 시점에 이미 다른 교전으로 파괴·무력화될 예정인 표적이 아님
- 동일한 신규 교전의 표적으로 이미 사용되지 않음

기본 정책은 신규 교전에서 표적당 1회, 공격자당 최대 2회다. 후보가 부족할 때 동일 `(공격자, 표적)` 쌍을 반복하여 목표 수를 채우지 않는다. 20개 고유 쌍을 만들 수 없으면 컴파일을 실패시키고 후보 부족 이유를 보고한다.

### 6.3 배정 순서

1. 표적을 실행 가능 task 수, 마지막 task 시각, 객체 ID 순으로 정렬한다.
2. 공격자를 현재 배정 수, 원문 직접사격 수, 객체 ID 순으로 정렬한다.
3. 반대 진영, 고유 쌍, 상한, 사거리 조건을 만족하는 첫 쌍을 선택한다.
4. 표적의 마지막 원문 task 이후로 슬롯 시각을 잡고 전체 시나리오 구간에 분산한다.
5. 필요하면 공격자만 사전 계산 사격 지점으로 이동시킨다. 표적의 기존 이동은 바꾸지 않는다.

표적 위치가 후처리에서 같은 `LOC_*`로 합쳐질 수 있으므로 `(공격자, 표적 객체)`뿐 아니라 예상 `(공격자, 정규화된 표적 위치)`도 함께 센다. 이미 선택된 슬롯과 같은 제압사격 SPO가 될 후보는 후순위로 미룬다. 전체 슬롯에서 예상되는 고유 `Provide-Suppressive-Fire-Loc` SPO가 70개보다 적으면 정적 감사에 실패한다.

위 절차는 무작위 선택을 사용하지 않는다.

## 7. 시간과 task 도달 가능성

현재 PLN은 객체별 큐를 즉시 실행하므로 사건의 `time_s`만 정렬해도 절대 시각이 보장되지 않는다. 각 객체에 대해 앞선 task의 예상 종료 시각을 누적하고, 다음 슬롯까지 남은 시간만큼 유한 `wait-duration`을 삽입한다.

이 예상 시간은 시뮬레이션의 완전한 실행시간 예측이 아니라 도달 가능성을 확보하기 위한 정적 스케줄이다. 이동 거리는 설정 속도로 나누고, 고정 지속시간 task는 템플릿의 duration을 사용한다. 실행시간을 계산할 수 없는 task는 뒤에 교전 슬롯을 놓지 않는다.

### `follow-entity`

현재 수확된 `follow-entity` 템플릿에는 검증된 시간·거리 종료 필드가 없다. 따라서 이번 구현에서는 다음 규칙으로 고정한다.

- 뒤에 다른 task가 없는 객체만 기존 무기한 follow를 유지한다.
- 뒤에 사격·엄폐·이동 등 후속 task가 있는 객체의 follow는 선두의 해당 시각 예상 위치로 향하는 유한 `move-to`로 내린다.
- 감사 단계에서 무기한 follow 뒤에 후속 task가 하나라도 있으면 빌드를 실패시킨다.

향후 VR-Forces에서 실제 동작하는 종료 필드를 수확하더라도 별도 설계 변경 없이 이번 구현에 추정 필드를 추가하지 않는다.

관계를 풍성하게 보이게 하려고 실행되지 않는 `Follow-Entity`를 남기지 않는다.

## 8. 실패 task 대체

### `find_firing_position`

현재 21/21 실패하므로 PLN에서 완전히 제거한다. 위협 객체 또는 후속 사격 표적과 사거리 조건을 이용해 사격 위치를 컴파일 시 계산하고, 그 좌표로 향하는 `move-to-location-task` 또는 검증된 `move-to` 템플릿을 사용한다.

### `find_cover`

현재 모델별 컨트롤러 성공률이 낮으므로 같은 방식으로 엄폐 지점을 사전 계산한다. 위협에서 멀어지는 방향과 전장 경계를 만족하는 golden 지형점을 선택해 그 지점 자체로 향하는 이동 task로 내린다.

**개정 2026-08-27 (사용자 결정).** 초판은 여기에 "객체 간 최소 이격"을 지점 선택 조건으로 함께 걸었다. 그 조건은 이 전장에서 만족할 수 없다 — golden 지형점이 21개인데 피격 사건은 77건이고, 가장 가까운 두 지점 사이가 246m다. 지점 선택 필터로 쓰면 엄폐를 만들지 못하고 지우기만 한다(실측: 배치 좌표 기준 50/77, 목적지 예약 기준 2/77).

지점 안에서 객체를 흩어 이격을 만드는 방식도 폐기한다. 그렇게 하면 목적지가 지명에서 15~90m 벗어나고, 후처리의 `snap`은 1m 이내만 지명으로 접으므로 엄폐 목적지 52개 중 50개가 GT에서 이름 없는 좌표 노드가 된다(실측). 고유 SPO의 주어·목적어가 의미를 가져야 한다는 이 프로젝트의 목표와 정면으로 어긋난다.

**목적지 안에서 객체가 어디에 서는지는 VR-Forces가 정한다.** 우리가 아는 척하지 않는다 — 이는 배치·사격 좌표에 대해 이 저장소가 이미 지키는 원칙과 같다(README "목적지 안에서 어디에 서는지는 VR-Forces가 정하므로 아는 척하면 G0와 어긋난다"). 따라서 엄폐 지점 선택에 객체 간 이격 조건을 걸지 않고, 여러 객체가 같은 지점으로 향하는 것을 허용한다.

두 경우 모두 GT에서 실행되지 않은 `find_*` 술어를 관측 사실처럼 유지하지 않는다. 대신 슬롯 또는 계획 감사 자료에 다음 의도를 남긴다.

```text
planned_intent = takes_firing_position_against | takes_cover_from
intent_object = 위협 객체 ID
executed_task = move-to
```

이 의도는 계획·감사 정보이며 관측 GT와 분리한다.

## 9. 관계 저장 계약

### 9.1 관측 GT

시뮬레이터가 내보낸 task 관측은 다음 두 관계로 정규화한다.

```text
(공격자, Fire-Weapon, 표적 객체)
(공격자, Provide-Suppressive-Fire-Loc, 표적 위치)
```

이를 위해 `vtmak/stkg/rewrite.py::_NAME`에 `predicate.py`가 반환하는 제압사격 내부 이름의 정규형 매핑을 추가한다. 좌표 목적어는 기존 `snap` 경로를 사용하여 가능한 경우 `LOC_*` 이름으로 바꾸고, 불가능하면 좌표 문자열을 유지한다.

두 술어는 모두 시뮬레이터가 실행 중인 task를 직접 보고한 값이다. `Fire-Weapon`은 객체 대 객체 관계이고, `Provide-Suppressive-Fire-Loc`은 객체 대 위치 관계다. `FFE-on-Location`과 제압사격은 모두 위치 대상 사격이지만 간접 화력타격과 직접 제압사격이라는 실행 의미가 다르므로 합치지 않는다. 조회 계층에서만 둘을 `Fires-At-Location`의 하위 유형으로 묶고, GT에 `Fires-At-Location` 중복 행을 추가하지 않는다.

이번 보강 외의 기존 관측 술어는 그대로 유지한다. “두 관계만 저장”은 이번 사격 보강이 새로 다루는 관계가 이 둘뿐이라는 뜻이며, 이동·대기·FFE 같은 기존 관측 술어를 삭제한다는 뜻이 아니다.

### 9.2 `suppresses`를 저장하지 않는 이유

위치 기반 제압 task 자체에는 표적 객체 UUID가 없다. 또한 제압사격을 수행했다는 사실만으로 특정 객체가 실제로 제압됐다고 단정할 수 없다. 슬롯의 표적 ID를 붙이거나 피격과 상태 변화를 조인하려면 관측 이외의 연결 규칙이 필요하므로, 이는 “눈에 직접 보이는 이벤트 중심 GT” 원칙에 맞지 않는다.

따라서 슬롯 기반 `suppresses` 매칭 모듈은 만들지 않고, 기존 원문 기반 R1 `suppresses`도 최종 관계 산출에서 제외한다. 표적의 제압 상태를 직접 저장할 필요가 생기면 `(표적, Has-State, Suppressed)`처럼 객체 자신의 상태로 표현하되, 공격자와의 인과관계로 바꾸는 작업은 별도 설계로 다룬다. 이번 구현에는 새 `Has-State` 술어도 추가하지 않는다.

## 10. 부대·편제 관계

다음 관계는 계속 생성하지 않는다.

- `partOf`
- `supports`
- `reinforces`
- `unitSuppressed`
- 부대가 주어인 `movesToward`, `occupies`, `firesUpon`

현재 제거 상태를 회귀 테스트로 고정한다. 객체 수준 `damages`, 지역 대상 `firesUpon`, 사건 수준 `causes`, `precedes`는 유지한다. 객체 간 `suppresses`는 부대·편제 관계는 아니지만 관측 전용 GT 원칙에 따라 최종 산출에서 제외한다.

## 11. 설정과 산출물

보강 수치와 상한은 코드에 박지 않고 새 설정 파일에 둔다. 제안 위치는 `config/engagement_enrichment.json`이다.

주요 설정은 다음과 같다.

```text
enabled
min_new_unique_pairs = 20
target_new_unique_pairs = 25
max_new_unique_pairs = 30
max_slots_per_shooter = 2
max_slots_per_target = 1
direct_fire_rounds = 1
suppress_rapid_duration_s = 5
suppress_duration_s = 10
suppress_ammo_limit = 10
minimum_observation_duration_s = 3
slot_spacing_s = 15
```

새 산출물은 다음과 같다.

- `build/engagements/slots.jsonl`: 모든 기존·보강 교전 슬롯과 provenance
- `build/engagements/audit.csv`: 후보 제외, task 도달 불가, 사거리 실패 등
- 기존 `build/scnx/battle.scnx`: 변경된 실행 시나리오
- 시뮬레이션 후 기존 GT CSV: 두 관측 술어 포함

## 12. 오류 처리

다음은 경고가 아니라 컴파일 실패다.

- 신규 고유 교전 쌍을 최소 20개 만들지 못함
- 정규화될 것으로 예상되는 고유 `Provide-Suppressive-Fire-Loc` SPO가 70개 미만
- 동일 `slot_id` 또는 동일 신규 `(shooter_id, target_id)` 중복
- 슬롯 공격자·표적이 같은 진영
- 공격자에게 유효한 직접사격 무기 또는 task 템플릿이 없음
- `fire-at-target`과 제압사격 사이에 다른 task가 삽입됨
- 무기한 follow 뒤에 후속 task가 존재함
- 최종 PLN에 `find_firing_position` 또는 `find_cover`가 남음
- task 템플릿 placeholder가 치환되지 않거나 괄호가 불균형함

후보 하나가 사거리·생존·스케줄 조건을 만족하지 못하는 것은 감사표에 사유를 남기고 다음 후보를 시도한다. 최소 목표에 도달할 수 없을 때만 전체 컴파일을 실패시킨다.

## 13. 검증

### 단위 테스트

- 제압 상태가 되는 직접사격도 `fire-at-target`과 제압사격 두 블록을 모두 생성
- 슬롯 생성의 결정성, 고유 쌍, 진영, 상한, 최소 20개 조건
- 저-task 표적 우선순위와 표적의 마지막 task 이후 배치
- 유효 사거리의 사격 지점 계산
- 무기한 follow 뒤 후속 task 금지
- `find_firing_position`과 `find_cover`의 이동 task 변환
- `Provide-Suppressive-Fire-Loc` 정규화와 좌표 snap
- GT와 최종 관계 산출물에 `suppresses`가 나타나지 않음
- 부대·편제 술어가 파생 관계에 다시 나타나지 않음

### 통합 테스트

- `scripts/01`부터 `scripts/04`까지 실행하여 `.scnx` 생성
- 압축 내부 PLN을 검사하여 기존 교전 77개와 신규 20~30개가 모두 두 단계인지 확인
- 고유 공격자–표적 수와 슬롯 수 일치 확인
- 실패 task와 도달 불가능 큐가 0건인지 확인
- 동일 입력으로 두 번 빌드했을 때 슬롯 파일과 `.scnx`가 결정적으로 동일한지 확인
- UAV 고정 객체 수, 계획 블록, 순찰 경로가 변경 전과 동일한지 확인
- 전체 `python -m pytest tests/ -q` 통과

### VR-Forces 실행 후 합격 기준

- 계획상 고유 `Fire-Weapon` 공격자–표적 쌍 약 100개
- GT에서 고유 `Fire-Weapon` SPO 최소 70개
- GT에서 고유 `Provide-Suppressive-Fire-Loc` 관계 최소 70개
- 반복 행 수와 고유 SPO 수를 별도로 보고
- 계획했으나 관측되지 않은 슬롯마다 실패 원인을 보고
- UAV 검출률은 측정할 수 있으나 이번 합격 판정에는 사용하지 않음

정적 빌드와 자동 테스트만으로 VR-Forces 런타임 성공을 주장하지 않는다. 최종 합격은 새 `.scnx`를 VR-Forces에서 실행하고 새 GT를 수집한 뒤 판정한다.

## 14. 예상 변경 지점

- `vtmak/scnx/spec.py`: 기존 교전을 슬롯으로 변환하고 보강 슬롯 결합
- `vtmak/scnx/plan.py`: 두 단계 사격, 시간 대기, follow 도달 가능성 처리
- 신규 `vtmak/scnx/engagements.py`: 후보 선택, 슬롯 배정, 사격·엄폐 좌표 계산
- `config/engagement_enrichment.json`: 보강 수와 상한
- `config/task_catalog.csv`: 검증된 duration·ammo 값과 필요한 유한 task 템플릿
- `config/pattern_map.csv` 및 `config/task_kinds.csv`: 실패 task를 이동 의도로 내리는 매핑
- `vtmak/scnx/audit.py`: 슬롯·도달 가능성 감사
- `vtmak/stkg/rewrite.py`: 제압사격 정규형 매핑
- `config/derive_rules.csv`와 `vtmak/derive/`: R1 `suppresses` 최종 산출 제외
- 관련 `tests/`: 단위·통합·회귀 검증

실제 구현 시 기존 모듈의 책임을 유지한다. 사건 해석은 `spec`, 슬롯 선택은 `engagements`, PLN 문자열 생성은 `plan`, 관측 정규화는 `stkg`, 기존 관계 합성은 `derive`에 둔다. 실행 슬롯과 관측을 조인하는 새 모듈은 만들지 않는다.

## 15. 구현 순서

1. 교전 슬롯 데이터 구조와 결정적 후보 선택
2. 기존 77개 직접사격을 두 단계 슬롯으로 변환
3. 신규 20~30개 저-task 표적 교전 생성
4. follow 및 실패 `find_*` task의 도달 가능성 개선
5. 제압사격 GT 정규화
6. 기존 R1 `suppresses` 최종 산출 제외
7. 정적 감사와 전체 회귀 검증
8. VR-Forces 실행, GT 재수집, 합격 지표 평가
