# -*- coding: utf-8 -*-
"""verify_nt.py — 산출 .nt 검증 및 온톨로지·CSV·NT 대응 대조

csv2nt.py 와 독립적으로 동작한다. 로더의 로직을 다시 실행하는 것이 아니라
산출물만 읽어서 원본 CSV·온톨로지와 맞는지 확인한다.

검사 항목
  V1 문법      모든 줄이 N-Triples 형식인가 (전수)
  V0 헤더      CSV 헤더가 기대한 17열과 같은가 (전수)
  V2 어휘      NT가 쓰는 bfstkg 술어가 전부 온톨로지에 정의돼 있는가 (전수)
  V3 행 대응   CSV 전체 행 ↔ Observation 노드가 1:1 인가 (전수, 해시+횟수 대조)
  V4 값 대응   표본 행을 NT에서 되짚어 CSV 원본과 값이 같은가 (표본 복원)
  V5 고아      object 자리의 bfstkg: IRI가 어딘가에 정의돼 있는가 (전수)
  V6 대응표    CSV 열 ↔ NT 술어 ↔ 정의 위치 (전수 집계)
  V7 트랙속성  트랙 속성 5종 + 진영 매핑이 CSV와 일치하는가 (전수)

사용법
  python verify_nt.py                       # out/ 검증
  python verify_nt.py --nt out --sample 3000
"""

import argparse
import csv
import gzip
import hashlib
import os
import random
import re
import sys
from collections import Counter, defaultdict

NS = "https://example.org/onto/battlefield-stkg#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

COLUMNS = ["subject", "predicate", "object", "timestamp", "latitude", "longitude",
           "source", "force", "tracking_id", "uuid", "entity_type",
           "damage", "smoke", "flaming", "mobility_kill", "firepower_kill",
           "suppression_level"]

# CSV 열 → 그 열이 만들어내는 NT 술어(들). V6 대응표의 기준.
COL2PRED = {
    "subject":           ["sourceSubject", "representsPlace"],
    "predicate":         ["observedPredicate"],
    "object":            ["observedObject"],
    "timestamp":         ["atTime"],
    "latitude":          ["asWKT"],
    "longitude":         ["asWKT"],
    "source":            ["observedBy", "trackedBy"],
    "force":             ["forceCode", "observedForce"],
    "tracking_id":       ["trackingId"],
    "uuid":              ["groundTruthMarking", "markingId"],
    "entity_type":       ["entityType", "disKind"],
    "damage":            ["damageLevel"],
    "smoke":             ["smoking"],
    "flaming":           ["flaming"],
    "mobility_kill":     ["mobilityKill"],
    "firepower_kill":    ["firepowerKill"],
    "suppression_level": ["suppressionLevel"],
}

LINE = re.compile(r'^(<[^>]*>)\s(<[^>]*>)\s(.+)\s\.$')

# ── 아래 두 표는 csv2nt.py 에서 import 하지 않고 일부러 따로 적는다. ────────
# 로더와 같은 표를 공유하면 로더가 틀렸을 때 검증기도 똑같이 틀려서 통과한다.
# README 의 매핑표를 보고 독립적으로 옮겨 적은 것이며, 로더와 어긋나면 V4가 잡는다.

EXPECT_HEADER = ["subject", "predicate", "object", "timestamp", "latitude", "longitude",
                 "source", "force", "tracking_id", "uuid", "entity_type",
                 "damage", "smoke", "flaming", "mobility_kill", "firepower_kill",
                 "suppression_level"]

EXPECT_PRED = {
    "move to":         ("moveTo",        "place"),
    "FFE-on-Location": ("ffeOnLocation", "place"),
    "Follow-Entity":   ("followEntity",  "mark"),
    "Fire-Weapon":     ("fireAtTarget",  "mark"),
    "find_cover":      ("findCover",     "mark"),
    "fired_by":        ("firedBy",       "empty"),
    "Wait-Duration":   ("waitDuration",  "empty"),
    "none":            (None,            None),
}

# 트랙 술어 → 대응 CSV 열 (V7)
TRACK_PROPS = [("trackingId", "tracking_id"), ("sourceSubject", "subject"),
               ("groundTruthMarking", "uuid"), ("entityType", "entity_type"),
               ("forceCode", "force")]


def row_hash(row):
    return hashlib.sha1("\x1f".join(row.get(c, "") or ""
                                    for c in COLUMNS).encode("utf-8")).hexdigest()[:16]


def onto_terms(paths):
    """온톨로지 ttl 들에서 정의된 bfstkg: 로컬명을 모은다."""
    terms = set()
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            src = f.read()
        terms |= set(re.findall(r"(?m)^bfstkg:([^\s]+)\s+a\s", src))
        terms |= set(re.findall(r"(?m)^bfstkg:([^\s]+)\s+rdfs:", src))
    return terms


