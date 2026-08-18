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

from ..geometry import Coord, tait_bryan
from .golden import Golden
from .spec import ControlObjectSpec, EntitySpec, ScnxSpec


class IScnxWriter(Protocol):
    def write(self, spec: ScnxSpec, out_dir: Path) -> Path:
        ...


# ---------- DirWriter (변경 없음: 로컬 검토용) --------------------------------

def _zip_write(z: zipfile.ZipFile, name: str, data) -> None:
    """날짜를 고정해 zip에 넣는다.

    writestr에 이름만 주면 현재 시각이 박혀 같은 입력에도 바이트가 달라진다.
    pack.ensure_golden과 같은 규칙(1980-01-01)을 쓴다.
    """
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


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
        # raw는 20KB짜리 원본 레코드라 검토용 JSON에는 넣지 않는다.
        "fixed_objects": [
            {"marking": f.marking, "label": f.label, "uuid": f.uuid,
             "dis": list(f.dis), "coord": _coord(f.coord),
             "plan": spec.fixed_plans.get(f.marking, [])}
            for f in spec.fixed_objects],
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
            _zip_write(z, "spec.json",
                       (seg_dir / "spec.json").read_text("utf-8"))
            for pln in sorted(plans_dir.glob("*.pln")):
                _zip_write(z, f"plans/{pln.name}", pln.read_text("utf-8"))
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

# force별 조직 트리 루트. VR-Forces가 시나리오마다 항상 만드는 노드라 이 이름은
# 어떤 .oob에서도 해석된다(golden의 aggregate UUID와 달리).
_FORCE_ROOT = {"ForceFriendly": "1 Force", "ForceOpposing": "2 Force",
               "ForceNeutral": "3 Force"}

# golden 복제 시 값 치환 대상 필드 정규식
_RE_OID = re.compile(r'\(object-identifier\s+"[^"]*"')
_RE_OTYPE = re.compile(r"\(object-type\s+\d+\s+\([\d ]+\)")
_RE_MARK = re.compile(r'\(marking-text "[^"]*"')
_RE_LABEL = re.compile(r'\(object-label "[^"]*"')
_RE_UUID = re.compile(r'\(uuid\s+"VRF_UUID:[^"]*"')
_RE_FORCE = re.compile(r"\(force\s+Force\w+\)")
_RE_PARENT = re.compile(r'\(parent-name\s+"[^"]*"\)')
_RE_SUBFL = re.compile(r"\(subordinate-of-force-level\s+\w+\)")
# 조직 트리 점검용 — 값만 뽑는다. parent-name은 USE-DEFAULT(따옴표 없음)도 온다.
_RE_UUID_VAL = re.compile(r'\(uuid\s+"VRF_UUID:([^"]*)"')
_RE_PARENT_VAL = re.compile(r'\(parent-name\s+(?:"VRF_UUID:([^"]*)"|(\S+?))\s*\)')
_RE_POS = re.compile(
    r"\(position\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*\)")
# 자세. 복제한 공여체의 값을 그대로 두면 전원이 같은 쪽을 본다 — 2026-08-09
# 실측에서 343객체 전부 heading 0°(진북)였고, 아군·적군이 같은 방향을 보고
# 서 있었다. reference-orientation은 move-along 프로세스가 쓰는 기준 자세라
# 같이 맞춘다.
_RE_ORIENT = re.compile(
    r"\(orientation-tait-bryan\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*"
    r"\s+-?\d[\d.eE+-]*\)")
_RE_REF_ORIENT = re.compile(
    r"\(reference-orientation\s+-?\d[\d.eE+-]*\s+-?\d[\d.eE+-]*"
    r"\s+-?\d[\d.eE+-]*\)")
# state-data의 AI 스위치. golden·campaign 레코드는 True로 저장돼 있다.
_RE_AI = re.compile(r"\(DtRwBoolean\s+AIEnabled\s+\w+((?:\s+publish)?)\)")

# 저작 시 모든 객체의 AI를 끈다(사용자 결정 2026-08-04, 2026-08-05 자동화).
# 매뉴얼 34.3대로 충돌회피·자동사격·피격반응만 꺼지고 task는 그대로 돈다
# (실측: 328객체 중 294객체가 AI Off로 오류 없이 수행). 켜 두면 계획에 없는
# 교전이 일어나 시나리오가 일찍 끝난다 — 그래서 기본값이 False다.
AI_ENABLED_DEFAULT = False


def _ai_switch(oob: str, enabled: bool) -> str:
    """.oob 안의 AIEnabled를 전부 원하는 값으로 맞춘다.

    스위치가 없는 객체에는 만들어 넣지 않는다. 통제점·라우트에는 state-data가
    없고, 거기에 AI 스위치를 넣으면 golden에 없는 형태가 된다.
    """
    return _RE_AI.sub(
        rf"(DtRwBoolean AIEnabled {'True' if enabled else 'False'}\1)", oob)


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


