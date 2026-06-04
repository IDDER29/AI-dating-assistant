import asyncio
import datetime
import logging
import re

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from credentials import GEMINI_API_KEY
from settings import (
    ANKET_PATTERN,
    CONVERSATION_SYSTEM_PROMPT,
    FIRST_MESSAGE_PROMPT,
    MAX_HISTORY_LENGTH,
)
from input_sanitizer import sanitize_user_input
from output_validator import validate_response
from storage import save_memories


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


async def classify_profile_quality(description: str, state) -> bool:
    """
    Returns True if the profile description is worth messaging.
    Falls back to character-count logic if AI is unavailable.
    """
    if not state.model:
        return len(description.strip()) > 10

    prompt = (
        f'Dating profile description: "{description}"\n\n'
        "Is this profile worth sending a first message to?\n"
        "Consider: genuine personality, conversation hooks, real effort.\n"
        "Ignore: blank, bot-like, purely transactional, or copy-paste profiles.\n"
        "Answer with only YES or NO."
    )
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
    if result and hasattr(result, "text"):
        answer = result.text.strip().upper()
        decision = answer.startswith("YES")
        logging.info(
            f"[AI] Profile classification ({len(description)} chars) → "
            f"{'LIKE' if decision else 'DISLIKE'}"
        )
        return decision

    return len(description.strip()) > 10


async def _update_memory(chat_id_str: str, recent_turns: list, state):
    """Extract and store key facts from recent turns into persistent memory."""
    if not state.model:
        return
    existing = state.conversation_memories.get(chat_id_str, "")
    turns_text = "\n".join(
        f"{t['role'].upper()}: {t['parts'][0]}" for t in recent_turns
    )
    prompt = (
        f"Existing notes about this person: {existing}\n\n"
        f"Recent conversation:\n{turns_text}\n\n"
        "Update the notes with any NEW key facts about the user "
        "(their name, job, hobbies, stated preferences, important things they mentioned). "
        "Be extremely concise — maximum 2 sentences. Facts only, no analysis. "
        "If nothing new is mentioned, return the existing notes unchanged."
    )
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
    if result and hasattr(result, "text"):
        updated = result.text.strip()
        if updated:
            state.conversation_memories[chat_id_str] = updated
            asyncio.create_task(asyncio.to_thread(save_memories, state))
            logging.info(
                f"[AI] Memory updated for user {chat_id_str} ({len(updated)} chars)."
            )


async def generate_conversation_response(chat_id: int, user_message: str, state) -> str:
    """Generate a contextual reply in an existing dialog."""
    fallback_message = "hm, something went wrong, repeat that"
    if not state.model:
        return fallback_message

    # Sanitize before any history manipulation
    user_message = sanitize_user_input(user_message)
    if not user_message:
        return fallback_message

    chat_id_str = str(chat_id)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Inject the most recent opener as first model turn for brand-new conversations
    if chat_id_str not in state.conversation_histories or \
            not state.conversation_histories[chat_id_str]:
        if state.sent_openers:
            oldest_opener = state.sent_openers.pop(0)
            state.conversation_histories[chat_id_str] = [{
                "role": "model",
                "parts": [oldest_opener["text"]],
                "timestamp": oldest_opener["sent_at"],
            }]
            logging.info(
                f"[AI] Injected sent opener as first model turn for user {chat_id}."
            )
        else:
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

        # Inject persistent memory into first turn (API copy only, not stored history)
        memory = state.conversation_memories.get(chat_id_str, "")
        if memory and history_for_api:
            history_for_api = list(history_for_api)
            if history_for_api[0]["role"] == "user":
                first_turn = dict(history_for_api[0])
                first_turn["parts"] = [
                    f"[About this person: {memory}]\n\n{first_turn['parts'][0]}"
                ]
                history_for_api[0] = first_turn

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

            # Update persistent memory every 4 turns
            turns = state.conversation_histories[chat_id_str]
            if len(turns) % 4 == 0 and len(turns) >= 4:
                asyncio.create_task(_update_memory(chat_id_str, turns[-4:], state))

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
