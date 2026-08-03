new_VTMAK
프로젝트 개요
`new_VTMAK`은 시간대별 전투 시나리오 원문을 구조화된 이벤트와 객체별 타임테이블로 변환하고, 이를 기반으로 VR-Forces에서 실행 가능한 `.scnx` 파일을 자동 생성하는 프로젝트임
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
1. 시나리오 원문 준비
원문 작성: 안지호
입력 파일: `scenario_original/scenario.txt`
원문에는 시각, 객체 ID, 모델, 역할, 위치, 행동, 대상, 상태 변화 정보가 포함됨
2. 전장 지명 좌표 준비
시나리오에 등장하는 장소를 VR-Forces 지형 위에 waypoint로 지정한 뒤 실제 위도·경도·고도를 추출함
Ala Moana 지형의 전술적 위치를 시스템이 자동으로 알 수 없으므로, 남측 제1방어선·중앙 킬존·적 포병진지 등 주요 장소의 중심점을 사람이 먼저 지정해야 함
```bash
python scripts/01_harvest_layout.py
```
출력:
```text
config/battlefield_layout.json
```
3. 원문 → 이벤트 변환
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
원문에 등장하는 객체를 기반으로 객체 사전 자동 생성
G0: `weapon_ranges.csv`를 이용한 무기 사거리 검증
G1: 템플릿 미매칭 문장, 누락 객체·지명 검증
4. 객체별 타임테이블 생성
이벤트를 객체별·시간 구간별로 재구성하여 위치와 상태 변화를 확인할 수 있도록 함
```bash
python scripts/03_build_timetable.py
```
출력:
```text
build/timetable/battle.csv
```
G2에서는 task 수행이 가능한 객체가 실제 행동 이벤트를 하나 이상 가지는지 확인함
5. VR-Forces 시나리오 생성
이벤트, 객체 사전, 좌표, DIS 정보, task 카탈로그, golden 객체 레코드를 이용하여 VR-Forces용 시나리오를 생성함
```bash
python scripts/04_compile_scnx.py
```
출력:
```text
build/scnx/battle.scnx
```
G3에서는 다음 항목을 확인함
모든 엔티티의 DIS 존재 여부
golden에 동일 DIS 엔티티가 있는지
좌표·UUID·PLN 문법의 정상 여부
task가 참조하는 객체와 템플릿의 존재 여부
6. 데이터 후처리
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
원본	후처리
`Move to {좌표}`	`predicate=move to`, `object=지명`
`Follow-Entity Entity: "X"`	`predicate=Follow-Entity`, `object=X`
`FFE-On-Location`	`predicate=FFE-on-Location`, `object=목표 지명`
`find_cover ... Threat=X`	`predicate=find_cover`, `object=X`
`None`	`predicate=none`, `object` 비움
발사체 행	`predicate=fired_by`, `object=확정된 사수`
발사체의 사수를 확정할 수 없는 경우에는 잘못된 관계를 만들지 않고 `object`를 비워 둠
실행 순서
```bash
python scripts/01_harvest_layout.py
python scripts/02_parse_events.py
python scripts/03_build_timetable.py
python scripts/04_compile_scnx.py
python scripts/05_data_postprocessing.py
```
테스트
```bash
python -m pytest tests/ -q
```
