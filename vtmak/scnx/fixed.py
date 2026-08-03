"""고정 객체 — 원문 밖에서 가져와 모든 시나리오에 같은 자리로 넣는 객체.

UAV처럼 원문이 서술하지 않지만 어느 규모에서든 같은 위치에 있어야 하는
객체가 있다. 좌표를 손으로 적지 않고, 이미 정상 저작된 시나리오(`campaign/`)의
레코드를 **원문 그대로** 복제한다. 좌표·DIS·자세·탑재 시스템이 통째로 따라오므로
새로 합성할 때 생기는 인스턴스화 실패 위험이 없다.

플랜은 붙이지 않는다. 그래서 VR-Forces에서 배치된 자리에 그대로 서 있는다
— 이것이 '항상 고정'의 구현이다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..geometry import Coord
from .golden import Golden
from .pack import ensure_golden

_RE_LABEL = re.compile(r'\(object-label "([^"]*)"')


@dataclass(frozen=True)
class FixedObject:
    marking: str
    label: str
    uuid: str
    dis: tuple[int, ...]
    coord: Coord
    raw: str            # .oob 레코드 원문. object-identifier만 갈아끼운다.


def load_fixed(config_path, root) -> list[FixedObject]:
    """config/fixed_objects.json → 복제할 레코드들.

    markings 순서대로 돌려준다. 하나라도 못 찾으면 예외다 — 조용히 빠지면
    '있는 줄 알았는데 없는' 상태가 되고, .scnx를 열어보기 전엔 모른다.
    """
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        return []
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    markings = list(cfg.get("markings") or [])
    if not markings:
        return []

    src = Path(root) / cfg["source_dir"]
    by_marking = {o.marking: o for o in Golden.load(ensure_golden(src)).objects}
    missing = [m for m in markings if m not in by_marking]
    if missing:
        raise KeyError(f"{src.name}에 없는 고정 객체: {missing}")

    out: list[FixedObject] = []
    for m in markings:
        o = by_marking[m]
        if o.position is None:
            raise ValueError(f"고정 객체에 좌표가 없다: {m}")
        label = _RE_LABEL.search(o.raw)
        out.append(FixedObject(
            marking=o.marking,
            label=label.group(1) if label else o.marking,
            uuid=o.uuid,
            dis=o.dis,
            coord=Coord.from_ecef(*o.position),
            raw=o.raw,
        ))
    return out
