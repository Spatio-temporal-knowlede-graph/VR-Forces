"""ver2.0 전까지 실데이터로 확인할 수 있는 만큼만 확인한다.

17열 판에는 force·entity_type이 있고 heading이 없다. 그래서 next_to와
in_range_of는 실데이터로 확인되고 방향 관계는 0건이 정상이다.
"""
import csv

import pytest

from vtmak.paths import BUILD, CONFIG
from vtmak.spatial.legacy import adapt_legacy
from vtmak.spatial.pipeline import INPUT_FIELDS, process_csv
from vtmak.spatial.thresholds import Thresholds

LEGACY = BUILD / "stkg" / "ground_truth_ver1.0.csv"

LEGACY_HEADER = ("subject,predicate,object,timestamp,latitude,longitude,source,"
                 "force,tracking_id,uuid,entity_type,damage,smoke,flaming,"
                 "mobility_kill,firepower_kill,suppression_level")
LEGACY_ROW = ("ENINF037,none,,2026-08-09T08:53:22.000Z,21.36869199,-157.74068262,"
              "GROUND_TRUTH,2,1:3001:1,ENINF037,3:1:222:11:5:30:6,0,false,false,"
              "false,false,0")


def test_maps_seventeen_columns_onto_the_nine_column_contract(tmp_path):
    source = tmp_path / "legacy.csv"
    source.write_text(LEGACY_HEADER + "\n" + LEGACY_ROW + "\n", encoding="utf-8")
    out = tmp_path / "adapted.csv"
    assert adapt_legacy(source, out) == 1
    with out.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == INPUT_FIELDS
        row = next(reader)
    assert row["heading"] == ""
    assert row["force"] == "2"
    assert row["entity_type"] == "3:1:222:11:5:30:6"


def test_limit_stops_after_the_given_number_of_timestamps(tmp_path):
    source = tmp_path / "legacy.csv"
    rows = [LEGACY_ROW.replace("08:53:22", f"08:53:{22 + i:02d}") for i in range(5)]
    source.write_text(LEGACY_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    assert adapt_legacy(source, tmp_path / "a.csv", limit_timestamps=2) == 2


def test_rejects_an_unexpected_legacy_schema(tmp_path):
    source = tmp_path / "legacy.csv"
    source.write_text("subject,predicate\nA,none\n", encoding="utf-8")
    with pytest.raises(ValueError):
        adapt_legacy(source, tmp_path / "a.csv")


@pytest.mark.skipif(not LEGACY.exists(), reason="ver1.0 GT가 없다")
def test_real_data_produces_next_to_and_in_range_of(tmp_path):
    adapted = tmp_path / "adapted.csv"
    adapt_legacy(LEGACY, adapted, limit_timestamps=60)
    stats = process_csv(adapted, tmp_path / "r.csv", tmp_path / "q.csv",
                        tmp_path / "m.json", config_dir=CONFIG,
                        thresholds=Thresholds(), dataset_version="ver1.0-legacy")
    assert stats.relation_counts["next_to"] > 0
    assert stats.relation_counts["in_range_of"] > 0
    # heading이 없으므로 방향 관계는 나올 수 없다.
    assert stats.relation_counts["in_front_of"] == 0
    assert stats.relation_counts["behind"] == 0
