"""ScnxSpec → 출력. 포맷 의존 코드는 IScnxWriter 뒤로 격리.

- DirWriter: golden 없이도 동작. 스펙을 사람이 읽을 수 있는 중간 산출(JSON +
  객체별 .pln)로 풀고 최소 zip 스텁을 만든다. 로컬 검토용.
- TemplateScnxWriter: golden .scnx의 정상 레코드를 슬롯 템플릿으로 삼아 실제
  로드 가능한 .scnx를 저작한다. 새로 합성하지 않고 복제·치환하므로(손편집
  비권장 포맷) 로드 실패 위험이 작다. 엔티티 자세/라우트 정점 등 golden으로
  값을 확정 못한 부분은 # VERIFY-ON-TARGET(GUI 로드 검증).
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from ..geometry import Coord
from .golden import Golden
from .spec import ControlObjectSpec, EntitySpec, ScnxSpec


class IScnxWriter(Protocol):
    def write(self, spec: ScnxSpec, out_dir: Path) -> Path:
        ...


# ---------- DirWriter (변경 없음: 로컬 검토용) --------------------------------

def _coord(c: Coord | None) -> dict | None:
    return None if c is None else {"lat": c.lat, "lon": c.lon, "alt": c.alt}


def _spec_to_dict(spec: ScnxSpec) -> dict:
    return {
        "scenario_id": spec.scenario_id, "terrain": spec.terrain,
        "entities": [{**{k: v for k, v in asdict(e).items() if k != "coord"},
                      "coord": _coord(e.coord)} for e in spec.entities],
        "control_objects": [
            {"ref_id": c.ref_id, "kind": c.kind, "uuid": c.uuid,
             "name": c.name, "coord": _coord(c.coord),
             "vertices": [_coord(v) for v in c.vertices]}
            for c in spec.control_objects],
        "entity_plans": {oid: [asdict(s) for s in steps]
                         for oid, steps in spec.entity_plans.items()},
    }


class DirWriter:
    def write(self, spec: ScnxSpec, out_dir: Path) -> Path:
        seg_dir = Path(out_dir) / spec.scenario_id
        plans_dir = seg_dir / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (seg_dir / "spec.json").write_text(
            json.dumps(_spec_to_dict(spec), ensure_ascii=False, indent=2),
            encoding="utf-8")
        for e in spec.entities:
            blocks = [s.pln for s in spec.entity_plans.get(e.object_id, [])
                      if s.pln]
            (plans_dir / f"{e.object_id}.pln").write_text(
                "\n".join(blocks), encoding="utf-8")
        scnx = seg_dir.with_suffix(".scnx")
        with zipfile.ZipFile(scnx, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("spec.json", (seg_dir / "spec.json").read_text("utf-8"))
            for pln in sorted(plans_dir.glob("*.pln")):
                z.writestr(f"plans/{pln.name}", pln.read_text("utf-8"))
        return scnx


# ---------- TemplateScnxWriter (golden 기반 실제 저작) ------------------------

# 고정 Plan 래퍼 리터럴(golden ys2.pln에서 확인). plan-name uuid = 엔티티 uuid.
_PLAN_VARS = (
    '      (plan-variables \n'
    '         (DtRwPlanSimulationObject\n'
    '            (SimulationObject_12345678910  "VRF_UUID:SimulationObject_12345678910"\n'
    '               (title \n                  (string-queue \n'
    '                     (translate=DtRwTranslatableStringObject "Simulation Object")\n'
    '                  )\n               )\n               (simulation-object  "")\n'
    '            )\n         )\n'
    '         (DtRwPlanSimulationObject\n'
    '            (CreatedObject_12345678910  "VRF_UUID:CreatedObject_12345678910"\n'
    '               (title \n                  (string-queue \n'
    '                     (translate=DtRwTranslatableStringObject "Created Object")\n'
    '                  )\n               )\n               (simulation-object  "")\n'
    '            )\n         )\n      )\n')

_FORCE = {"BLUE": "ForceFriendly", "RED": "ForceOpposing"}

# golden 복제 시 값 치환 대상 필드 정규식
_RE_OID = re.compile(r'\(object-identifier\s+"[^"]*"')
_RE_OTYPE = re.compile(r"\(object-type\s+\d+\s+\([\d ]+\)")
_RE_MARK = re.compile(r'\(marking-text "[^"]*"')
_RE_LABEL = re.compile(r'\(object-label "[^"]*"')
_RE_UUID = re.compile(r'\(uuid\s+"VRF_UUID:[^"]*"')
_RE_FORCE = re.compile(r"\(force\s+Force\w+\)")
_RE_POS = re.compile(
    r"\(position\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*\)")


def _fmt_ecef(c: Coord) -> str:
    x, y, z = c.to_ecef()
    return f"{x:.6f} {y:.6f} {z:.6f}"


def _ascii_stem(seg: str) -> str:
    """내부 파일명/출력명은 ASCII로. 한글 파일명이 VR-Forces zip 처리에서
    문제될 여지를 없앤다(golden도 'ys2' ASCII였음). scenario-name(표시용)은
    원래 한글을 유지한다."""
    m = re.match(r"(\d+)일차(?:-(\d+))?$", seg)
    if m:
        return f"day{m.group(1)}" + (f"_{m.group(2)}" if m.group(2) else "")
    return re.sub(r"[^0-9A-Za-z_-]", "_", seg) or "scn"


class TemplateScnxWriter:
    def __init__(self, golden_path: str = "yewon_test.scnx",
                 emit_plans: bool = True) -> None:
        self.golden = Golden.load(golden_path)
        self.emit_plans = emit_plans
        self._plat = self.golden.template_for("1")   # 차량/장비
        self._life = self.golden.template_for("3")   # 보병
        self._point = self.golden.template_for("16")  # 점
        self._route = self.golden.template_for("17")  # 라우트

    # --- 레코드 치환 ---------------------------------------------------------
    def _entity_record(self, e: EntitySpec, oid: str, mark: str) -> str:
        if e.dis is None:
            raise ValueError(f"DIS 미확정으로 저작 불가: {e.object_id} "
                             "(dis_catalog.csv 채우기 필요)")
        # 정확히 같은 DIS 모델의 실제 golden 레코드를 우선 사용(시스템·부품이
        # 모델과 일치해 인스턴스화 안전). 없을 때만 종류별 대표로 폴백.
        exact = self.golden.entity_by_dis(e.dis)
        tmpl = exact or (self._life if e.dis and e.dis[0] == 3 else self._plat)
        if tmpl is None:
            raise ValueError("golden에 해당 부류 엔티티 템플릿이 없음")
        dis = " ".join(str(x) for x in e.dis)
        force = _FORCE.get(e.faction, "ForceNeutral")
        r = tmpl.raw
        r = _RE_OID.sub(f'(object-identifier  "{oid}"', r, count=1)
        r = _RE_OTYPE.sub(f"(object-type  1 ({dis})", r)
        # marking-text는 DIS 네트워크 이름(11byte 한계) — 한글은 초과·깨짐.
        # 짧은 ASCII를 쓰고 한글 원명은 object-label(로컬)에 둔다.
        r = _RE_MARK.sub(f'(marking-text "{mark}"', r, count=1)
        r = _RE_LABEL.sub(f'(object-label "{e.name}"', r, count=1)
        r = _RE_UUID.sub(f'(uuid  "VRF_UUID:{e.uuid}"', r, count=1)
        r = _RE_FORCE.sub(f"(force {force})", r, count=1)
        r = _RE_POS.sub(f"(position  {_fmt_ecef(e.coord)})", r)
        return r

    def _control_record(self, c: ControlObjectSpec, oid: str, mark: str) -> str:
        tmpl = self._route if c.kind == "ROUTE" else self._point
        if tmpl is None:
            raise ValueError("golden에 control-object 템플릿이 없음")
        r = tmpl.raw
        r = _RE_OID.sub(f'(object-identifier  "{oid}"', r, count=1)
        r = _RE_MARK.sub(f'(marking-text "{mark}"', r, count=1)
        r = _RE_LABEL.sub(f'(object-label "{c.name}"', r, count=1)
        r = _RE_UUID.sub(f'(uuid  "VRF_UUID:{c.uuid}"', r, count=1)
        if c.coord is not None:
            r = _RE_POS.sub(f"(position  {_fmt_ecef(c.coord)})", r)
        return r

    def _oob(self, spec: ScnxSpec) -> str:
        parts = ["(order-of-battle"]
        n = 3001
        for e in spec.entities:
            # marking은 DIS 네트워크 이름(11byte). 객체 ID에서 하이픈만 빼면
            # 최장 11자에 딱 들어가고 전부 유일하다. Data Logger 출력에서
            # 시나리오 객체로 되짚으려면 이 값이 의미를 가져야 한다.
            parts.append("  " + self._entity_record(
                e, f"1:3001:{n}", e.object_id.replace("-", "")[:11]))
            n += 1
        for k, c in enumerate(spec.control_objects, 1):
            parts.append("  " + self._control_record(c, f"1:3001:{n}", f"P{k}"))
            n += 1
        parts.append(")\n")
        return "\n".join(parts)

    def _pln(self, spec: ScnxSpec) -> str:
        out = ['(', '   (Plan-File (version "2.0"))']
        if not self.emit_plans:
            out.append(")\n")
            return "\n".join(out)
        for e in spec.entities:
            blocks = [s.pln for s in spec.entity_plans.get(e.object_id, [])
                      if s.pln]
            if not blocks:
                continue
            body = "\n".join("         " + b for b in blocks)
            out.append(
                "(Plan \n      (pending-triggers )\n      (triggers )\n"
                f'      (plan-name  "VRF_UUID:{e.uuid}")\n'
                "      (quick-launch-flags 4)\n      (ordinal 1)\n"
                f"{_PLAN_VARS}"
                f"      (Block \n{body}\n      )\n"
                "      (plan-execution-stack \n      )\n   )")
        out.append(")\n")
        return "\n".join(out)

    def _omp(self, spec: ScnxSpec) -> str:
        """object-map(.omp) — 시나리오의 모든 객체 uuid 목록.

        VR-Forces가 이 주소맵으로 객체를 인스턴스화한다. 여기 없는 .oob
        객체는 로드돼도 화면/목록에 나타나지 않는다(golden .omp는 전 객체
        uuid를 1:1로 담고 있었음).
        """
        rows = []
        for uid in ([e.uuid for e in spec.entities]
                    + [c.uuid for c in spec.control_objects]):
            rows.append(
                f'      (map-entry \n         (address  1 3001)\n'
                f'         (uuid  "VRF_UUID:{uid}")\n      )')
        return "(address-map \n   (object-map \n" + "\n".join(rows) + "\n   )\n)\n"

    def _scn(self, spec: ScnxSpec, stem: str) -> str:
        raw = self.golden.files[_gname(self.golden, ".scn")].decode(
            "utf-8", "replace")
        # 내부 파일 basename을 golden stem(ys2) → 이 시나리오 stem으로 교체
        gstem = _gstem(self.golden)
        raw = raw.replace(gstem, stem)
        raw = re.sub(r'\(scenario-name "[^"]*"',
                     f'(scenario-name "{spec.scenario_id}"', raw, count=1)
        return raw

    # --- 저작 ---------------------------------------------------------------
    def write(self, spec: ScnxSpec, out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = _ascii_stem(spec.scenario_id)
        gstem = _gstem(self.golden)

        payload: dict[str, bytes] = {}
        # 1) 생성 파일
        payload[f"{stem}.scn"] = self._scn(spec, stem).encode("utf-8")
        payload[f"{stem}.oob"] = self._oob(spec).encode("utf-8")
        payload[f"{stem}.pln"] = self._pln(spec).encode("utf-8")
        payload[f"{stem}.omp"] = self._omp(spec).encode("utf-8")
        # 2) 나머지는 golden boilerplate를 stem만 바꿔 복제(객체 uuid 참조 없음)
        for name, data in self.golden.files.items():
            base = name[len(gstem):] if name.startswith(gstem) else name
            ext = Path(name).suffix
            if ext in (".scn", ".oob", ".pln", ".omp"):
                continue
            payload[f"{stem}{base}"] = data

        scnx = out_dir / f"{stem}.scnx"
        with zipfile.ZipFile(scnx, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in payload.items():
                z.writestr(name, data)
        return scnx


def _gname(g: Golden, suffix: str) -> str:
    for n in g.files:
        if n.endswith(suffix):
            return n
    raise KeyError(suffix)


def _gstem(g: Golden) -> str:
    return Path(_gname(g, ".scn")).stem


def get_writer(name: str, golden: str = "yewon_test.scnx") -> IScnxWriter:
    if name == "dir":
        return DirWriter()
    if name == "template":
        return TemplateScnxWriter(golden)
    raise ValueError(f"알 수 없는 writer: {name} (dir|template)")
