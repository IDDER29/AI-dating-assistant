import asyncio
import datetime
import logging
import re

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from credentials import GEMINI_API_KEY
from settings import (
    ANKET_PATTERN,
    CHARS_PER_TOKEN_ESTIMATE,
    CONVERSATION_SYSTEM_PROMPT,
    FIRST_MESSAGE_PROMPT,
    GEMINI_FALLBACK_MODEL,
    GEMINI_PRIMARY_MODEL,
    MAX_CONTEXT_TOKENS,
    MAX_HISTORY_LENGTH,
)
from input_sanitizer import sanitize_user_input
from output_validator import validate_response
from stats import record_event
from storage import save_memories


def _estimate_tokens(text: str) -> int:
    """Rough token count: CHARS_PER_TOKEN_ESTIMATE chars per token (conservative for Ru/En mix)."""
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


def _estimate_history_tokens(history: list) -> int:
    """Estimate total tokens in a conversation history list."""
    total = 0
    for turn in history:
        for part in turn.get("parts", []):
            total += _estimate_tokens(str(part))
    return total


def _record_api_call(result, call_type: str, chat_id_str: str = ""):
    """
    Read token usage metadata from a Gemini API response and record to stats.
    Gemini response objects expose usage_metadata with prompt/response/total token counts.
    Safe to call with result=None (records a failed call).
    """
    if result is None:
        record_event("api_call", {
            "type": call_type,
            "status": "failed",
            "chat_id": chat_id_str,
        })
        return

    metadata = getattr(result, "usage_metadata", None)
    if metadata:
        record_event("api_call", {
            "type": call_type,
            "status": "ok",
            "chat_id": chat_id_str,
            "prompt_tokens": getattr(metadata, "prompt_token_count", 0),
            "response_tokens": getattr(metadata, "candidates_token_count", 0),
            "total_tokens": getattr(metadata, "total_token_count", 0),
        })
    else:
        record_event("api_call", {
            "type": call_type,
            "status": "ok",
            "chat_id": chat_id_str,
        })


def initialize_ai(state):
    """
    Initialize Gemini with the pinned primary model, falling back to the
    latest-alias if the pinned version is unavailable.
    Stores the active model name in state.active_model_name.
    """
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        logging.error(f"[AI] Failed to configure Gemini API key: {e}")
        state.model = None
        return

    for model_name in [GEMINI_PRIMARY_MODEL, GEMINI_FALLBACK_MODEL]:
        try:
            state.model = genai.GenerativeModel(
                model_name,
                system_instruction=CONVERSATION_SYSTEM_PROMPT,
            )
            state.active_model_name = model_name
            logging.info(f"[AI] Gemini model initialized: {model_name}")
            if model_name == GEMINI_FALLBACK_MODEL:
                logging.warning(
                    f"[AI] Using fallback model '{model_name}' — primary model "
                    f"'{GEMINI_PRIMARY_MODEL}' unavailable. Update GEMINI_PRIMARY_MODEL "
                    "in settings.py when a new version is available."
                )
            return
        except Exception as e:
            logging.warning(
                f"[AI] Could not initialize model '{model_name}': {e}. "
                "Trying next candidate..."
            )

    logging.error(
        "[AI] All Gemini model candidates failed to initialize. "
        "Check GEMINI_API_KEY and model availability."
    )
    state.model = None
    state.active_model_name = None


def cleanup_ai_response(text: str) -> str:
    """Clean AI output from unwanted punctuation and whitespace."""
    cleaned_text = text.replace("–", " ").replace("—", " ")
    cleaned_text = cleaned_text.strip().rstrip(".?!")
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)
    cleaned_text = cleaned_text.replace(" ,", ",")
    return cleaned_text.strip()


async def with_rate_limit_handling(api_call, timeout_sec: float = 30.0):
    """
    Execute a synchronous Gemini API call with:
    - asyncio.to_thread (non-blocking)
    - 30s timeout per attempt
    - Up to 3 retries for transient errors:
        ResourceExhausted (429), ServiceUnavailable (503),
        DeadlineExceeded (504), InternalServerError (500), TimeoutError
    - Single attempt then None for permanent errors:
        NotFound (model deprecated), PermissionDenied (bad key)
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

        except google_exceptions.NotFound as e:
            logging.error(
                f"[AI] Model not found: {e}. "
                "The model version may be deprecated. "
                "Update GEMINI_PRIMARY_MODEL in settings.py."
            )
            record_event("api_error", {"reason": "model_not_found", "error": str(e)[:100]})
            return None

        except google_exceptions.PermissionDenied as e:
            logging.error(
                f"[AI] Permission denied: {e}. "
                "Check that GEMINI_API_KEY is valid and not revoked."
            )
            record_event("api_error", {"reason": "permission_denied", "error": str(e)[:100]})
            return None

    logging.error("[AI] Failed to execute API request after 3 attempts.")
    record_event("api_error", {"reason": "all_retries_exhausted"})
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
    _record_api_call(result, "first_message")

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
    _record_api_call(result, "profile_classify")
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
    _record_api_call(result, "memory_update", chat_id_str)
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

    # Trim by estimated token budget first, keeping at least 4 turns for coherence.
    history = state.conversation_histories[chat_id_str]
    while len(history) > 4 and _estimate_history_tokens(history) > MAX_CONTEXT_TOKENS:
        history.pop(0)
    # Hard fallback: also cap by turn count to bound API payload size.
    if len(history) > MAX_HISTORY_LENGTH:
        state.conversation_histories[chat_id_str] = history[-MAX_HISTORY_LENGTH:]

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
        _record_api_call(result, "conversation", chat_id_str)

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

            # Warn if context is getting large
            estimated = _estimate_history_tokens(turns)
            if estimated > MAX_CONTEXT_TOKENS * 0.8:
                logging.warning(
                    f"[AI] Context token estimate for {chat_id} is high: "
                    f"~{estimated} tokens (budget: {MAX_CONTEXT_TOKENS})"
                )

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
