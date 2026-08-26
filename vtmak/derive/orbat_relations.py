"""R8~R12 — 편제에서 부대 사실을 만든다.

시뮬레이터가 aggregate를 CSV로 내보내는지에 의존하지 않는다. 내보내기 판이
바뀌어도 같은 결과가 나와야 하고, 부대 fact가 관측 유무에 좌우되면 데이터셋의
관계 구성이 판마다 달라진다.

시간축: partOf·supports·reinforces는 t0에 한 번 낸다. 백마고지 데이터셋은
관계를 매 관측마다 복제해 test 20,210행 중 18,189행(90%)이 앞 시각 fact의
반복이었다 — '직전에 본 fact를 다시 낸다'는 규칙 하나로 90%를 맞춘다. 그 함정을
반복하지 않는다. 소속이 실제로 바뀌면 그 시점에 다시 낸다.
"""
from __future__ import annotations

from collections import defaultdict

from .relations import Relation, RuleResult, unit_members

# 편제표가 선언한 값. 관측에서 파생한 relations.LAYER("derived")와 섞이면
# 어느 쪽이 만든 값인지 산출물에서 되물어야 한다.
LAYER_ORBAT = "orbat"

# R8·R9의 provenance. R1~R7은 event_id를 근거로 대 원문 문장까지 되짚을 수
# 있지만, 이 둘은 이벤트를 안 읽는다 — 근거가 될 event_id가 애초에 없다.
# 대신 그 값을 실제로 선언한 파일을 가리킨다. (u.unit_id,)나 (a, b)처럼
# 관계 자신의 subject/object를 provenance로 되풀이하면 "이 사실의 근거는
# 이 사실"이라는 동어반복이 되어 추적에 쓸모가 없다.
ORBAT_CONFIG_PATH = "config/orbat.json"


def r8_part_of(orbat) -> RuleResult:
    """partOf(엔티티, 소대) · partOf(소대, 중대) · partOf(중대, 대대).

    체인을 접어서 partOf(엔티티, 대대)까지 내지 않는다. 2단계 전이를 규칙이
    배울 재료를 남기는 것이 이 관계를 넣는 이유다.
    """
    rels = []
    for u in orbat.units():
        for oid in u.members:
            rels.append(Relation("R8", "partOf", oid, u.unit_id,
                                 (ORBAT_CONFIG_PATH,), LAYER_ORBAT))
        if u.parent:
            rels.append(Relation("R8", "partOf", u.unit_id, u.parent,
                                 (ORBAT_CONFIG_PATH,), LAYER_ORBAT))
    return RuleResult(tuple(rels))


def r9_task_organization(orbat) -> RuleResult:
    """supports·reinforces. 원문에 근거가 없어 편제표가 선언한 값이다."""
    rels = []
    for a, b in orbat.supports():
        rels.append(Relation("R9", "supports", a, b, (ORBAT_CONFIG_PATH,),
                             LAYER_ORBAT))
    for a, b in orbat.reinforces():
        rels.append(Relation("R9", "reinforces", a, b, (ORBAT_CONFIG_PATH,),
                             LAYER_ORBAT))
    return RuleResult(tuple(rels))


# ── R10~R12 관측에서 부대가 주어인 fact ───────────────────────────────────
# R8·R9와 달리 layer를 안 넘긴다 — 기본값 "derived"(relations.LAYER)를 쓴다.
# 이 셋은 편제표 선언이 아니라 이벤트를 접어 만든 값이라, LAYER_ORBAT를
# 쓰면 "편제표가 이렇게 말했다"는 거짓 근거가 붙는다.


def _cluster_by_time(items, window):
    """(시각, actor, event_id) 목록을 시각 간격이 window 이내면 한 군집으로 묶는다.

    간격이 window를 넘으면 새 군집을 연다. moveTo 실측 간격은 보고 지터
    1초와 실제 국면 전환 127~276초 사이가 뚜렷이 갈리고 그 사이엔 관측값이
    아예 없다 — window를 그 틈 어디에 둬도 결과가 같다. 지터를 확실히
    삼키면서 국면 전환보다는 훨씬 작은 값을 쓰면 된다.
    """
    items = sorted(items)
    clusters: list[list[tuple[int, str, str]]] = []
    cur: list[tuple[int, str, str]] = []
    last_t = None
    for t, actor, eid in items:
        if cur and t - last_t > window:
            clusters.append(cur)
            cur = []
        cur.append((t, actor, eid))
        last_t = t
    if cur:
        clusters.append(cur)
    return clusters


