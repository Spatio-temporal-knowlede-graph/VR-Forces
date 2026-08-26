"""DIS 열거값 하나로 이격거리와 사거리를 한 번에 꺼내는 조회 층.

세 파일을 직접 읽지 않는다. DisCatalog·ClassMap·WeaponRanges가 이미 각자를
읽고 norm()으로 키를 맞춘다. 여기서 다시 읽으면 정규화 규칙이 두 벌이 되고,
지금 없는 불일치를 새로 만든다.

DisCatalog는 entity_class → DIS 방향이라 역인덱스를 만든다. 관측 CSV가 주는
것은 DIS 쪽이기 때문이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ranges import RangeSpec, WeaponRanges
from ..registry import ClassMap
from ..scnx.catalog import DisCatalog
from .thresholds import SPACING_BY_TYPE_GROUP


def _dis_key(value: str) -> str:
    """'1:1:222:1:2:1:0'과 '1 1 222 1 2 1 0'을 같은 키로 만든다."""
    parts = [p for p in value.replace(":", " ").replace(",", " ").split() if p]
    return " ".join(parts)


@dataclass(frozen=True)
class EntityProfile:
    entity_class: str
    type_group: str
    spacing_m: float
    direct: RangeSpec | None
    indirect: RangeSpec | None

    @property
    def max_range_m(self) -> float | None:
        """가장 멀리 닿는 사거리. 무장이 없으면 None."""
        reach = [s.max_m for s in (self.direct, self.indirect) if s is not None]
        return max(reach) if reach else None


class ProfileIndex:
    """DIS 열거값 → EntityProfile."""

    def __init__(self, by_dis: dict[str, EntityProfile]) -> None:
        self._by_dis = by_dis

    @classmethod
    def load(cls, config_dir: Path) -> "ProfileIndex":
        """세 설정이 서로 맞물리지 않으면 처리를 시작하지 않는다."""
        config_dir = Path(config_dir)
        dis = DisCatalog.load(config_dir / "dis_catalog.csv")
        class_map = ClassMap.load(config_dir / "entity_class_map.csv")
        ranges = WeaponRanges.load(config_dir / "weapon_ranges.csv")

        by_dis: dict[str, EntityProfile] = {}
        for entity_class in ranges.classes():
            if not dis.known(entity_class):
                raise ValueError(
                    f"CLASS_JOIN_MISMATCH: {entity_class!r}가 weapon_ranges에는 "
                    f"있는데 dis_catalog에 없다")
            code = dis.dis(entity_class)
            if code is None:
                # dis 열이 비어 있는 클래스다. 이름은 맞지만 DIS를 아직 확정 못 했다는
                # 뜻이라 관측 CSV에서 만날 수 없다 — 건너뛴다. 이름이 안 맞는 경우와
                # 구분해야 한다. 둘 다 None이 오지만 뒤쪽은 설정 결함이다.
                continue
            if not class_map.known(entity_class):
                raise ValueError(
                    f"CLASS_JOIN_MISMATCH: {entity_class!r}가 weapon_ranges에는 "
                    f"있는데 entity_class_map에 없다")
            group = class_map.type_group(entity_class)
            if group not in SPACING_BY_TYPE_GROUP:
                raise ValueError(
                    f"CLASS_JOIN_MISMATCH: type_group {group!r}({entity_class})의 "
                    f"이격거리가 thresholds.SPACING_BY_TYPE_GROUP에 없다")
            by_dis[_dis_key(" ".join(str(n) for n in code))] = EntityProfile(
                entity_class=entity_class,
                type_group=group,
                spacing_m=SPACING_BY_TYPE_GROUP[group],
                direct=ranges.spec(entity_class, "direct"),
                indirect=ranges.spec(entity_class, "indirect"),
            )
        return cls(by_dis)

    def of(self, entity_type: str) -> EntityProfile | None:
        """모르는 타입은 None. 기본값을 지어내지 않는다."""
        if not entity_type or not entity_type.strip():
            return None
        return self._by_dis.get(_dis_key(entity_type))
