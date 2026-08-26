# -*- coding: utf-8 -*-
"""archive.py — 산출물 보관용 매니페스트 생성

무엇을 무엇으로부터 언제 만들었는지, 그리고 그 파일이 나중에 바뀌지 않았는지
확인할 수 있게 SHA256 지문을 남긴다. 지식그래프는 원본 CSV·스키마·로더가
모두 같아야 재현되므로 셋 다 지문을 뜬다.

  python archive.py --date 2026-08-25
"""

import argparse
import gzip
import hashlib
import os
import sys
from datetime import datetime, timezone


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_lines(path):
    op = gzip.open if path.endswith(".gz") else open
    nl = 0
    with op(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            nl += b.count(b"\n")
    return nl


def human(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unit == "GB":
            return "%.1f %s" % (nbytes, unit)
        nbytes /= 1024.0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(here, "..", "VR-Forces dataset ver1.0"))
    ap.add_argument("--out", default=os.path.join(here, "out_gz"))
    ap.add_argument("--date", default=None, help="빌드 일자(미지정 시 현재 UTC)")
    a = ap.parse_args()

    stamp = a.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csvdir, outdir = os.path.abspath(a.csv), os.path.abspath(a.out)

    L = []
    L.append("# 지식그래프 산출물 매니페스트\n")
    L.append("빌드 일자: **%s**  ·  데이터셋: **VR-Forces dataset ver1.0 "
             "(20260809_175237)**\n" % stamp)
    L.append("이 표의 SHA256이 모두 일치하면 같은 그래프가 재현된다. "
             "`python csv2nt.py --gzip` 으로 약 25초에 다시 만들 수 있다.\n")

    def section(title, files, base, lines=False):
        L.append("\n## %s\n" % title)
        L.append("| 파일 | 크기 | %s SHA256 |" % ("줄(트리플) |" if lines else ""))
        L.append("|---|---:|%s---|" % ("---:|" if lines else ""))
        tot = 0
        for fn in sorted(files):
            p = os.path.join(base, fn)
            sz = os.path.getsize(p)
            tot += sz
            if lines:
                nl = count_lines(p)
                L.append("| `%s` | %s | %s | `%s` |" % (fn, human(sz), "{:,}".format(nl), sha256(p)))
            else:
                L.append("| `%s` | %s | `%s` |" % (fn, human(sz), sha256(p)))
            print("  %-46s %10s" % (fn, human(sz)))
        return tot

    print("입력 CSV")
    src = [f for f in os.listdir(csvdir) if f.endswith("_annotated.csv")]
    section("입력 — 원본 CSV", src, csvdir)

    print("\n스키마")
    sch = []
    for p, label in ((os.path.join(here, "..", "classes_VR_with_properties.ttl"), None),
                     (os.path.join(here, "stkg_ext_v1.0.ttl"), None)):
        if os.path.exists(p):
            sch.append(p)
    L.append("\n## 입력 — 스키마\n")
    L.append("| 파일 | 크기 | SHA256 |")
    L.append("|---|---:|---|")
    for p in sch:
        L.append("| `%s` | %s | `%s` |"
                 % (os.path.relpath(p, here).replace("\\", "/"),
                    human(os.path.getsize(p)), sha256(p)))
        print("  %-46s %10s" % (os.path.basename(p), human(os.path.getsize(p))))

    print("\n변환 코드")
    L.append("\n## 입력 — 변환 코드\n")
    L.append("| 파일 | 크기 | SHA256 |")
    L.append("|---|---:|---|")
    for fn in ("csv2nt.py", "verify_nt.py", "archive.py"):
        p = os.path.join(here, fn)
        if os.path.exists(p):
            L.append("| `%s` | %s | `%s` |" % (fn, human(os.path.getsize(p)), sha256(p)))
            print("  %-46s %10s" % (fn, human(os.path.getsize(p))))

    print("\n산출 그래프")
    outs = [f for f in os.listdir(outdir) if f.endswith((".nt", ".nt.gz"))]
    tot = section("산출 — 지식그래프", outs, outdir, lines=True)

    L.append("\n합계 %s · %s\n" % (human(tot), outdir.replace("\\", "/")))
    L.append("\n## 검증\n")
    L.append("`python verify_nt.py` 전 항목 통과 기준으로 보관한다.\n")
    L.append("| 검사 | 내용 |")
    L.append("|---|---|")
    L.append("| V1 문법 | 모든 줄이 N-Triples 형식 (전수) |")
    L.append("| V2 어휘 | NT가 쓰는 bfstkg 술어가 전부 온톨로지에 정의됨 (전수) |")
    L.append("| V3 행 대응 | CSV 고유 행 ↔ Observation 노드 1:1 (전수, 해시 대조) |")
    L.append("| geom | 좌표 있는 고유 행 수 = geom 노드 수 (전수) |")
    L.append("| V4 값 대응 | 표본 행을 NT에서 복원해 CSV 원본과 값 일치 |")
    L.append("| V5 고아 | object 자리 bfstkg IRI가 전부 어딘가에 정의됨 (전수) |")

    dst = os.path.join(here, "MANIFEST.md")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    print("\n→ %s" % dst)


if __name__ == "__main__":
    main()
