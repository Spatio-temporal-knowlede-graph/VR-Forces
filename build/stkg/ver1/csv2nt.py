# -*- coding: utf-8 -*-
"""csv2nt.py — VR-Forces dataset ver1.0 → N-Triples 지식그래프

입력 : VR-Forces dataset ver1.0/*_annotated.csv  (17열)
출력 : out/obs_<관측자>.nt  (관측자별 1파일)
근거 : classes_VR_with_properties.ttl + kg_build/stkg_ext_v1.0.ttl

====================================================================
적재 방침
====================================================================
CSV에 있는 값은 버리지 않는다. 매핑되는 온톨로지 어휘가 있으면 그것도 붙이되
원시 값을 항상 함께 남겨 원본 대조가 가능하게 한다. 행을 통째로 걸러내지
않는다. 빈 칸은 빈 칸으로 둔다 — RDF에서 "값이 없다"는 트리플의 부재로
표현되며, 없는 값을 지어내지 않는 것이 정직한 표현이다.

--------------------------------------------------------------------
왜 CSV의 subject,predicate,object 3열을 그대로 트리플로 쓰지 않는가
--------------------------------------------------------------------
한 행에는 관계 3열 말고도 timestamp·source·좌표·손상상태 6종이 붙는다.
`ENM1A2003 moveTo LOC_중앙계곡` 한 줄로 쓰면 이것들이 전부 사라지고,
게다가 RDF는 같은 트리플을 1개로 취급하므로 26분치 시계열이 통째로
1개 트리플로 뭉개진다. 그래서 관계를 노드로 구체화한다(reification).

    CSV 1행  =  Observation 개체 1개  +  거기 매달린 트리플 8~16개

--------------------------------------------------------------------
IRI 설계 — 관측 IRI는 (행 내용 해시)-(그 내용의 몇 번째 등장)
--------------------------------------------------------------------
  관측    bfstkg:obs/<src>/<17열 해시>-<n>  예 obs/ground_truth/a7aa14a9186c0652-2
  기하    bfstkg:obs/<src>/<17열 해시>-<n>/geom
  트랙    bfstkg:trk/<src>/<tracking_id>    예 trk/UAV_1/1-3001-5
  마킹    bfstkg:ent/<uuid>                 예 ent/ENINF001   (관측자 무관, 전역)
          ※ 지형지물(disKind 16)의 uuid('P2'·'Waypoint 1')는 지도 마커
            내부 ID 라 마킹 노드를 만들지 않는다. 값은 트랙의
            groundTruthMarking 리터럴로만 남는다.
  관측자  bfstkg:UAV_1 …                    (온톨로지 S6에 이미 있음)
  지점    bfstkg:LOC_중앙계곡               (온톨로지 S5에 이미 있음)

행 번호가 아니라 내용 해시를 쓰는 이유:

 (1) 재현성. 데이터팀이 정렬만 바꿔 CSV를 다시 뽑아도 IRI가 그대로다.
     행 번호였다면 관측 111만 개의 이름이 전부 바뀌어 증분 갱신·버전 비교가
     불가능하다.

 (2) 같은 (tracking_id, timestamp)인데 좌표가 다른 행이 5.2만 쌍 있다.
     타임스탬프가 초 단위라 한 초 안의 서로 다른 순간이 겹쳐 보이는 것이며
     둘 다 진짜 관측이다. 내용이 다르면 해시도 다르므로 양쪽이 모두 남는다.
     ("같은 개체·같은 시각이면 중복" 식으로 지웠다면 최대 50m 이동이 날아간다.)

접미사 -<n> 을 붙여 CSV 1행 = Observation 1개를 지킨다(온톨로지 Observation
정의가 "CSV 1행"이다). ground_truth 에는 17열이 글자 하나까지 같은 행이 52만
쌍 있는데, 그것이 export 아티팩트인지 실제 이중 샘플링인지 판정할 근거가 없다.
병합은 되돌릴 수 없고 보존은 쿼리로 언제든 접을 수 있으므로 보존한다.
중복을 무시하고 세려면 IRI 접미사가 -1 인 것만 취하면 된다.

트랙 IRI는 관측자별로 분리해 둔다. 단 tracking_id 원시 값을 bfstkg:trackingId
리터럴로 함께 남기므로, 이 값이 전역 ID로 확인되면 리터럴 조인으로 관측자
경계를 넘어 묶을 수 있다. (2026-08-25 데이터팀 확인 요청 중)

--------------------------------------------------------------------
사용법
--------------------------------------------------------------------
  python csv2nt.py                          # 기본 경로 자동 탐색
  python csv2nt.py --in "../VR-Forces dataset ver1.0" --out out
  python csv2nt.py --gzip                   # .nt.gz 로 압축 출력
  python csv2nt.py --limit 1000             # 파일당 N행만 (시험용)
  python csv2nt.py --state changed          # 손상상태를 기본값과 다를 때만 기록
  python csv2nt.py --skip-landmark-rows     # 지형지물 행(kind 16) 제외
"""

