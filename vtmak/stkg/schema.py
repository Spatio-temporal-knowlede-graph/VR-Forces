"""내보내기 판마다 다른 CSV 열 이름을 표준 이름으로 맞춘다.

05(후처리)와 06(평가)이 **같은 규칙**으로 읽어야 한다. 06이 따로
`row.get("object") or row.get("subject")`로 주체를 어림짐작하고 있었는데,
20260809판은 object 열을 전 행 `-`로 채워 보내므로 그 어림짐작이 모든 행의
주체를 `-`로 읽었다. 규칙은 여기 한 곳에만 둔다.

지금까지 본 판 셋이다.

  20260803  subject, predicate, object, latitude, longitude, timestamp,
            source, CID                                            (8열)
  20260804  object(=행위 주체), event, subject(=전 행 '-'), lat, lon, …
            이름을 바꾸면서 subject와 object의 뜻까지 맞바꿔 놨다. 열 하나씩
            별칭을 걸면 두 이름이 서로 덮어써서 못 푼다 — 헤더 전체로 판을
            알아보고 통째로 옮긴다.
  20260809  20260803의 8열에서 CID가 빠지고 상태 열 10개가 붙었다 (force,
            tracking_id, uuid, entity_type, damage, smoke, flaming,
            mobility_kill, firepower_kill, suppression_level). 표준 이름과
            이미 같으므로 옮길 것이 없다 — 새 열은 그대로 통과시킨다.

열을 우리 쪽 목록으로 못박지 않는 이유가 여기 있다. 내보내기가 열을 더
주면 그대로 내보내고, CID처럼 빼면 없는 대로 낸다. 뭘 받았는지는 산출
CSV의 헤더가 말해 준다.
"""
from __future__ import annotations

#   (판을 알아보는 열 집합, 원본 열 → 이 코드가 쓰는 표준 열)
_SCHEMAS = [
    ({"object", "event", "subject", "lat", "lon"},
     {"object": "subject", "event": "predicate", "subject": "object",
      "lat": "latitude", "lon": "longitude"}),
]

# 표준 이름. 이 여섯 열이 없으면 후처리를 못 한다.
REQUIRED = ("subject", "predicate", "timestamp", "source", "latitude",
            "longitude")

# object 열이 비었음을 뜻하는 값. 내보내기는 빈 자리를 `-`로 채운다.
BLANKS = frozenset({"", "-"})


def standardize(row: dict) -> dict:
    """내보내기 열 이름을 표준 이름으로 맞춘다. 모르는 판은 그대로 둔다."""
    for signature, mapping in _SCHEMAS:
        if signature <= row.keys():
            row = {mapping.get(k, k): v for k, v in row.items()}
            break
    row.setdefault("object", "")
    return row


def object_of(row: dict) -> str:
    """object 열에 내보내기가 실제로 채워 준 값. 빈 자리 표시는 ''로 준다.

    20260809판부터 `Fire Weapon` 행에 한해 대상이 미리 채워져 나온다(실측
    ground_truth 650행). 나머지 행은 전부 `-`다.
    """
    value = (row.get("object") or "").strip()
    return "" if value in BLANKS else value
