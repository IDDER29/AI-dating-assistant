import asyncio
import datetime
import logging
import re

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from config import (
    ANKET_PATTERN,
    CONVERSATION_SYSTEM_PROMPT,
    FIRST_MESSAGE_PROMPT,
    GEMINI_API_KEY,
    MAX_HISTORY_LENGTH,
)
from output_validator import validate_response


def initialize_ai(state):
    """Initialize the Gemini model with system_instruction."""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        state.model = genai.GenerativeModel(
            "gemini-1.5-flash-latest",
            system_instruction=CONVERSATION_SYSTEM_PROMPT,
        )
        logging.info("Google Gemini model successfully initialized.")
    except Exception as e:
        logging.error(f"Failed to configure Google Gemini model: {e}")
        state.model = None


def cleanup_ai_response(text: str) -> str:
    """Clean AI output from unwanted punctuation and whitespace."""
    cleaned_text = text.replace("–", " ").replace("—", " ")
    cleaned_text = cleaned_text.strip().rstrip(".?!")
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)
    cleaned_text = cleaned_text.replace(" ,", ",")
    return cleaned_text.strip()


async def with_rate_limit_handling(api_call, timeout_sec: float = 30.0):
    """
    Wrap a synchronous Gemini API call with timeout, retries, and full error
    handling for rate limits, server errors, and network timeouts.
    """
    for attempt in range(1, 4):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(api_call),
                timeout=timeout_sec,
            )

        except asyncio.TimeoutError:
            logging.warning(
                f"[AI] API call timed out after {timeout_sec}s "
                f"(attempt {attempt}/3). Retrying in 10s..."
            )
            await asyncio.sleep(10)

        except google_exceptions.ResourceExhausted as e:
            retry_delay = 60
            if hasattr(e, "error") and hasattr(e.error, "metadata"):
                for meta in e.error.metadata:
                    if meta[0] == "retry-delay":
                        retry_delay = int(meta[1].seconds) + 1
                        break
            logging.warning(
                f"[AI] Rate limit hit. Retrying in {retry_delay}s "
                f"(attempt {attempt}/3)..."
            )
            await asyncio.sleep(retry_delay)

        except (
            google_exceptions.ServiceUnavailable,
            google_exceptions.DeadlineExceeded,
            google_exceptions.InternalServerError,
        ) as e:
            logging.warning(
                f"[AI] Retryable server error: {type(e).__name__} "
                f"(attempt {attempt}/3). Retrying in 15s..."
            )
            await asyncio.sleep(15)

    logging.error("[AI] Failed to execute API request after 3 attempts.")
    return None


async def generate_first_message(anket_text: str, state) -> str:
    """Generate the first message for a new profile."""
    fallback_message = "your profile seemed very interesting, shall we chat?"
    if not state.model:
        return fallback_message

    match = ANKET_PATTERN.match(anket_text)
    profile_text = match.group(4).strip() if match and match.group(4) else ""

    if len(profile_text) < 15:
        profile_text = "Profile description is short or meaningless"

    prompt = FIRST_MESSAGE_PROMPT.format(profile_text=profile_text)
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))

    if result and hasattr(result, "text"):
        return cleanup_ai_response(getattr(result, "text"))
    return fallback_message


async def generate_conversation_response(chat_id: int, user_message: str, state) -> str:
    """Generate a contextual reply in an existing dialog."""
    fallback_message = "hm, something went wrong, repeat that"
    if not state.model:
        return fallback_message

    chat_id_str = str(chat_id)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if chat_id_str not in state.conversation_histories:
        state.conversation_histories[chat_id_str] = []

    user_turn = {"role": "user", "parts": [user_message], "timestamp": now_iso}
    state.conversation_histories[chat_id_str].append(user_turn)

    if len(state.conversation_histories[chat_id_str]) > MAX_HISTORY_LENGTH:
        state.conversation_histories[chat_id_str] = \
            state.conversation_histories[chat_id_str][-MAX_HISTORY_LENGTH:]

    try:
        history_for_api = [
            {"role": str(msg["role"]), "parts": list(msg["parts"])}
            for msg in state.conversation_histories[chat_id_str]
        ]
        history_to_send = history_for_api[:-1] if history_for_api else []
        chat_session = state.model.start_chat(history=history_to_send)
        last_parts = history_for_api[-1].get("parts", []) if history_for_api else [user_message]

        result = await with_rate_limit_handling(
            lambda: chat_session.send_message(last_parts)
        )

        if result and hasattr(result, "text"):
            ai_response = cleanup_ai_response(getattr(result, "text"))

            validation = validate_response(ai_response)
            if not validation.valid:
                logging.warning(
                    f"[AI] Response failed validation ({validation.reason}). "
                    "Rolling back user turn and using fallback."
                )
                if (state.conversation_histories[chat_id_str] and
                        state.conversation_histories[chat_id_str][-1]["role"] == "user"):
                    state.conversation_histories[chat_id_str].pop()
                return fallback_message

            state.conversation_histories[chat_id_str].append({
                "role": "model",
                "parts": [ai_response],
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            return ai_response

        # API returned None — roll back user turn
        state.conversation_histories[chat_id_str].pop()
        return fallback_message

    except Exception as e:
        if (state.conversation_histories[chat_id_str] and
                state.conversation_histories[chat_id_str][-1] == user_turn):
            state.conversation_histories[chat_id_str].pop()
        logging.error(f"[AI] Unexpected error in generation: {e}", exc_info=True)
        return fallback_message
