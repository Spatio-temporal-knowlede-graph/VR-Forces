"""battle.jsonl → 규칙이 쓰는 세 가지 색인.

규칙마다 이벤트를 훑으면 3,000건을 규칙 수만큼 다시 읽는다. 그보다 나쁜 것은
정렬을 규칙마다 따로 하는 것이다 — R3의 '시간 최근접'과 R7의 '시간 인접'이
서로 다른 순서를 보면 조용히 다른 답이 나온다. 순서는 여기서 한 번만 정한다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..parser import Event

# 이벤트 정렬 키. 같은 시각이면 event_id가 원문 등장 순서라 그걸 따른다.
_ORDER = lambda e: (e.time_s, e.event_id)   # noqa: E731


class EventIndex:
    def __init__(self, events: list[Event]) -> None:
        self.events: tuple[Event, ...] = tuple(sorted(events, key=_ORDER))
        self._line: dict[int, tuple[Event, ...]] = {}
        self._actor: dict[str, tuple[Event, ...]] = {}
        self._pred: dict[str, tuple[Event, ...]] = {}
        for key, get in ((self._line, lambda e: e.line_no),
                         (self._actor, lambda e: e.actor),
                         (self._pred, lambda e: e.predicate)):
            acc: dict = defaultdict(list)
            for e in self.events:
                acc[get(e)].append(e)
            key.update({k: tuple(v) for k, v in acc.items()})

    @classmethod
    def load(cls, path) -> "EventIndex":
        path = Path(path)
        text = path.read_text(encoding="utf-8")     # 없으면 FileNotFoundError
        return cls([Event(**json.loads(line))
                    for line in text.splitlines() if line.strip()])

    def by_line(self, line_no: int) -> tuple[Event, ...]:
        return self._line.get(line_no, ())

    def by_actor(self, actor: str) -> tuple[Event, ...]:
        return self._actor.get(actor, ())

    def by_predicate(self, predicate: str) -> tuple[Event, ...]:
        return self._pred.get(predicate, ())

    def ids(self) -> set[str]:
        """참조 무결성 검사용 — provenance가 가리켜도 되는 event_id 전부."""
        return {e.event_id for e in self.events}
