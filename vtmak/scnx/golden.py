"""golden .scnx 파서 — 좌표 수확과 TemplateScnxWriter가 공유한다.

golden(예: ys2.scnx)은 GUI로 저작한 정상 시나리오다. 여기서
  1) 한글 지명 점/지역 객체의 실제 ECEF 좌표(→ map_pack 자동 채움)
  2) 엔티티/라우트/점 레코드의 원본 텍스트(→ writer의 슬롯 템플릿)
  3) 빈 boilerplate 내부 파일(→ writer가 그대로 복제)
를 얻는다. .scnx는 손편집 비권장 포맷이라, 새로 합성하기보다 정상 레코드를
복제·치환하는 편이 로드 실패 위험이 작다.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# object-type 첫 값 → 객체 부류(golden ys2.oob 실측)
KIND_PLATFORM = "1"   # 차량/장비 엔티티
KIND_LIFEFORM = "3"   # 보병 엔티티
KIND_POINT = "16"     # 점(control-point/waypoint)
KIND_ROUTE = "17"     # 라우트
KIND_AREA = "18"      # 지역

ENTITY_KINDS = {KIND_PLATFORM, KIND_LIFEFORM}
CONTROL_KINDS = {KIND_POINT, KIND_ROUTE, KIND_AREA}


@dataclass(frozen=True)
class GoldenObject:
    kind: str                      # object-type 첫 값
    dis: tuple[int, ...]           # 7튜플
    marking: str
    uuid: str                      # VRF_UUID 뒤 순수 uuid
    position: tuple[float, float, float] | None  # ECEF (있으면)
    raw: str                       # 레코드 원문(슬롯 치환용)


@dataclass
class Golden:
    files: dict[str, bytes] = field(default_factory=dict)  # 내부파일명→원본
    objects: list[GoldenObject] = field(default_factory=list)

    @classmethod
    def load(cls, scnx_path) -> "Golden":
        g = cls()
        with zipfile.ZipFile(scnx_path) as z:
            for n in z.namelist():
                g.files[n] = z.read(n)
        oob = _text(g.files.get(_ext(g.files, ".oob"), b""))
        g.objects = _parse_objects(oob)
        return g

    def points_and_areas(self) -> list[GoldenObject]:
        return [o for o in self.objects if o.kind in (KIND_POINT, KIND_AREA)]

    def template_for(self, kind: str) -> GoldenObject | None:
        """해당 부류의 대표 레코드(슬롯 템플릿). 가장 작은 것을 고른다."""
        cands = [o for o in self.objects if o.kind == kind]
        return min(cands, key=lambda o: len(o.raw)) if cands else None

    def entity_by_dis(self, dis: tuple[int, ...]) -> GoldenObject | None:
        """정확히 같은 DIS(모델)의 실제 엔티티 레코드. 모델별 시스템·부품이
        그대로라 인스턴스화가 안전하다(종류별 대표 복제보다 정확)."""
        for o in self.objects:
            if o.kind in ENTITY_KINDS and o.dis == dis:
                return o
        return None


def _ext(files: dict, suffix: str) -> str:
    for n in files:
        if n.endswith(suffix):
            return n
    return ""


def _text(b: bytes) -> str:
    return b.decode("utf-8", "replace")


_UUID_RE = re.compile(r'uuid\s+"VRF_UUID:([0-9a-fA-F-]+)"')
_MARK_RE = re.compile(r'marking-text "([^"]*)"')
_OT_RE = re.compile(r"object-type\s+\d+\s+\(([\d ]+)\)")
_POS_RE = re.compile(
    r"parent-kinematics-state\s+\(position\s+"
    r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)")


def _parse_objects(oob: str) -> list[GoldenObject]:
    out: list[GoldenObject] = []
    for raw in _balanced_records(oob, "(local-vrf-object"):
        ot = _OT_RE.search(raw)
        if not ot:
            continue
        dis = tuple(int(x) for x in ot.group(1).split())
        kind = str(dis[0])
        uuid = _UUID_RE.search(raw)
        mark = _MARK_RE.search(raw)
        pos = _POS_RE.search(raw)
        position = ((float(pos.group(1)), float(pos.group(2)),
                     float(pos.group(3))) if pos else None)
        out.append(GoldenObject(
            kind=kind, dis=dis, marking=mark.group(1) if mark else "",
            uuid=uuid.group(1) if uuid else "",
            position=position, raw=raw))
    return out


def _balanced_records(text: str, head: str) -> list[str]:
    """head로 시작하는 괄호 균형 레코드들을 잘라낸다."""
    out: list[str] = []
    i = text.find(head)
    while i >= 0:
        depth, j = 0, i
        while j < len(text):
            c = text[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(text[i:j + 1])
        i = text.find(head, j + 1)
    return out
