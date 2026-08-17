import re
import zipfile
from pathlib import Path

import pytest

from vtmak.gates import blocking
from vtmak.geometry import BattlefieldLayout
from vtmak.orbat import OrbatConfig, build_orbat
from vtmak.paths import SCENARIO
from vtmak.parser import PatternMap, parse_scenario
from vtmak.ranges import WeaponRanges
from vtmak.registry import UNCLASSIFIED, ClassMap, build_registry
from vtmak.roster import RosterPlan, filter_events, select_roster
from vtmak.scnx.catalog import DisCatalog, TaskCatalog, TaskKinds
from vtmak.scnx.gates import check_g3, weapons_in
from vtmak.scnx.golden import Golden, _balanced_records
from vtmak.scnx.plan import SKIP_UNSUPPORTED, PlanStep
from vtmak.scnx.pack import ensure_golden
from vtmak.scnx.places import PlaceCodes
from vtmak.scnx.spec import build_spec
from vtmak.scnx.writer import get_writer

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ensure_golden(ROOT / "yewon_test")


def _build_spec(orbat=None):
    """test_spec._build과 같은 구성. 명부를 감축한 뒤에야 편제를 지어야
    unit_of_entity가 저작 대상 328객체와 어긋나지 않는다."""
    cfg = ROOT / "config"
    pm = PatternMap.load(cfg / "pattern_map.csv")
    res = parse_scenario(
        SCENARIO.read_text(encoding="utf-8"),
        pm)
    lay = BattlefieldLayout.load(cfg / "battlefield_layout.json")
    cm = ClassMap.load(cfg / "entity_class_map.csv")
    reg = build_registry(res.events, cm, lay.static_ids())
    task_ids = {e.event_id for e in res.events
                if pm.task_kind_of(e) not in ("", "noop")}
    keep = select_roster(res.events, reg, RosterPlan.load(cfg / "roster.json"),
                         task_ids)
    events = filter_events(res.events, keep)
    reg = {o: d for o, d in reg.items() if o in keep}
    ob = build_orbat(reg, OrbatConfig.load(cfg / "orbat.json")) if orbat else None
    dis = DisCatalog.load(cfg / "dis_catalog.csv")
    spec = build_spec(events, reg, lay, pm,
                      TaskCatalog.load(cfg / "task_catalog.csv"),
                      TaskKinds.load(cfg / "task_kinds.csv"), dis,
                      WeaponRanges.load(cfg / "weapon_ranges.csv"), "battle",
                      orbat=ob)
    return spec, dis


@pytest.fixture(scope="module")
def built():
    return _build_spec()


@pytest.fixture(scope="module")
def spec_with_orbat():
    spec, _ = _build_spec(orbat=True)
    return spec


@pytest.fixture(scope="module")
def writer():
    return get_writer("template", str(GOLDEN))


@pytest.fixture(scope="module")
def writer_with_place_codes():
    """place_codes를 준 writer.

    F3 리뷰: 위 `writer` 픽스처는 place_codes 없이 만들어져 `_oob`가 전부
    `P{k}` 폴백 경로를 탄다. 그래서 04에서 `place_codes=`가 빠지거나
    시그니처가 리팩터돼도 기존 테스트는 초록으로 남는다. 실제로 04가
    쓰는 것과 같은 경로(place_codes 있음)를 별도 픽스처로 추가한다 —
    기존 픽스처는 그대로 두어 폴백 경로 커버리지도 잃지 않는다.
    """
    cfg = ROOT / "config"
    place_codes = PlaceCodes.load(cfg / "location_codes.csv")
    return get_writer("template", str(GOLDEN), place_codes=place_codes)


@pytest.fixture(scope="module")
def oob_with_place_codes(spec_with_orbat, writer_with_place_codes):
    return writer_with_place_codes._oob(spec_with_orbat)


@pytest.fixture(scope="module")
def written(built, tmp_path_factory):
    spec, _ = built
    out_dir = tmp_path_factory.mktemp("scnx")
    return get_writer("template", str(GOLDEN)).write(spec, out_dir)


@pytest.fixture(scope="module")
def scnx_with_units(spec_with_orbat, writer):
    return writer._oob(spec_with_orbat)


@pytest.fixture(scope="module")
def omp_with_units(spec_with_orbat, writer):
    return writer._omp(spec_with_orbat)


