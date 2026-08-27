"""입력 → 관계 구간 CSV·품질 리포트·매니페스트."""
import json

import pytest

from vtmak.paths import CONFIG
from vtmak.spatial.pipeline import (QUALITY_FIELDS, RELATION_FIELDS,
                                    process_csv)
from vtmak.spatial.thresholds import PREDICATES, PROVISIONAL, Thresholds

HEADER = ("subject,predicate,object,latitude,longitude,timestamp,"
          "heading,entity_type,force")
M4 = "3:1:225:1:41:1:0"      # US Army M4, 직접 0-500m, 이격 2m
LAT, LON = 21.38, -157.74
NORTH_2M = 21.380018        # 약 2m 북쪽


def _row(subject, lat, stamp, force="1", dis=M4, heading="0.0",
         predicate="none", obj=""):
    return (f"{subject},{predicate},{obj},{lat:.8f},{LON:.8f},{stamp},"
            f"{heading},{dis},{force}")


@pytest.fixture
def run(tmp_path):
    def _run(lines, thresholds=None):
        source = tmp_path / "in.csv"
        source.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
        rel = tmp_path / "relations.csv"
        qual = tmp_path / "quality.csv"
        man = tmp_path / "manifest.json"
        stats = process_csv(source, rel, qual, man, config_dir=CONFIG,
                            thresholds=thresholds or Thresholds(),
                            dataset_version="test1.0")
        return stats, rel, qual, man
    return _run


def test_writes_headers_even_with_no_relations(run):
    _, rel, qual, _ = run([_row("A", LAT, "2026-08-09T08:00:00.000Z")])
    assert rel.read_text(encoding="utf-8").splitlines()[0] == ",".join(RELATION_FIELDS)
    assert qual.read_text(encoding="utf-8").splitlines()[0] == ",".join(QUALITY_FIELDS)


def test_produces_a_next_to_interval_across_two_timestamps(run):
    lines = []
    for stamp in ("2026-08-09T08:00:00.000Z", "2026-08-09T08:00:01.000Z"):
        lines.append(_row("A", LAT, stamp))
        lines.append(_row("B", NORTH_2M, stamp))
    stats, rel, _, _ = run(lines)
    rows = [r for r in rel.read_text(encoding="utf-8").splitlines()[1:] if "next_to" in r]
    assert len(rows) == 1
    assert "test1.0" in rows[0]
    assert stats.relation_counts["next_to"] == 1


def test_support_count_matches_the_number_of_timestamps(run):
    lines = []
    for i in range(3):
        stamp = f"2026-08-09T08:00:0{i}.000Z"
        lines += [_row("A", LAT, stamp), _row("B", NORTH_2M, stamp)]
    _, rel, _, _ = run(lines)
    row = [r for r in rel.read_text(encoding="utf-8").splitlines()[1:] if "next_to" in r][0]
    assert row.split(",")[5] == "3"


def test_active_follow_pair_suppresses_next_to(run):
    stamp = "2026-08-09T08:00:00.000Z"
    lines = [_row("A", LAT, stamp, predicate="Follow-Entity", obj="B"),
             _row("B", NORTH_2M, stamp)]
    _, rel, _, _ = run(lines)
    assert "next_to" not in rel.read_text(encoding="utf-8")


def test_opposing_forces_produce_in_range_of(run):
    stamp = "2026-08-09T08:00:00.000Z"
    lines = [_row("A", LAT, stamp, force="1"), _row("B", NORTH_2M, stamp, force="2")]
    stats, _, _, _ = run(lines)
    assert stats.relation_counts["in_range_of"] == 2   # 양쪽 다 사수다


def test_manifest_records_versions_counts_and_storage(run):
    stamp = "2026-08-09T08:00:00.000Z"
    _, _, _, man = run([_row("A", LAT, stamp), _row("B", NORTH_2M, stamp)])
    payload = json.loads(man.read_text(encoding="utf-8"))
    assert payload["dataset_version"] == "test1.0"
    assert payload["threshold_config_version"] == Thresholds().version
    assert payload["symmetric_storage"] == "canonical"
    assert sorted(payload["symmetric"]) == ["approach", "next_to"]
    assert "next_to" in payload["counts"]
    assert "approach" not in payload["counts"]
    # time_base는 확인 전까지 unverified가 기본이다 — 확신에 찬 오답이 정직한
    # 모름보다 나쁘다(§14).
    assert payload["time_base"] == "unverified"
    assert set(payload["provisional"]) == PROVISIONAL
    assert "approach" in payload["approach_note"]


def test_manifest_has_a_threshold_config_sha256_even_without_an_override(run):
    stamp = "2026-08-09T08:00:00.000Z"
    _, _, _, man = run([_row("A", LAT, stamp), _row("B", NORTH_2M, stamp)])
    payload = json.loads(man.read_text(encoding="utf-8"))
    assert len(payload["threshold_config_sha256"]) == 64  # 기본값만 써도 해시는 있다


def test_manifest_time_base_can_be_overridden(tmp_path):
    stamp = "2026-08-09T08:00:00.000Z"
    source = tmp_path / "in.csv"
    source.write_text("\n".join([HEADER, _row("A", LAT, stamp),
                                 _row("B", NORTH_2M, stamp)]) + "\n", encoding="utf-8")
    man = tmp_path / "manifest.json"
    process_csv(source, tmp_path / "r.csv", tmp_path / "q.csv", man,
               config_dir=CONFIG, thresholds=Thresholds(), dataset_version="v",
               time_base="simulation")
    assert json.loads(man.read_text(encoding="utf-8"))["time_base"] == "simulation"


