"""05 후처리 — 열은 8열 그대로, 술어는 정규형, object는 채운다."""
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.stkg.rewrite import OUT_COLS, rewrite

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def layout():
    return BattlefieldLayout.load(ROOT / "config" / "battlefield_layout.json")


def _layout():
    from vtmak.geometry import BattlefieldLayout
    return BattlefieldLayout.load(
        Path(__file__).resolve().parents[1] / "config" / "battlefield_layout.json")


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


def _row_20260809(subject, predicate, coord, obj="-",
                  ts="2026-08-09T08:53:44.000Z", source="GROUND_TRUTH"):
    """20260809판 17열. CID가 빠지고 상태 열 10개가 붙었다."""
    lat, lon = coord
    return {"subject": subject, "predicate": predicate, "object": obj,
            "timestamp": ts, "latitude": f"{lat}", "longitude": f"{lon}",
            "source": source, "force": "1", "tracking_id": "1:3001:5",
            "uuid": subject, "entity_type": "3:1:225:1:41:1:0", "damage": "0",
            "smoke": "false", "flaming": "false", "mobility_kill": "false",
            "firepower_kill": "false", "suppression_level": "0"}


def test_output_inherits_whatever_columns_the_export_gave(layout):
    """열 목록을 못박지 않는다. 판마다 열이 다르고, 목록을 코드에 두면 새 열이
    조용히 사라진다."""
    rows = [_row_20260809("FRINF001", "None", _at(layout, "LOC_중앙킬존"))]
    out, _, _, _ = rewrite(rows, layout)
    assert list(out[0]) == list(rows[0])
    assert out[0]["entity_type"] == "3:1:225:1:41:1:0"
    assert out[0]["suppression_level"] == "0"


def test_fire_weapon_keeps_the_target_the_export_supplied(layout):
    """20260809판에서 유일하게 대상이 미리 채워져 오는 술어다(실측 GT 650행).
    우리가 만든 값이 아니라 관측이므로 덮어쓰지 않는다."""
    rows = [_row_20260809("FRINF041", "Fire Weapon",
                          _at(layout, "LOC_중앙킬존"), obj="ENT72006")]
    out, _, _, _ = rewrite(rows, layout)
    assert out[0]["predicate"] == "Fire-Weapon"
    assert out[0]["object"] == "ENT72006"


def test_wait_duration_has_no_target(layout):
    rows = [_row_20260809("FRINF001", "Wait-Duration Seconds-To-Wait:60",
                          _at(layout, "LOC_중앙킬존"))]
    out, _, _, tally = rewrite(rows, layout)
    assert out[0]["predicate"] == "Wait-Duration"
    assert out[0]["object"] == ""
    assert not tally.unparsed          # 파싱 실패로 쌓이면 안 된다


def test_waypoint_target_becomes_a_control_point_not_an_entity(layout):
    """통제점은 지우지 않되 객체로 세지 않는다. 06의 객체명 대조가 05의
    집계와 같은 답을 써야 한다."""
    rows = [_row_20260809("FRINF027", 'Move-To Waypoint: "P10"',
                          _at(layout, "LOC_중앙킬존")),
            _row_20260809("P10", "None", _at(layout, "LOC_중앙킬존"))]
    out, _, _, tally = rewrite(rows, layout)
    assert out[0]["predicate"] == "move to"
    assert out[0]["object"] == "P10"
    assert tally.object_locations == {"P10"}
    assert not tally.object_entities
    assert tally.control_subjects == {"P10"}
    assert tally.entities == 1                 # FRINF027만 객체다
    assert tally.seen == 1


def test_control_point_name_becomes_place_name():
    """`Move-To Waypoint: "C_VALLEY"`가 지명으로 돌아온다.

    시뮬레이터는 uuid가 아니라 marking을 그대로 내보낸다(실측
    `Move-To Waypoint: "P3"`). 대조표가 없으면 그 이름이 산출물에 남는다.
    """
    rows = [{"subject": "FRINF001", "predicate": 'Move-To Waypoint: "C_VALLEY"',
             "object": "-", "latitude": "21.38", "longitude": "-157.74",
             "timestamp": "2026-08-09T08:53:44.000Z", "source": "UAV 1"}]
    out, _, _, _ = rewrite(rows, _layout(), place_names={"C_VALLEY": "LOC_중앙계곡"})
    assert (out[0]["predicate"], out[0]["object"]) == ("move to", "LOC_중앙계곡")


def test_unknown_control_point_name_survives():
    """표에 없는 이름은 버리지 않고 원문을 남긴다 — 옛 판 CSV가 그렇다."""
    rows = [{"subject": "FRINF001", "predicate": 'Move-To Waypoint: "P3"',
             "object": "-", "latitude": "21.38", "longitude": "-157.74",
             "timestamp": "2026-08-09T08:53:44.000Z", "source": "UAV 1"}]
    out, _, _, _ = rewrite(rows, _layout(), place_names={"C_VALLEY": "LOC_중앙계곡"})
    assert out[0]["object"] == "P3"


def test_no_bare_control_point_numbers_survive():
    """산출 CSV에 P\\d+ 형태 object가 남으면 지명화가 반쪽이다.

    옛 판 marking(`P3`, `P10`)을 대조표에 **둔** 채로 확인한다 —
    `C_VALLEY`처럼 애초에 `P\\d+` 꼴이 아닌 marking을 쓰면 조회가 죽어도
    통과해 버려 회귀를 못 잡는다. 대조표가 있는 실행에서만 의미가 있다 —
    없으면 원문을 남기는 것이 옳다.
    """
    import re
    rows = [{"subject": "FRINF001", "predicate": f'Move-To Waypoint: "{c}"',
             "object": "-", "latitude": "21.38", "longitude": "-157.74",
             "timestamp": "2026-08-09T08:53:44.000Z", "source": "UAV 1"}
            for c in ("P3", "P10")]
    names = {"P3": "LOC_중앙계곡", "P10": "LOC_남측제1방어선"}
    out, _, _, _ = rewrite(rows, _layout(), place_names=names)
    assert not [r for r in out if re.fullmatch(r"P\d+", r["object"])]
