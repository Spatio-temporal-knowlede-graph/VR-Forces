"""문자열 정규화 — 프로젝트 전체가 이 두 함수만 쓴다.

원문·dis_catalog·task_catalog가 같은 모델을 다르게 적는다
('T-72 MBT' / 'T 72 MBT'). 매칭 키를 여기서 한 곳으로 모은다.
"""
from __future__ import annotations

import re


def norm(s: str | None) -> str:
    """모델명·클래스명 매칭 키. 공백과 하이픈을 지우고 소문자화."""
    return re.sub(r"[\s\-]+", "", s or "").lower()


def loc_id(surface: str | None) -> str:
    """지명 표면형 → LOC_ 접두 식별자. 공백만 지우고 원문자는 보존한다.

    사람이 config를 읽고 고칠 수 있어야 하므로 한글을 남긴다.
    이미 LOC_로 시작하면 그대로 돌려준다(멱등).
    """
    s = re.sub(r"\s+", "", surface or "")
    return s if s.startswith("LOC_") else f"LOC_{s}"
