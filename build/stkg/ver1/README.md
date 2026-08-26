# build/stkg/ver1 — 온톨로지 기반 지식그래프 (N-Triples)

VR-Forces dataset ver1.0(`20260809_175237`)의 annotated CSV를 온톨로지에 맞춰
N-Triples로 변환한 결과와, 그 변환·검증 코드다.

## 파일

| 파일 | 내용 |
|---|---|
| `obs_UAV_1~4.nt.gz` · `obs_ground_truth.nt.gz` | 관측자별 지식그래프 (합계 **15,324,093 트리플**) |
| `classes_VR_with_properties.ttl` | 본 온톨로지 (스키마) |
| `stkg_ext_v1.0.ttl` | 확장 스키마 — 본 온톨로지에 없던 용어 14종 |
| `csv2nt.py` | CSV → N-Triples 변환기 |
| `verify_nt.py` | 산출물 검증 (CSV·온톨로지 대조) |
| `archive.py` | SHA256 매니페스트 생성 |
| `README.md` (아래) · `열대응표.md` · `MANIFEST.md` | 설계 근거·열 대응표·지문 |

`.nt.gz`는 트리플스토어가 그대로 읽는다. 압축을 푼 `.nt`는 2.9 GB라 저장소에
올리지 않았다 — `csv2nt.py`로 약 40초에 재생성된다.

## 재생성

```bash
# 이 저장소에서 실행할 때는 --in 으로 CSV 위치를 지정한다
python csv2nt.py --in ../  --onto classes_VR_with_properties.ttl --out out --gzip
python verify_nt.py --nt out --csv ../ --onto classes_VR_with_properties.ttl --ext stkg_ext_v1.0.ttl
```

※ `ground_truth_20260809_175237_annotated.csv`는 이 저장소에 없다. UAV 4개는
`build/stkg/`의 원본으로 재생성되지만 ground_truth는 별도로 받아야 한다.

## 확인 요청 중인 사항

`stkg_ext_v1.0.ttl`의 X6절에 9건 정리돼 있다. 그중 설계에 영향이 큰 둘:

- **`tracking_id`가 관측자별이 아니라 전역 ID로 보임** — UAV 4파일의 값이
  ground_truth와 100% 겹치고, 같은 값은 어디서든 같은 `uuid`를 가리킨다(471/471).
  `yewon_test.oob`의 `(object-identifier "1:3001:20")`과 같은 값이다.
- **지형지물 스트림 좌표가 등재 좌표와 어긋남** — 12곳 중 5곳이 445~880m 차이.
  `config/battlefield_layout.json` 및 `yewon_test.oob`와는 일치하므로 스트림 쪽
  문제로 보인다. 회신 전까지 `representsPlace`를 위치 판단에 쓰지 말 것.

---

아래는 작업 폴더(`kg_build/`) 기준으로 쓰인 원본 README다. 경로만 위와 다르고
설계·매핑·검증 내용은 그대로 유효하다.

---

# kg_build — VR-Forces dataset ver1.0 → 지식그래프(.nt)

## 파일

| 파일 | 용도 |
|---|---|
| `csv2nt.py` | annotated CSV(17열) → N-Triples 변환기 |
| `verify_nt.py` | 산출물 검증 + 온톨로지·CSV·NT 대응 대조 |
| `archive.py` | 보관용 매니페스트(SHA256) 생성 |
| `stkg_ext_v1.0.ttl` | 본 온톨로지에 없는 용어 14개(확장 스키마) |
| `out/` | `.nt` 원본 (2.9 GB) — 작업용, 40초에 재생성 가능 |
| `out_gz/` | `.nt.gz` **보관본** (98 MB) |
| `MANIFEST.md` | 입력·코드·산출물 SHA256 지문 |

## 실행

```bash
python csv2nt.py                     # out/ 에 .nt 생성 (약 40초)
python csv2nt.py --gzip --out out_gz # 보관본
python verify_nt.py                  # 검증 (약 40초)
python archive.py --date 2026-08-25  # 매니페스트 갱신

python csv2nt.py --state changed       # 손상상태를 기본값과 다를 때만(출력 축소)
python csv2nt.py --skip-landmark-rows  # 지형지물 행 제외
python csv2nt.py --limit 1000          # 시험용
```

