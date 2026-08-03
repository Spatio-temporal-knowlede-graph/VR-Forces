from vtmak.norm import loc_id, norm


def test_norm_makes_hyphen_and_space_variants_equal():
    # 원문은 'T-72 MBT', dis_catalog는 'T 72 MBT'로 적혀 있다.
    assert norm("T-72 MBT") == norm("T 72 MBT")
    assert norm("MO-120RT-61 Mortar") == norm("MO 120RT 61 Mortar")
    assert norm("US ArmyM4") == norm("US Army M4")


def test_norm_does_not_collide_across_distinct_models():
    assert norm("M901 Patriot Launcher") != norm("MIM-104 Patriot Launcher")
    assert norm("T-69 MBT") != norm("T-72 MBT")


def test_norm_handles_none_and_empty():
    assert norm(None) == ""
    assert norm("") == ""


def test_loc_id_prefixes_and_strips_spaces_only():
    assert loc_id("남측 제1방어선") == "LOC_남측제1방어선"
    assert loc_id("목표 A 남측") == "LOC_목표A남측"


def test_loc_id_is_idempotent():
    assert loc_id(loc_id("중앙 킬존")) == "LOC_중앙킬존"
