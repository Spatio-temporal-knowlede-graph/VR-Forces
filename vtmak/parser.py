"""원문 → 이벤트. 문법 분석 없이 문장 템플릿을 fullmatch한다.

원문은 기계 생성 텍스트라 문장 템플릿이 유한하다(3,000문장 / 16 템플릿).
객체 ID가 문장에 명시되어 있어(**US Army M4(FR-INF-001, 방어 보병 1)**)
행위자·대상 판정이 추측이 아니다. 선행 프로젝트가 조사로 역할을 추측하다
겪은 '행위자와 대상이 뒤바뀜' 문제가 여기서는 발생하지 않는다.
"""
from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .norm import loc_id

# 원문 PDF가 마지막 문장에서 끊겨 있다(변환 손실 아님). 조용히 버리지 않고
# 선언된 예외로 둔다.
KNOWN_TRUNCATION = "**M1028"


def _ent(model: str, ident: str) -> str:
    """**모델명(ID, 역할)** 또는 **모델명(ID)** — 2차 언급엔 역할이 없다."""
    return (r"\*\*(?P<" + model + r">[^*(]+?)\("
            r"(?P<" + ident + r">[A-Z][A-Z0-9\-]+)"
            r"(?:,\s*(?P<" + ident + r"_role>[^)]*?))?\)\*\*")


_T = r"(?P<t>\d\d):(?P<s>\d\d)에 "
_L = r"[^*]+?"          # 지명 — 엔티티 마크업(**)을 넘지 않는다
_S = r"[^*]+?"          # 상태

# 순서가 우선순위다. moveTo가 사격 문장을 삼키므로 사격을 먼저 둔다.
TEMPLATES: list[tuple[str, str]] = [
    ("directFireAt",
     _T + _ent("m", "a") + r"은/는 (?P<src>" + _L + r")에서 "
     + _ent("tm", "tgt") + r"을/를 향해 직접사격을 수행한다"),
    ("aimAt",
     _T + _ent("m", "a") + r"은/는 (?P<src>" + _L + r")에서 "
     + _ent("tm", "tgt") + r"을/를 향해 포신 정렬 후 간접사격 준비을 수행한다"),
    ("indirectFireAt",
     _T + _ent("m", "a") + r"은/는 (?P<src>" + _L + r")에서 "
     + _ent("tm", "tgt") + r"을/를 향해 간접사격을 수행한다"),
    ("hitBy",
     _T + _ent("m", "a") + r"은/는 (?P<loc>" + _L + r")에서 "
     + _ent("sm", "srcobj") + r"의 직접사격에 피격된다"),
    ("hitArea",
     _T + _ent("m", "a") + r"은/는 " + _ent("sm", "srcobj")
     + r"의 사격으로 주변 탄착을 받는다"),
    ("moveTo",
     _T + _ent("m", "a") + r"은/는 (?P<src>" + _L + r")에서 (?P<dst>" + _L
     + r")을/를 향해 (?P<act>[^*]+?)을 수행한다"),
    ("locatedAt",
     _T + _ent("m", "a") + r"은/는 (?P<loc>" + _L + r")에 위치한다"),
    ("stopAt",
     _T + _ent("m", "a") + r"은/는 (?P<loc>" + _L + r")에 정지한다"),
    ("stayAt",
     _T + _ent("m", "a") + r"은/는 (?P<loc>" + _L + r")에 잔류한다"),
    ("targetArea", r"목표 구역은 (?P<loc>" + _L + r")이다"),
    ("stateInit",
     _ent("m", "a") + r"의 초기 상태는 (?P<s1>" + _S + r") 상태이다"),
    ("stateChange",
     _ent("m", "a") + r"은/는 (?P<s0>" + _S + r") 상태에서 (?P<s1>" + _S
     + r") 상태로 전환한다"),
    ("stateHold",
     _ent("m", "a") + r"은/는 (?P<s1>" + _S + r") 상태를 유지한다"),
    ("noTask",
     r"이후 (?P<a>[A-Z][A-Z0-9\-]+)에는 일반 이동·사격 task를 부여하지 않는다"),
    ("engAttacker",
     r"공격자 객체는 (?P<a>[A-Z][A-Z0-9\-]+)이고, "
     r"목표 객체는 (?P<tgt>[A-Z][A-Z0-9\-]+)이다"),
    ("engSource",
     r"피격 원천 객체는 (?P<srcobj>[A-Z][A-Z0-9\-]+)이고, "
     r"피격 대상 객체는 (?P<a>[A-Z][A-Z0-9\-]+)이다"),
]

_COMPILED = [(name, re.compile(pat)) for name, pat in TEMPLATES]


