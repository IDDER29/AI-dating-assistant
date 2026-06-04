from settings import ANKET_PATTERN


class TestAnketPattern:
    def test_matches_full_profile(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow — I love hiking")
        assert m is not None
        assert m.group(1) == "Anna"
        assert m.group(2) == "24"
        assert m.group(3).strip() == "Moscow"
        assert m.group(4) == "I love hiking"

    def test_matches_no_description(self):
        m = ANKET_PATTERN.match("Boris, 30, SPb")
        assert m is not None
        assert m.group(4) is None

    def test_matches_multiline_description(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow — I love\nhiking")
        assert m is not None
        assert "hiking" in m.group(4)

    def test_no_match_text_age(self):
        m = ANKET_PATTERN.match("Anna, twenty four, Moscow — description")
        assert m is None

    def test_matches_em_dash(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow — desc")
        assert m is not None

    def test_matches_en_dash(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow – desc")
        assert m is not None
