"""task_kinds.csv — plan.py의 코드 표 세 개를 대체한 사전."""
from pathlib import Path

import pytest

from vtmak.scnx.catalog import TaskKinds

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"


@pytest.fixture(scope="module")
def kinds():
    return TaskKinds.load(CFG / "task_kinds.csv")


def test_ref_kind_selects_a_different_label_list(kinds):
    """같은 kind라도 참조가 객체냐 좌표냐에 따라 후보가 갈린다."""
    assert kinds.get("fire_direct", "ENTITY").labels == (
        "대상 직접사격", "대상 자동무장 사격")
    assert kinds.get("fire_direct", "COORD").labels == ("대상 직접사격",)


def test_ref_field_and_fire_kind_are_per_task_kind(kinds):
    assert kinds.ref_field("move_cover") == "source_obj"
    assert kinds.ref_field("follow") == "unit_leader"
    assert kinds.ref_field("move") == "dst"
    assert kinds.fire_kind("fire_indirect") == "indirect"
    assert kinds.fire_kind("move") == ""


def test_unknown_kind_is_not_silently_empty(kinds):
    """조용히 빈 값을 주면 왜 task가 안 나오는지 .scnx를 열기 전엔 모른다."""
    assert kinds.get("없는kind", "ENTITY") is None
    assert not kinds.known("없는kind")
    with pytest.raises(KeyError, match="없는kind"):
        kinds.ref_field("없는kind")


def test_conflicting_rows_are_an_error(tmp_path):
    """같은 kind의 두 행이 참조 필드를 다르게 적으면 어느 쪽이 맞는지 알 수 없다."""
    p = tmp_path / "task_kinds.csv"
    p.write_text(
        "task_kind,ref_kind,참조_필드,사거리_종류,행동_후보,비고\r\n"
        "move,COORD,dst,,좌표로 이동,\r\n"
        "move,ENTITY,target,,좌표로 이동,\r\n",
        encoding="utf-8", newline="")
    with pytest.raises(ValueError, match="참조_필드"):
        TaskKinds.load(p)


def test_wildcard_ref_kind_matches_anything(tmp_path):
    p = tmp_path / "task_kinds.csv"
    p.write_text(
        "task_kind,ref_kind,참조_필드,사거리_종류,행동_후보,비고\r\n"
        "wait,*,,,대기,참조 대상 없음\r\n",
        encoding="utf-8", newline="")
    k = TaskKinds.load(p)
    assert k.get("wait", "COORD").labels == ("대기",)
    assert k.get("wait", "ENTITY").labels == ("대기",)
    assert k.ref_field("wait") == ""
