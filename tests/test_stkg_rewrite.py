"""05 후처리 — 열은 8열 그대로, 술어는 정규형, object는 채운다."""
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.stkg.rewrite import OUT_COLS, rewrite

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def layout():
    return BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")


def _row(subject, predicate, coord, ts="2026-08-03T08:09:12.000Z",
         source="GROUND_TRUTH"):
    lat, lon = coord
    return {"subject": subject, "predicate": predicate, "object": "-",
            "latitude": f"{lat}", "longitude": f"{lon}", "timestamp": ts,
            "source": source, "CID": "-1"}


def _at(layout, lid):
    c = layout.coord(lid)
    return c.lat, c.lon


def _ecef_blob(layout, lid):
    x, y, z = layout.coord(lid).to_ecef()
    return f"{{{x}, {y}, {z}}}"


def test_output_keeps_the_eight_source_columns(layout):
    rows = [_row("FRINF001", "None", _at(layout, "LOC_중앙킬존"))]
    out, _, _, _ = rewrite(rows, layout)
    assert list(out[0]) == OUT_COLS
    assert len(OUT_COLS) == 8


def test_move_becomes_move_to_with_a_place_name(layout):
    lid = "LOC_중앙킬존"
    rows = [_row("FRINF001", f"Move to {_ecef_blob(layout, lid)}",
                 _at(layout, "LOC_동측능선"))]
    out, _, _, _ = rewrite(rows, layout)
    assert out[0]["predicate"] == "move to"
    assert out[0]["object"] == lid


def test_follow_becomes_follow_entity_with_the_followed_entity(layout):
    rows = [_row("ENINF010", 'Follow-Entity Entity: "ENINF001" Offset: <0 0 0>',
                 _at(layout, "LOC_중앙킬존"))]
    out, _, _, _ = rewrite(rows, layout)
    assert out[0]["predicate"] == "Follow-Entity"
    assert out[0]["object"] == "ENINF001"


def test_ffe_becomes_ffe_on_location_with_the_target_place(layout):
    lid = "LOC_적포병진지"
    raw = (f'FFE-On-Location "Location={_ecef_blob(layout, lid)}"  Name of '
           f"Weapons to Fire: Indirect-Fire-Gun:m9333he. Number-Of-Rounds: 1")
    rows = [_row("FRMORT001", raw, _at(layout, "LOC_아군박격포진지"))]
    out, _, _, _ = rewrite(rows, layout)
    assert out[0]["predicate"] == "FFE-on-Location"
    assert out[0]["object"] == lid


def test_find_cover_keeps_the_threat_as_object(layout):
    raw = ("find_cover: ChooseFiringPosition=False; DistanceFromThreat=2; "
           "Threat=FRINF001; Range=50")
    rows = [_row("ENINF001", raw, _at(layout, "LOC_중앙킬존"))]
    out, _, _, _ = rewrite(rows, layout)
    assert out[0]["predicate"] == "find_cover"
    assert out[0]["object"] == "FRINF001"


def test_none_stays_none_with_an_empty_object(layout):
    rows = [_row("FRM901001", "None", _at(layout, "LOC_아군포병진지"))]
    out, _, _, _ = rewrite(rows, layout)
    assert out[0]["predicate"] == "none"
    assert out[0]["object"] == ""


def test_simulator_infrastructure_rows_are_removed(layout):
    """원문에 없고 물리 객체도 아니다. Force는 좌표까지 쓰레기값이다."""
    here = _at(layout, "LOC_중앙킬존")
    rows = [_row("FRINF001", "None", here),
            _row("2 Force", "None", (42.32429274, 45.0)),
            _row("Observer 1", "None", here),
            _row("GlobalEnv 1", "None", here)]
    out, _, _, tally = rewrite(rows, layout)
    assert [r["subject"] for r in out] == ["FRINF001"]
    assert tally.dropped == 3
    assert tally.total == tally.out + tally.dropped


def test_munition_row_gets_fired_by_and_the_confirmed_shooter(layout):
    """세 신호가 다 맞으면 사수가 붙는다."""
    mortar = _at(layout, "LOC_아군박격포진지")
    target_lid = "LOC_적포병진지"
    raw = (f'FFE-On-Location "Location={_ecef_blob(layout, target_lid)}"  Name '
           f"of Weapons to Fire: Indirect-Fire-Gun:m9333he. Number-Of-Rounds: 1")
    rows = [
        _row("FRMORT001", raw, mortar, ts="2026-08-03T08:09:12.000Z"),
        _row("FRMORT001", "None", mortar, ts="2026-08-03T08:09:22.000Z"),
        _row("M933HE 1", "None", mortar, ts="2026-08-03T08:09:22.000Z"),
        _row("M933HE 1", "None", _at(layout, target_lid),
             ts="2026-08-03T08:09:48.000Z"),
    ]
    out, links, _, tally = rewrite(rows, layout)
    shells = [r for r in out if r["subject"] == "M933HE 1"]
    assert all(r["predicate"] == "fired_by" for r in shells)
    assert all(r["object"] == "FRMORT001" for r in shells)
    assert tally.munitions_linked == len(shells)
    assert links[("GROUND_TRUTH", "M933HE 1")].shooter == "FRMORT001"


def test_unconfirmed_munition_keeps_the_object_empty(layout):
    """사수를 못 찾으면 술어만 fired_by로 두고 object는 비운다."""
    rows = [_row("M933HE 1", "None", _at(layout, "LOC_중앙킬존"))]
    out, links, unresolved, tally = rewrite(rows, layout)
    assert out[0]["predicate"] == "fired_by"
    assert out[0]["object"] == ""
    assert not links
    assert unresolved
    assert tally.munitions_linked == 0


def test_sources_are_not_mixed_when_pairing(layout):
    """드론이 본 발사체가 전역이 본 박격포에 붙으면 안 된다."""
    mortar = _at(layout, "LOC_아군박격포진지")
    target_lid = "LOC_적포병진지"
    raw = (f'FFE-On-Location "Location={_ecef_blob(layout, target_lid)}"  Name '
           f"of Weapons to Fire: Indirect-Fire-Gun:m9333he. Number-Of-Rounds: 1")
    rows = [
        _row("FRMORT001", raw, mortar, ts="2026-08-03T08:09:12.000Z"),
        _row("M933HE 1", "None", mortar, ts="2026-08-03T22:00:12.000Z",
             source="UAV 2"),
        _row("M933HE 1", "None", _at(layout, target_lid),
             ts="2026-08-03T22:00:40.000Z", source="UAV 2"),
    ]
    out, links, _, _ = rewrite(rows, layout)
    assert not links
    assert all(r["object"] == "" for r in out if r["subject"] == "M933HE 1")