def test_threshold_config_sha256_hashes_the_override_file_when_given(tmp_path):
    stamp = "2026-08-09T08:00:00.000Z"
    source = tmp_path / "in.csv"
    source.write_text("\n".join([HEADER, _row("A", LAT, stamp),
                                 _row("B", NORTH_2M, stamp)]) + "\n", encoding="utf-8")
    override = tmp_path / "t.json"
    override.write_text(json.dumps({"interest_distance_m": 200.0}), encoding="utf-8")
    man = tmp_path / "manifest.json"
    process_csv(source, tmp_path / "r.csv", tmp_path / "q.csv", man,
               config_dir=CONFIG, thresholds=Thresholds.load(override),
               dataset_version="v", thresholds_path=override)
    payload = json.loads(man.read_text(encoding="utf-8"))

    import hashlib
    expected = hashlib.sha256(override.read_bytes()).hexdigest()
    assert payload["threshold_config_sha256"] == expected


def test_rejects_a_schema_mismatch(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("subject,predicate,object\nA,none,\n", encoding="utf-8")
    with pytest.raises(ValueError):
        process_csv(source, tmp_path / "r.csv", tmp_path / "q.csv",
                    tmp_path / "m.json", config_dir=CONFIG,
                    thresholds=Thresholds(), dataset_version="v")


def test_rejects_a_timestamp_that_reappears_after_another(run):
    early, late = "2026-08-09T08:00:00.000Z", "2026-08-09T08:00:01.000Z"
    lines = [_row("A", LAT, early), _row("B", LAT, late), _row("C", LAT, early)]
    with pytest.raises(ValueError, match="시각으로 묶여 있지 않다"):
        run(lines)


def test_rejects_a_frame_earlier_than_the_previous_one(run):
    late, early = "2026-08-09T08:00:05.000Z", "2026-08-09T08:00:02.000Z"
    lines = [_row("A", LAT, late), _row("A", LAT, early)]
    with pytest.raises(ValueError, match="시각순이 아니다"):
        run(lines)


def test_a_gap_beyond_the_merge_cap_is_reported_as_sampling_gap(run):
    early, late = "2026-08-09T08:00:00.000Z", "2026-08-09T08:03:47.000Z"  # 227초 뒤
    lines = [_row("A", LAT, early), _row("A", LAT, late)]
    _, _, qual, _ = run(lines)
    assert "SAMPLING_GAP" in qual.read_text(encoding="utf-8")


def test_a_gap_within_the_merge_cap_is_not_reported(run):
    early, late = "2026-08-09T08:00:00.000Z", "2026-08-09T08:00:03.000Z"  # 병합상한 이내
    lines = [_row("A", LAT, early), _row("A", LAT, late)]
    _, _, qual, _ = run(lines)
    assert "SAMPLING_GAP" not in qual.read_text(encoding="utf-8")


def test_unmapped_entity_type_is_reported(run):
    stamp = "2026-08-09T08:00:00.000Z"
    lines = [_row("A", LAT, stamp, dis="9:9:999:9:9:9:9"), _row("B", NORTH_2M, stamp)]
    _, _, qual, _ = run(lines)
    assert "UNMAPPED_ENTITY_TYPE" in qual.read_text(encoding="utf-8")


def test_never_emits_approach(run):
    stamp = "2026-08-09T08:00:00.000Z"
    _, rel, _, _ = run([_row("A", LAT, stamp), _row("B", NORTH_2M, stamp)])
    assert "approach" not in rel.read_text(encoding="utf-8")


def test_blank_force_suppresses_in_range_of_but_still_reports_it(run):
    stamp = "2026-08-09T08:00:00.000Z"
    lines = [_row("A", LAT, stamp, force=""), _row("B", NORTH_2M, stamp, force="")]
    stats, _, qual, _ = run(lines)
    # force가 비면 필터를 적용할 수 없으므로 in_range_of 자체를 만들지 않는다(§3.3).
    # 소속을 유추해 필터를 흉내 내면 안 되므로, 빈 문자열끼리를 '같은 편'으로도
    # '다른 편'으로도 취급하지 않고 그냥 관계를 내지 않는다.
    assert stats.relation_counts["in_range_of"] == 0
    assert "MISSING_FORCE" in qual.read_text(encoding="utf-8")


def test_duplicate_rows_for_one_subject_match_a_single_row_per_subject(run):
    stamp = "2026-08-09T08:00:00.000Z"
    # A가 이 시각에 두 행(팩트마다 한 행)을 갖는다 — 실제 내보내기의 정상 형태다.
    dup_lines = [
        _row("A", LAT, stamp, predicate="none"),
        _row("A", LAT, stamp, predicate="Follow-Entity", obj="C"),
        _row("B", NORTH_2M, stamp),
        _row("C", LAT, stamp),
    ]
    single_lines = [
        _row("A", LAT, stamp, predicate="Follow-Entity", obj="C"),
        _row("B", NORTH_2M, stamp),
        _row("C", LAT, stamp),
    ]
    dup_stats, _, _, _ = run(dup_lines)
    single_stats, _, _, _ = run(single_lines)
    assert dup_stats.relation_counts == single_stats.relation_counts


def test_manifest_counts_include_predicates_that_produced_nothing(run):
    stamp = "2026-08-09T08:00:00.000Z"
    # 둘 다 force="1"이라 in_range_of는 대립 진영 필터에 걸려 0건으로 남는다.
    _, _, _, man = run([_row("A", LAT, stamp), _row("B", NORTH_2M, stamp)])
    counts = json.loads(man.read_text(encoding="utf-8"))["counts"]
    assert counts["in_range_of"] == 0
    assert set(counts) == set(PREDICATES)