import argparse
import csv
import gzip
import hashlib
import os
import re
import sys
from collections import Counter

# ─────────────────────────────────────────────────────────────
# 네임스페이스
# ─────────────────────────────────────────────────────────────
NS  = "https://example.org/onto/battlefield-stkg#"
XSD = "http://www.w3.org/2001/XMLSchema#"
GEO = "http://www.opengis.net/ont/geosparql#"
SF  = "http://www.opengis.net/ont/sf#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
CRS84 = "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>"

# CSV 열 순서 — 해시 계산과 결측 검사에 쓴다.
COLUMNS = ["subject", "predicate", "object", "timestamp", "latitude", "longitude",
           "source", "force", "tracking_id", "uuid", "entity_type",
           "damage", "smoke", "flaming", "mobility_kill", "firepower_kill",
           "suppression_level"]

# ─────────────────────────────────────────────────────────────
# 매핑표 — 데이터 값 → 온톨로지 용어
# ─────────────────────────────────────────────────────────────

# CSV predicate → (온톨로지 술어, object 열의 성격)
#   "place" : object 가 LOC_* (Landmark)
#   "mark"  : object 가 정답 마킹 (ENINF001 등)
#   "empty" : object 가 항상 빈값 — 술어만 기록
#   None    : 관계 없음 — 순수 위치 관측
#
# 'none' 은 observedPredicate 를 만들지 않는다. ver1.0 의 모든 행이 predicate
# 값을 명시적으로 가지므로 술어의 부재는 언제나 'none'을 뜻하며 모호하지 않다.
PRED = {
    "move to":         ("moveTo",        "place"),
    "FFE-on-Location": ("ffeOnLocation", "place"),
    "Follow-Entity":   ("followEntity",  "mark"),
    "Fire-Weapon":     ("fireAtTarget",  "mark"),
    "find_cover":      ("findCover",     "mark"),
    "fired_by":        ("firedBy",       "empty"),   # ver1.0 은 사수 정보 없음
    "Wait-Duration":   ("waitDuration",  "empty"),   # ver1.0 은 지속시간 값 없음
    "none":            (None,            None),
}

# force 코드 → 진영 개체 (온톨로지 S1.1). 매핑 안 되는 값도 forceCode 로 보존한다.
#   1 아군 · 2 적군 · 3 지형지물(개체 아님) · 0 미상(ver1.0 에 2건)
FORCE = {"1": "FriendlyForce", "2": "EnemyForce"}

# entity_type 첫 필드 = DIS Entity Kind.
#   1 플랫폼(차량·화포) · 2 탄약(비행 중 발사체) · 3 인원 · 16 지형지물
LANDMARK_KIND = "16"
MUNITION_KIND = "2"

# 손상상태 6열 → (온톨로지 속성, XSD 타입, 기본값)
STATE_COLS = [
    ("damage",            "damageLevel",      "integer", "0"),
    ("smoke",             "smoking",          "boolean", "false"),
    ("flaming",           "flaming",          "boolean", "false"),
    ("mobility_kill",     "mobilityKill",     "boolean", "false"),
    ("firepower_kill",    "firepowerKill",    "boolean", "false"),
    ("suppression_level", "suppressionLevel", "integer", "0"),
]

# ─────────────────────────────────────────────────────────────
# N-Triples 직렬화 도우미
# ─────────────────────────────────────────────────────────────

