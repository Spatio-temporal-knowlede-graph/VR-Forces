from pathlib import Path

import pytest

from vtmak.stkg.resolve import load_uuid_map, to_marking

ROOT = Path(__file__).resolve().parents[1]
OOB = ROOT / "campaign" / "campaign.oob"


@pytest.fixture(scope="module")
def uuid_map():
    return load_uuid_map(OOB)


def test_map_is_not_empty(uuid_map):
    assert len(uuid_map) > 100


def test_every_value_is_a_marking(uuid_map):
    for marking in uuid_map.values():
        assert marking
        assert '"' not in marking


def test_uuid_keys_have_no_vrf_prefix(uuid_map):
    for key in uuid_map:
        assert not key.startswith("VRF_UUID:")


def test_to_marking_resolves_a_known_uuid(uuid_map):
    known_uuid = next(iter(uuid_map))
    assert to_marking(known_uuid, uuid_map) == uuid_map[known_uuid]


def test_to_marking_returns_none_for_unknown():
    assert to_marking("2c380775-b3d4-7144-8815-4ef6c9e202ce", {}) is None


def test_to_marking_tolerates_vrf_prefix(uuid_map):
    known_uuid = next(iter(uuid_map))
    assert to_marking(f"VRF_UUID:{known_uuid}", uuid_map) \
        == uuid_map[known_uuid]
