"""고정 객체(UAV) — campaign에서 복제해 어느 규모에서든 같은 자리로 들어가는가."""
import dataclasses
import re  # noqa: F401  (object-identifier 유일성 검사에서 쓴다)
import zipfile
from pathlib import Path

import pytest

from vtmak.geometry import BattlefieldLayout
from vtmak.parser import PatternMap, parse_scenario
from vtmak.paths import SCENARIO
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.fixed import load_fixed
from vtmak.scnx.gates import check_g3
from vtmak.scnx.golden import Golden, _parse_objects
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.spec import build_spec
from vtmak.scnx.writer import get_writer

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
GOLDEN = ensure_golden(ROOT / "yewon_test")


@pytest.fixture(scope="module")
def fixed():
    return load_fixed(CFG / "fixed_objects.json", ROOT)


def _spec(scenario: Path, fixed, target_entities: int | None = None):
    pm = PatternMap.load(CFG / "pattern_map.csv")
    res = parse_scenario(scenario.read_text(encoding="utf-8"), pm)
    lay = BattlefieldLayout.load(CFG / "battlefield_layout.json")
    reg = build_registry(res.events, ClassMap.load(CFG / "entity_class_map.csv"),
                         lay.static_ids())
    task_ids = {e.event_id for e in res.events
                if pm.task_kind(e.template, e.action_label) not in ("", "noop")}
    plan = RosterPlan.load(CFG / "roster.json")
    if target_entities is not None:
        plan = dataclasses.replace(plan, target_entities=target_entities)
    keep = select_roster(res.events, reg, plan, task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    dis = DisCatalog.load(CFG / "dis_catalog.csv")
    return build_spec(events, reg, lay, pm,
                      TaskCatalog.load(CFG / "task_catalog.csv"), dis,
                      WeaponRanges.load(CFG / "weapon_ranges.csv"),
                      "battle", fixed=fixed), dis


@pytest.fixture(scope="module")
def built(fixed):
    return _spec(SCENARIO, fixed)


@pytest.fixture(scope="module")
def written(built, tmp_path_factory):
    spec, _ = built
    out = get_writer("template", str(GOLDEN)).write(
        spec, tmp_path_factory.mktemp("scnx"))
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist()}


def test_config_declares_the_uavs(fixed):
    assert [f.marking for f in fixed] == ["UAV 1", "UAV 2", "UAV 3", "UAV 4"]
    assert all(not f.coord.is_zero() for f in fixed)
    # 전부 같은 공중 플랫폼 DIS(domain 2 = air).
    assert {f.dis for f in fixed} == {(1, 2, 225, 50, 25, 1, 0)}


def test_records_are_copied_verbatim_from_campaign(fixed):
    """좌표·uuid를 우리가 다시 계산하지 않는다 — 원본 그대로여야 고정이다."""
    src = {o.marking: o for o in _parse_objects(
        (ROOT / "campaign" / "campaign.oob").read_text(
            encoding="utf-8", errors="replace"))}
    for f in fixed:
        assert f.uuid == src[f.marking].uuid
        assert f.coord.to_ecef() == pytest.approx(src[f.marking].position)


def test_missing_marking_is_an_error(tmp_path):
    """조용히 빠지면 .scnx를 열어보기 전까지 없어진 걸 모른다."""
    cfg = tmp_path / "fixed_objects.json"
    cfg.write_text('{"source_dir": "campaign", "markings": ["UAV 9"]}',
                   encoding="utf-8")
    with pytest.raises(KeyError, match="UAV 9"):
        load_fixed(cfg, ROOT)


def test_absent_config_means_no_fixed_objects(tmp_path):
    assert load_fixed(tmp_path / "none.json", ROOT) == []


def test_written_oob_carries_every_fixed_object(written, fixed):
    oob = written["battle.oob"]
    got = {o.marking: o for o in _parse_objects(oob)}
    for f in fixed:
        assert f.marking in got, f.marking
        assert got[f.marking].uuid == f.uuid
        assert got[f.marking].position == pytest.approx(f.coord.to_ecef())


def test_object_identifiers_stay_unique_after_appending(written):
    ids = re.findall(r'\(object-identifier\s+"([^"]*)"', written["battle.oob"])
    assert len(ids) == len(set(ids)), "object-identifier 충돌"


def test_fixed_objects_are_in_the_object_map(written, fixed):
    """.omp에 없는 .oob 객체는 로드돼도 화면에 안 나온다."""
    for f in fixed:
        assert f.uuid in written["battle.omp"], f.marking


def test_fixed_objects_have_no_plan(written, fixed):
    """플랜이 없어야 배치된 자리에 그대로 서 있는다 — '항상 고정'."""
    for f in fixed:
        assert f.uuid not in written["battle.pln"], f.marking


def test_g3_catches_a_uuid_collision_with_generated_entities(built):
    spec, dis = built
    g = Golden.load(GOLDEN)
    assert [v for v in check_g3(spec, g, dis) if v.code == "C3.4"] == []

    clash = dataclasses.replace(spec.fixed_objects[0],
                                uuid=spec.entities[0].uuid)
    saved = spec.fixed_objects
    spec.fixed_objects = [clash]
    try:
        v = [x for x in check_g3(spec, g, dis) if x.code == "C3.4"]
        assert len(v) == 1 and "고정 객체" in v[0].detail
        assert v[0].severity == "BLOCK"
    finally:
        spec.fixed_objects = saved


@pytest.mark.parametrize("n", (60, 40, 20))
def test_fixed_objects_are_identical_at_every_scale(n, fixed, built):
    """명부를 줄여도 UAV는 개수·좌표·uuid가 그대로다.

    원문에서 나오는 객체가 아니라 밖에서 붙이는 객체이므로, roster 규모와
    무관해야 한다.
    """
    base, _ = built
    spec, _ = _spec(SCENARIO, fixed, target_entities=n)
    assert len(spec.entities) < len(base.entities), "명부가 줄어야 의미가 있다"
    assert ([(f.marking, f.uuid, f.coord.as_tuple()) for f in spec.fixed_objects]
            == [(f.marking, f.uuid, f.coord.as_tuple())
                for f in base.fixed_objects])