_ESC = {'\\': '\\\\', '"': '\\"', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def esc(s):
    return "".join(_ESC.get(c, c) for c in s)


def iri(full):
    return "<" + full + ">"


def n(local):
    """bfstkg: 로컬명 → 완전 IRI. 한글 로컬명(LOC_중앙계곡)도 IRI에 그대로 쓸 수 있다."""
    return "<" + NS + local + ">"


def lit(value, datatype=None):
    if datatype:
        return '"%s"^^<%s>' % (esc(value), datatype)
    return '"%s"' % esc(value)


def slug(s):
    """IRI 로컬명에 부적합한 문자를 치환. 'UAV 1'→'UAV_1', '1:3001:5'→'1-3001-5'"""
    return re.sub(r"[^0-9A-Za-z_\-가-힣]", lambda m: "-" if m.group() == ":" else "_", s)


def row_hash(row):
    """17열 전체의 지문. 내용이 같으면 같고 다르면 다르다.
    구분자 \x1f 는 CSV 값에 나타나지 않으므로 열 경계가 뭉개지지 않는다.

    ※ COLUMNS 에 없는 열은 해시에 들어가지 않는다. 그래서 열이 추가된 CSV를
      그대로 먹이면 그 열만 다른 두 행이 같은 해시가 되어 조용히 병합된다.
      check_header() 가 그 상황을 사전에 막는다 — 우회하지 말 것."""
    joined = "\x1f".join(row.get(c, "") or "" for c in COLUMNS)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


class HeaderMismatch(Exception):
    pass


def check_header(fieldnames, path):
    """CSV 헤더가 COLUMNS 와 정확히 같은지 확인한다.

    열이 늘거나 이름이 바뀐 데이터셋(ver1.1 등)을 말없이 처리하면 새 열이
    통째로 유실되고, 그 열만 다른 행들이 같은 해시로 병합된다. 로더는
    그것을 감지할 방법이 없으므로 여기서 멈추는 편이 안전하다.
    새 데이터셋을 받으면 COLUMNS·STATE_COLS·PRED 를 갱신하고 다시 돌린다."""
    got = list(fieldnames or [])
    if got == COLUMNS:
        return
    missing = [c for c in COLUMNS if c not in got]
    extra = [c for c in got if c not in COLUMNS]
    msg = ["CSV 헤더가 이 로더가 아는 17열과 다릅니다: %s" % os.path.basename(path)]
    if missing:
        msg.append("  없어진 열: %s" % ", ".join(missing))
    if extra:
        msg.append("  새로 생긴 열: %s   ← 이 값들은 그래프에 실리지 않습니다" % ", ".join(extra))
    if not missing and not extra:
        msg.append("  열 순서가 다릅니다.")
        msg.append("  기대: %s" % ", ".join(COLUMNS))
        msg.append("  실제: %s" % ", ".join(got))
    msg.append("  → csv2nt.py 의 COLUMNS·STATE_COLS·PRED 매핑표를 갱신한 뒤 다시 실행하세요.")
    raise HeaderMismatch("\n".join(msg))


# ─────────────────────────────────────────────────────────────
# 변환 본체
# ─────────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.rows = 0
        self.triples = 0
        self.observations = 0        # Observation 노드 수 (= 처리한 행 수)
        self.dup_rows = 0            # 앞선 행과 17열이 완전히 같은 행(별개 노드로 보존)
        self.tracks = 0
        self.landmark_rows = 0
        self.munition_rows = 0
        self.no_trkid = 0            # tracking_id 없이 이름을 트랙 키로 쓴 행
        self.empty_cells = Counter() # 열별 빈 칸 수 — 결측 현황 보고용
        self.unknown_pred = Counter()
        self.unknown_place = Counter()   # object 열의 LOC_* 가 온톨로지에 없음
        self.unknown_landmark = Counter() # 지형지물 행의 subject 가 온톨로지에 없음
        self.unmapped_force = Counter()
        self.type_conflict = Counter()
        self.src_mismatch = Counter()
        self.dropped = Counter()     # 부득이 버린 행과 사유
        self.anomaly = Counter()     # 버리진 않았으나 짚어둘 값


def convert(path, out, known_landmarks, emit_all_state=True,
            skip_landmark_rows=False, limit=None):
    """CSV 한 개를 N-Triples 로 변환해 out 에 쓴다. Stats 를 돌려준다."""
    st = Stats()

    # 파일명에서 관측자 슬러그를 뽑는다: 'UAV_1_20260809_175237_annotated.csv' → 'UAV_1'
    base = os.path.basename(path)
    m = re.match(r"(.+?)_\d{8}_\d{6}_annotated\.csv$", base)
    src_slug = slug(m.group(1)) if m else slug(base.replace("_annotated.csv", ""))
    # source 열이 이 이름과 맞는지 대조하기 위한 정규화 형태
    src_norm = src_slug.lower()

    occurrence = {}         # 행 해시 → 몇 번째 등장인가 (IRI 접미사)
    seen_track = set()      # 트랙 키 — 트랙 선언은 1회만
    seen_mark = set()       # 마킹 로컬명 — 마킹 노드 선언도 1회만
    track_type = {}         # 트랙 키 → entity_type (충돌 감시)

    def w(s, p, o):
        out.write("%s %s %s .\n" % (s, p, o))
        st.triples += 1

    def declare_mark(local, label):
        """정답 마킹 노드를 1회만 선언한다. uuid 열에서 온 것이든
        object 열에서만 참조된 것이든 똑같이 선언해 고아 노드를 막는다.
        식별자는 markingId 를 쓴다 — groundTruthMarking 은 domain 이 Track 이라
        마킹에 붙이면 추론기가 그 마킹을 Track 으로 단정한다."""
        if local in seen_mark:
            return
        seen_mark.add(local)
        w(n("ent/" + local), iri(RDF + "type"), n("EntityMarking"))
        w(n("ent/" + local), n("markingId"), lit(label))

    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        check_header(rd.fieldnames, path)
        for i, r in enumerate(rd, start=1):
            if limit and i > limit:
                break
            st.rows += 1

            for c in COLUMNS:
                if not (r.get(c) or "").strip():
                    st.empty_cells[c] += 1

            subject = r["subject"].strip()
            uuid    = r["uuid"].strip()
            trkid   = r["tracking_id"].strip()
            etype   = r["entity_type"].strip()
            force   = r["force"].strip()
            source  = r["source"].strip()
            stamp   = r["timestamp"].strip()

            # source 열이 파일명과 다르면 관측자 귀속이 틀어진다. 경고만 하고 진행.
            if source and source.replace(" ", "_").lower() != src_norm:
                st.src_mismatch[source] += 1

            dis_kind = etype.split(":", 1)[0] if etype else ""

            if dis_kind == LANDMARK_KIND:
                st.landmark_rows += 1
                if skip_landmark_rows:
                    continue
            elif dis_kind == MUNITION_KIND:
                st.munition_rows += 1

            # ── 트랙 식별키 ────────────────────────────────────────────
            # 정상: tracking_id. 예외: UAV 파일의 탄약 행은 tracking_id 가 비어
            # 있어 subject 이름을 임시 키로 쓴다. 이름('M933HE 1')은 몇 분 뒤
            # 다음 발에 재사용되므로 이 트랙 하나에 여러 발이 섞인다 —
            # ground_truth 는 tracking_id 가 있어 정상이다.
            if trkid:
                trk_key = "tid:" + trkid
                trk_local = "trk/%s/%s" % (src_slug, slug(trkid))
            elif subject:
                trk_key = "name:" + subject
                trk_local = "trk/%s/name-%s" % (src_slug, slug(subject))
                st.no_trkid += 1
            else:
                st.dropped["tracking_id·subject 둘 다 없음"] += 1
                continue
            trk = n(trk_local)

            # ── 트랙 선언 (파일당 1회) ─────────────────────────────────
            if trk_key not in seen_track:
                seen_track.add(trk_key)
                st.tracks += 1
                w(trk, iri(RDF + "type"), n("Track"))
                w(trk, n("trackedBy"), n(src_slug))
                if trkid:
                    w(trk, n("trackingId"), lit(trkid))
                if subject:
                    w(trk, n("sourceSubject"), lit(subject))
                    # 지형지물 트랙(disKind 16)만 온톨로지 S5 지점으로 잇는다.
                    # dis_kind 를 함께 보지 않으면, 일반 개체의 subject 가 우연히
                    # LOC_* 와 같은 이름일 때 그 개체가 지점이 되어버린다.
                    # ※ 이 연결은 이름만 대조하며 좌표를 확인하지 않는다.
                    #   ver1.0 지형지물 12곳 중 5곳은 스트림 좌표가 등재 좌표와
                    #   445~880m 어긋난다(stkg_ext X6-9). 데이터팀 확인 대기 중.
                    if dis_kind == LANDMARK_KIND:
                        if subject in known_landmarks:
                            w(trk, n("representsPlace"), n(subject))
                        else:
                            st.unknown_landmark[subject] += 1
                if uuid:
                    w(trk, n("groundTruthMarking"), lit(uuid))
                if etype:
                    w(trk, n("entityType"), lit(etype))
                    # 정수가 아니면 xsd:integer 리터럴이 깨지므로 원본만 남긴다.
                    if dis_kind.isdigit():
                        w(trk, n("disKind"), lit(dis_kind, XSD + "integer"))
                    else:
                        st.anomaly["entity_type 첫 필드가 정수 아님"] += 1
                    track_type[trk_key] = etype
                if force:
                    if force.lstrip("-").isdigit():
                        w(trk, n("forceCode"), lit(force, XSD + "integer"))
                    else:
                        st.anomaly["force 가 정수 아님"] += 1
                    if force in FORCE:
                        w(trk, n("observedForce"), n(FORCE[force]))
                    else:
                        st.unmapped_force[force] += 1
            elif etype and track_type.get(trk_key, etype) != etype:
                st.type_conflict[trk_key] += 1

            # ── 마킹 노드 ─────────────────────────────────────────────
            # 지형지물(disKind 16)의 uuid 는 'P2'·'Waypoint 1' 같은 지도 마커
            # 내부 ID 이지 실개체 식별자가 아니다. EntityMarking 의 정의
            # ("전역 유일 실개체 식별자")에 맞지 않으므로 노드를 만들지 않는다.
            # 그 값은 트랙의 groundTruthMarking 리터럴로만 보존한다.
            if uuid and dis_kind != LANDMARK_KIND:
                declare_mark(slug(uuid), uuid)

            # ── 관측 레코드 ───────────────────────────────────────────
            # IRI = 17열 해시 + 같은 내용의 몇 번째 등장인가.
            # CSV 1행 = Observation 1개를 지킨다(온톨로지 Observation 정의).
            # 완전히 같은 행이 52만 쌍 있지만 그것이 export 아티팩트인지 실제
            # 이중 샘플링인지 판정할 근거가 없다. 병합은 되돌릴 수 없고 보존은
            # 쿼리로 언제든 접을 수 있으므로 보존한다 — 중복 제거는 아래 한 줄:
            #   SELECT (COUNT(DISTINCT ?h) ...) / 또는 IRI 접미사 -1 만 취하기
            h = row_hash(r)
            k = occurrence[h] = occurrence.get(h, 0) + 1
            if k > 1:
                st.dup_rows += 1
            obs_local = "obs/%s/%s-%d" % (src_slug, h, k)
            obs = n(obs_local)
            st.observations += 1
            w(obs, iri(RDF + "type"), n("Observation"))
            w(obs, n("observationOf"), trk)
            w(obs, n("observedBy"), n(src_slug))
            if stamp:
                w(obs, n("atTime"), lit(stamp, XSD + "dateTime"))
            else:
                st.anomaly["timestamp 빈칸(관측 노드는 생성)"] += 1

            # 위치 — GeoSPARQL 점. WKT 는 (경도 위도) 순서다.
            lat, lon = r["latitude"].strip(), r["longitude"].strip()
            if lat and lon:
                gm = n(obs_local + "/geom")
                w(obs, iri(GEO + "hasGeometry"), gm)
                w(gm, iri(RDF + "type"), iri(SF + "Point"))
                w(gm, iri(GEO + "asWKT"),
                  lit("%s POINT(%s %s)" % (CRS84, lon, lat), GEO + "wktLiteral"))

            # 손상·피격 상태. 기본값 포함 전부 기록한다(--state changed 로 축소 가능).
            # 빈 칸은 트리플을 만들지 않는다 — 값이 없다는 사실을 지어내지 않기 위함.
            for col, prop, dt, default in STATE_COLS:
                v = r[col].strip()
                if not v:
                    continue
                if not emit_all_state and v == default:
                    continue
                if dt == "integer" and not v.lstrip("-").isdigit():
                    st.anomaly["%s 가 정수 아님" % col] += 1
                    continue
                if dt == "boolean" and v not in ("true", "false"):
                    st.anomaly["%s 가 불리언 아님" % col] += 1
                    continue
                w(obs, n(prop), lit(v, XSD + dt))

            # ── 관계 술어 + 대상 ──────────────────────────────────────
            p_raw = r["predicate"].strip()
            if p_raw not in PRED:
                st.unknown_pred[p_raw] += 1
                continue
            prop, obj_kind = PRED[p_raw]
            if prop is None:                 # 'none' — 순수 위치 관측
                continue
            w(obs, n("observedPredicate"), n(prop))

            tgt = r["object"].strip()
            if obj_kind == "empty" or not tgt:
                continue
            if obj_kind == "place":
                # 지점명은 IRI 로컬명이 되므로 IRI 에 못 쓰는 문자가 있으면
                # 깨진 IRI 가 조용히 나간다. slug 로 걸러내되, 값이 바뀌면
                # 온톨로지의 LOC_* IRI 와 어긋나므로 반드시 경고한다.
                tgt_local = slug(tgt)
                if tgt_local != tgt:
                    st.anomaly["지점명에 IRI 불가 문자: %s" % tgt] += 1
                if tgt not in known_landmarks:
                    st.unknown_place[tgt] += 1
                w(obs, n("observedObject"), n(tgt_local))
            else:                            # obj_kind == "mark"
                # object 로만 등장하는 마킹도 선언한다(UAV 1의 ENINF001 등).
                declare_mark(slug(tgt), tgt)
                w(obs, n("observedObject"), n("ent/" + slug(tgt)))

    return st


# ─────────────────────────────────────────────────────────────
# 온톨로지에서 Landmark 목록 읽기 (LOC_* 대조용)
# ─────────────────────────────────────────────────────────────

def load_landmarks(ttl_path):
    if not ttl_path or not os.path.exists(ttl_path):
        return set()
    with open(ttl_path, encoding="utf-8") as f:
        return set(re.findall(r"(?m)^bfstkg:(LOC_\S+)\s+a\s+bfstkg:Landmark", f.read()))


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    # 윈도 콘솔 기본 코드페이지(cp949)에서 한글·기호가 깨지지 않게 한다.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="VR-Forces annotated CSV → N-Triples")
    ap.add_argument("--in", dest="indir",
                    default=os.path.join(here, "..", "VR-Forces dataset ver1.0"),
                    help="annotated CSV 폴더")
    ap.add_argument("--out", dest="outdir", default=os.path.join(here, "out"),
                    help="출력 폴더")
    ap.add_argument("--onto", default=os.path.join(here, "..", "classes_VR_with_properties.ttl"),
                    help="Landmark 대조에 쓸 온톨로지 파일")
    ap.add_argument("--state", choices=["all", "changed"], default="all",
                    help="all(기본): 손상상태 전부 기록 / changed: 기본값과 다를 때만")
    ap.add_argument("--skip-landmark-rows", action="store_true",
                    help="지형지물 행(entity_type kind=16)을 적재하지 않는다")
    ap.add_argument("--gzip", action="store_true", help=".nt.gz 로 압축 출력")
    ap.add_argument("--limit", type=int, default=None, help="파일당 최대 행수(시험용)")
    a = ap.parse_args()

    indir = os.path.abspath(a.indir)
    outdir = os.path.abspath(a.outdir)
    os.makedirs(outdir, exist_ok=True)

    files = sorted(f for f in os.listdir(indir) if f.endswith("_annotated.csv"))
    if not files:
        sys.exit("annotated CSV 를 찾지 못했습니다: %s" % indir)

    known = load_landmarks(os.path.abspath(a.onto))
    print("온톨로지 Landmark %d개 로드" % len(known))
    print("입력 %s" % indir)
    print("출력 %s" % outdir)
    print("손상상태 %s · 지형지물 행 %s\n"
          % ("전부 기록" if a.state == "all" else "변동분만",
             "제외" if a.skip_landmark_rows else "적재"))

    total_t = total_r = total_o = total_d = 0
    agg_pred, agg_loc, agg_force = Counter(), Counter(), Counter()
    agg_empty, agg_drop, agg_src = Counter(), Counter(), Counter()
    agg_lm = Counter()
    agg_anom = Counter()

    for fn in files:
        src = os.path.join(indir, fn)
        m = re.match(r"(.+?)_\d{8}_\d{6}_annotated\.csv$", fn)
        stem = slug(m.group(1)) if m else slug(fn[:-4])
        dst = os.path.join(outdir, "obs_%s%s" % (stem, ".nt.gz" if a.gzip else ".nt"))

        opener = (lambda p: gzip.open(p, "wt", encoding="utf-8", newline="")) if a.gzip \
                 else (lambda p: open(p, "w", encoding="utf-8", newline=""))
        try:
            with opener(dst) as out:
                st = convert(src, out, known,
                             emit_all_state=(a.state == "all"),
                             skip_landmark_rows=a.skip_landmark_rows,
                             limit=a.limit)
        except HeaderMismatch as e:
            os.path.exists(dst) and os.remove(dst)
            sys.exit("\n[중단] %s\n" % e)

        size = os.path.getsize(dst)
        print("%-44s %9d행 → %9d트리플   %s  %.1f MB"
              % (fn, st.rows, st.triples, os.path.basename(dst), size / 1048576))
        print("      관측 %d · 트랙 %d · 동일내용 재등장 %d(보존) · 지형지물 행 %d · 탄약 행 %d"
              % (st.observations, st.tracks, st.dup_rows, st.landmark_rows, st.munition_rows))
        if st.no_trkid:
            print("      · tracking_id 없어 이름을 트랙 키로 쓴 행 %d" % st.no_trkid)
        if st.type_conflict:
            print("      ! 한 트랙에 entity_type 이 여러 개 %d건" % len(st.type_conflict))
        if st.src_mismatch:
            print("      ! source 열이 파일명과 불일치:", dict(st.src_mismatch))
        if st.dropped:
            print("      ! 버린 행:", dict(st.dropped))
        if st.anomaly:
            print("      · 짚어둘 값(적재는 됨):", dict(st.anomaly))

        total_t += st.triples
        total_r += st.rows
        total_o += st.observations
        total_d += st.dup_rows
        agg_pred.update(st.unknown_pred)
        agg_loc.update(st.unknown_place)
        agg_lm.update(st.unknown_landmark)
        agg_force.update(st.unmapped_force)
        agg_empty.update(st.empty_cells)
        agg_drop.update(st.dropped)
        agg_anom.update(st.anomaly)
        agg_src.update(st.src_mismatch)

    print("\n합계: %d행 → %d트리플 (Observation %d · 그중 17열이 동일한 재등장 %d, 모두 보존)"
          % (total_r, total_t, total_o, total_d))

    if agg_empty:
        print("\n빈 칸 현황 (값이 없으므로 트리플을 만들지 않음):")
        for c in COLUMNS:
            if agg_empty[c]:
                print("   %-18s %d행" % (c, agg_empty[c]))
    else:
        print("\n빈 칸 없음.")

    print()
    if agg_pred:
        print("! 매핑표에 없는 predicate:", dict(agg_pred))
    if agg_loc:
        print("! object 열의 지점명이 온톨로지에 없음:", dict(agg_loc.most_common(10)))
    if agg_lm:
        print("! 지형지물 행의 subject 가 온톨로지에 없음:", dict(agg_lm.most_common(10)))
    if agg_force:
        print("! 진영 어휘가 없는 force 코드 (forceCode 로는 보존됨):", dict(agg_force))
    if agg_src:
        print("! source 열 불일치:", dict(agg_src))
    if agg_drop:
        print("! 버린 행:", dict(agg_drop))
    if agg_anom:
        print("! 짚어둘 값(적재는 됨):", dict(agg_anom))
    if not (agg_pred or agg_loc or agg_lm or agg_force or agg_src or agg_drop):
        print("경고 없음 — 모든 값이 온톨로지 용어로 매핑되었고 버려진 행이 없습니다.")


if __name__ == "__main__":
    main()
