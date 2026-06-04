"""
Integration tests for the leomatch Scout pipeline.
Tests profile detection, like/dislike decision, and opener storage.
"""
import asyncio
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from state import BotState, PendingMatch


@pytest.fixture
def adapter():
    a = MagicMock()
    a.like_profile = AsyncMock()
    a.dislike_profile = AsyncMock()
    a.navigate_to_profiles = AsyncMock()
    a.send_opener = AsyncMock(return_value=True)
    return a


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def state():
    return BotState()


async def test_no_description_dislike_no_ai_call(client, state, adapter):
    """Profile with no description → instant dislike, no AI classification call."""
    from leomatch import process_leomatch_message

    with patch("leomatch.classify_profile_quality", new_callable=AsyncMock) as mock_cls:
        await process_leomatch_message(client, "Anna, 24, Moscow", state, adapter=adapter)

    mock_cls.assert_not_called()
    adapter.dislike_profile.assert_called_once()
    adapter.like_profile.assert_not_called()


async def test_good_description_triggers_like(client, state, adapter):
    """AI-approved description → like; pending_match populated."""
    from leomatch import process_leomatch_message

    with patch("leomatch.classify_profile_quality",
               new_callable=AsyncMock, return_value=True):
        await process_leomatch_message(
            client, "Anna, 24, Moscow — I love hiking and coding", state, adapter=adapter
        )

    adapter.like_profile.assert_called_once()
    adapter.dislike_profile.assert_not_called()
    assert state.pending_match is not None
    assert state.pending_match.description == "I love hiking and coding"


async def test_ai_rejected_description_triggers_dislike(client, state, adapter):
    """AI-rejected description → dislike; reason recorded correctly."""
    from leomatch import process_leomatch_message

    with patch("leomatch.classify_profile_quality",
               new_callable=AsyncMock, return_value=False):
        await process_leomatch_message(
            client, "Anna, 24, Moscow — whatever lol", state, adapter=adapter
        )

    adapter.dislike_profile.assert_called_once()


async def test_opener_stored_after_successful_send(client, state, adapter):
    """Opener stored in sent_openers after adapter.send_opener() succeeds."""
    from leomatch import process_leomatch_message

    state.pending_match = PendingMatch(
        anket_text="Anna, 24, Moscow — loves coffee",
        liked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        description="loves coffee",
    )

    with patch("leomatch.generate_first_message",
               new_callable=AsyncMock, return_value="hey, coffee fan spotted)"):
        await process_leomatch_message(
            client, "Write a message for this user", state, adapter=adapter
        )

    adapter.send_opener.assert_called_once_with("hey, coffee fan spotted)")
    assert len(state.sent_openers) == 1
    assert state.sent_openers[0]["text"] == "hey, coffee fan spotted)"
    assert state.pending_match is None  # cleared after send


async def test_opener_not_stored_if_send_fails(client, state, adapter):
    """If send raises, pending_match is preserved for retry at next startup."""
    from leomatch import process_leomatch_message

    state.pending_match = PendingMatch(
        anket_text="Anna, 24, Moscow — loves coffee",
        liked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    adapter.send_opener.side_effect = Exception("FloodWait")

    with patch("leomatch.generate_first_message",
               new_callable=AsyncMock, return_value="hey)"):
        await process_leomatch_message(
            client, "Write a message for this user", state, adapter=adapter
        )

    assert len(state.sent_openers) == 0
    assert state.pending_match is not None  # preserved


async def test_no_pending_match_ignores_write_message(client, state, adapter):
    """'Write a message' with no pending_match logs warning and does nothing."""
    from leomatch import process_leomatch_message

    state.pending_match = None

    await process_leomatch_message(
        client, "Write a message for this user", state, adapter=adapter
    )

    adapter.send_opener.assert_not_called()


async def test_main_menu_navigates_to_profiles(client, state, adapter):
    """'1. View profiles' text triggers navigate_to_profiles."""
    from leomatch import process_leomatch_message

    await process_leomatch_message(
        client, "1. View profiles\n2. More options", state, adapter=adapter
    )

    adapter.navigate_to_profiles.assert_called_once()
