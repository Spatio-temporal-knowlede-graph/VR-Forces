import re
import zipfile
from pathlib import Path

import pytest

from vtmak.gates import blocking
from vtmak.geometry import BattlefieldLayout
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import UNCLASSIFIED, ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog
from vtmak.scnx.gates import check_g3, weapons_in
from vtmak.scnx.golden import Golden
from vtmak.scnx.plan import PlanStep
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
        SCENARIO.read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    task_ids = {e.event_id for e in res.events
                if pm.task_kind(e.template, e.action_label) not in ("", "noop")}
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"),
                         task_ids)
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


def test_g3_flags_unauthored_steps_by_classification(built):
    """저작 못 한 스텝은 C3.5로 나간다 — 미분류 모델이면 REPORT, 아니면 BLOCK.

    ver70 명부는 전 모델이 분류돼 있어 실제 C3.5는 0건이다. 규칙이 살아 있는지
    보려고 pln 없는 스텝을 하나 지어 넣고 두 갈래를 다 밟는다.
    """
    spec, dis = built
    g = Golden.load(GOLDEN)
    assert [x for x in check_g3(spec, g, dis) if x.code == "C3.5"] == []

    ent = spec.entities[0]
    broken = PlanStep(event_id="ETEST", time_s=0, template="moveTo",
                      task_kind="move", action_label=None, pln=None,
                      issues=["템플릿 없음"])
    saved_steps = spec.entity_plans.get(ent.object_id, [])
    saved_group = ent.type_group
    spec.entity_plans[ent.object_id] = list(saved_steps) + [broken]
    try:
        v = [x for x in check_g3(spec, g, dis) if x.code == "C3.5"]
        assert [x.severity for x in v] == ["BLOCK"]
        assert v[0].detail.startswith(f"{ent.object_id} ETEST")

        ent.type_group = UNCLASSIFIED
        v = [x for x in check_g3(spec, g, dis) if x.code == "C3.5"]
        assert [x.severity for x in v] == ["REPORT"]
    finally:
        ent.type_group = saved_group
        spec.entity_plans[ent.object_id] = saved_steps


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


def test_markings_carry_object_ids(written, built):
    """Data Logger 출력을 시나리오 객체로 되짚으려면 marking이 ID여야 한다."""
    with zipfile.ZipFile(written) as z:
        oob = z.read(f"{written.stem}.oob").decode("utf-8", "replace")
    marks = set(re.findall(r'\(marking-text "([^"]*)"\)', oob))
    # marking은 객체 id에서 기호만 뗀 것이다. 어떤 객체가 남든 이 규칙은 같다.
    spec, _ = built
    for e in spec.entities:
        assert re.sub(r"[^0-9A-Za-z]", "", e.object_id) in marks, e.object_id


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
    """같은 스펙이면 항상 같은 바이트.

    내용뿐 아니라 파일 바이트까지 본다. zip 항목은 이름만 주면 현재 시각이
    박혀서, 내용만 비교하면 실행 시각마다 달라지는 것을 놓친다(실제로 놓쳤다).
    """
    spec, _ = built
    a = get_writer("template", str(GOLDEN)).write(spec, tmp_path / "a")
    b = get_writer("template", str(GOLDEN)).write(spec, tmp_path / "b")
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        assert za.namelist() == zb.namelist()
        for n in za.namelist():
            assert za.read(n) == zb.read(n), n
    assert a.read_bytes() == b.read_bytes()


def test_every_task_weapon_exists_on_that_model(built):
    """태스크가 지정한 무기를 그 객체가 실제로 갖고 있는가.

    task_catalog 템플릿은 type_group 단위라 무기 이름이 하나로 박혀 있다.
    '보병 - 소총(M4 계열)'에는 M4를 든 미군과 AK-47을 든 적군이 같이 있어서,
    박힌 이름을 그대로 두면 적 보병이 "M4 rifle"로 쏘라는 태스크를 받는다.
    그 무기가 없으니 사격을 실행하지 못한다(실측: 80객체 중 23객체가 그랬다).
    """
    spec, _ = built
    g = Golden.load(GOLDEN)
    dis_by_id = {e.object_id: e.dis for e in spec.entities}
    cls_by_id = {e.object_id: e.entity_class for e in spec.entities}
    bad = []
    for oid, steps in spec.entity_plans.items():
        have = g.weapons_of(dis_by_id.get(oid) or ())
        for st in steps:
            for w in weapons_in(st.pln or ""):
                if w.split(":")[0] not in have:
                    bad.append((cls_by_id.get(oid), w, sorted(have)))
    assert bad == [], bad[:5]


def test_ak47_infantry_fires_with_ak47(built):
    """적 보병 사격 태스크가 AK-47을 지정하는가(회귀 방지 못박기)."""
    spec, _ = built
    ak = [oid for oid, e in {e.object_id: e for e in spec.entities}.items()
          if e.entity_class == "Russian Soldier AK47"]
    assert ak
    fired = [w for oid in ak for st in spec.entity_plans.get(oid, [])
             for w in weapons_in(st.pln or "")]
    assert fired, "적 보병에게 사격 태스크가 하나도 없다"
    assert set(fired) == {"AK-47"}, set(fired)