def _fold(index, orbat, rules, ratio, window, templates, target_of, rule_id,
         predicate):
    """구성원 과반이 같은 국면·같은 대상에 대해 같은 일을 하면 부대 사실이다.

    '같은 국면'은 정확히 같은 초(1초 입도)가 아니라 시각 간격이 window 이내인
    보고 묶음이다. 1초 입도로 접으면 20명짜리 소대가 60·61·62초에 나눠
    보고돼 과반을 못 채우는 경우가 생긴다 — 그러면 살아남는 값은 대개
    구성원 1~2명짜리 소규모 편성뿐이라, note가 경고한 "소수의 이동이 부대
    이동으로 읽히는" 왜곡이 그대로 재현된다. window를 늘려 보고 지터를
    삼키되, 서로 다른 국면끼리 묶이지 않도록 국면 전환 간격보다는 훨씬
    작게 둔다(threshold `unit_fold_window_s`, config/derive_rules.csv).

    분모는 `unit_members(index, rules, orbat)`를 그대로 쓴다 — R6와 같은
    이유다. actor만 세면(맞기만 하고 쏘지 않는 구성원처럼) 이벤트에서
    다른 역할로만 등장하는 구성원이 분모에서 빠질 수 있다.

    provenance는 그 군집을 이룬 이벤트들의 event_id다. R1~R7과 같은 계약을
    지킨다 — 이 규칙은 이벤트를 읽으므로 event_id가 있고, 구성원 id를
    대신 넣으면 원문 문장까지 되짚을 길이 끊긴다. 부수 효과로 접힌 시각이
    event_id를 통해 복원 가능해진다 — 시각 자체를 Relation에 담지 않아도
    되는 이유다.
    """
    members = unit_members(index, rules, orbat)
    groups: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
    for e in index.events:
        if e.template not in templates:
            continue
        pl = orbat.platoon_of(e.actor) if e.actor else None
        target = target_of(e)
        if not pl or not target:
            continue
        groups[(pl, target)].append((e.time_s, e.actor, e.event_id))

    rels = []
    for (pl, target), items in sorted(groups.items()):
        roster = set(members.get(pl, ()))
        for cluster in _cluster_by_time(items, window):
            actors = {a for _, a, _ in cluster}
            if not roster or len(actors) / len(roster) < ratio:
                continue
            event_ids = tuple(sorted({eid for _, _, eid in cluster}))
            rels.append(Relation(rule_id, predicate, pl, target, event_ids))
    return RuleResult(tuple(rels))


def r10_unit_moves(index, orbat, rules) -> RuleResult:
    """movesToward(부대, 지명) — 구성원 과반이 같은 곳으로 갈 때."""
    return _fold(index, orbat, rules, rules.threshold("unit_move_ratio"),
                 rules.threshold("unit_fold_window_s"),
                 {"moveTo"}, lambda e: e.dst, "R10", "movesToward")


def r11_unit_occupies(index, orbat, rules) -> RuleResult:
    """occupies(부대, 지명) — 구성원 과반이 그 자리에 멈춰 있을 때."""
    return _fold(index, orbat, rules, rules.threshold("unit_occupy_ratio"),
                 rules.threshold("unit_fold_window_s"),
                 {"stopAt", "stayAt"}, lambda e: e.location, "R11", "occupies")


def r12_unit_fires(index, orbat, rules) -> RuleResult:
    """firesUpon(부대, 대상) — 구성원 다수가 같은 대상을 쏠 때.

    대상은 엔티티일 수도 지역 표기 객체일 수도 있다. 가리지 않는다 — 무엇을
    쐈는지는 대상 id가 말한다.

    실측 한계: 이 데이터에서 (소대, 대상) 쌍은 directFireAt·indirectFireAt을
    합쳐도 전부 시각이 유일하다(98개 군집 전부 크기 1) — window를 아무리
    조정해도 묶일 짝이 없다. 그래서 R12는 접지 않는다. 사실상 R4가 이미
    내는 firesUpon(사격자, 대상)의 사격자를 그 소속 소대로 다시 쓰는
    규칙이다. 그래도 부대가 주어인 fact라는 값은 있다 — 백마고지는 그런
    fact가 0건이었다.
    """
    return _fold(index, orbat, rules, rules.threshold("unit_fire_ratio"),
                 rules.threshold("unit_fold_window_s"),
                 {"directFireAt", "indirectFireAt"}, lambda e: e.target,
                 "R12", "firesUpon")