@dataclass
class Event:
    event_id: str
    time_s: int
    line_no: int
    predicate: str
    template: str
    actor: str = ""
    actor_class: str = ""
    actor_role: str = ""
    location: str = ""
    src: str = ""
    dst: str = ""
    target: str = ""
    target_class: str = ""
    target_role: str = ""
    source_obj: str = ""
    source_class: str = ""
    action_label: str = ""
    state_from: str = ""
    state_to: str = ""
    source_line: str = ""

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class ParseResult:
    events: list[Event] = field(default_factory=list)
    unmatched: list[tuple[int, str]] = field(default_factory=list)
    sentence_count: int = 0


class PatternMap:
    """원문 문장 종류 → 술어 + task_kind.

    키가 셋이고 구체적인 쪽이 이긴다.
      state_transition  '<이전>><다음>'  상태전이. 가장 구체적이다
      move_action       이동 행동 이름    moveTo 안에서 갈린다
      template          문장 템플릿 이름  기본값
    """

    def __init__(self) -> None:
        self._tmpl: dict[str, tuple[str, str]] = {}
        self._move: dict[str, tuple[str, str]] = {}
        self._trans: dict[tuple[str, str], tuple[str, str]] = {}

    @classmethod
    def load(cls, path) -> "PatternMap":
        pm = cls()
        with open(Path(path), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                key, kind = row["key"].strip(), row["kind"].strip()
                val = (row["predicate"].strip(), row["task_kind"].strip())
                if kind == "template":
                    pm._tmpl[key] = val
                elif kind == "move_action":
                    pm._move[key] = val
                elif kind == "state_transition":
                    if ">" not in key:
                        raise ValueError(
                            "state_transition 키는 '<이전 상태>><다음 상태>' "
                            f"형식이어야 한다: {key!r}")
                    a, b = key.split(">", 1)
                    pm._trans[(a.strip(), b.strip())] = val
        return pm

    def _row(self, template: str, action_label: str,
             state_from: str, state_to: str) -> tuple[str, str] | None:
        hit = self._trans.get((state_from, state_to))
        if hit is not None:
            return hit
        if template == "moveTo" and action_label in self._move:
            return self._move[action_label]
        return self._tmpl.get(template)

    def predicate_of(self, template: str, action_label: str = "",
                     state_from: str = "", state_to: str = "") -> str:
        row = self._row(template, action_label, state_from, state_to)
        return row[0] if row else ""

    def task_kind_of(self, event) -> str:
        """Event를 통째로 받는다.

        인자를 옵션으로 늘리면 state_from/state_to를 안 넘긴 호출부가 조용히
        다른 답을 받는다. 호출부가 여섯 곳뿐이라 한 번에 바꾼다.
        """
        row = self._row(event.template, event.action_label,
                        event.state_from, event.state_to)
        return row[1] if row else "noop"


def _sentences(text: str):
    """(줄번호, 문장). 원문은 한 줄에 1~3문장이 '다. '로 이어진다."""
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        for part in re.split(r"(?<=다)\.\s*", line):
            part = part.strip().rstrip(".")
            if part:
                yield line_no, part


def parse_scenario(text: str, pattern_map: PatternMap) -> ParseResult:
    res = ParseResult()
    seq = 0
    carry_time = 0          # 시각 없는 문장(상태 서술)은 직전 시각을 잇는다
    for line_no, sent in _sentences(text):
        res.sentence_count += 1
        for name, rx in _COMPILED:
            m = rx.fullmatch(sent)
            if not m:
                continue
            seq += 1
            g = m.groupdict()
            if g.get("t") is not None:
                carry_time = int(g["t"]) * 60 + int(g["s"])
            act = (g.get("act") or "").strip()
            s_from = (g.get("s0") or "").strip()
            s_to = (g.get("s1") or "").strip()
            res.events.append(Event(
                event_id=f"E{seq:05d}",
                time_s=carry_time,
                line_no=line_no,
                template=name,
                predicate=pattern_map.predicate_of(name, act, s_from, s_to),
                actor=g.get("a") or "",
                actor_class=(g.get("m") or "").strip(),
                actor_role=(g.get("a_role") or "").strip(),
                location=loc_id(g["loc"]) if g.get("loc") else "",
                src=loc_id(g["src"]) if g.get("src") else "",
                dst=loc_id(g["dst"]) if g.get("dst") else "",
                target=g.get("tgt") or "",
                target_class=(g.get("tm") or "").strip(),
                target_role=(g.get("tgt_role") or "").strip(),
                source_obj=g.get("srcobj") or "",
                source_class=(g.get("sm") or "").strip(),
                action_label=act,
                state_from=s_from,
                state_to=s_to,
                source_line=sent,
            ))
            break
        else:
            res.unmatched.append((line_no, sent))
    return res
