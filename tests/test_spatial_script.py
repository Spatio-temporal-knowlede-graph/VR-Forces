"""실행 스크립트 — 인자 해석과 종료 코드."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "script_08", ROOT / "scripts" / "08_spatial_relations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEADER = ("subject,predicate,object,latitude,longitude,timestamp,"
          "heading,entity_type,force")
ROWS = [
    "A,none,,21.38000000,-157.74000000,2026-08-09T08:00:00.000Z,0.0,3:1:225:1:41:1:0,1",
    "B,none,,21.38001800,-157.74000000,2026-08-09T08:00:00.000Z,0.0,3:1:225:1:41:1:0,1",
]


def test_parser_defaults_to_the_repo_config():
    from vtmak.paths import CONFIG
    module = _load()
    args = module.build_parser().parse_args(
        ["in.csv", "--relations", "r.csv", "--quality", "q.csv", "--manifest", "m.json"])
    assert args.config_dir == CONFIG
    assert args.dataset_version == "unversioned"


def test_parser_accepts_a_threshold_override():
    module = _load()
    args = module.build_parser().parse_args(
        ["in.csv", "--relations", "r.csv", "--quality", "q.csv",
         "--manifest", "m.json", "--thresholds", "t.json"])
    assert args.thresholds == Path("t.json")


def test_main_returns_zero_and_prints_json(tmp_path, capsys):
    module = _load()
    source = tmp_path / "in.csv"
    source.write_text("\n".join([HEADER, *ROWS]) + "\n", encoding="utf-8")
    status = module.main([
        str(source), "--relations", str(tmp_path / "r.csv"),
        "--quality", str(tmp_path / "q.csv"), "--manifest", str(tmp_path / "m.json"),
        "--dataset-version", "test1.0"])
    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["timestamps"] == 1
    assert payload["relation_counts"]["next_to"] == 1


def test_main_returns_two_on_a_missing_input(tmp_path, capsys):
    module = _load()
    status = module.main([
        str(tmp_path / "missing.csv"), "--relations", str(tmp_path / "r.csv"),
        "--quality", str(tmp_path / "q.csv"), "--manifest", str(tmp_path / "m.json")])
    assert status == 2
    assert "error:" in capsys.readouterr().err
