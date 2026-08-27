from pathlib import Path

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import Event
from vtmak.registry import EntityDef
from vtmak.scnx.engagements import EnrichmentConfig, build_source_slots

ROOT = Path(__file__).resolve().parents[1]


def _entity(oid, faction, weapon="M4 rifle"):
    return EntityDef(oid, "US Army M4", "소총수", faction,
                     "보병 - 소총(M4 계열)", (weapon,),
                     "LOC_A" if faction == "BLUE" else "LOC_B",
                     "기동 또는 사격 가능", True)


def test_config_loads_exact_limits(tmp_path):
    path = tmp_path / "engagement.json"
    path.write_text('{"enabled":true,"min_new_unique_pairs":20,'
                    '"target_new_unique_pairs":25,"max_new_unique_pairs":30,'
                    '"max_slots_per_shooter":2,"max_slots_per_target":1,'
                    '"max_target_task_count":2,"direct_fire_rounds":1,'
                    '"suppress_rapid_duration_s":5,"suppress_duration_s":10,'
                    '"suppress_ammo_limit":10,'
                    '"minimum_observation_duration_s":3,"slot_spacing_s":15}',
                    encoding="utf-8")
    cfg = EnrichmentConfig.load(path)
    assert (cfg.min_new_unique_pairs, cfg.target_new_unique_pairs,
            cfg.max_new_unique_pairs) == (20, 25, 30)
    assert (cfg.direct_fire_rounds, cfg.suppress_duration_s,
            cfg.suppress_ammo_limit) == (1, 10, 10)
    # 뒤에 붙은 스케줄·엄폐 설정은 기본값을 갖는다 — 옛 JSON도 그대로 읽힌다.
    assert cfg.movement_speed_mps == 6.0
    assert cfg.min_expected_suppress_spo == 70


def test_repository_config_matches_defaults():
    loaded = EnrichmentConfig.load(
        ROOT / "config" / "engagement_enrichment.json")
    assert loaded == EnrichmentConfig.defaults()


def test_direct_fire_event_becomes_one_source_slot():
    layout = BattlefieldLayout({"locations": {
        "LOC_A": {"lat": 21.0, "lon": 105.0},
        "LOC_B": {"lat": 21.001, "lon": 105.0}}})
    event = Event("E1", 30, 1, "directFireAt", "directFireAt",
                  actor="FR-A", src="LOC_A", target="EN-B")
    registry = {"FR-A": _entity("FR-A", "BLUE"),
                "EN-B": _entity("EN-B", "RED", "AK-47")}
    slots = build_source_slots([event], registry, layout,
                               EnrichmentConfig.defaults())
    assert len(slots) == 1
    assert slots[0].slot_id == "SRC-E1"
    assert slots[0].origin == "source"
    assert (slots[0].shooter_id, slots[0].target_id) == ("FR-A", "EN-B")
    assert slots[0].source_event_ids == ("E1",)
    assert slots[0].provenance == "directFireAt:E1"
    assert slots[0].target_ref == "LOC_B"
    assert slots[0].firing_ref == ""          # 원문 슬롯은 제자리에서 쏜다
    assert slots[0].firing_coord is None
