"""발사체 → 쏜 객체. 추론이 아니라 확정만 한다.

최근접 엔티티를 발사자로 보는 방식은 틀린다. 실측에서 포구 최근접만 보면
M933HE 1의 1등(26.7m)과 2등(32.2m)이 5.5m 차이라 어느 쪽도 못 고른다.

그래서 서로 **독립인 신호 셋**이 같은 짝을 가리킬 때만 확정한다.

1. 태스크 종료   사수의 FFE가 발사체 첫 관측 **전에** 끝났고, 그 뒤로 없다.
                 FFE가 계속 도는 사수는 아직 안 쏜 것이다(실측: ENMORT003은
                 08:16:16까지 FFE가 살아 있고 발사체가 없다).
2. 탄착점        발사체 마지막 위치가 그 사수의 FFE 표적에 가장 가깝고,
                 2등과 배수 이상 벌어진다.
3. 포구          발사체 첫 위치 기준 최근접 사수도 같은 사수다.

여기에 1:1까지 걸어 한 사수가 두 발을 갖지 못하게 한다. 하나라도 어긋나면
관계를 만들지 않는다 — 억지로 붙이면 틀린 관계가 정답 행세를 한다.

FFE 무기명과 발사체 이름은 대조하지 않는다. 실측에서 무기명이 `m9333he`,
발사체가 `M933HE`라 문자열이 같지 않다. 같은 것을 가리키는 게 뻔해 보여도
철자가 다른 두 이름을 같다고 우기는 순간 그건 추론이다.
"""
from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass

_RE_FFE_LOC = re.compile(r'^FFE-On-Location\s+"Location=\{([^}]+)\}"')

# 발사체 이름은 '<탄종> <번호>' 꼴이다. 실측: 'M933HE 1'.
_RE_MUNITION = re.compile(r"^(M107|M933HE|PAC-3)\s+\d+$")

# 탄착점 1등이 2등보다 이만큼 가까워야 짝으로 인정한다. 배수만 걸면 1등이
# 0.0m일 때 어떤 2등이든 통과해 버린다 — 절대 간격을 함께 건다. 실측 네 발은
# 둘 다 넉넉히 넘는다(가장 빠듯한 것이 88.5m 대 719.9m).
_MARGIN = 3.0
_SEPARATION_M = 50.0


def is_munition(subject: str) -> bool:
    return bool(_RE_MUNITION.match(subject))


def ffe_target(predicate: str) -> tuple[float, float, float] | None:
    """FFE 술어 원문에서 표적 좌표를 꺼낸다. FFE가 아니면 None."""
    m = _RE_FFE_LOC.match(predicate.strip())
    if not m:
        return None
    try:
        x, y, z = (float(v) for v in m.group(1).split(","))
    except ValueError:
        return None
    return x, y, z


@dataclass(frozen=True)
class Link:
    munition: str
    shooter: str
    evidence: str


@dataclass
class _Shooter:
    targets: set                        # FFE가 지시한 표적 좌표들
    last_ffe: str                       # FFE가 마지막으로 보인 시각
    pos: dict                           # 시각 → 위치


@dataclass
class _Munition:
    first_ts: str
    first_pos: tuple[float, float, float]
    last_ts: str
    last_pos: tuple[float, float, float]


