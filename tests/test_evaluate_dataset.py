"""06 대조 — 05가 낸 CSV를 읽는 쪽의 분류 규칙.

05와 06이 같은 답을 써야 한다. 한쪽만 통제점을 객체로 세면 원문에 없는
이름 11개가 '못 맞춘 객체'로 평가에 유령처럼 남는다(locate.is_place 주석).
"""
import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ANNOTATED_COLS = ["subject", "predicate", "object",
                  "timestamp", "latitude", "longitude"]


@pytest.fixture(scope="module")
def evaluate():
    spec = importlib.util.spec_from_file_location(
        "evaluate_dataset", ROOT / "scripts" / "06_evaluate_dataset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _annotated(path: Path, rows) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ANNOTATED_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def _row(subject, predicate="none", obj=""):
    return {"subject": subject, "predicate": predicate, "object": obj,
            "timestamp": "2026-08-09T08:53:44.000Z",
            "latitude": "21.38376150", "longitude": "-157.74491520"}


def test_place_name_subject_counts_as_a_control_point_not_an_entity(
        evaluate, tmp_path):
    """지명화한 통제점을 객체로 세면 안 된다.

    05가 주체 `P10`을 `LOC_중앙킬존`으로 바꿔 내보내므로, `P3`·`P10` 꼴만
    통제점으로 보는 06은 그 지명을 전투 객체로 세어 버린다.
    """
    path = _annotated(tmp_path / "gt_annotated.csv",
                      [_row("LOC_중앙킬존"),
                       _row("FRINF027", "move to", "LOC_중앙킬존")])
    scan = evaluate.Scan("ground_truth")
    scan.read_annotated(path)

    assert scan.controls == {"LOC_중앙킬존"}
    assert scan.entities == {"FRINF027"}
