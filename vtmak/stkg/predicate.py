"""predicate 원문 → 정규화 술어 + object 원문.

내보내기가 object 열을 안 채우고 대상을 predicate 문자열 안에 박아 놓는다.
실측 478,360행 중 52,044행(10.9%)이 이미 엔티티를 품고 있다. 여기서 꺼낸다.

돌려주는 값 세 가지를 구분할 것.
  Parsed(predicate="follows", ...)  관계다
  Parsed(predicate="", ...)         관계가 아니다(위치 테이블행). None·suppressed_prone
  None                              파싱 실패. report에 원문과 함께 적는다

object_kind="given"은 대상이 predicate 문자열이 아니라 **object 열**에 있다는
뜻이다. 20260809판 `Fire Weapon`이 그렇다 — 내보내기가 직사 표적을 미리
채워 준다. 이때는 꺼낼 것이 없으므로 object_raw가 None이고, 호출부가 행의
object 열을 그대로 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RE_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

# 관계가 아니라고 아는 술어. 파싱 실패와 구분해야 report가 쓸모 있다.
_NOT_A_RELATION = frozenset({"None", "suppressed_prone"})

_RE_FOLLOW = re.compile(r'^Follow-Entity Entity:\s*"([^"]+)"')
_RE_MOVE_COORD = re.compile(r"^Move to \{([^}]+)\}")
_RE_MOVE_WP = re.compile(r'^Move-To Waypoint:\s*"([^"]+)"')
_RE_FFE = re.compile(r'^FFE-On-Location\s+"Location=\{([^}]+)\}"')
_RE_TARGET = re.compile(r"^Target-entity task:\s*(.+?)\s*$")
_RE_FIND_COVER = re.compile(r"^find_cover:.*?\bThreat=([^;]+?)\s*;")
_RE_FIND_FIRING = re.compile(
    r"^find_firing_position:.*?\bThreat=([^;]+?)\s*;")
# 직사 사격. 표적이 문자열에 없다 — object 열에 미리 채워져 온다.
_RE_FIRE_WEAPON = re.compile(r"^Fire Weapon\b")
_RE_WAIT = re.compile(r"^Wait-Duration\b")
_RE_SUPPRESS = re.compile(
    r"^provide_suppressive_fire_loc:.*?\btargetLocation=\{([^}]+)\}")


@dataclass(frozen=True)
class Parsed:
    predicate: str
    object_raw: str | None
    object_kind: str          # entity | uuid | coord | none


def _coord(blob: str) -> str:
    """'{a, b, c}' 속 알맹이를 공백 없는 정규형으로."""
    return ",".join(part.strip() for part in blob.split(","))


def parse(raw: str) -> Parsed | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw in _NOT_A_RELATION:
        return Parsed("", None, "none")

    m = _RE_FOLLOW.match(raw)
    if m:
        return Parsed("follows", m.group(1), "entity")

    m = _RE_MOVE_COORD.match(raw)
    if m:
        return Parsed("moves_to", _coord(m.group(1)), "coord")

    m = _RE_MOVE_WP.match(raw)
    if m:
        return Parsed("moves_to", m.group(1), "uuid")

    m = _RE_FFE.match(raw)
    if m:
        return Parsed("fires_at", _coord(m.group(1)), "coord")

    m = _RE_SUPPRESS.match(raw)
    if m:
        return Parsed("suppresses", _coord(m.group(1)), "coord")

    m = _RE_FIND_COVER.match(raw)
    if m:
        # Threat는 uuid가 아니라 marking으로 나온다(실측: Threat=FRINF001).
        return Parsed("takes_cover_from", m.group(1).strip(), "entity")

    m = _RE_FIND_FIRING.match(raw)
    if m:
        # Threat가 통제점으로도 나온다(실측: Threat=P10). 여기서 가리지
        # 않는다 — 이름이 객체인지 자리인지는 대조하는 쪽이 판단한다.
        return Parsed("takes_firing_position_against", m.group(1).strip(),
                      "entity")

    if _RE_FIRE_WEAPON.match(raw):
        return Parsed("fires_weapon_at", None, "given")

    if _RE_WAIT.match(raw):
        # 대기는 대상이 없는 태스크다. 관계가 아니라고 못박아 두면 '파싱
        # 실패'로 쌓여 report를 어지럽히지 않는다.
        return Parsed("waits", None, "none")

    m = _RE_TARGET.match(raw)
    if m:
        val = m.group(1)
        kind = "uuid" if _RE_UUID.fullmatch(val) else "entity"
        return Parsed("engages", val, kind)

    return None
