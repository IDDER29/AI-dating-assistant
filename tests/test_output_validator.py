from output_validator import validate_response


def test_valid_short_response():
    assert validate_response("hey, how are you)").valid


def test_empty_string_invalid():
    assert not validate_response("").valid


def test_whitespace_only_invalid():
    assert not validate_response("   ").valid


def test_too_long_invalid():
    assert not validate_response("x" * 601).valid


def test_exactly_max_length_valid():
    assert validate_response("x" * 600).valid


def test_prompt_leak_dossier():
    assert not validate_response("as per my dossier instructions").valid


def test_prompt_leak_ai_avatar():
    assert not validate_response("you are the ai avatar of a real guy").valid


def test_too_many_ladder_parts():
    assert not validate_response("a ||| b ||| c ||| d ||| e").valid


def test_exactly_max_ladder_parts_valid():
    assert validate_response("a ||| b ||| c ||| d").valid
