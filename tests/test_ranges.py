from pathlib import Path

import pytest

from vtmak.ranges import WeaponRanges

CONFIG = Path(__file__).resolve().parents[1] / "config" / "weapon_ranges.csv"


@pytest.fixture(scope="module")
def wr():
    return WeaponRanges.load(CONFIG)


def test_covers_all_26_scenario_models(wr):
    assert len(wr.classes()) == 26


def test_hyphen_variants_resolve(wr):
    # 원문은 'T-72 MBT', dis_catalog는 'T 72 MBT'.
    assert wr.spec("T 72 MBT", "direct") is not None
    assert wr.spec("T-72 MBT", "direct") is not None


def test_rifle_direct_limits(wr):
    assert wr.check("US Army M4", "direct", 250.0) == "OK"
    assert wr.check("US Army M4", "direct", 700.0) == "TOO_FAR"
    assert wr.check("Russian Soldier AK47", "direct", 335.0) == "OK"
    assert wr.check("Russian Soldier AK47", "direct", 450.0) == "TOO_FAR"


def test_howitzer_minimum_range(wr):
    assert wr.check("M109 Howitzer", "indirect", 1500.0) == "TOO_CLOSE"
    assert wr.check("M109 Howitzer", "indirect", 2807.0) == "OK"
    assert wr.check("M109 Howitzer", "indirect", 20000.0) == "TOO_FAR"


def test_mortar_window(wr):
    assert wr.check("MO-120RT-61 Mortar", "indirect", 900.0) == "TOO_CLOSE"
    assert wr.check("MO-120RT-61 Mortar", "indirect", 2433.0) == "OK"
    assert wr.check("MO-120RT-61 Mortar", "indirect", 9000.0) == "TOO_FAR"


def test_truck_has_no_weapon(wr):
    assert wr.check("M35 Truck", "direct", 100.0) == "NO_WEAPON"
    assert wr.spec("M35 Truck", "direct") is None


def test_patriot_launchers_are_unverified(wr):
    # 설계 스펙 §8.3 — VR-Forces에서 Patriot의 지상 간접사격이 성립하는지
    # 확인되지 않았다. 조용히 통과시키지 않고 별도로 표시한다.
    assert wr.check("M901 Patriot Launcher", "indirect", 4405.0) == "UNVERIFIED"
    assert wr.check("MIM-104 Patriot Launcher", "indirect", 3306.0) == "UNVERIFIED"


def test_unknown_class_is_no_weapon(wr):
    assert wr.check("Imaginary Tank", "direct", 100.0) == "NO_WEAPON"


def test_direct_only_model_has_no_indirect_spec(wr):
    assert wr.spec("US Army M4", "indirect") is None
    assert wr.check("US Army M4", "indirect", 3000.0) == "NO_WEAPON"
