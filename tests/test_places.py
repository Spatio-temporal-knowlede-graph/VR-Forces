"""지명 코드표 — DIS marking(11byte ASCII)에 한글을 못 넣어 코드를 붙인다."""
import json
from pathlib import Path

import pytest

from vtmak.scnx.places import PlaceCodes

ROOT = Path(__file__).resolve().parents[1]
CODES = ROOT / "config" / "location_codes.csv"
LAYOUT = ROOT / "config" / "battlefield_layout.json"


@pytest.fixture(scope="module")
def codes():
    return PlaceCodes.load(CODES)


def test_covers_every_location(codes):
    """지명이 하나라도 빠지면 그 통제점이 다시 P{k}로 나간다."""
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    assert set(codes.codes()) == set(layout["locations"])


def test_codes_fit_dis_marking(codes):
    """marking-text는 11바이트 ASCII다. 넘으면 잘려서 유일성이 깨진다."""
    for loc_id, code in codes.codes().items():
        assert code.isascii(), loc_id
        assert 0 < len(code.encode("ascii")) <= 11, (loc_id, code)


def test_codes_are_unique(codes):
    values = list(codes.codes().values())
    assert len(values) == len(set(values))


def test_round_trip(codes):
    assert codes.code("LOC_중앙계곡") == "C_VALLEY"
    assert codes.loc_id("C_VALLEY") == "LOC_중앙계곡"


def test_unknown_key_is_loud(codes):
    """없는 지명에 기본값을 주면 P{k}가 조용히 되살아난다."""
    with pytest.raises(KeyError):
        codes.code("LOC_없는곳")