def test_g3_has_no_blocking_violations(built):
    spec, dis = built
    v = check_g3(spec, Golden.load(GOLDEN), dis)
    assert blocking(v) == [], [x.detail for x in blocking(v)]


def test_g3_flags_unauthored_steps_by_classification(built):
    """저작 못 한 스텝은 C3.5로 나간다 — 의도한 스킵이면 REPORT, 아니면 BLOCK.

    의도한 스킵은 둘이다. (1) skip_reason이 붙은 것 — VR-Forces가 실행을
    거부함이 실측된 조합. (2) 미분류 모델 — 무기체계가 확정되지 않은 것.
    나머지는 저작 결함이라 BLOCK이다. 규칙이 살아 있는지 보려고 pln 없는
    스텝을 하나 지어 넣고 두 갈래를 다 밟는다.
    """
    spec, dis = built
    g = Golden.load(GOLDEN)
    # 실제 산출에 남는 C3.5는 전부 의도한 스킵이라 REPORT여야 한다.
    existing = [x for x in check_g3(spec, g, dis) if x.code == "C3.5"]
    assert existing, "실측으로 걸러내는 조합이 하나도 없다 — 필터가 죽었다"
    assert {x.severity for x in existing} == {"REPORT"}

    ent = spec.entities[0]
    broken = PlanStep(event_id="ETEST", time_s=0, template="moveTo",
                      task_kind="move", action_label=None, pln=None,
                      issues=["템플릿 없음"])
    saved_steps = spec.entity_plans.get(ent.object_id, [])
    saved_group = ent.type_group
    spec.entity_plans[ent.object_id] = list(saved_steps) + [broken]

    def injected():
        return [x for x in check_g3(spec, g, dis)
                if x.code == "C3.5" and "ETEST" in x.detail]

    try:
        # (1) 사유 없는 저작 실패 = 결함 → BLOCK
        assert [x.severity for x in injected()] == ["BLOCK"]
        assert injected()[0].detail.startswith(f"{ent.object_id} ETEST")

        # (2) 실행 불가가 실측된 조합 → REPORT
        broken.skip_reason = SKIP_UNSUPPORTED
        assert [x.severity for x in injected()] == ["REPORT"]
        broken.skip_reason = ""

        # (3) 미분류 모델 → REPORT
        ent.type_group = UNCLASSIFIED
        assert [x.severity for x in injected()] == ["REPORT"]
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


def test_every_object_is_written_with_ai_off(written):
    """AI를 켜 두면 계획에 없는 교전이 나서 시나리오가 일찍 끝난다.

    golden 레코드는 AIEnabled True로 저장돼 있어서, 예전에는 VR-Forces에서
    손으로 328개를 껐다. 저작 단계에서 끈다(2026-08-05).
    """
    with zipfile.ZipFile(written) as z:
        oob = z.read(f"{written.stem}.oob").decode("utf-8", "replace")
    assert "AIEnabled True" not in oob
    assert oob.count("AIEnabled False") > 0


def test_ai_switch_only_touches_objects_that_have_one(built, tmp_path):
    """통제점처럼 state-data가 없는 객체에 스위치를 만들어 넣지 않는다."""
    spec, _ = built
    on = get_writer_oob(spec, tmp_path / "on", ai_enabled=True)
    off = get_writer_oob(spec, tmp_path / "off", ai_enabled=False)
    assert on.count("AIEnabled") == off.count("AIEnabled")
    assert on.count("AIEnabled True") == off.count("AIEnabled False")
    assert "AIEnabled False" not in on


def get_writer_oob(spec, out_dir, *, ai_enabled: bool) -> str:
    from vtmak.scnx.writer import TemplateScnxWriter
    out = TemplateScnxWriter(str(GOLDEN), ai_enabled=ai_enabled).write(
        spec, out_dir)
    with zipfile.ZipFile(out) as z:
        return z.read(f"{out.stem}.oob").decode("utf-8", "replace")


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


def test_mapping_tables_stay_out_of_the_code():
    """매핑 표가 코드로 돌아오면 config/task_kinds.csv가 정본이 아니게 된다."""
    src = (ROOT / "vtmak" / "scnx" / "plan.py").read_text(encoding="utf-8")
    for name in ("LABEL_CANDIDATES", "REF_FIELD", "FIRE_KIND"):
        assert f"{name}:" not in src and f"{name} =" not in src, name


