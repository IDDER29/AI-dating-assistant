from ai_client import cleanup_ai_response


def test_cleanup_removes_em_dash():
    # dash replaced by space, then whitespace collapsed → single space
    assert cleanup_ai_response("hello — world") == "hello world"


def test_cleanup_removes_en_dash():
    assert cleanup_ai_response("hello – world") == "hello world"


def test_cleanup_strips_trailing_period():
    assert cleanup_ai_response("hello.") == "hello"


def test_cleanup_strips_trailing_question_mark():
    assert cleanup_ai_response("really?") == "really"


def test_cleanup_strips_trailing_exclamation():
    assert cleanup_ai_response("wow!") == "wow"


def test_cleanup_collapses_spaces():
    assert cleanup_ai_response("hello   world") == "hello world"


def test_cleanup_fixes_space_before_comma():
    assert cleanup_ai_response("hello ,world") == "hello,world"


def test_cleanup_preserves_closing_paren():
    # Persona uses ) as a smirk — must not be stripped
    assert cleanup_ai_response("sure)") == "sure)"
