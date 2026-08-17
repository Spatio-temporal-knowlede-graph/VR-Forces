"""STKG 파생 관계 레이어 — 추출 GT(Track A)를 읽기만 한다.

`build/events/battle.jsonl`은 원문에서 문장 틀로 뽑은 **추출 정본**이다. 여기서
하는 일은 그 이벤트들을 **합성**해 원문에 문장으로는 없는 관계를 만드는 것이고,
따라서 이 패키지는 순수 소비자다 — 이벤트 한 줄도 고치지 않는다.

파생 관계는 전부 `layer="derived"` · `rule_id` · `provenance`(근거 event_id)를
달고 나간다. 셋 중 하나라도 없으면 어느 규칙이 왜 그 관계를 만들었는지 되짚을
수 없고, 그러면 Track A와 섞였을 때 구분할 방법이 사라진다.

주의 — `vtmak/stkg/predicate.py`의 어휘(`follows`·`moves_to`…)는 저작이 끝난
`.pln`을 역파싱하는 별개 체계다. 이름이 비슷해도 같은 어휘가 아니다.
"""