def test_org_tree_closes_with_units(scnx_with_units):
    """parent-name이 전부 이 .oob 안에서 해석된다. 안 그러면 무한 로딩이다."""
    oob = scnx_with_units
    declared = set(re.findall(r'\(uuid\s+"VRF_UUID:([^"]*)"', oob)) | {
        "1 Force", "2 Force", "3 Force"}
    refs = re.findall(r'\(parent-name\s+(?:"VRF_UUID:([^"]*)"|(\S+?))\s*\)', oob)
    dangling = sorted({a for a, b in refs if a and a not in declared} |
                      {b for a, b in refs if b and b != "USE-DEFAULT"})
    assert dangling == []


def test_every_entity_hangs_under_a_platoon(scnx_with_units, spec_with_orbat):
    """고아 엔티티가 있으면 편제가 반쪽이다.

    브리프 원안의 정규식(`\\(local-vrf-object.*?\\n   \\)`)은 writer가 정확히
    3칸 들여쓰기로 레코드를 닫는다는 가정에 기대 취약하다. 대신 golden.py가
    aggregate 파싱에 쓰는 것과 같은 괄호 균형 파싱(`_balanced_records`)으로
    레코드를 잘라 들여쓰기와 무관하게 만든다. 단언 내용(엔티티 328 전원이
    소대 uuid 밑에 걸린다)은 원안 그대로 유지한다.
    """
    oob = scnx_with_units
    pl_uuids = {u.uuid for u in spec_with_orbat.units if u.echelon == "소대"}
    recs = _balanced_records(oob, "(local-vrf-object")
    hung = 0
    for r in recs:
        m = re.search(r'\(parent-name\s+"VRF_UUID:([^"]*)"', r)
        if m and m.group(1) in pl_uuids:
            hung += 1
    assert hung == len(spec_with_orbat.entities)


def test_omp_lists_every_object_with_units(scnx_with_units, omp_with_units,
                                           spec_with_orbat):
    oob_uuids = set(re.findall(r'\(uuid\s+"VRF_UUID:([^"]*)"', scnx_with_units))
    omp_uuids = set(re.findall(r'\(uuid\s+"VRF_UUID:([^"]*)"', omp_with_units))
    assert oob_uuids == omp_uuids
    assert len(omp_uuids) == (len(spec_with_orbat.entities)
                              + len(spec_with_orbat.units)
                              + len(spec_with_orbat.control_objects)
                              + len(spec_with_orbat.fixed_objects))


def test_control_point_markings_are_place_codes_not_p_numbers(
        oob_with_place_codes, spec_with_orbat):
    """place_codes를 준 실제 경로(04와 같은 경로)에서 통제점 marking을 본다.

    place_codes 없이 만든 writer로는 `_oob`가 항상 `P{k}` 폴백을 타서, 04에서
    `place_codes=` 인자가 빠지거나 시그니처가 리팩터돼도 기존 3개 `_oob`
    테스트가 계속 초록이었다(F3). 여기서는 marking-text가 지명 코드이고
    `P\\d+` 형태가 0개임을 직접 단언한다.
    """
    marks = re.findall(r'\(marking-text "([^"]*)"\)', oob_with_place_codes)
    assert len(marks) == (len(spec_with_orbat.entities)
                          + len(spec_with_orbat.control_objects)
                          + len(spec_with_orbat.units))
    n_control = len(spec_with_orbat.control_objects)
    assert n_control > 0
    p_number = re.compile(r"^P\d+$")
    p_number_marks = [m for m in marks if p_number.match(m)]
    assert p_number_marks == [], p_number_marks


def test_unit_records_leave_formation_name_blank(scnx_with_units,
                                                  spec_with_orbat):
    """골든 부대 레코드 7개(대대·중대 2·소대 4) 전수 확인 결과 formation-name이
    전부 빈 문자열이었다 — 대형 카탈로그 조회 값으로 보여 저작 시 채우면 안
    된다. 부대명은 object-label에 있으니 이 필드는 골든 값 그대로 둔다.
    """
    recs = _balanced_records(scnx_with_units, "(aggregate ")
    assert len(recs) == len(spec_with_orbat.units)
    for r in recs:
        m = re.search(r'\(formation-name\s+"([^"]*)"', r)
        assert m and m.group(1) == "", r[:200]