## 결과

1,113,387행 → **15,324,117 트리플** (약 40초). 매핑 실패 0건, 버려진 행 0건.
**CSV 1행 = Observation 1개**가 정확히 지켜진다.

| 관측자 | 행 | Observation | 고유 내용 | 트리플 |
|---|---:|---:|---:|---:|
| UAV 1 | 18,992 | 18,992 | 16,123 | 274,002 |
| UAV 2 | 18,757 | 18,757 | 15,934 | 269,987 |
| UAV 3 | 24,581 | 24,581 | 20,501 | 358,463 |
| UAV 4 | 24,675 | 24,675 | 20,847 | 360,451 |
| ground_truth | 1,026,382 | 1,026,382 | 501,718 | 14,061,214 |

## 적재 방침

**CSV에 있는 값은 버리지 않는다.** 매핑되는 온톨로지 어휘가 있으면 그것도 붙이되
원시 값을 항상 함께 남겨 원본 대조가 가능하게 한다. 행을 통째로 걸러내지 않는다.
빈 칸은 빈 칸으로 둔다 — RDF에서 "값이 없다"는 트리플의 부재로 표현되며, 없는
값을 지어내지 않는 것이 정직한 표현이다.

ver1.0의 빈 칸은 UAV 파일의 탄약 행 91개뿐이다(`force`·`tracking_id`·`uuid`·
`entity_type`·손상상태 6열). `object` 716,736행은 `predicate`가 `none`·`fired_by`·
`Wait-Duration`이라 원래 대상이 없는 경우다.

## 모델

CSV의 `subject,predicate,object` 3열을 그대로 트리플로 쓰지 않는다. 한 행에는
`timestamp·source·좌표·손상상태 6종`이 함께 붙는데, 관계만 3중항으로 뽑으면
이것들이 전부 사라지고 RDF가 중복 트리플을 1개로 합치므로 26분치 시계열이
뭉개진다. 그래서 관계를 노드로 구체화한다.

```
CSV 1행  =  Observation 1개  +  거기 매달린 트리플 8~16개

Observer ──trackedBy── Track ──observationOf── Observation
   UAV_1              tracking_id             시각·좌표·손상·관계
```

### IRI

```
관측    bfstkg:obs/<관측자>/<17열 해시>-<n>   obs/ground_truth/a7aa14a9186c0652-2
기하    bfstkg:obs/<관측자>/<17열 해시>-<n>/geom
트랙    bfstkg:trk/<관측자>/<tracking_id>     trk/UAV_1/1-3001-5
마킹    bfstkg:ent/<uuid>                     ent/ENINF001   (관측자 무관, 전역)
```

**해시를 쓰는 이유**는 재현성이다. 데이터팀이 정렬만 바꿔 CSV를 다시 뽑아도
IRI가 그대로다. 행 번호였다면 1,500만 개 이름이 전부 바뀌어 증분 갱신·버전
비교가 불가능하다.

**접미사 `-<n>`을 붙이는 이유**는 CSV 1행 = Observation 1개를 지키기 위해서다
(온톨로지의 Observation 정의가 "CSV 1행"이다). ground_truth에는 17열이 글자
하나까지 같은 행이 **52만 쌍** 있지만, 그것이 export 아티팩트인지 실제 이중
샘플링인지 판정할 근거가 없다. **병합은 되돌릴 수 없고 보존은 쿼리로 언제든
접을 수 있으므로 보존한다.** 중복을 무시하고 세려면 IRI 접미사가 `-1`인 것만
취하면 된다.

같은 `(tracking_id, timestamp)`인데 좌표가 다른 행도 **5.2만 쌍** 있다.
타임스탬프가 초 단위라 한 초 안의 서로 다른 순간이 겹쳐 보이는 것이며 둘 다
진짜 관측이다(94%가 1m 미만, 최대 50m). 내용이 다르면 해시도 다르므로 양쪽이
모두 남는다.

