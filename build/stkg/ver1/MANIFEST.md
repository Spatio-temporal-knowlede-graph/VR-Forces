# 지식그래프 산출물 매니페스트

빌드 일자: **2026-08-25**  ·  데이터셋: **VR-Forces dataset ver1.0 (20260809_175237)**

이 표의 SHA256이 모두 일치하면 같은 그래프가 재현된다. `python csv2nt.py --gzip` 으로 약 25초에 다시 만들 수 있다.


## 입력 — 원본 CSV

| 파일 | 크기 |  SHA256 |
|---|---:|---|
| `UAV_1_20260809_175237_annotated.csv` | 2.8 MB | `c90b1956c5c5670dda86c4df97e0bbd017f576efdcc7ffdb990836123266a52c` |
| `UAV_2_20260809_175237_annotated.csv` | 2.8 MB | `7b2b4d9ae9b88097680920a2017fa9ec543ffa022ad9fd2119d57ba388b5519e` |
| `UAV_3_20260809_175237_annotated.csv` | 3.7 MB | `bd1d7254a4eecd8eb97a277a6356afbecb7bdf06329ac11306df3b104005021d` |
| `UAV_4_20260809_175237_annotated.csv` | 3.7 MB | `8e3ef805c9b9aa9005364e9ba9c87899878c3195a87788017f7c6d06fdd5b994` |
| `ground_truth_20260809_175237_annotated.csv` | 151.8 MB | `d9385871eafdef1d9db956acfcc64c703115858d9667a2b1877acc4c1bb7556f` |

## 입력 — 스키마

| 파일 | 크기 | SHA256 |
|---|---:|---|
| `../classes_VR_with_properties.ttl` | 137.9 KB | `4a22107924862af09d993e7355d1eee2914c0184c8ec0639629f2dd0afdd9c1b` |
| `stkg_ext_v1.0.ttl` | 16.1 KB | `6c8e42925e563c34be9f80953a4fedcfa97baf01e69daa11a1f1086ae55ffa2b` |

## 입력 — 변환 코드

| 파일 | 크기 | SHA256 |
|---|---:|---|
| `csv2nt.py` | 30.2 KB | `198481ddde489abace88a26172b7f650b90c2c95d62043044be8540dad73250d` |
| `verify_nt.py` | 19.6 KB | `1902baf3d50c6a8c56b714bd0bd90f1f962f232986940638239c25c039312770` |
| `archive.py` | 5.2 KB | `2af79f50c97719725a1f5743ee9c3b7cf0517a630ba3f24d59a9a545edcd38ae` |

## 산출 — 지식그래프

| 파일 | 크기 | 줄(트리플) | SHA256 |
|---|---:|---:|---|
| `obs_UAV_1.nt.gz` | 1.6 MB | 274,002 | `ab2807a9752388076143e1771ceb538bb977d310294ec424d4079689ee65cbfa` |
| `obs_UAV_2.nt.gz` | 1.6 MB | 269,987 | `38e14d2cc3352c636ee47839f6bde95f39f4fbca84c11101a1077b45ac50b87c` |
| `obs_UAV_3.nt.gz` | 2.3 MB | 358,463 | `6ba5cd3d17460081ca132b1d4c5b6c78be6b1eb59945ec6382a75e55d2b0a6c1` |
| `obs_UAV_4.nt.gz` | 2.3 MB | 360,451 | `49a3d23f9a00ed7d47a06ca4a169dd64d1984606be7695a5b0cfe825cd95ead3` |
| `obs_ground_truth.nt.gz` | 89.8 MB | 14,061,190 | `d90d7ad7ce28454d76ca0b445894cb8ca72720856bf59cc5ccdb54414a2438ac` |

합계 97.6 MB · C:/Users/0119i/Desktop/ontology_VR/온톨로지_초안_제작이후/kg_build/out_gz


## 검증

`python verify_nt.py` 전 항목 통과 기준으로 보관한다.

| 검사 | 내용 |
|---|---|
| V1 문법 | 모든 줄이 N-Triples 형식 (전수) |
| V2 어휘 | NT가 쓰는 bfstkg 술어가 전부 온톨로지에 정의됨 (전수) |
| V3 행 대응 | CSV 고유 행 ↔ Observation 노드 1:1 (전수, 해시 대조) |
| geom | 좌표 있는 고유 행 수 = geom 노드 수 (전수) |
| V4 값 대응 | 표본 행을 NT에서 복원해 CSV 원본과 값 일치 |
| V5 고아 | object 자리 bfstkg IRI가 전부 어딘가에 정의됨 (전수) |
