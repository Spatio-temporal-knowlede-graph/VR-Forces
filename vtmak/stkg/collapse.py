"""tick 단위 관측을 구간 관계로 접는다.

'Follow-Entity → ENINF001'이 46,976행이지만 표현하는 사실은 '누가 언제부터
언제까지 따랐다'뿐이다. 지식그래프의 시간 표현으로도 구간이 정본이고,
입력의 완전중복 54.5%도 여기서 함께 사라진다.

공백을 사이에 두고 같은 관계가 재개되면 나눈다. 이어붙이면 관측하지 않은
구간을 관측했다고 주장하게 된다. GT 샘플링에 1,058초·215초 공백이 있다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .derive import Obs


@dataclass(frozen=True)
class Relation:
    subject: str
    predicate: str
    object: str
    object_type: str
    t_start: str
    t_end: str
    source: str
    confidence: str
    evidence: str


def _t(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def collapse(obs: list[Obs], gap_s: float = 3.0) -> list[Relation]:
    key = lambda o: (o.subject, o.predicate, o.object, o.object_type,
                     o.source, o.confidence)
    out: list[Relation] = []
    groups: dict[tuple, list[Obs]] = {}
    for o in obs:
        groups.setdefault(key(o), []).append(o)

    for k, items in groups.items():
        items.sort(key=lambda o: _t(o.timestamp))
        start = prev = items[0]
        for cur in items[1:]:
            if (_t(cur.timestamp) - _t(prev.timestamp)).total_seconds() > gap_s:
                out.append(Relation(*k[:4], start.timestamp, prev.timestamp,
                                    k[4], k[5], start.evidence))
                start = cur
            prev = cur
        out.append(Relation(*k[:4], start.timestamp, prev.timestamp,
                            k[4], k[5], start.evidence))

    out.sort(key=lambda r: (r.t_start, r.subject, r.predicate, r.object))
    return out
