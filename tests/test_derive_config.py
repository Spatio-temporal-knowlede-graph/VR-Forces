"""derive_rules.csv — 규칙의 데이터 매핑은 코드가 아니라 이 표에 있다."""
import csv
from pathlib import Path

import pytest

from vtmak.derive.config import DeriveRules

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"


@pytest.fixture(scope="module")
def rules():
    return DeriveRules.load(CFG / "derive_rules.csv")


def test_hit_states_map_a_state_to_a_rule_and_relation(rules):
    """'손상'이 damages가 되는 근거는 코드가 아니라 표다.

    rule_id도 표에서 온다. 관계 이름만 넘기면 파생 관계가 무슨 규칙인지를
    코드가 다시 정해야 하고, 그 순간 표 밖에 두 번째 정본이 생긴다.

    옛 '제압'→R1·suppresses 매핑은 2026-08-27에 표에서 지웠다(설계 §9.2) —
    남은 hit_state는 손상 하나뿐이다.
    """
    assert rules.hit_states() == {"손상": ("R2", "damages")}


def test_derive_rules_config_has_no_suppression_mapping():
    """R1 행과 suppresses 값이 표 어디에도 남지 않았는지 원문으로 확인한다.

    DeriveRules는 kind별로 접은 뷰(hit_states/area_state/flag)만 노출하고
    행 자체를 보관하지 않는다 — 'R1이라는 rule_id가 표에 아예 없다'는
    주장은 그 뷰로는 증명이 안 된다. 그래서 CSV를 직접 읽는다.
    """
    with open(CFG / "derive_rules.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert "R1" not in {r["rule_id"].strip() for r in rows}
    assert "suppresses" not in {r["value"].strip() for r in rows}


def test_area_state_marks_the_indirect_fire_impact(rules):
    assert rules.area_state() == ("정상", "피격 지역")


def test_threshold_is_a_float_from_the_table(tmp_path):
    """현 표에는 임계값 행이 없다 — 부대 접기 비율이 유일한 용도였다.

    kind는 남긴다. 값을 코드가 아니라 표에서 읽는다는 계약은 규칙이 하나
    없어졌다고 사라지지 않는다. 그래서 표에 없는 지금도 파싱은 못 박아 둔다.
    """
    p = tmp_path / "t.csv"
    p.write_text("rule_id,kind,key,value,note\nR0,threshold,ratio,0.25,\n",
                 encoding="utf-8")
    v = DeriveRules.load(p).threshold("ratio")
    assert isinstance(v, float) and v == 0.25


def test_flag_reads_true_false(rules):
    assert rules.flag("skip_state_hold") is True


def test_unknown_lookups_are_loud_not_empty(rules):
    """조용한 기본값은 규칙이 왜 0건인지 못 찾게 만든다."""
    with pytest.raises(KeyError, match="없는임계값"):
        rules.threshold("없는임계값")
    with pytest.raises(KeyError, match="없는플래그"):
        rules.flag("없는플래그")


def test_unknown_kind_is_rejected_at_load(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("rule_id,kind,key,value,note\nR0,오타kind,a,b,\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="오타kind"):
        DeriveRules.load(p)
