import asyncio
import datetime
import logging

from ai_client import classify_profile_quality, generate_first_message
from config import (
    ACTION_COOLDOWN_SECONDS,
    ANKET_PATTERN,
    BOT_USERNAME,
    KNOWN_SYSTEM_MESSAGES,
)
from utils import get_message_text


async def leomatch_handler(client, message, state):
    """Dispatch messages coming from the dating bot."""
    event_type = "EDITED" if message.edit_date else "NEW"
    logging.info(f"[LEOMATCH-DISPATCHER] Received event (Type: {event_type})")
    text = get_message_text(message)
    if not text:
        logging.info("[LEOMATCH-DISPATCHER] Empty event, ignoring.")
        return

    if ANKET_PATTERN.match(text):
        if state.leomatch_task and not state.leomatch_task.done():
            state.leomatch_task.cancel()
            logging.info(
                "[LEOMATCH-DISPATCHER] New profile arrived. Old task cancelled."
            )
        state.leomatch_task = asyncio.create_task(
            process_leomatch_task(client, message, state)
        )
    else:
        await process_leomatch_message(client, text, state)


async def process_leomatch_task(client, message, state):
    """Background task for handling the profile after cooldown."""
    try:
        time_since_last_action = (
            datetime.datetime.now(datetime.timezone.utc) - state.last_action_time
        ).total_seconds()
        if time_since_last_action < ACTION_COOLDOWN_SECONDS:
            wait_time = ACTION_COOLDOWN_SECONDS - time_since_last_action
            logging.info(
                f"[LEOMATCH-TASK] Cooldown active. Waiting {wait_time:.1f} sec..."
            )
            await asyncio.sleep(wait_time)

        text = get_message_text(message)
        logging.info("[LEOMATCH-TASK] Cooldown over. Processing last profile.")
        await process_leomatch_message(client, text, state)
    except asyncio.CancelledError:
        logging.info(
            "[LEOMATCH-TASK] Task cancelled (fresher profile arrived)."
        )
    except Exception as e:
        logging.error(
            f"[LEOMATCH-TASK] Error in profile processing task: {e}",
            exc_info=True,
        )


async def process_leomatch_message(client, text: str, state, is_startup: bool = False):
    """Execute direct actions in the dating bot."""
    text_str = str(text) if text else ""
    # use a local variable to help inference
    # truncate for logging
    truncated_text = text_str[:120] if len(text_str) > 120 else text_str
    logging.info(f"[LEOMATCH-EXECUTOR] Analyzing text: \"{truncated_text}\"")

    if any(phrase in text for phrase in KNOWN_SYSTEM_MESSAGES):
        logging.info(
            "[LEOMATCH-EXECUTOR] System/ad message detected. Ignoring."
        )
        return

    if "1. View profiles" in text:
        logging.info("[LEOMATCH-EXECUTOR] Main menu. Pressing '1'.")
        await asyncio.sleep(2)
        await client.send_message(BOT_USERNAME, "1")
        return

    match = ANKET_PATTERN.match(text)
    if match:
        state.last_seen_anket_text = text
        logging.info(
            f"[LEOMATCH-EXECUTOR] Profile '{match.group(1).strip()}' saved to memory."
        )
        description = (match.group(4) or "").strip()

        if description:
            should_like = await classify_profile_quality(description, state)
        else:
            should_like = False
            logging.info("[LEOMATCH-EXECUTOR] No description. Disliking.")

        if should_like:
            logging.info("[LEOMATCH-EXECUTOR] Profile approved. Liking...")
            await asyncio.sleep(3)
            await client.send_message(BOT_USERNAME, "💌 / 📹")
        else:
            logging.info("[LEOMATCH-EXECUTOR] Profile rejected. Disliking...")
            await asyncio.sleep(3)
            await client.send_message(BOT_USERNAME, "👎")

        state.last_action_time = datetime.datetime.now(datetime.timezone.utc)
        logging.info(
            f"[LEOMATCH-EXECUTOR] Cooldown for {ACTION_COOLDOWN_SECONDS}s started."
        )
        return

    if "Write a message for this user" in text:
        if state.last_seen_anket_text:
            logging.info("[LEOMATCH-EXECUTOR] Message request. Generating...")
            intro_message = await generate_first_message(state.last_seen_anket_text, state)
            if len(intro_message) > 300:
                logging.warning(
                    f"[LEOMATCH-EXECUTOR] AI message too long ({len(intro_message)} chars). "
                    "Using fallback."
                )
                intro_message = (
                    "your profile caught my eye, but my brain is on strike today) "
                    "tell me something about yourself that's not in the profile"
                )
            try:
                await asyncio.sleep(5)
                await client.send_message(BOT_USERNAME, intro_message)

                # Store opener AFTER confirmed send (fixes ISSUE-17)
                state.sent_openers.append({
                    "text": intro_message,
                    "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
                state.sent_openers = state.sent_openers[-5:]
                state.last_seen_anket_text = None
                logging.info("[LEOMATCH-EXECUTOR] Opener sent and stored. Memory cleared.")
            except Exception as e:
                logging.error(f"[LEOMATCH-EXECUTOR] Failed to send opener: {e}")
        else:
            logging.warning(
                "[LEOMATCH-EXECUTOR] Write message request but no profile in memory. "
                "Ignoring."
            )
        return

    if not is_startup:
        logging.warning(f"[LEOMATCH-EXECUTOR] Unrecognized text: '{text}'")
