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


# Persona collapse detection
def test_persona_collapse_ai_admission():
    assert not validate_response("i am an ai and i cannot do that").valid


def test_persona_collapse_language_model():
    assert not validate_response("as a language model i must be transparent").valid


def test_persona_collapse_cannot_fulfill():
    assert not validate_response("i cannot fulfill this request").valid


def test_persona_collapse_just_a_bot():
    assert not validate_response("look i'm just a bot i can't really help you").valid


def test_persona_collapse_not_able_to():
    assert not validate_response("i'm not able to discuss this topic").valid


def test_normal_lowercase_no_false_positive():
    # Persona speaks in lowercase — these normal messages must not be flagged
    assert validate_response("yeah i'm free on friday, why?").valid
    assert validate_response("i don't know what you mean, explain)").valid
    assert validate_response("sounds good, let me think about it").valid