| CSV 행 | 내용 | IRI | 결과 |
|---|---|---|---|
| 340 | 17열 동일 | `a7aa…0652-1` | 별개 노드 ✓ |
| 679 | ↑와 완전 동일 | `a7aa…0652-2` | 별개 노드 ✓ (보존) |
| 400035 | 위도 21.37351599 | `9bb9…09ef-1` | 별개 노드 ✓ |
| 400374 | 위도 21.37358328 | `aaff…7187-1` | 별개 노드 ✓ |

## 매핑

### predicate (8종)

| CSV | 온톨로지 | object 열 |
|---|---|---|
| `move to` | `moveTo` | LOC_* (Landmark) |
| `FFE-on-Location` | `ffeOnLocation` | LOC_* |
| `Follow-Entity` | `followEntity` | 마킹 → `ent/*` |
| `Fire-Weapon` | `fireAtTarget` | 마킹 → `ent/*` |
| `find_cover` | `findCover` | 마킹 → `ent/*` |
| `fired_by` | `firedBy` | ver1.0은 항상 빈값 |
| `Wait-Duration` | `waitDuration` | ver1.0은 값 없음 |
| `none` | (술어 없음) | 순수 위치 관측 |

`none`은 `observedPredicate`를 만들지 않는다. ver1.0의 모든 행이 predicate 값을
명시적으로 가지므로 술어의 부재는 언제나 `none`을 뜻하며 모호하지 않다.

### entity_type 첫 필드 = DIS Entity Kind

`1` 플랫폼 · `2` 탄약 · `3` 인원 · `16` 지형지물 → `bfstkg:disKind`로 파생

지형지물 행 33,277개도 **적재한다.** `subject`(LOC_동측능선)와 `uuid`(P2)의
대응이 이 행에만 있기 때문이다. 트랙에 `sourceSubject`로 원본을 남기고,
온톨로지 S5에 등재된 지점이면 `representsPlace`로 잇는다(101건).

```turtle
bfstkg:trk/ground_truth/1-3001-10  bfstkg:representsPlace  bfstkg:LOC_동측능선 .
```

### force

`1`→`FriendlyForce` · `2`→`EnemyForce` · `3` 지형지물 · `0` 미상(2건)

매핑 여부와 무관하게 원시 코드를 `forceCode`로 항상 보존한다(3,115건).

## 검증 — `python verify_nt.py`

로더와 독립적으로 동작한다. 로더 로직을 다시 실행하는 게 아니라 산출물만 읽어
원본 CSV·온톨로지와 대조한다. **2026-08-25 기준 전 항목 통과.**

| 검사 | 범위 | 내용 | 결과 |
|---|---|---|---|
| V0 헤더 | 전수 | CSV 헤더가 기대한 17열과 같은가 | 5파일 일치 |
| V1 문법 | 전수 | 모든 줄이 N-Triples 형식 | 15,324,117줄 위반 0 |
| V2 어휘 | 전수 | NT가 쓰는 bfstkg 술어가 온톨로지에 정의됨 | 21종 전부 정의 (외부 표준 2종 별도) |
| V3 행 대응 | 전수 | CSV **전체** 행 ↔ Observation 1:1 (해시+횟수) | 1,113,387 ↔ 1,113,387 |
| geom | 전수 | 좌표 있는 행 수 = geom 노드 수 | 1,113,387 일치 |
| V4 값 대응 | 표본 | NT에서 값·술어·대상을 복원해 CSV와 비교 | 파일당 3,000행 불일치 0 |
| V5 고아 | 전수 | object 자리 bfstkg IRI가 전부 정의됨 | 5,016종 중 미정의 0 |
| V7 트랙속성 | 전수 | 트랙의 5개 속성 + 진영 매핑이 CSV와 일치 | 트랙 4,939개 불일치 0 |
| domain/range | 전수 | emit 하는 모든 트리플이 선언된 domain·range 를 지키는가 | 위반 0 |

V3가 핵심이다. CSV의 행 수와 NT의 Observation 수가 해시별 등장 횟수까지
정확히 같다는 것은 **버려진 행도 지어낸 행도 없다**는 뜻이다. V4·V7이 그 위에서
값·매핑까지 맞는지 확인한다.

