import re
import zipfile
from pathlib import Path

import pytest

from vtmak.gates import blocking
from vtmak.geometry import BattlefieldLayout
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.gates import check_g3
from vtmak.scnx.golden import Golden
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.spec import build_spec
from vtmak.scnx.writer import get_writer

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ensure_golden(ROOT / "yewon_test")


@pytest.fixture(scope="module")
def built():
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(
        (ROOT / "scenario_original" / "scenario_v3.txt").read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"))
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    dis = DisCatalog.load(cfg / "dis_catalog.csv")
    spec = build_spec(events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"), dis,
                      WeaponRanges.load(cfg / "weapon_ranges.csv"), "battle")
    return spec, dis


@pytest.fixture(scope="module")
def written(built, tmp_path_factory):
    spec, _ = built
    out_dir = tmp_path_factory.mktemp("scnx")
    return get_writer("template", str(GOLDEN)).write(spec, out_dir)


def test_g3_has_no_blocking_violations(built):
    spec, dis = built
    v = check_g3(spec, Golden.load(GOLDEN), dis)
    assert blocking(v) == [], [x.detail for x in blocking(v)]


def test_g3_reports_unclassified_patriots(built):
    spec, dis = built
    v = check_g3(spec, Golden.load(GOLDEN), dis)
    reported = [x for x in v if x.code == "C3.5"]
    assert reported
    assert all(x.severity == "REPORT" for x in reported)
    assert {x.detail.split()[0] for x in reported} == {"EN-MIM-001", "FR-M901-001"}


def test_writes_a_scnx_with_the_required_members(written):
    assert written.exists() and written.suffix == ".scnx"
    with zipfile.ZipFile(written) as z:
        names = z.namelist()
    stem = written.stem
    for ext in (".scn", ".oob", ".pln", ".omp"):
        assert f"{stem}{ext}" in names, ext


def test_oob_contains_every_entity(written, built):
    spec, _ = built
    with zipfile.ZipFile(written) as z:
        oob = z.read(f"{written.stem}.oob").decode("utf-8", "replace")
    assert oob.count("(local-vrf-object") == (len(spec.entities)
                                              + len(spec.control_objects))


def test_markings_are_ascii_and_within_dis_limit(written, built):
    # 한글 marking은 DIS 11byte 한계를 넘겨 깨지고 클릭이 안 된다.
    spec, _ = built
    with zipfile.ZipFile(written) as z:
        oob = z.read(f"{written.stem}.oob").decode("utf-8", "replace")
    marks = re.findall(r'\(marking-text "([^"]*)"\)', oob)
    assert len(marks) == len(spec.entities) + len(spec.control_objects)
    for m in marks:
        assert m.isascii(), m
        assert len(m) <= 11, m


def test_markings_carry_object_ids(written):
    """Data Logger 출력을 시나리오 객체로 되짚으려면 marking이 ID여야 한다."""
    with zipfile.ZipFile(written) as z:
        oob = z.read(f"{written.stem}.oob").decode("utf-8", "replace")
    marks = set(re.findall(r'\(marking-text "([^"]*)"\)', oob))
    assert "FRINF001" in marks
    assert "ENCAESAR001" in marks


def test_omp_lists_every_object(written, built):
    spec, _ = built
    with zipfile.ZipFile(written) as z:
        omp = z.read(f"{written.stem}.omp").decode("utf-8", "replace")
    assert omp.count("(map-entry") == (len(spec.entities)
                                       + len(spec.control_objects))


def test_pln_blocks_are_balanced_and_reference_entities(written, built):
    spec, _ = built
    with zipfile.ZipFile(written) as z:
        pln = z.read(f"{written.stem}.pln").decode("utf-8", "replace")
    planned = sum(1 for v in spec.entity_plans.values()
                  if any(s.pln for s in v))
    assert pln.count("(Plan ") == planned
    assert pln.count("(") == pln.count(")")
    uuids = {e.uuid for e in spec.entities}
    for name in re.findall(r'\(plan-name  "VRF_UUID:([^"]+)"\)', pln):
        assert name in uuids


def test_scn_points_at_the_terrain_and_new_stem(written):
    with zipfile.ZipFile(written) as z:
        scn = z.read(f"{written.stem}.scn").decode("utf-8", "replace")
    assert "Ala Moana.mtf" in scn
    assert f'(Order-Of-Battle "{written.stem}.oob")' in scn
    assert "yewon_test" not in scn


def test_output_is_byte_identical_across_runs(built, tmp_path):
    spec, _ = built
    a = get_writer("template", str(GOLDEN)).write(spec, tmp_path / "a")
    b = get_writer("template", str(GOLDEN)).write(spec, tmp_path / "b")
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        assert za.namelist() == zb.namelist()
        for n in za.namelist():
            assert za.read(n) == zb.read(n), n
