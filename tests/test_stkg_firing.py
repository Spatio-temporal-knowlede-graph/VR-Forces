"""발사체 → 사수 확정. 신호 셋이 다 맞을 때만 붙어야 한다."""
from vtmak.stkg.firing import ffe_target, is_munition, link

# 국지 좌표로 충분하다. 판정이 쓰는 것은 거리뿐이다.
MORTAR_A = (0.0, 0.0, 0.0)
MORTAR_B = (0.0, 60.0, 0.0)
TARGET_A = (2000.0, 0.0, 0.0)
TARGET_B = (2000.0, 3000.0, 0.0)


def _ffe(target):
    x, y, z = target
    return (f'FFE-On-Location "Location={{{x}, {y}, {z}}}"  Name of Weapons '
            f"to Fire: Indirect-Fire-Gun:m9333he. Number-Of-Rounds: 1")


def _row(subject, ts, pos, predicate="None"):
    return {"subject": subject, "timestamp": ts, "predicate": predicate,
            "_pos": pos}


def _link(rows):
    return link(rows, lambda r: r["_pos"])


def _scene(target_b=TARGET_B, spawn=(5.0, 0.0, 0.0), impact=TARGET_A):
    """사수 둘 다 T1에 FFE를 끝내고, T2에 발사체가 하나 나타난다.

    기본 배치에서는 탄착도 포구도 A를 가리킨다. 각 시험은 이 중 하나만
    비틀어서 그 신호가 실제로 판정을 막는지 본다.
    """
    return [
        _row("FRMORT001", "T1", MORTAR_A, _ffe(TARGET_A)),
        _row("FRMORT002", "T1", MORTAR_B, _ffe(target_b)),
        _row("FRMORT001", "T2", MORTAR_A),
        _row("FRMORT002", "T2", MORTAR_B),
        _row("M933HE 1", "T2", spawn),
        _row("M933HE 1", "T3", impact),
    ]


def test_recognises_munition_subjects():
    assert is_munition("M933HE 1")
    assert is_munition("PAC-3 2")
    assert not is_munition("FRMORT001")
    assert not is_munition("M933HE")          # 번호가 없으면 발사체가 아니다


def test_reads_the_target_out_of_an_ffe_task():
    assert ffe_target(_ffe(TARGET_A)) == TARGET_A
    assert ffe_target("Move to {1, 2, 3}") is None


def test_links_when_every_signal_agrees():
    links, unresolved = _link(_scene())
    assert links["M933HE 1"].shooter == "FRMORT001"
    assert not unresolved


def test_shooter_still_firing_is_not_a_candidate():
    """FFE가 아직 도는 사수는 안 쏜 것이다. 실측 ENMORT003이 그렇다."""
    rows = _scene()
    for r in rows:
        if r["subject"] == "FRMORT001" and r["timestamp"] == "T2":
            r["predicate"] = _ffe(TARGET_A)       # A는 아직 쏘는 중
    links, unresolved = _link(rows)
    assert links.get("M933HE 1") is None or \
        links["M933HE 1"].shooter != "FRMORT001"


def test_no_candidate_at_all_is_reported():
    rows = [r for r in _scene() if not r["predicate"].startswith("FFE")]
    links, unresolved = _link(rows)
    assert not links
    assert "FFE가 끝난" in unresolved[0]


def test_ambiguous_impact_is_left_unresolved():
    """두 사수의 표적이 붙어 있으면 어느 쪽인지 못 가린다."""
    links, unresolved = _link(_scene(target_b=(2000.0, 30.0, 0.0)))
    assert not links
    assert "못 가림" in unresolved[0]


def test_muzzle_disagreeing_with_impact_is_left_unresolved():
    """탄착은 A를 가리키는데 포구는 B에 붙어 있으면 확정하지 않는다."""
    links, unresolved = _link(_scene(spawn=(0.0, 59.0, 0.0)))
    assert not links
    assert "엇갈림" in unresolved[0]


def test_one_shooter_cannot_own_two_rounds():
    rows = _scene()
    rows += [_row("M933HE 2", "T2", (5.0, 1.0, 0.0)),
             _row("M933HE 2", "T3", TARGET_A)]
    links, unresolved = _link(rows)
    assert len(links) == 1
    assert any("이미" in u for u in unresolved)
