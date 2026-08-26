"""임계값은 한 곳에만 있어야 한다 — 재보정이 코드 수정이 아니라 설정 수정이 되도록."""
import json

import pytest

from vtmak.spatial.thresholds import (PREDICATES, SPACING_BY_TYPE_GROUP,
                                      SYMMETRIC_PREDICATES, Thresholds)


def test_defaults_match_the_spec():
    t = Thresholds()
    assert t.interest_distance_m == 500.0
    assert t.next_to_multiplier == 3.0
    assert t.max_merge_gap_s == 3.0
    assert t.min_bearing_distance_m == 0.5
    assert t.front_sector_deg == 45.0
    assert t.behind_sector_deg == 135.0
    assert t.symmetric_storage == "canonical"


def test_spacing_covers_every_type_group():
    assert set(SPACING_BY_TYPE_GROUP) == {
        "보병 - 소총(M4 계열)",
        "보병 - RPG 계열",
        "차량/장갑차 - M2HB 계열",
        "포병 - 박격포(m9333he 계열)",
        "포병 - 155mm 자주포",
        "미사일 발사대 - Patriot",
    }
    assert SPACING_BY_TYPE_GROUP["보병 - 소총(M4 계열)"] == 2.0
    assert SPACING_BY_TYPE_GROUP["차량/장갑차 - M2HB 계열"] == 10.0
    assert SPACING_BY_TYPE_GROUP["포병 - 155mm 자주포"] == 15.0


def test_only_next_to_and_approach_are_symmetric():
    assert SYMMETRIC_PREDICATES == frozenset({"next_to", "approach"})


def test_approach_is_out_of_scope_for_now():
    assert "approach" not in PREDICATES
    assert PREDICATES == ("next_to", "in_front_of", "behind", "in_range_of")


def test_load_without_path_returns_defaults():
    assert Thresholds.load(None) == Thresholds()


def test_load_overrides_only_named_keys(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"interest_distance_m": 200.0, "version": "test.1"}),
                 encoding="utf-8")
    t = Thresholds.load(p)
    assert t.interest_distance_m == 200.0
    assert t.version == "test.1"
    assert t.next_to_multiplier == 3.0


def test_load_rejects_unknown_keys(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"nearness": 10.0}), encoding="utf-8")
    with pytest.raises(ValueError):
        Thresholds.load(p)


def test_load_rejects_unknown_symmetric_storage(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"symmetric_storage": "maybe"}), encoding="utf-8")
    with pytest.raises(ValueError):
        Thresholds.load(p)
