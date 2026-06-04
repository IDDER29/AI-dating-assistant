import datetime
from state import BotState, PendingMatch


def test_botstate_default_init():
    state = BotState()
    assert state.pending_match is None
    assert state.conversation_histories == {}
    assert state.whitelist_ids == set()
    assert state.active_model_name is None


def test_botstate_datetime_fields_are_timezone_aware():
    state = BotState()
    assert state.last_action_time.tzinfo is not None
    assert state.start_time.tzinfo is not None
    assert state.last_action_time.tzinfo == datetime.timezone.utc


def test_botstate_post_init_rejects_naive_datetime():
    import pytest
    with pytest.raises(ValueError, match="timezone-aware"):
        BotState(
            last_action_time=datetime.datetime.min  # naive — no tzinfo
        )


def test_pending_match_fields():
    pm = PendingMatch(
        anket_text="Anna, 24, Moscow — loves coffee",
        liked_at="2026-06-04T12:00:00+00:00",
        description="loves coffee",
    )
    assert pm.opener_text is None
    assert pm.description == "loves coffee"
    assert "Anna" in pm.anket_text


def test_last_reply_times_accepts_datetime():
    state = BotState()
    now = datetime.datetime.now(datetime.timezone.utc)
    state.last_reply_times[12345] = now
    assert isinstance(state.last_reply_times[12345], datetime.datetime)


def test_meeting_signals_detected_is_set():
    state = BotState()
    state.meeting_signals_detected.add(99999)
    assert 99999 in state.meeting_signals_detected
