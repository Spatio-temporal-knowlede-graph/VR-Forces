"""`.oob` 레코드에서 uuid → marking 표를 만든다.

CSV의 predicate는 대상을 uuid로 적기도 한다(Move-To Waypoint, Target-entity
task). uuid를 그대로 내보내면 다른 산출물과 조인할 수 없으므로 marking으로
되짚는다.

짝이 되는 `.oob`이 없으면 표가 비고 to_marking이 None을 돌려준다. 그때
호출부는 uuid 원문을 유지하고 object_type="uuid"로 표시해야 한다 — 버리지
않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

# 레코드 안에서 marking-text가 uuid보다 먼저 나온다(marking → ... → uuid).
_RE_PAIR = re.compile(
    r'\(marking-text "([^"]*)".*?\(uuid\s+"VRF_UUID:([^"]+)"', re.S)


def load_uuid_map(oob_path) -> dict[str, str]:
    text = Path(oob_path).read_text(encoding="utf-8", errors="replace")
    return {uuid: marking for marking, uuid in _RE_PAIR.findall(text)}


def to_marking(uuid: str, uuid_map: dict[str, str]) -> str | None:
    key = uuid[len("VRF_UUID:"):] if uuid.startswith("VRF_UUID:") else uuid
    return uuid_map.get(key)