def _check_org_tree(oob: str) -> None:
    """parent-name이 이 .oob 안에서 해석되는가.

    복제해 온 레코드가 원본 시나리오의 aggregate를 그대로 가리키면, 그 UUID는
    여기 없다. VR-Forces는 조직 트리를 못 닫고 로딩이 끝나지 않는다(실측:
    battle.scnx 무한 로딩 — golden '부대 1' 예하 4개). 파일을 쓰기 전에 잡는다.
    """
    declared = set(_RE_UUID_VAL.findall(oob)) | set(_FORCE_ROOT.values())
    dangling = sorted({a for a, b in _RE_PARENT_VAL.findall(oob)
                       if a and a not in declared} |
                      {b for a, b in _RE_PARENT_VAL.findall(oob)
                       if b and b != "USE-DEFAULT"})
    if dangling:
        raise ValueError(
            "이 .oob에 없는 상위 노드를 parent-name이 참조한다 "
            f"(로딩이 끝나지 않는다): {dangling}")


class TemplateScnxWriter:
    def __init__(self, golden_path: str = "yewon_test.scnx",
                 emit_plans: bool = True,
                 ai_enabled: bool = AI_ENABLED_DEFAULT) -> None:
        self.golden = Golden.load(golden_path)
        self.emit_plans = emit_plans
        self.ai_enabled = ai_enabled
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
        # golden 레코드의 상위 노드를 그대로 두면 두 가지가 깨진다.
        # (1) donor가 golden의 aggregate('부대 1') 예하였으면 이 .oob에 없는
        #     UUID를 참조한다 — VR-Forces가 조직 트리를 못 닫아 로딩이 안 끝난다.
        # (2) donor가 '1 Force' 직속이면 force만 ForceOpposing으로 바꾼 적군이
        #     아군 force 밑에 들어간다.
        # force에 맞는 루트로 다시 걸고 force 직속으로 되돌린다.
        r = _RE_PARENT.sub(
            f'(parent-name  "VRF_UUID:{_FORCE_ROOT[force]}")', r, count=1)
        r = _RE_SUBFL.sub("(subordinate-of-force-level True)", r, count=1)
        r = _RE_POS.sub(f"(position  {_fmt_ecef(e.coord)})", r)
        # 방위는 ECEF 기준 오일러각이라 위경도마다 값이 다르다 — 좌표를 바꾼
        # 다음에 계산해야 맞는다. 피치·롤은 0으로 둔다(Ground Clamping이
        # 지면 경사를 잡는다).
        tb = " ".join(f"{v:.6f}" for v in tait_bryan(e.coord, e.heading))
        r = _RE_ORIENT.sub(f"(orientation-tait-bryan  {tb})", r)
        r = _RE_REF_ORIENT.sub(f"(reference-orientation  {tb})", r)
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
        for f in spec.fixed_objects:
            # 원본 시나리오의 레코드를 쓴다. object-identifier만 이 .oob 안에서
            # 유일하도록 다시 매긴다. 좌표·고도·짐벌은 fixed.load_fixed가 이미
            # config 값으로 치환해 뒀다 — 여기서는 더 손대지 않는다.
            parts.append("  " + _RE_OID.sub(
                f'(object-identifier  "1:3001:{n}"', f.raw, count=1))
            n += 1
        parts.append(")\n")
        # AI 스위치는 마지막에 한 번에 맞춘다 — 엔티티·통제점·고정 객체 중
        # 어느 경로로 들어온 레코드든 빠짐없이 같은 값이 되게.
        oob = _ai_switch("\n".join(parts), self.ai_enabled)
        _check_org_tree(oob)
        return oob

    @staticmethod
    def _plan(uuid: str, blocks: list[str]) -> str:
        body = "\n".join("         " + b for b in blocks)
        return ("(Plan \n      (pending-triggers )\n      (triggers )\n"
                f'      (plan-name  "VRF_UUID:{uuid}")\n'
                "      (quick-launch-flags 4)\n      (ordinal 1)\n"
                f"{_PLAN_VARS}"
                f"      (Block \n{body}\n      )\n"
                "      (plan-execution-stack \n      )\n   )")

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
            out.append(self._plan(e.uuid, blocks))
        # 고정 객체 플랜. 붙는 행동은 task_catalog에 있는 것만이고, Plan 요소는
        # spec.FIXED_PLAN_ELEMENTS가 거른다(UAV는 Set + 선회 감시 Task).
        for f in spec.fixed_objects:
            blocks = list(spec.fixed_plans.get(f.marking, ()))
            if not blocks:
                continue
            out.append(self._plan(f.uuid, blocks))
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
                    + [c.uuid for c in spec.control_objects]
                    + [f.uuid for f in spec.fixed_objects]):
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
                _zip_write(z, name, data)
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