def link(rows, ecef_of) -> tuple[dict[str, Link], list[str]]:
    """한 source 안의 행들 → {발사체: Link}, 확정 못 한 사유.

    호출부가 source별로 나눠서 부른다. 같은 발사체가 여러 관측자에게
    보이므로(실측: M933HE 1이 GROUND_TRUTH와 UAV 2 양쪽에 있다) 섞으면
    다른 시각대의 관측이 하나로 이어진다.
    """
    shooters: dict[str, _Shooter] = {}
    munitions: dict[str, _Munition] = {}
    seen_pos: dict[str, dict[str, tuple[float, float, float]]] = (
        collections.defaultdict(dict))

    for row in rows:
        subject, ts = row["subject"], row["timestamp"]
        pos = ecef_of(row)
        seen_pos[subject][ts] = pos

        if is_munition(subject):
            m = munitions.get(subject)
            if m is None:
                munitions[subject] = _Munition(ts, pos, ts, pos)
            else:
                # 행 순서를 믿지 않는다. 시각으로 양 끝을 잡는다.
                if ts < m.first_ts:
                    m.first_ts, m.first_pos = ts, pos
                if ts > m.last_ts:
                    m.last_ts, m.last_pos = ts, pos
            continue

        target = ffe_target(row["predicate"])
        if target is None:
            continue
        s = shooters.get(subject)
        if s is None:
            shooters[subject] = _Shooter({target}, ts, {})
        else:
            s.targets.add(target)
            if ts > s.last_ffe:
                s.last_ffe = ts

    for name, s in shooters.items():
        s.pos = seen_pos.get(name, {})

    return _match(shooters, munitions)


def _match(shooters: dict[str, _Shooter],
           munitions: dict[str, _Munition]) -> tuple[dict[str, Link], list[str]]:
    links: dict[str, Link] = {}
    unresolved: list[str] = []
    taken: dict[str, str] = {}          # 사수 → 발사체 (1:1을 지키기 위해)

    for name in sorted(munitions):
        mun = munitions[name]

        # 1. 발사체가 나타나기 전에 FFE가 끝난 사수만 후보다. 표적이 여럿인
        #    사수는 어느 표적으로 쐈는지 모르므로 후보에서 뺀다.
        cands = {s: sh for s, sh in shooters.items()
                 if sh.last_ffe < mun.first_ts and len(sh.targets) == 1}
        if not cands:
            unresolved.append(f"{name}: 첫 관측({mun.first_ts}) 전에 FFE가 "
                              f"끝난 표적 하나짜리 사수 없음")
            continue

        # 2. 탄착점 기준. 1등과 2등이 충분히 벌어져야 한다.
        by_impact = sorted(
            ((math.dist(mun.last_pos, next(iter(sh.targets))), s)
             for s, sh in cands.items()))
        best_d, best = by_impact[0]
        if len(by_impact) > 1:
            second_d, second = by_impact[1]
            if second_d < best_d * _MARGIN or second_d - best_d < _SEPARATION_M:
                unresolved.append(
                    f"{name}: 탄착 1등 {best}({best_d:.1f}m)과 2등 "
                    f"{second}({second_d:.1f}m)이 붙어 못 가림 "
                    f"({_MARGIN:.0f}배 또는 {_SEPARATION_M:.0f}m 간격 필요)")
                continue

        # 3. 포구 기준 최근접도 같은 사수여야 한다.
        by_muzzle = sorted(
            ((math.dist(mun.first_pos, sh.pos[mun.first_ts]), s)
             for s, sh in cands.items() if mun.first_ts in sh.pos))
        if not by_muzzle:
            unresolved.append(f"{name}: 첫 관측 시각({mun.first_ts})에 "
                              f"후보 사수의 위치가 없음")
            continue
        muzzle_d, muzzle_best = by_muzzle[0]
        if muzzle_best != best:
            unresolved.append(f"{name}: 탄착은 {best}, 포구는 {muzzle_best}로 "
                              f"엇갈림")
            continue

        # 4. 한 사수가 두 발을 갖지 못한다.
        if best in taken:
            unresolved.append(f"{name}: {best}이 이미 {taken[best]}에 물림")
            continue

        taken[best] = name
        links[name] = Link(name, best,
                           f"탄착 {best_d:.1f}m(2등 "
                           f"{by_impact[1][0]:.1f}m) · 포구 {muzzle_d:.1f}m · "
                           f"FFE 종료 {cands[best].last_ffe}"
                           if len(by_impact) > 1 else
                           f"탄착 {best_d:.1f}m(유일) · 포구 {muzzle_d:.1f}m · "
                           f"FFE 종료 {cands[best].last_ffe}")
    return links, unresolved
