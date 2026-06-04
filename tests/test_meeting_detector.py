from meeting_detector import detect_meeting_signal


class TestMeetingSignals:
    def test_russian_meet(self):
        assert detect_meeting_signal("давай встретимся в кофейне")

    def test_russian_coffee(self):
        assert detect_meeting_signal("выпьем кофе как-нибудь?")

    def test_english_meet(self):
        assert detect_meeting_signal("let's meet up sometime")

    def test_english_coffee(self):
        assert detect_meeting_signal("want to grab coffee?")

    def test_negative_normal_message(self):
        assert not detect_meeting_signal("how are you today?")

    def test_negative_empty(self):
        assert not detect_meeting_signal("")

    def test_negative_none(self):
        assert not detect_meeting_signal(None)

    def test_case_insensitive_russian(self):
        assert detect_meeting_signal("ДАВАЙ ВСТРЕТИМСЯ")

    def test_case_insensitive_english(self):
        assert detect_meeting_signal("LET'S MEET")
