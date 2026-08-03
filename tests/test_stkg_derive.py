from pathlib import Path

import pytest

from vtmak.stkg.derive import Obs, fired_by, load_munition_map

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "config" / "munition_map.csv"
TS = "2026-08-03T05:49:40.000Z"


@pytest.fixture(scope="module")
def mmap():
    return load_munition_map(MAP)


def test_map_covers_the_three_measured_munitions(mmap):
    assert set(mmap) == {"M107", "M933HE", "PAC-3"}


def test_howitzer_shell_binds_to_the_nearest_howitzer(mmap):
    rels, unresolved = fired_by(
        {("GROUND_TRUTH", "M107 4"): (TS, (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("FRM109001", (1.3, 0.0, 0.0)),
                                ("ENINF001", (2.0, 0.0, 0.0))]},
        mmap)
    assert unresolved == []
    assert len(rels) == 1
    assert rels[0].subject == "M107 4"
    assert rels[0].predicate == "fired_by"
    assert rels[0].object == "FRM109001"
    assert rels[0].object_type == "entity"
    assert rels[0].source == "GROUND_TRUTH"
    assert rels[0].confidence == "inferred"
    assert "1.3" in rels[0].evidence


def test_mortar_shell_binds_to_a_mortar(mmap):
    """실측: GROUND_TRUTH M933HE 4 → FRMORT001 26.3m."""
    rels, unresolved = fired_by(
        {("GROUND_TRUTH", "M933HE 4"): (TS, (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("FRMORT001", (26.3, 0.0, 0.0))]}, mmap)
    assert unresolved == []
    assert rels[0].object == "FRMORT001"


def test_source_is_not_mixed(mmap):
    """실측 회귀 케이스. M933HE 1이 GROUND_TRUTH와 UAV 2 양쪽에 나온다.
    source를 섞으면 UAV가 본 발사체가 GT가 본 박격포에 붙어, 서로 다른
    시간대의 관측을 하나로 잇는다."""
    rels, unresolved = fired_by(
        {("UAV 2", "M933HE 1"): ("2026-08-03T22:00:12.000Z",
                                 (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("ENMORT001", (26.7, 0.0, 0.0))]}, mmap)
    assert rels == []
    assert len(unresolved) == 1


def test_mortar_shell_does_not_bind_to_a_tank(mmap):
    """실측 회귀 케이스. UAV 2가 본 M933HE 1의 최근접은 FRT80001(1500.5m)
    이다. 전차는 박격포탄을 쏘지 않으므로 관계를 만들면 안 된다."""
    ts = "2026-08-03T22:00:12.000Z"
    rels, unresolved = fired_by(
        {("UAV 2", "M933HE 1"): (ts, (0.0, 0.0, 0.0))},
        {("UAV 2", ts): [("FRT80001", (1500.5, 0.0, 0.0))]}, mmap)
    assert rels == []
    assert len(unresolved) == 1
    assert "M933HE 1" in unresolved[0]


def test_patriot_round_does_not_bind_to_a_mortar(mmap):
    """정합성 검사가 없으면 최근접만으로 패트리엇 요격탄이 박격포에 붙는다."""
    rels, unresolved = fired_by(
        {("GROUND_TRUTH", "PAC-3 1"): (TS, (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("FRMORT001", (19.1, 0.0, 0.0))]}, mmap)
    assert rels == []
    assert len(unresolved) == 1
    assert "PAC-3 1" in unresolved[0]


def test_patriot_round_binds_to_a_patriot_launcher(mmap):
    rels, _ = fired_by(
        {("GROUND_TRUTH", "PAC-3 1"): (TS, (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("FRMORT001", (19.1, 0.0, 0.0)),
                                ("FRM901001", (40.0, 0.0, 0.0))]}, mmap)
    assert len(rels) == 1
    assert rels[0].object == "FRM901001"


def test_too_far_is_unresolved(mmap):
    rels, unresolved = fired_by(
        {("GROUND_TRUTH", "M107 1"): (TS, (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("ENCAESAR002", (900.0, 0.0, 0.0))]}, mmap)
    assert rels == []
    assert len(unresolved) == 1


def test_unknown_munition_prefix_is_unresolved(mmap):
    rels, unresolved = fired_by(
        {("GROUND_TRUTH", "UNKNOWN 9"): (TS, (0.0, 0.0, 0.0))},
        {("GROUND_TRUTH", TS): [("FRM109001", (1.0, 0.0, 0.0))]}, mmap)
    assert rels == []
    assert len(unresolved) == 1
