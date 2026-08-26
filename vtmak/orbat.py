"""역할군 → 편제(소대·중대·대대).

원문 1,294줄에 소대·중대·대대 언급이 0건이라 편제는 추출이 아니라 저작이다.
그런데 (진영 × 역할 × 초기 배치 지명)으로 역할군 30개가 이미 깔끔하게 나오므로,
축약 정원만 얹어 결정적으로 분할한다. 난수도 해시도 쓰지 않는다 — 정렬된
목록의 순서가 편성을 정한다(placement.py와 같은 규칙).

roster.unit_of()는 건드리지 않는다. 그건 roster.json의 quota 키(FR-INF)라
편제로 바꾸면 명부 감축이 통째로 어긋난다. 편제는 여기서만 다룬다.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ECHELON_PL = "소대"
ECHELON_CO = "중대"
ECHELON_BN = "대대"

# units()의 정렬 순위. 대대 → 중대 → 소대 순으로, 자식의 parent는 항상 이
# 순위에서 자기보다 앞서는 제대다(소대의 parent는 중대나 대대, 중대의
# parent는 대대). 그래서 이 순위로 정렬하면 "부모가 먼저 나온다"가
# 구조적으로 보장된다 — unit_id 사전식 정렬만으로는 안 된다
# ('UNIT-EN-AD-PL1' < 'UNIT-EN-BN'이라 소대가 대대보다 먼저 나온다).
_ECHELON_RANK = {ECHELON_BN: 0, ECHELON_CO: 1, ECHELON_PL: 2}

_ROLE_INDEX = re.compile(r"\s*\d+$")


def role_stem(role: str) -> str:
    """'방어 보병 12' → '방어 보병'. 역할은 객체마다 번호가 붙어 온다."""
    return _ROLE_INDEX.sub("", (role or "").strip())


@dataclass(frozen=True)
class Unit:
    unit_id: str
    name: str
    marking: str
    echelon: str
    faction: str
    parent: str                      # 상위 unit_id. 대대는 ""
    members: tuple[str, ...] = ()    # 엔티티 object_id. 소대만 채워진다


@dataclass
class OrbatConfig:
    platoons_per_company: int
    apply_split_to: set
    capacity: dict
    capacity_override: dict
    company_functions: set
    company_split_by_location: set
    function_code: dict
    function_of_role: dict
    faction_code: dict
    faction_name: dict
    battalion_name: dict
    supports: tuple = ()
    reinforces: tuple = ()

    @classmethod
    def load(cls, path) -> "OrbatConfig":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        doc, sim = d["doctrine"], d["simulation_abstraction"]
        # supports/reinforces는 .get(key, [])로 읽지 않는다. 키가 오타나거나
        # 리팩터로 빠지면 빈 리스트가 되어 build_orbat이 조용히 지원관계
        # 0건을 낳고, test_task_organization_targets_exist는 루프가 0회
        # 돌아 공허하게 통과한다 — 지원관계가 통째로 사라져도 테스트가
        # 초록으로 보이는 것이다. 그래서 필수 키로 취급해 시끄럽게 죽는다.
        for key in ("supports", "reinforces"):
            if key not in d:
                raise KeyError(f"{path}: orbat.json에 필수 키 {key!r}가 없다")
        return cls(
            platoons_per_company=int(doc["platoons_per_company"]),
            apply_split_to=set(doc["apply_split_to"]),
            capacity=dict(sim["platoon_capacity"]),
            capacity_override=dict(sim["platoon_capacity_override"]),
            company_functions=set(d["company_functions"]),
            company_split_by_location=set(d["company_split_by_location"]),
            function_code=dict(d["function_code"]),
            function_of_role=dict(d["function_of_role"]),
            faction_code=dict(d["faction_code"]),
            faction_name=dict(d["faction_name"]),
            battalion_name=dict(d["battalion_name"]),
            supports=tuple(tuple(p) for p in d["supports"]),
            reinforces=tuple(tuple(p) for p in d["reinforces"]),
        )

    def function(self, role: str) -> str:
        stem = role_stem(role)
        if stem not in self.function_of_role:
            raise KeyError(f"orbat.json의 function_of_role에 없는 역할: {stem!r}")
        return self.function_of_role[stem]

    def platoon_capacity(self, role: str, func: str) -> int:
        stem = role_stem(role)
        if stem in self.capacity_override:
            return int(self.capacity_override[stem])
        if func not in self.capacity:
            raise KeyError(f"orbat.json의 platoon_capacity에 없는 기능: {func}")
        return int(self.capacity[func])


class Orbat:
    def __init__(self, units: list[Unit], supports=(), reinforces=()) -> None:
        self._u = {u.unit_id: u for u in units}
        self._of: dict[str, str] = {}
        for u in units:
            for oid in u.members:
                self._of[oid] = u.unit_id
        self._supports = tuple(supports)
        self._reinforces = tuple(reinforces)

    def units(self) -> list[Unit]:
        """(제대 순위, unit_id) 순. 부모가 항상 자식보다 먼저 나온다.

        unit_id 사전식 정렬만 쓰면 'UNIT-EN-AD-PL1'이 'UNIT-EN-BN'보다
        앞서는 것처럼 자식이 부모를 앞지르는 경우가 생긴다(67개 중 9개).
        다음 태스크들이 이 순서 그대로 .oob에 부대를 저작하는데, 이
        저장소의 알려진 실패 모드가 정확히 "parent-name이 안 닫히면
        VR-Forces가 무한 로딩한다"이다. 제대 순위(대대<중대<소대)로
        정렬하면 부모-먼저가 구조적으로 보장된다 — 소대의 parent는 항상
        중대나 대대, 중대의 parent는 항상 대대이기 때문이다.
        """
        return [self._u[k] for k in
               sorted(self._u, key=lambda k: (_ECHELON_RANK[self._u[k].echelon], k))]

    def get(self, unit_id: str) -> Unit:
        if unit_id not in self._u:
            raise KeyError(f"없는 부대: {unit_id}")
        return self._u[unit_id]

    def platoon_of(self, object_id: str) -> str | None:
        return self._of.get(object_id)

    def chain(self, unit_id: str) -> tuple[str, ...]:
        """자기 → 상위 → ... → 대대."""
        out, cur, seen = [], unit_id, set()
        while cur:
            if cur in seen:
                raise ValueError(f"부대 트리에 사이클: {unit_id}")
            seen.add(cur)
            out.append(cur)
            cur = self.get(cur).parent
        return tuple(out)

    def supports(self) -> tuple:
        return self._supports

    def reinforces(self) -> tuple:
        return self._reinforces


def build_orbat(registry, cfg: OrbatConfig) -> Orbat:
    taskable = {o: d for o, d in registry.items() if d.taskable}

    # 역할군: (진영, 역할, 초기 배치). 정렬된 id 순서가 소대 배정을 정한다.
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for oid in sorted(taskable):
        d = taskable[oid]
        groups[(d.faction, role_stem(d.role), d.initial_location)].append(oid)

    units: list[Unit] = []
    for faction in sorted({f for f, _, _ in groups}):
        units += _build_faction(faction, groups, cfg, taskable)
    return Orbat(units, cfg.supports, cfg.reinforces)


def _build_faction(faction, groups, cfg, taskable) -> list[Unit]:
    fc = cfg.faction_code[faction]
    bn_id = f"UNIT-{fc}-BN"
    out = [Unit(bn_id, cfg.battalion_name[faction], f"{fc}BN",
                ECHELON_BN, faction, "")]

    # 기능 → [(역할, 지명, 소대멤버 리스트)]
    by_func: dict[str, list[tuple[str, str, list[list[str]]]]] = defaultdict(list)
    for (f, role, loc), members in sorted(groups.items()):
        if f != faction:
            continue
        func = cfg.function(role)
        cap = cfg.platoon_capacity(role, func)
        chunks = [members[i:i + cap] for i in range(0, len(members), cap)]
        by_func[func].append((role, loc, chunks))

    for func in sorted(by_func):
        code = cfg.function_code[func]
        if func in cfg.company_functions:
            out += _build_companies(faction, fc, code, func, by_func[func],
                                    bn_id, cfg)
        else:
            out += _build_direct(faction, fc, code, func, by_func[func], bn_id,
                                 cfg)
    return out


def _build_companies(faction, fc, code, func, entries, bn_id, cfg) -> list[Unit]:
    """중대를 만드는 기능. 전차는 지명별로, 보병은 3소대마다 나눈다."""
    buckets: dict[str, list[list[str]]] = defaultdict(list)
    for role, loc, chunks in entries:
        key = loc if func in cfg.company_split_by_location else ""
        buckets[key] += chunks

    out: list[Unit] = []
    co_no = 0
    for key in sorted(buckets):
        chunks = buckets[key]
        per = (cfg.platoons_per_company if func in cfg.apply_split_to
               else len(chunks))
        n_co = max(1, math.ceil(len(chunks) / per))
        for i in range(n_co):
            co_no += 1
            co_id = f"UNIT-{fc}-{code}-CO{co_no}"
            # 지명별로 갈린 중대는 번호만으로는 어느 중대가 어디인지 안
            # 보인다("적군 전차중대 1"). name(=object-label)에 분할 근거인
            # 지명을 넣는다. unit_id·marking은 하류가 쓰므로 그대로 둔다.
            if key:
                place = key[4:] if key.startswith("LOC_") else key
                label = f"{cfg.faction_name[faction]} {func}중대({place})"
                if n_co > 1:
                    label += f" {i + 1}"
            else:
                label = f"{cfg.faction_name[faction]} {func}중대 {co_no}"
            out.append(Unit(co_id, label,
                            f"{fc}{code}CO{co_no}", ECHELON_CO, faction, bn_id))
            for j, members in enumerate(chunks[i * per:(i + 1) * per], 1):
                out.append(Unit(
                    f"{co_id}-PL{j}",
                    f"{cfg.faction_name[faction]} {func}중대 {co_no} {j}소대",
                    f"{fc}{code}C{co_no}P{j}", ECHELON_PL, faction, co_id,
                    tuple(members)))
    return out


def _build_direct(faction, fc, code, func, entries, bn_id, cfg) -> list[Unit]:
    """중대를 만들지 않는 기능 — 대대 직할 소대로 단다."""
    out: list[Unit] = []
    pl_no = 0
    for role, loc, chunks in entries:
        for members in chunks:
            pl_no += 1
            out.append(Unit(
                f"UNIT-{fc}-{code}-PL{pl_no}",
                f"{cfg.faction_name[faction]} {func} {pl_no}소대",
                f"{fc}{code}PL{pl_no}", ECHELON_PL, faction, bn_id,
                tuple(members)))
    return out
