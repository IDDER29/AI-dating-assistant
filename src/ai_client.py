from __future__ import annotations

import asyncio
import datetime
import logging
import re

from google import genai
from google.genai import types, errors as genai_errors

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


# ── Token estimation ──────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token count: CHARS_PER_TOKEN_ESTIMATE chars/token (conservative for Ru/En)."""
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


def _estimate_history_tokens(history: list) -> int:
    """Estimate total tokens across a conversation history list."""
    total = 0
    for turn in history:
        for part in turn.get("parts", []):
            total += _estimate_tokens(str(part))
    return total


# ── SDK helpers ───────────────────────────────────────────────────────────────

def _to_sdk_contents(history_dicts: list) -> list[types.Content]:
    """
    Convert our internal history format (list of dicts with role/parts/timestamp)
    to the google-genai SDK's Content objects.
    Roles are identical: 'user' and 'model'.
    """
    contents = []
    for turn in history_dicts:
        role = turn["role"]
        parts = [types.Part(text=str(p)) for p in turn.get("parts", []) if p]
        if parts:
            contents.append(types.Content(role=role, parts=parts))
    return contents


def _record_api_call(result, call_type: str, chat_id_str: str = ""):
    """
    Read token usage from a Gemini response and record to stats.
    Safe to call with result=None (records a failed call).
    usage_metadata field names are the same in google-genai as in google-generativeai.
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


# ── Initialisation ────────────────────────────────────────────────────────────

def initialize_ai(state):
    """
    Create a google-genai Client and set the active model name.
    Validates connectivity by calling client.models.get() for each
    candidate model name; falls back to the latest-alias if the pinned
    version is unavailable.
    """
    try:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logging.error(f"[AI] Failed to create Gemini client: {e}")
        state.ai_client = None
        state.active_model_name = None
        return

    for model_name in [GEMINI_PRIMARY_MODEL, GEMINI_FALLBACK_MODEL]:
        try:
            # Lightweight sync call to verify the model is accessible
            ai_client.models.get(model=model_name)
            state.ai_client = ai_client
            state.active_model_name = model_name
            logging.info(f"[AI] Gemini model validated and ready: {model_name}")
            if model_name == GEMINI_FALLBACK_MODEL:
                logging.warning(
                    f"[AI] Using fallback model '{model_name}' — primary model "
                    f"'{GEMINI_PRIMARY_MODEL}' unavailable. "
                    "Update GEMINI_PRIMARY_MODEL in settings.py."
                )
            return
        except genai_errors.ClientError as e:
            logging.warning(
                f"[AI] Model '{model_name}' not accessible (HTTP {e.code}). "
                "Trying next candidate..."
            )
        except Exception as e:
            logging.warning(
                f"[AI] Could not validate model '{model_name}': {e}. "
                "Trying next candidate..."
            )

    # Both candidates failed validation — set client anyway so the error
    # is surfaced clearly on the first API call rather than with a None-guard.
    state.ai_client = ai_client
    state.active_model_name = GEMINI_PRIMARY_MODEL
    logging.error(
        "[AI] Could not validate any Gemini model. "
        "Check GEMINI_API_KEY and model availability. "
        "The bot will attempt to run but API calls may fail."
    )


# ── Response cleanup ──────────────────────────────────────────────────────────

def cleanup_ai_response(text: str) -> str:
    """Normalise AI output: strip dashes, trailing punctuation, extra whitespace."""
    cleaned = text.replace("–", " ").replace("—", " ")
    cleaned = cleaned.strip().rstrip(".?!")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace(" ,", ",")
    return cleaned.strip()


# ── Retry wrapper ─────────────────────────────────────────────────────────────

async def with_api_retry(api_call_fn, timeout_sec: float = 30.0):
    """
    Execute an async Gemini API call with timeout and retry.

    api_call_fn must be a zero-argument callable that returns a coroutine,
    e.g.  lambda: client.aio.models.generate_content(...)

    Retry policy:
    - asyncio.TimeoutError          → retry up to 3 times (10s gap)
    - ClientError HTTP 429          → retry up to 3 times (60s gap)
    - ServerError (5xx)             → retry up to 3 times (15s gap)
    - ClientError 404 / 403         → no retry, return None immediately
    - Other ClientError             → no retry, return None immediately
    """
    for attempt in range(1, 4):
        try:
            return await asyncio.wait_for(api_call_fn(), timeout=timeout_sec)

        except asyncio.TimeoutError:
            logging.warning(
                f"[AI] API call timed out after {timeout_sec}s "
                f"(attempt {attempt}/3). Retrying in 10s..."
            )
            await asyncio.sleep(10)

        except genai_errors.ClientError as e:
            if e.code == 429:
                logging.warning(
                    f"[AI] Rate limit (429). Retrying in 60s "
                    f"(attempt {attempt}/3)..."
                )
                await asyncio.sleep(60)
            elif e.code == 404:
                logging.error(
                    f"[AI] Model not found (404): {e.message}. "
                    "Update GEMINI_PRIMARY_MODEL in settings.py."
                )
                record_event("api_error", {
                    "reason": "model_not_found",
                    "error": str(e.message)[:100],
                })
                return None
            elif e.code == 403:
                logging.error(
                    f"[AI] Permission denied (403): {e.message}. "
                    "Check that GEMINI_API_KEY is valid and not revoked."
                )
                record_event("api_error", {
                    "reason": "permission_denied",
                    "error": str(e.message)[:100],
                })
                return None
            else:
                logging.error(
                    f"[AI] Client error (HTTP {e.code}): {e.message}. "
                    "Not retrying."
                )
                record_event("api_error", {
                    "reason": f"client_error_{e.code}",
                    "error": str(e.message)[:100],
                })
                return None

        except genai_errors.ServerError as e:
            logging.warning(
                f"[AI] Server error (HTTP {e.code}) (attempt {attempt}/3). "
                "Retrying in 15s..."
            )
            await asyncio.sleep(15)

    logging.error("[AI] Failed to execute API request after 3 attempts.")
    record_event("api_error", {"reason": "all_retries_exhausted"})
    return None


# ── Generation functions ──────────────────────────────────────────────────────

async def generate_first_message(anket_text: str, state) -> str:
    """Generate the opening message for a new profile."""
    fallback_message = "your profile seemed very interesting, shall we chat?"
    if not state.ai_client:
        return fallback_message

    match = ANKET_PATTERN.match(anket_text)
    profile_text = match.group(4).strip() if match and match.group(4) else ""
    if len(profile_text) < 15:
        profile_text = "Profile description is short or meaningless"

    prompt = FIRST_MESSAGE_PROMPT.format(profile_text=profile_text)
    result = await with_api_retry(
        lambda: state.ai_client.aio.models.generate_content(
            model=state.active_model_name,
            contents=prompt,
        )
    )
    _record_api_call(result, "first_message")

    if result and hasattr(result, "text") and result.text:
        return cleanup_ai_response(result.text)
    return fallback_message


async def classify_profile_quality(description: str, state) -> bool:
    """
    Return True if the profile description is worth sending an opener to.
    Falls back to character-count heuristic if the AI client is unavailable.
    """
    if not state.ai_client:
        return len(description.strip()) > 10

    prompt = (
        f'Dating profile description: "{description}"\n\n'
        "Is this profile worth sending a first message to?\n"
        "Consider: genuine personality, conversation hooks, real effort.\n"
        "Ignore: blank, bot-like, purely transactional, or copy-paste profiles.\n"
        "Answer with only YES or NO."
    )
    result = await with_api_retry(
        lambda: state.ai_client.aio.models.generate_content(
            model=state.active_model_name,
            contents=prompt,
        )
    )
    _record_api_call(result, "profile_classify")

    if result and hasattr(result, "text") and result.text:
        decision = result.text.strip().upper().startswith("YES")
        logging.info(
            f"[AI] Profile classification ({len(description)} chars) → "
            f"{'LIKE' if decision else 'DISLIKE'}"
        )
        return decision

    return len(description.strip()) > 10


async def _update_memory(chat_id_str: str, recent_turns: list, state):
    """Extract and persist key facts from recent conversation turns."""
    if not state.ai_client:
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
    result = await with_api_retry(
        lambda: state.ai_client.aio.models.generate_content(
            model=state.active_model_name,
            contents=prompt,
        )
    )
    _record_api_call(result, "memory_update", chat_id_str)

    if result and hasattr(result, "text") and result.text:
        updated = result.text.strip()
        if updated:
            state.conversation_memories[chat_id_str] = updated
            asyncio.create_task(asyncio.to_thread(save_memories, state))
            logging.info(
                f"[AI] Memory updated for user {chat_id_str} ({len(updated)} chars)."
            )


async def generate_conversation_response(chat_id: int, user_message: str, state) -> str:
    """Generate a contextual reply in an existing conversation."""
    fallback_message = "hm, something went wrong, repeat that"
    if not state.ai_client:
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

    # Trim by estimated token budget; keep at least 4 turns for coherence
    history = state.conversation_histories[chat_id_str]
    while len(history) > 4 and _estimate_history_tokens(history) > MAX_CONTEXT_TOKENS:
        history.pop(0)
    if len(history) > MAX_HISTORY_LENGTH:
        state.conversation_histories[chat_id_str] = history[-MAX_HISTORY_LENGTH:]

    try:
        history_for_api = [
            {"role": str(msg["role"]), "parts": list(msg["parts"])}
            for msg in state.conversation_histories[chat_id_str]
        ]

        # Inject persistent memory into first turn (API copy only — not stored history)
        memory = state.conversation_memories.get(chat_id_str, "")
        if memory and history_for_api:
            history_for_api = list(history_for_api)
            if history_for_api[0]["role"] == "user":
                first_turn = dict(history_for_api[0])
                first_turn["parts"] = [
                    f"[About this person: {memory}]\n\n{first_turn['parts'][0]}"
                ]
                history_for_api[0] = first_turn

        # Convert to SDK Content objects and call generate_content with full history.
        # system_instruction is applied via GenerateContentConfig on every call.
        sdk_contents = _to_sdk_contents(history_for_api)
        config = types.GenerateContentConfig(
            system_instruction=CONVERSATION_SYSTEM_PROMPT,
        )

        result = await with_api_retry(
            lambda: state.ai_client.aio.models.generate_content(
                model=state.active_model_name,
                contents=sdk_contents,
                config=config,
            )
        )
        _record_api_call(result, "conversation", chat_id_str)

        if result and hasattr(result, "text") and result.text:
            ai_response = cleanup_ai_response(result.text)

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

            # Warn if context is growing large
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