### 검증기가 실제로 잡는지 — 결함 주입 시험

항상 OK만 내는 검사는 쓸모가 없으므로, 고의로 망가뜨려 탐지되는지 확인했다.

| 주입한 결함 | 탐지 |
|---|---|
| `move to`를 `ffeOnLocation`으로 잘못 매핑 | V4 실패 `{'predicate': 263}` |
| 진영 매핑을 뒤집음(아군↔적군) | V7 실패 `{'force↔observedForce': 123}` |
| WKT 좌표를 (위도 경도) 순서로 뒤바꿈 | V4 실패 `{'좌표': 336}` |
| 열이 추가된 CSV(ver1.1 가정) | V0 실패 — 새 열 `altitude` 지적 |

### 두 스크립트는 매핑표를 공유하지 않는다

`verify_nt.py`는 `csv2nt.py`에서 매핑표를 import하지 않고 **따로 적어 둔다.**
같은 표를 공유하면 로더가 틀렸을 때 검증기도 똑같이 틀려서 통과하기 때문이다.
실제로 초기 버전은 `row_hash` 가정을 공유한 탓에, 열이 추가된 CSV에서 데이터가
유실됐는데도 양쪽 다 "전 항목 통과"를 냈다. 지금은 헤더 검사(V0)가 양쪽에
독립적으로 들어가 그 상황을 막는다.

### 헤더 가드

`csv2nt.py`는 CSV 헤더가 아는 17열과 다르면 **변환을 중단한다.**

```
[중단] CSV 헤더가 이 로더가 아는 17열과 다릅니다: UAV_1_..._annotated.csv
  새로 생긴 열: altitude   ← 이 값들은 그래프에 실리지 않습니다
  → csv2nt.py 의 COLUMNS·STATE_COLS·PRED 매핑표를 갱신한 뒤 다시 실행하세요.
```

관측 IRI가 17열 해시라서, 모르는 열이 있으면 그 열만 다른 행이 같은 해시로
조용히 병합된다. 데이터셋이 ver1.1로 올라가면 이 메시지가 먼저 뜬다.

### V6 — 온톨로지 · CSV · NT 대응표

| CSV 열 | NT 술어 | 트리플 | 정의 위치 |
|---|---|---:|---|
| `subject` | `sourceSubject` | 4,976 | 확장 |
| | `representsPlace` | 101 | 확장 |
| `predicate` | `observedPredicate` | 407,697 | 본체 |
| `object` | `observedObject` | 396,631 | 본체 |
| `timestamp` | `atTime` | 1,113,387 | 본체 |
| `latitude`·`longitude` | `geo:asWKT` | 1,113,387 | GeoSPARQL |
| `source` | `observedBy` | 1,113,387 | 본체 |
| | `trackedBy` | 4,976 | 본체 |
| `force` | `forceCode` | 4,939 | 확장 |
| | `observedForce` | 4,838 | 확장 |
| `tracking_id` | `trackingId` | 4,939 | 본체 |
| `uuid` | `groundTruthMarking` (트랙) | 4,939 | 본체 |
| | `markingId` (마킹) | 871 | 확장 |
| `entity_type` | `entityType` | 4,939 | 확장 |
| | `disKind` | 4,939 | 확장 |
| `damage` | `damageLevel` | 1,113,296 | 확장 |
| `smoke` | `smoking` | 1,113,296 | 확장 |
| `flaming` | `flaming` | 1,113,296 | 확장 |
| `mobility_kill` | `mobilityKill` | 1,113,296 | 확장 |
| `firepower_kill` | `firepowerKill` | 1,113,296 | 확장 |
| `suppression_level` | `suppressionLevel` | 1,113,296 | 확장 |
| — | `observationOf` | 1,113,387 | 본체 (구조) |
| — | `geo:hasGeometry` | 1,113,387 | GeoSPARQL (구조) |

