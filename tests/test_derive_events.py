"""파생 레이어의 입력 인덱스 — battle.jsonl을 읽기만 한다."""
from pathlib import Path

import pytest

from vtmak.derive.events import EventIndex

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "build" / "events" / "battle.jsonl"


@pytest.fixture(scope="module")
def idx():
    return EventIndex.load(EVENTS)


def test_loads_every_event_as_parser_event(idx):
    """파생 모듈은 자기 이벤트 스키마를 만들지 않는다 — parser.Event 그대로다."""
    from vtmak.parser import Event
    assert len(idx.events) == 3000
    assert all(isinstance(e, Event) for e in idx.events)


def test_indexes_by_line_actor_and_predicate(idx):
    """같은 원문 줄에서 나온 이벤트가 한 묶음으로 잡혀야 R1이 성립한다."""
    hit = next(e for e in idx.events if e.predicate == "hitBy")
    mates = idx.by_line(hit.line_no)
    assert hit in mates
    assert {e.predicate for e in mates} >= {"hitBy", "engagementSource"}
    assert len(idx.by_predicate("directFireAt")) == 77
    assert all(e.actor == hit.actor for e in idx.by_actor(hit.actor))


def test_actor_events_are_time_ordered(idx):
    """R3·R7이 시간 최근접·인접에 기대므로 정렬은 인덱스가 보증한다."""
    for actor in ("FR-INF-001", "EN-INF-001"):
        seq = idx.by_actor(actor)
        assert [e.time_s for e in seq] == sorted(e.time_s for e in seq)


def test_missing_file_is_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        EventIndex.load(tmp_path / "없는파일.jsonl")
