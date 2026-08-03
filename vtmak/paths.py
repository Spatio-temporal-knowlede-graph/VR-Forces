"""경로 한 곳 모음.

원문 파일 이름이 바뀔 때(scenario_v3 → scenario_ver70 …) 고칠 자리가 여러 곳이면
스크립트는 새 파일을, 테스트는 없어진 파일을 보게 된다. 실제로 그렇게 깨졌다.
경로는 여기서만 정한다.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONFIG = ROOT / "config"
BUILD = ROOT / "build"
GOLDEN_DIR = ROOT / "yewon_test"

# 파이프라인이 읽는 시나리오 원문. 원문을 바꾸면 이 한 줄만 고친다.
DEFAULT_SCENARIO = ROOT / "scenario_original" / "scenario.txt"

# 다른 원문으로 한 번만 돌려 볼 때 쓰는 우회로. 안 주면 위 기본값이다 —
# 정본은 여전히 여기다.
SCENARIO = Path(os.environ.get("VTMAK_SCENARIO") or DEFAULT_SCENARIO)