def open_nt(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") \
        else open(p, encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--nt", default=os.path.join(here, "out"))
    ap.add_argument("--csv", default=os.path.join(here, "..", "VR-Forces dataset ver1.0"))
    ap.add_argument("--onto", default=os.path.join(here, "..", "classes_VR_with_properties.ttl"))
    ap.add_argument("--ext", default=os.path.join(here, "stkg_ext_v1.0.ttl"))
    ap.add_argument("--sample", type=int, default=3000, help="V4 표본 행수(파일당)")
    a = ap.parse_args()

    ntdir, csvdir = os.path.abspath(a.nt), os.path.abspath(a.csv)
    defined = onto_terms([os.path.abspath(a.onto), os.path.abspath(a.ext)])
    print("온톨로지 정의 용어 %d개 로드\n" % len(defined))

    ntfiles = sorted(f for f in os.listdir(ntdir) if f.endswith((".nt", ".nt.gz")))
    csvfiles = {}
    for f in sorted(os.listdir(csvdir)):
        m = re.match(r"(.+?)_\d{8}_\d{6}_annotated\.csv$", f)
        if m:
            csvfiles[m.group(1)] = os.path.join(csvdir, f)

    fail = 0
    grand = Counter()
    pred_use = Counter()
    own_pred = Counter()      # bfstkg 네임스페이스 술어만 (V2 대상)
    ext_ns = {}               # 외부 술어 → 어느 표준인지
    all_defined_subj = set()      # 전 파일에 걸쳐 선언된 bfstkg 로컬명
    all_obj_refs = Counter()      # object 자리에 쓰인 bfstkg 로컬명(geom 제외)

    for ntf in ntfiles:
        stem = ntf[len("obs_"):].split(".")[0]
        path = os.path.join(ntdir, ntf)
        print("=" * 72)
        print(ntf)

        # ── V1 문법 · 어휘 수집 · Observation 해시 수집 ──────────────
        bad = 0
        lines = 0
        obs_h = set()
        obs_mult = Counter()
        geom_nodes = set()
        classes = Counter()
        with open_nt(path) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                lines += 1
                m = LINE.match(line)
                if not m:
                    bad += 1
                    continue
                s, p, o = m.group(1)[1:-1], m.group(2)[1:-1], m.group(3)
                if p.startswith(NS):
                    pred_use[p[len(NS):]] += 1
                    own_pred[p[len(NS):]] += 1     # V2 대상 = 우리 네임스페이스만
                elif p == RDF_TYPE:
                    if o.startswith("<" + NS):
                        classes[o[len(NS) + 1:-1]] += 1
                else:
                    # 외부 표준 어휘(GeoSPARQL 등). 우리 온톨로지가 정의할 대상이
                    # 아니므로 V2에서 제외하되 대응표에는 집계한다.
                    pred_use[p.rsplit("#", 1)[-1]] += 1
                    ext_ns[p.rsplit("#", 1)[-1]] = p.rsplit("#", 1)[0].rsplit("/", 1)[-1]
                if s.startswith(NS):
                    loc = s[len(NS):]
                    if loc.startswith("obs/") and loc.endswith("/geom"):
                        geom_nodes.add(loc)
                    elif loc.startswith("obs/") and p == RDF_TYPE:
                        tail = loc.rsplit("/", 1)[1]
                        obs_h.add(tail.rsplit("-", 1)[0])
                        obs_mult[tail.rsplit("-", 1)[0]] += 1
                    if p == RDF_TYPE:
                        all_defined_subj.add(loc)
                if o.startswith("<" + NS):
                    loc = o[len(NS) + 1:-1]
                    if not (loc.startswith("obs/") and loc.endswith("/geom")):
                        all_obj_refs[loc] += 1

        print("  V1 문법     %s  (%d줄, 위반 %d)"
              % ("OK" if bad == 0 else "실패", lines, bad))
        fail += bad > 0

        # ── V3 행 대응 ───────────────────────────────────────────────
        csvp = csvfiles.get(stem)
        if not csvp:
            print("  ! 대응 CSV 없음 — V3·V4 생략")
            continue
        csv_h = set()
        csv_mult = Counter()
        csv_rows = 0
        with open(csvp, encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            hdr = list(rd.fieldnames or [])
            ok0 = hdr == EXPECT_HEADER
            print("  V0 헤더     %s  %d열%s"
                  % ("OK" if ok0 else "실패", len(hdr),
                     "" if ok0 else "  기대와 다름: 없어진 %s / 새로 생긴 %s"
                     % ([c for c in EXPECT_HEADER if c not in hdr],
                        [c for c in hdr if c not in EXPECT_HEADER])))
            if not ok0:
                print("       ! 해시가 이 열들만 덮으므로 새 열만 다른 행은 병합됩니다.")
            fail += not ok0
            for r in rd:
                csv_rows += 1
                h = row_hash(r)
                csv_h.add(h)
                csv_mult[h] += 1
        # obs IRI 는 <해시>-<몇번째>. 해시별 등장 횟수가 CSV 와 같아야 한다.
        only_csv = set(csv_mult) - set(obs_mult)
        only_nt = set(obs_mult) - set(csv_mult)
        cnt_mismatch = {h: (csv_mult.get(h, 0), obs_mult.get(h, 0))
                        for h in set(csv_mult) | set(obs_mult)
                        if csv_mult.get(h, 0) != obs_mult.get(h, 0)}
        ok3 = not only_csv and not only_nt and not cnt_mismatch
        print("  V3 행 대응  %s  CSV %d행 → Observation %d (고유 내용 %d)"
              % ("OK" if ok3 else "실패", csv_rows, sum(obs_mult.values()), len(obs_mult)))
        if not ok3:
            print("       CSV에만 %d · NT에만 %d · 횟수 불일치 %d"
                  % (len(only_csv), len(only_nt), len(cnt_mismatch)))
        fail += not ok3
        # 좌표가 있는 CSV 고유 행 수와 geom 노드 수가 같아야 한다.
        with open(csvp, encoding="utf-8-sig", newline="") as f:
            nxy = sum(1 for r in csv.DictReader(f)
                      if r["latitude"].strip() and r["longitude"].strip())
        okg = len(geom_nodes) == nxy
        print("  geom 노드   %s  %d개 (좌표 있는 행 %d)"
              % ("OK" if okg else "불일치", len(geom_nodes), nxy))
        fail += not okg

        # ── V4 값 대응 (표본 복원) ───────────────────────────────────
        target = set(random.Random(42).sample(sorted(csv_h), min(a.sample, len(csv_h))))
        rec = defaultdict(dict)
        with open_nt(path) as f:
            for line in f:
                m = LINE.match(line.rstrip("\n"))
                if not m:
                    continue
                s, p, o = m.group(1)[1:-1], m.group(2)[1:-1], m.group(3)
                if not s.startswith(NS):
                    continue
                loc = s[len(NS):]
                if not loc.startswith("obs/"):
                    continue
                h = loc.split("/")[2].rsplit("-", 1)[0]
                if h not in target:
                    continue
                key = p[len(NS):] if p.startswith(NS) else p.rsplit("#", 1)[-1]
                rec[h][key] = o
        # CSV에서 표본 행을 찾아 값 비교
        mism = Counter()
        checked = 0
        with open(csvp, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                h = row_hash(r)
                if h not in target or h not in rec:
                    continue
                if h in rec and rec[h].get("_done"):
                    continue
                rec[h]["_done"] = True
                checked += 1
                d = rec[h]
                if r["timestamp"].strip() and \
                   d.get("atTime", "").strip('"').split('"')[0] != r["timestamp"].strip():
                    mism["timestamp"] += 1
                lat, lon = r["latitude"].strip(), r["longitude"].strip()
                if lat and lon:
                    wkt = d.get("asWKT", "")
                    if ("POINT(%s %s)" % (lon, lat)) not in wkt:
                        mism["좌표"] += 1
                # 관계 술어 매핑
                exp = EXPECT_PRED.get(r["predicate"].strip(), "??")
                if exp == "??":
                    mism["predicate(매핑표에 없음)"] += 1
                else:
                    ep, ekind = exp
                    got_p = d.get("observedPredicate", "")
                    if ep is None:
                        if got_p:
                            mism["predicate(none인데 술어 있음)"] += 1
                    elif NS + ep not in got_p:
                        mism["predicate"] += 1
                    got_o = d.get("observedObject", "")
                    tgt = r["object"].strip()
                    if ep and ekind == "place" and tgt and NS + tgt not in got_o:
                        mism["object(place)"] += 1
                    if ep and ekind == "mark" and tgt and NS + "ent/" not in got_o:
                        mism["object(mark)"] += 1
                    if ekind == "empty" and got_o:
                        mism["object(빈값인데 대상 있음)"] += 1
                for col, prop, in (("damage", "damageLevel"), ("smoke", "smoking"),
                                   ("flaming", "flaming"),
                                   ("mobility_kill", "mobilityKill"),
                                   ("firepower_kill", "firepowerKill"),
                                   ("suppression_level", "suppressionLevel")):
                    v = r[col].strip()
                    got = d.get(prop, "")
                    if v and ('"%s"' % v) not in got:
                        mism[col] += 1
                    if not v and got:
                        mism[col + "(빈칸인데 값 있음)"] += 1
        ok4 = not mism
        print("  V4 값 대응  %s  표본 %d행 복원 대조%s"
              % ("OK" if ok4 else "실패", checked, "" if ok4 else "  " + str(dict(mism))))
        fail += not ok4

        # ── V7 트랙 속성 대조 (트랙 수가 적으므로 전수) ───────────────
        trk = defaultdict(dict)
        with open_nt(path) as f:
            for line in f:
                m = LINE.match(line.rstrip("\n"))
                if not m:
                    continue
                sj, p, o = m.group(1)[1:-1], m.group(2)[1:-1], m.group(3)
                if sj.startswith(NS) and sj[len(NS):].startswith("trk/") and p.startswith(NS):
                    trk[sj[len(NS):]][p[len(NS):]] = o
        tmis = Counter()
        tseen = set()
        with open(csvp, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                tid = r["tracking_id"].strip()
                key = ("trk/%s/%s" % (stem, tid.replace(":", "-"))) if tid else None
                if not key or key in tseen or key not in trk:
                    continue
                tseen.add(key)
                d = trk[key]
                for prop, col in TRACK_PROPS:
                    v = r[col].strip()
                    got = d.get(prop, "")
                    if v and ('"%s"' % v) not in got:
                        tmis["%s↔%s" % (col, prop)] += 1
                    if not v and got:
                        tmis["%s(빈칸인데 값 있음)" % col] += 1
                f_ = r["force"].strip()
                exp_force = {"1": "FriendlyForce", "2": "EnemyForce"}.get(f_)
                got_f = d.get("observedForce", "")
                if exp_force and NS + exp_force not in got_f:
                    tmis["force↔observedForce"] += 1
                if not exp_force and got_f:
                    tmis["observedForce(매핑 없는데 값 있음)"] += 1
        ok7 = not tmis
        print("  V7 트랙속성 %s  트랙 %d개 전수 대조%s"
              % ("OK" if ok7 else "실패", len(tseen), "" if ok7 else "  " + str(dict(tmis))))
        fail += not ok7

        grand["rows"] += csv_rows
        grand["obs"] += sum(obs_mult.values())
        grand["uniq"] += len(obs_h)
        grand["triples"] += lines

    # ── V2 어휘 ──────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    undef_p = {p: c for p, c in own_pred.items() if p not in defined}
    print("V2 어휘     %s  bfstkg 술어 %d종 전부 정의됨 (외부 표준 %d종 별도)"
          % ("OK" if not undef_p else "실패", len(own_pred), len(ext_ns)))
    if undef_p:
        print("     온톨로지에 없는 술어:", undef_p)
    fail += bool(undef_p)

    # ── V5 고아 ──────────────────────────────────────────────────────
    undef_o = {}
    for loc, c in all_obj_refs.items():
        if loc in all_defined_subj or loc in defined:
            continue
        undef_o[loc] = c
    print("V5 고아     %s  object 자리 bfstkg IRI %d종 중 미정의 %d종"
          % ("OK" if not undef_o else "실패", len(all_obj_refs), len(undef_o)))
    if undef_o:
        for k, v in sorted(undef_o.items(), key=lambda x: -x[1])[:10]:
            print("     %-40s %d회" % (k, v))
    fail += bool(undef_o)

    # ── V6 대응표 ────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("V6  CSV 열 ↔ NT 술어 ↔ 정의 위치\n")
    print("  %-18s %-22s %12s  %s" % ("CSV 열", "NT 술어", "트리플 수", "정의"))
    print("  " + "-" * 68)
    ext_terms = onto_terms([os.path.abspath(a.ext)])
    for col in COLUMNS:
        for i, p in enumerate(COL2PRED[col]):
            where = ext_ns.get(p) or ("확장" if p in ext_terms else ("본체" if p in defined else "미정의!"))
            cnt = pred_use.get(p, 0)
            print("  %-18s %-22s %12s  %s"
                  % (col if i == 0 else "", p, "{:,}".format(cnt), where))
    used = set(pred_use)
    mapped = {p for v in COL2PRED.values() for p in v}
    extra = sorted(used - mapped)
    if extra:
        print("\n  구조 술어(열에서 직접 오지 않음):")
        for p in extra:
            where = ext_ns.get(p) or ("확장" if p in ext_terms else ("본체" if p in defined else "미정의!"))
            print("  %-18s %-22s %12s  %s" % ("", p, "{:,}".format(pred_use[p]), where))

    print("\n" + "=" * 72)
    print("합계 CSV %s행 → Observation %s (고유 내용 %s) · 트리플 %s"
          % ("{:,}".format(grand["rows"]), "{:,}".format(grand["obs"]),
             "{:,}".format(grand["uniq"]), "{:,}".format(grand["triples"])))
    print("결과: %s" % ("전 항목 통과" if fail == 0 else "실패 %d건" % fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
