from vtmak.stkg.predicate import Parsed, parse


def test_follow_entity_yields_entity_marking():
    p = parse('Follow-Entity Entity: "ENINF001" Offset: <-0 0 -0 >')
    assert p == Parsed("follows", "ENINF001", "entity")


def test_move_to_yields_coord():
    p = parse("Move to {-5499123.141030, -2250320.406046, 2311025.754248}")
    assert p.predicate == "moves_to"
    assert p.object_kind == "coord"
    assert p.object_raw == "-5499123.141030,-2250320.406046,2311025.754248"


def test_move_to_waypoint_yields_uuid():
    p = parse('Move-To Waypoint: "62f22b9c-d768-531d-9242-e32d8a056ee9"')
    assert p == Parsed("moves_to", "62f22b9c-d768-531d-9242-e32d8a056ee9",
                       "uuid")


def test_ffe_on_location_yields_coord():
    raw = ('FFE-On-Location "Location={-5498573.025370, -2251262.832114, '
           '2311309.431241}"  Name of Weapons to Fire: '
           "Indirect-Fire-Gun:m9333he. Number-Of-Rounds: 1. "
           "Height-Above-Terrain: 0")
    p = parse(raw)
    assert p.predicate == "fires_at"
    assert p.object_kind == "coord"
    assert p.object_raw.startswith("-5498573.025370,")


def test_target_entity_task_with_uuid():
    p = parse("Target-entity task: 2c380775-b3d4-7144-8815-4ef6c9e202ce")
    assert p == Parsed("engages", "2c380775-b3d4-7144-8815-4ef6c9e202ce",
                       "uuid")


def test_target_entity_task_with_marking():
    """UUID가 아닌 값도 온다. 실측 24행이 'M933HE 2'였다."""
    p = parse("Target-entity task: M933HE 2")
    assert p == Parsed("engages", "M933HE 2", "entity")


def test_find_cover_threat_is_a_marking_not_a_uuid():
    raw = ("find_cover: ChooseFiringPosition=False; DistanceFromThreat=2; "
           "FaceThreat=False; ForwardDirection=6.28318; OnlyForward=False; "
           "Range=100; StartFrom=0; StartingLocation={-5499510.258721, "
           "-2250984.063019, 2309459.984596}; Threat=FRINF001; "
           "ThreatRadius=2; ")
    assert parse(raw) == Parsed("takes_cover_from", "FRINF001", "entity")


def test_none_is_not_a_relation():
    assert parse("None") == Parsed("", None, "none")


def test_suppressed_prone_is_known_but_not_a_relation():
    """관계 어휘 11종에 없다. 파싱 실패가 아니므로 None이 아니다."""
    assert parse("suppressed_prone") == Parsed("", None, "none")


def test_unknown_predicate_returns_none():
    assert parse("Completely-Unknown-Task foo=1") is None


def test_empty_string_returns_none():
    assert parse("") is None


def test_fire_weapon_says_the_object_is_in_the_object_column():
    """20260809판에서 새로 나온 직사 술어. 표적이 문자열에 없다 — 내보내기가
    object 열에 미리 채워 준다(실측 ground_truth 650행)."""
    p = parse("Fire Weapon")
    assert p == Parsed("fires_weapon_at", None, "given")


def test_wait_duration_is_a_relationless_task():
    """대기는 대상이 없다. 파싱 실패로 쌓이면 report만 어지럽힌다."""
    p = parse("Wait-Duration Seconds-To-Wait:60")
    assert p == Parsed("waits", None, "none")


def test_find_firing_position_yields_the_threat():
    """실측 Threat는 통제점으로도 온다(Threat=P10). 여기서 가리지 않는다."""
    raw = ("find_firing_position: DistanceFromThreat=2; Range=100; "
           "Threat=P10; ThreatRadius=2;")
    assert parse(raw) == Parsed("takes_firing_position_against", "P10",
                                "entity")


def test_suppressive_fire_is_an_observed_location_task():
    """§9.2: 제압사격 태스크는 위치 좌표만 준다 — 대상 UUID가 없다. 제압
    사격을 했다고 해서 특정 객체가 제압됐다는 뜻은 아니므로, 시뮬레이터가
    직접 보고한 이 위치 관측만 담는다. 옛 이름 `suppresses`는 객체 효과를
    암시해 관측과 어긋났다."""
    parsed = parse("provide_suppressive_fire_loc: "
                   "targetLocation={1.0, 2.0, 3.0}")
    assert parsed.predicate == "provides_suppressive_fire_at"
    assert parsed.object_raw == "1.0,2.0,3.0"
    assert parsed.object_kind == "coord"
