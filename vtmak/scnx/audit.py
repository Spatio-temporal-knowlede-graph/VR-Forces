"""저작된 .scnx 되읽기 → 객체별 태스크 타임테이블.

03이 만드는 timetable/battle.csv는 '원문 이벤트가 말하는 상태·위치'다.
이건 그 반대 방향이다 — 실제로 파일에 들어간 .oob 객체와 .pln 태스크를
다시 파싱해서, 객체마다 무슨 행동을 몇 시에 갖는지 보여준다. 스펙을 믿지
않고 산출물을 믿는다(저작 누락은 여기서만 보인다).

시각은 .pln에 없다(VR-Forces 플랜은 순서만 가진 큐다). 그래서 스펙의
PlanStep과 순서로 맞물려 event 시각을 붙인다. 개수가 어긋나면 그 자체가
결함이므로 조용히 넘기지 않고 note에 남긴다.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..parser import Event
from .catalog import TaskKinds
from .golden import _balanced_records  # 괄호 균형 레코드 절단(같은 포맷)
from .spec import ScnxSpec

_UUID_RE = re.compile(r'VRF_UUID:([0-9a-fA-F][0-9a-fA-F-]+)')
_PLAN_NAME_RE = re.compile(r'\(plan-name\s+"VRF_UUID:([^"]+)"')
_TASK_TYPE_RE = re.compile(r'\(task-type\s+"([^"]*)"\)')
_SET_TYPE_RE = re.compile(r'\(set-data-request-type\s+"([^"]*)"\)')
_SCRIPT_ID_RE = re.compile(r'\(script-id\s+"([^"]*)"\)')
_OID_RE = re.compile(r'\(object-identifier\s+"([^"]*)"')
_MARK_RE = re.compile(r'\(marking-text "([^"]*)"')
_LABEL_RE = re.compile(r'\(object-label "([^"]*)"')
_OTYPE_RE = re.compile(r"\(object-type\s+\d+\s+\(([\d ]+)\)")
_UUID_FIELD_RE = re.compile(r'\(uuid\s+"VRF_UUID:([^"]+)"')
_PLAN_HEAD_RE = re.compile(r"\(Plan(?=\s)")          # (Plan-File은 걸리지 않는다
_STEP_HEAD_RE = re.compile(r"\((?:Task|Set)(?=\s)")


@dataclass(frozen=True)
class ScnxObject:
    identifier: str
    marking: str
    label: str
    uuid: str
    dis: tuple[int, ...]

    @property
    def kind(self) -> str:
        return str(self.dis[0]) if self.dis else ""


@dataclass(frozen=True)
class ScnxTask:
    seq: int                    # 플랜 내 순번(1부터)
    task_type: str
    script_id: str
    refs: tuple[str, ...]       # 태스크가 참조하는 uuid들


@dataclass
class ScnxContents:
    stem: str
    objects: list[ScnxObject] = field(default_factory=list)
    plans: dict[str, list[ScnxTask]] = field(default_factory=dict)


def read_scnx(path) -> ScnxContents:
    """.scnx(zip)에서 .oob 객체와 .pln 플랜을 되읽는다."""
    with zipfile.ZipFile(Path(path)) as z:
        names = z.namelist()
        oob_name = next((n for n in names if n.endswith(".oob")), "")
        pln_name = next((n for n in names if n.endswith(".pln")), "")
        oob = z.read(oob_name).decode("utf-8", "replace") if oob_name else ""
        pln = z.read(pln_name).decode("utf-8", "replace") if pln_name else ""
    return ScnxContents(stem=Path(oob_name or pln_name).stem,
                        objects=parse_oob(oob), plans=parse_pln(pln))


def parse_oob(oob: str) -> list[ScnxObject]:
    out: list[ScnxObject] = []
    for raw in _balanced_records(oob, "(local-vrf-object"):
        ot = _OTYPE_RE.search(raw)
        uid = _UUID_FIELD_RE.search(raw)
        if not ot or not uid:
            continue
        oid = _OID_RE.search(raw)
        mark = _MARK_RE.search(raw)
        label = _LABEL_RE.search(raw)
        out.append(ScnxObject(
            identifier=oid.group(1) if oid else "",
            marking=mark.group(1) if mark else "",
            label=label.group(1) if label else "",
            uuid=uid.group(1),
            dis=tuple(int(x) for x in ot.group(1).split())))
    return out


def parse_pln(pln: str) -> dict[str, list[ScnxTask]]:
    """plan-name uuid(=엔티티 uuid) → 순서대로의 태스크 목록.

    Block 안에는 (Task ...) 말고 (Set ...)도 섞인다(보급 저속 기동의
    set-speed). 스펙의 PlanStep과 1:1로 맞물리려면 둘 다 순서대로 세야 한다.
    """
    plans: dict[str, list[ScnxTask]] = {}
    for raw in _records(pln, _PLAN_HEAD_RE):
        name = _PLAN_NAME_RE.search(raw)
        if not name:
            continue
        tasks: list[ScnxTask] = []
        for i, t in enumerate(_records(raw, _STEP_HEAD_RE), 1):
            ttype = _TASK_TYPE_RE.search(t) or _SET_TYPE_RE.search(t)
            sid = _SCRIPT_ID_RE.search(t)
            tasks.append(ScnxTask(
                seq=i,
                task_type=ttype.group(1) if ttype else "",
                script_id=sid.group(1) if sid else "",
                refs=tuple(dict.fromkeys(_UUID_RE.findall(t)))))
        plans[name.group(1)] = tasks
    return plans


def _records(text: str, head: re.Pattern[str]) -> list[str]:
    """head가 여는 괄호 균형 레코드들을 파일에 나온 순서 그대로 잘라낸다.

    (Plan-File을 (Plan으로 오인하지 않도록 여는 토큰을 정규식으로 잡는다.
    Block 안에는 (Task와 (Set이 섞여 있고 순서가 곧 실행 순서다.
    """
    out: list[str] = []
    for m in head.finditer(text):
        depth, j = 0, m.start()
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(text[m.start():j + 1])
    return out


# ---------- 스펙과 맞물리기 --------------------------------------------------

@dataclass
class TaskRow:
    object_id: str
    name: str
    faction: str
    entity_class: str
    type_group: str
    marking: str
    seq: int
    time_s: int | None
    event_id: str
    template: str
    task_kind: str
    action_label: str
    task_type: str          # .pln 실측
    script_id: str          # .pln 실측
    ref_id: str             # 참조 대상(객체 id 또는 지명)
    ref_kind: str           # ENTITY | CONTROL | COORD | ""
    in_scnx: bool
    note: str


@dataclass
class ObjectRow:
    object_id: str
    name: str
    faction: str
    entity_class: str
    type_group: str
    marking: str
    initial_state: str
    n_tasks: int
    n_dropped: int          # 스펙에서 태스크로 못 간 이벤트 수
    t_first: int | None
    t_last: int | None
    kinds: str              # "move×3 fire_direct×2"
    sequence: str           # "00:00 이동→중앙계곡 | 02:42 직접사격→EN-T72-003"


def hhmmss(t: int | None) -> str:
    if t is None:
        return ""
    return f"{t // 60:02d}:{t % 60:02d}"


def build_rows(spec: ScnxSpec, contents: ScnxContents, kinds: TaskKinds,
               events: list[Event] | None = None
               ) -> tuple[list[TaskRow], list[ObjectRow], list[str]]:
    """스펙(시각·의미) × .scnx 실측(태스크)을 엮어 두 표와 경고를 만든다.

    events를 주면 좌표로 저작된 태스크(move-to-location-task 등, uuid가 없다)의
    참조 대상도 원문 이벤트에서 되살려 ref_id에 채운다. kinds는 그 참조가
    어느 필드에 있는지(config/task_kinds.csv) 찾는 데 쓴다.
    """
    warnings: list[str] = []
    by_event = {e.event_id: e for e in (events or [])}
    by_uuid = {o.uuid: o for o in contents.objects}
    ent_name = {e.uuid: e.object_id for e in spec.entities}
    ctl_name = {c.uuid: c.ref_id for c in spec.control_objects}

    missing = [e.object_id for e in spec.entities if e.uuid not in by_uuid]
    if missing:
        warnings.append(f".oob에 없는 스펙 엔티티 {len(missing)}개: "
                        + ", ".join(missing[:5]))
    # 고정 객체(UAV)도 Set만 든 플랜을 갖는다 — 스펙이 아는 플랜이므로
    # 주인 없는 플랜이 아니다.
    fixed_name = {f.uuid: f.marking for f in spec.fixed_objects}
    orphan = set(contents.plans) - set(ent_name) - set(fixed_name)
    if orphan:
        warnings.append(f"주인 없는 플랜 {len(orphan)}개")

    tasks: list[TaskRow] = []
    objects: list[ObjectRow] = []
    for e in spec.entities:
        steps = spec.entity_plans.get(e.object_id, [])
        authored = [s for s in steps if s.pln]
        actual = contents.plans.get(e.uuid, [])
        obj = by_uuid.get(e.uuid)
        marking = obj.marking if obj else ""
        if len(actual) != len(authored):
            warnings.append(
                f"{e.object_id}: .pln 태스크 {len(actual)}개 ≠ 스펙 {len(authored)}개")

        rows: list[TaskRow] = []
        for i, step in enumerate(authored):
            t = actual[i] if i < len(actual) else None
            ref_id, ref_kind = _resolve_ref(t, ent_name, ctl_name)
            if not ref_id:
                ref_id = _event_ref(by_event.get(step.event_id),
                                    step.task_kind, kinds)
                ref_kind = "COORD" if ref_id else ""
            rows.append(TaskRow(
                object_id=e.object_id, name=e.name, faction=e.faction,
                entity_class=e.entity_class, type_group=e.type_group,
                marking=marking, seq=i + 1, time_s=step.time_s,
                event_id=step.event_id, template=step.template,
                task_kind=step.task_kind,
                action_label=step.action_label or "",
                task_type=t.task_type if t else "",
                script_id=t.script_id if t else "",
                ref_id=ref_id, ref_kind=ref_kind,
                in_scnx=t is not None,
                note="" if t is not None else ".pln에 해당 태스크 없음"))
        # 저작되지 못한 이벤트도 같은 표에 남긴다(누락은 여기서만 보인다).
        for step in steps:
            if step.pln:
                continue
            rows.append(TaskRow(
                object_id=e.object_id, name=e.name, faction=e.faction,
                entity_class=e.entity_class, type_group=e.type_group,
                marking=marking, seq=0, time_s=step.time_s,
                event_id=step.event_id, template=step.template,
                task_kind=step.task_kind, action_label=step.action_label or "",
                task_type="", script_id="",
                ref_id=_event_ref(by_event.get(step.event_id), step.task_kind,
                                  kinds),
                ref_kind="",
                in_scnx=False, note="; ".join(step.issues) or "태스크 미생성"))
        rows.sort(key=lambda r: (r.time_s if r.time_s is not None else 0,
                                 r.seq, r.event_id))
        tasks.extend(rows)

        live = [r for r in rows if r.in_scnx]
        times = [r.time_s for r in live if r.time_s is not None]
        objects.append(ObjectRow(
            object_id=e.object_id, name=e.name, faction=e.faction,
            entity_class=e.entity_class, type_group=e.type_group,
            marking=marking, initial_state=e.initial_state,
            n_tasks=len(live), n_dropped=len(rows) - len(live),
            t_first=min(times) if times else None,
            t_last=max(times) if times else None,
            kinds=_kinds(live), sequence=_sequence(live)))
    return tasks, objects, warnings


def _resolve_ref(task: ScnxTask | None, ent: dict[str, str],
                 ctl: dict[str, str]) -> tuple[str, str]:
    if task is None:
        return "", ""
    for u in task.refs:
        if u in ent:
            return ent[u], "ENTITY"
    for u in task.refs:
        if u in ctl:
            return ctl[u], "CONTROL"
    return "", ""


def _event_ref(e: Event | None, kind: str, kinds: TaskKinds) -> str:
    """좌표로 저작된 태스크의 참조 대상을 원문 이벤트에서 되살린다.

    '좌표로 이동'·'제압사격'·'좌표 대상 간접사격'은 .pln에 uuid가 아니라
    ECEF 좌표만 남는다. 표에서 '어디로/누구를'이 비면 읽을 수 없다.

    동반 행동(`move_slow:속도 지정`처럼 `기반kind:행동`)은 task_kinds.csv에
    없는 이름이다. 참조는 바로 앞뒤의 본 태스크 줄이 이미 보여주므로 비운다.
    """
    if e is None or not kinds.known(kind):
        return ""
    field = kinds.ref_field(kind)
    if field == "unit_leader":       # 선두는 .pln uuid로만 알 수 있다
        return ""
    return getattr(e, field, "") or e.dst or e.target or ""


def _kinds(rows: list[TaskRow]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.task_kind] = counts.get(r.task_kind, 0) + 1
    return " ".join(f"{k}×{v}" for k, v in sorted(counts.items()))


def _sequence(rows: list[TaskRow]) -> str:
    out = []
    for r in rows:
        ref = f"→{r.ref_id}" if r.ref_id else ""
        out.append(f"{hhmmss(r.time_s)} {r.action_label or r.task_kind}{ref}")
    return " | ".join(out)