**17개 열 전부 대응이 있고, 대응이 없는 열은 없다.** 손상상태 6열이 1,113,296인 것은
UAV 탄약 행 91개가 빈 칸이기 때문이다(1,113,387 − 91). 트랙 단위 술어가 4,939인 것은
트랙 수(4,976) 중 `tracking_id`가 있는 것만 세기 때문이다.

`uuid` 열이 두 술어로 나뉜 것에 주의. 같은 문자열이 **트랙**에는
`groundTruthMarking`, **마킹 노드**에는 `markingId`로 붙는다. 둘을 한 술어로 쓰면
`groundTruthMarking`의 domain이 `Track`이라 마킹까지 Track으로 추론된다.

## 보관 — `out_gz/` + `MANIFEST.md`

| | 크기 |
|---|---:|
| `out/` (`.nt`) | 2.9 GB — 작업용 |
| `out_gz/` (`.nt.gz`) | **98 MB — 보관본** |

압축본도 동일하게 검증을 통과했다(트리플스토어는 대개 `.gz`를 그대로 읽는다).
`out/`은 `csv2nt.py`로 40초에 재생성되므로 굳이 장기 보관하거나 저장소에 올릴
이유가 없다.

`MANIFEST.md`에 **입력 CSV 5개 · 스키마 2개 · 변환 코드 3개 · 산출물 5개**의
SHA256을 남겼다. 이 지문이 모두 일치하면 같은 그래프가 재현된다. 원본이 바뀌었는지,
누가 산출물을 손댔는지 확인할 때 쓴다.

## 적재

`.nt`는 그래프 이름을 담지 못하므로, 관측자 구분은 **적재할 때 대상 그래프를
지정**해서 만든다.

```bash
tdb2.tdbloader --loc=./db --graph=https://example.org/onto/battlefield-stkg/graph/UAV_1 \
               out/obs_UAV_1.nt
```

GraphDB는 Import 화면에서 파일마다 target named graph를 지정하면 된다.
스키마 2개(`classes_VR_with_properties.ttl`, `stkg_ext_v1.0.ttl`)는 default graph로.

## 알려진 사항

- **`tracking_id`가 관측자별이 아니라 전역 ID다.** UAV 4파일의 tracking_id가
  ground_truth와 100% 겹치고, 같은 tracking_id는 어느 관측자에서든 같은 uuid를
  가리킨다(471/471, 불일치 0). 온톨로지 S4.3의 "관측자가 부여한 트랙 식별자"와
  맞지 않는다. **데이터팀 확인 요청 중(2026-08-25).** 현재 트랙 IRI는 관측자별로
  분리해 두었고, `trackingId` 리터럴을 함께 남기므로 전역 ID로 확정되면 리터럴
  조인으로 관측자 경계를 넘어 묶을 수 있다.
- **UAV 파일의 탄약 행(kind=2)은 `tracking_id`가 비어 있다.** 이름
  (`M933HE 1`)을 임시 트랙 키로 쓰므로 트랙 하나에 여러 발이 섞인다(91행).
  ground_truth는 `tracking_id`가 있어 정상이다.
- **`resolvedTo`는 비운다.** 개체정합은 별도 연구 대상이라는 스키마 S4.3 방침 그대로.

## 미해결 — 데이터팀 확인 필요

`stkg_ext_v1.0.ttl` X6절 참조.

1. `tracking_id`의 정체(위 참조).
2. `fired_by`의 사수 정보가 없다(온톨로지는 "대상=확정 사수"로 정의).
3. `Wait-Duration`의 지속시간 값이 어느 열에도 없다.
4. UAV 파일 탄약 행의 `tracking_id` 결측이 의도인가.
5. `force=0` 2건의 의미.
6. `damage` 척도 정의(관측값은 0과 3뿐).
7. `CID` 열 삭제로 온톨로지 S7 `RecognitionLevel` 5종과 `cid` 속성이 소스를
   잃었다. 재등장 가능성이 있으면 온톨로지에서 지우지 말고 보류.
8. **밀리초 타임스탬프.** 초 단위라 같은 초 안의 서로 다른 관측이 겹친다
   (5.2만 쌍). 소수점 이하가 오면 근본 해결된다.
