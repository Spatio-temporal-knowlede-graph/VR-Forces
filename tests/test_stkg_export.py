from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.stkg.export import build

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def layout():
    return BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")


def _row(subject, predicate, ts="2026-08-03T05:20:00.000Z",
         lat="21.3", lon="-157.7", source="GROUND_TRUTH"):
    return {"subject": subject, "predicate": predicate, "object": "-",
            "latitude": lat, "longitude": lon, "timestamp": ts,
            "source": source, "CID": "-1"}


def test_accounting_invariant_holds(layout):
    rows = [
        _row("1 Force", "None"),
        _row("E5", "None"),
        _row("ENT72003", "None", ts="1970-01-01T12:00:04.040Z"),
        _row("FRINF001", 'Follow-Entity Entity: "ENINF001" Offset: <-0 0 -0 >'),
        _row("FRINF002", "None"),
        _row("FRINF003", "Completely-Unknown-Task foo=1"),
    ]
    _, positions, tally, _ = build(rows, layout, {}, {})
    assert tally.total == len(rows)
    assert (tally.relation_rows + tally.position_rows
            + tally.dropped + tally.quarantined) == tally.total


def test_infra_and_effects_never_reach_output(layout):
    rows = [_row("1 Force", "None"), _row("GlobalEnv 1", "None"),
            _row("E9", "None"), _row("Observer 1", "None")]
    relations, positions, tally, _ = build(rows, layout, {}, {})
    assert relations == []
    assert positions == []
    assert tally.dropped == 4


def test_follow_entity_becomes_a_relation_with_an_object(layout):
    rows = [_row("FRINF001",
                 'Follow-Entity Entity: "ENINF001" Offset: <-0 0 -0 >')]
    relations, _, _, _ = build(rows, layout, {}, {})
    assert len(relations) == 1
    assert relations[0].predicate == "follows"
    assert relations[0].object == "ENINF001"
    assert relations[0].object_type == "entity"
    assert relations[0].confidence == "observed"


def test_none_predicate_goes_to_positions(layout):
    relations, positions, tally, _ = build([_row("FRINF001", "None")],
                                           layout, {}, {})
    assert relations == []
    assert len(positions) == 1
    assert positions[0]["subject"] == "FRINF001"
    assert positions[0]["kind"] == "entity"


def test_unresolvable_uuid_keeps_the_uuid_and_is_marked(layout):
    """짝이 되는 .oob이 없으면 uuid를 버리지 않고 표시한다."""
    rows = [_row("FRINF001",
                 'Move-To Waypoint: "62f22b9c-d768-531d-9242-e32d8a056ee9"')]
    relations, _, _, _ = build(rows, layout, {}, {})
    assert relations[0].object == "62f22b9c-d768-531d-9242-e32d8a056ee9"
    assert relations[0].object_type == "uuid"


def test_resolvable_uuid_becomes_a_marking(layout):
    rows = [_row("FRINF001",
                 'Move-To Waypoint: "62f22b9c-d768-531d-9242-e32d8a056ee9"')]
    umap = {"62f22b9c-d768-531d-9242-e32d8a056ee9": "P7"}
    relations, _, _, _ = build(rows, layout, umap, {})
    assert relations[0].object == "P7"
    assert relations[0].object_type == "waypoint"


def test_every_relation_has_a_non_empty_object(layout):
    rows = [_row("FRINF001",
                 "Move to {-5499123.141030, -2250320.406046, 2311025.754248}"),
            _row("FRINF002",
                 'Follow-Entity Entity: "ENINF001" Offset: <-0 0 -0 >')]
    relations, _, _, _ = build(rows, layout, {}, {})
    assert relations
    for rel in relations:
        assert rel.object


def test_a_relation_row_does_not_also_become_a_position(layout):
    """한 행은 관계 아니면 위치, 둘 중 하나다. 양쪽에 넣으면 회계가 맞아도
    파일 내용이 어긋난다."""
    rows = [_row("FRINF001",
                 'Follow-Entity Entity: "ENINF001" Offset: <-0 0 -0 >')]
    relations, positions, tally, _ = build(rows, layout, {}, {})
    assert len(relations) == 1
    assert positions == []
    assert tally.position_rows == 0
    assert tally.relation_rows == 1


def test_position_count_matches_the_positions_list(layout):
    rows = [_row("FRINF001", "None"), _row("FRINF002", "None"),
            _row("FRINF003",
                 'Follow-Entity Entity: "ENINF001" Offset: <-0 0 -0 >')]
    _, positions, tally, _ = build(rows, layout, {}, {})
    assert len(positions) == tally.position_rows == 2


def test_unparsed_predicates_are_counted_not_dropped(layout):
    rows = [_row("FRINF001", "Completely-Unknown-Task foo=1")]
    _, positions, tally, _ = build(rows, layout, {}, {})
    assert tally.unparsed == {"Completely-Unknown-Task foo=1": 1}
    assert len(positions) == 1   # 위치는 살린다
