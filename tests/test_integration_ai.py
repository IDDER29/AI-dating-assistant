"""
Integration tests for the AI generation pipeline.
Uses a mock Gemini model — no real API calls.
Verifies the full flow: sanitize → history build → validate → return
"""
import asyncio
import datetime
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from state import BotState


def _make_fake_result(text: str):
    """Create a fake Gemini API response with the given text."""
    result = MagicMock()
    result.text = text
    result.usage_metadata = MagicMock()
    result.usage_metadata.prompt_token_count = 100
    result.usage_metadata.candidates_token_count = 50
    result.usage_metadata.total_token_count = 150
    return result


@pytest.fixture
def state_with_model():
    state = BotState()
    mock_model = MagicMock()
    mock_chat = MagicMock()
    mock_model.start_chat.return_value = mock_chat
    state.model = mock_model
    state.active_model_name = "gemini-1.5-flash-002"
    return state, mock_chat


async def test_generate_response_basic_flow(state_with_model):
    """User message → AI response → appended to history with correct roles."""
    state, mock_chat = state_with_model
    mock_chat.send_message.return_value = _make_fake_result("hey, what's up")

    from ai_client import generate_conversation_response
    result = await generate_conversation_response(12345, "hello", state)

    assert result == "hey, what's up"
    history = state.conversation_histories["12345"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "model"
    assert history[1]["parts"][0] == "hey, what's up"


async def test_generate_response_api_none_rolls_back(state_with_model):
    """When API returns None, user turn is removed — no orphaned turn."""
    state, mock_chat = state_with_model
    mock_chat.send_message.return_value = None

    from ai_client import generate_conversation_response
    result = await generate_conversation_response(12345, "hello", state)

    assert "went wrong" in result
    history = state.conversation_histories.get("12345", [])
    assert all(t["role"] != "user" for t in history), \
        "Orphaned user turn found after API None"


async def test_generate_response_validation_failure_rolls_back(state_with_model):
    """Prompt-leak response is rejected; user turn is removed."""
    state, mock_chat = state_with_model
    mock_chat.send_message.return_value = _make_fake_result(
        "as per my dossier i should reply like this"
    )

    from ai_client import generate_conversation_response
    result = await generate_conversation_response(12345, "hey", state)

    assert "went wrong" in result
    history = state.conversation_histories.get("12345", [])
    assert all(t["role"] != "user" for t in history), \
        "User turn not rolled back after validation failure"


async def test_persona_collapse_rolls_back(state_with_model):
    """Persona collapse (AI admits AI nature) is rejected and rolled back."""
    state, mock_chat = state_with_model
    mock_chat.send_message.return_value = _make_fake_result(
        "i am an ai and cannot help with that"
    )

    from ai_client import generate_conversation_response
    result = await generate_conversation_response(12345, "are you real?", state)

    assert "went wrong" in result
    history = state.conversation_histories.get("12345", [])
    assert all(t["role"] != "user" for t in history)


async def test_opener_injected_for_new_conversation(state_with_model):
    """Opener from sent_openers is injected as first model turn."""
    state, mock_chat = state_with_model
    state.sent_openers = [{
        "text": "your profile caught my eye)",
        "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }]
    mock_chat.send_message.return_value = _make_fake_result("yeah tell me more")

    from ai_client import generate_conversation_response
    await generate_conversation_response(99999, "hi there", state)

    history = state.conversation_histories["99999"]
    assert history[0]["role"] == "model"
    assert history[0]["parts"][0] == "your profile caught my eye)"
    assert len(state.sent_openers) == 0  # popped


async def test_multiple_turns_accumulate_correctly(state_with_model):
    """Two round-trips produce 4 history entries with alternating roles."""
    state, mock_chat = state_with_model
    mock_chat.send_message.side_effect = [
        _make_fake_result("i'm good)"),
        _make_fake_result("yeah i love coffee"),
    ]

    from ai_client import generate_conversation_response
    await generate_conversation_response(11111, "how are you", state)
    await generate_conversation_response(11111, "do you like coffee?", state)

    history = state.conversation_histories["11111"]
    assert len(history) == 4
    assert [t["role"] for t in history] == ["user", "model", "user", "model"]


async def test_sanitization_strips_null_bytes(state_with_model):
    """Null bytes in the user message are stripped before reaching AI."""
    state, mock_chat = state_with_model
    mock_chat.send_message.return_value = _make_fake_result("ok")

    from ai_client import generate_conversation_response
    await generate_conversation_response(11111, "hello\x00world", state)

    # The user turn stored in history must not contain null bytes
    history = state.conversation_histories["11111"]
    user_turns = [t for t in history if t["role"] == "user"]
    assert "\x00" not in user_turns[0]["parts"][0]
