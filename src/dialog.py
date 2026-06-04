import asyncio
import datetime
import random

from ai_client import generate_conversation_response
from input_sanitizer import sanitize_user_input
from settings import (
    GRACE_PERIOD_SECONDS,
    MIN_REPLY_INTERVAL_SEC,
    TYPING_SPEED_CPS,
    compute_reply_delay,
)
from logging_setup import BotLogger, redact
from meeting_detector import detect_meeting_signal
from stats import record_event
from storage import save_histories
from utils import get_message_text

# Module-level logger for dispatcher events (no chat_id yet)
_log = BotLogger("DIALOG")


async def _persist_histories(state):
    """Persist conversation histories off the event loop."""
    await asyncio.to_thread(save_histories, state)


async def private_chat_handler(client, message, state, adapter):
    """
    Dispatch incoming private messages.
    Extracts all needed data from the message object immediately — before the
    closure is created — so process_dialogue_task never holds a stale reference
    to a Pyrogram message object across a multi-hour delay.
    """
    chat_id = message.chat.id
    user_name = message.from_user.first_name if message.from_user else "Unknown"

    if chat_id in state.whitelist_ids:
        _log.info(f"User (ID: {chat_id}) is in whitelist. Ignoring.", chat_id=chat_id)
        return

    await adapter.mark_read(chat_id)
    _log.info(f"Message from user {chat_id} marked as read.", chat_id=chat_id)

    # Accumulate message text for burst detection
    text = get_message_text(message)
    if text:
        if chat_id not in state.message_buffers:
            state.message_buffers[chat_id] = []
        state.message_buffers[chat_id].append(text)

    if chat_id in state.active_dialogue_tasks:
        state.active_dialogue_tasks[chat_id].cancel()
        _log.info(f"User {chat_id} wrote again. Timer restarted.", chat_id=chat_id)

    # Pass scalar values only — no reference to the Pyrogram message object
    task = asyncio.create_task(
        process_dialogue_task(client, chat_id, user_name, state, adapter)
    )
    state.active_dialogue_tasks[chat_id] = task


async def process_dialogue_task(client, chat_id: int, user_name: str, state, adapter):
    """
    Background task for a full reply cycle.
    Accepts chat_id and user_name as plain scalars — not a Pyrogram message
    object — so there is no lifetime risk during long delays.
    """
    # Scoped logger: every log line from this task carries chat_id automatically
    log = BotLogger("DIALOG", chat_id=chat_id)

    try:
        log.info(f"Waiting {GRACE_PERIOD_SECONDS}s in case user is still typing...")
        await asyncio.sleep(GRACE_PERIOD_SECONDS)

        # Collect all messages buffered during the grace period
        buffered = state.message_buffers.pop(chat_id, [])
        if buffered:
            user_message = "\n".join(buffered)
            if len(buffered) > 1:
                log.info(f"Combined {len(buffered)} buffered messages.")
        else:
            # Buffer was empty — message had no text (e.g. media with no caption)
            log.warning("No buffered messages. Cancelling.")
            return

        # Sanitize at the dispatch boundary
        user_message = sanitize_user_input(user_message)
        if not user_message:
            log.warning("Message was empty after sanitization.")
            return

        # Meeting signal detection
        if detect_meeting_signal(user_message):
            log.info("🎯 Meeting signal detected!")
            state.meeting_signals_detected.add(chat_id)
            record_event("meeting_signal", {"chat_id": chat_id, "user_name": user_name})
            await adapter.notify_operator(
                f"🎯 MEETING SUGGESTED\n\n"
                f"User: {user_name} (ID: {chat_id})\n"
                f"Message: \"{user_message[:300]}\"\n\n"
                f"➡️ Add ID {chat_id} to whitelist.json, then:\n"
                f"   kill -HUP <pid>   (to take over without restart)"
            )

        # Natural reply delay based on gap since last message
        chat_id_str = str(chat_id)
        gap_seconds = 0.0
        if (chat_id_str in state.conversation_histories and
                state.conversation_histories[chat_id_str]):
            last_ts_str = state.conversation_histories[chat_id_str][-1].get("timestamp")
            if last_ts_str:
                try:
                    last_ts = datetime.datetime.fromisoformat(last_ts_str)
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=datetime.timezone.utc)
                    gap_seconds = (
                        datetime.datetime.now(datetime.timezone.utc) - last_ts
                    ).total_seconds()
                except ValueError:
                    pass

        delay = compute_reply_delay(gap_seconds)
        log.info(
            f"Reply in ~{delay // 60}m {delay % 60}s (gap: {gap_seconds:.0f}s)."
        )
        await asyncio.sleep(delay)

        # Per-user rate limit
        last_reply = state.last_reply_times.get(chat_id)
        if last_reply:
            elapsed = (
                datetime.datetime.now(datetime.timezone.utc) - last_reply
            ).total_seconds()
            if elapsed < MIN_REPLY_INTERVAL_SEC:
                log.info(
                    f"Rate limiting: only {elapsed:.0f}s since last reply "
                    f"(min: {MIN_REPLY_INTERVAL_SEC}s). Skipping."
                )
                return

        log.info("Generating reply...")

        if not state.conversation_histories.get(chat_id_str):
            record_event("conversation_started", {"chat_id": chat_id})

        ai_response = await generate_conversation_response(chat_id, user_message, state)
        asyncio.create_task(_persist_histories(state))

        if not ai_response or not ai_response.strip():
            log.warning("Empty AI response. Skipping send.")
            await adapter.notify_operator(
                f"⚠️ API failure for {user_name} (ID: {chat_id}). Fallback message sent."
            )
            return

        if "|||" in ai_response:
            log.info("Sending in ladder mode.")
            parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
            if not parts:
                log.warning("Ladder split produced no parts. Skipping send.")
                return
            for part in parts:
                typing_delay = (len(part) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
                await adapter.show_typing(chat_id)
                log.info(
                    f"Simulating typing {typing_delay:.1f}s "
                    f"(part length: {len(part)} chars)"
                )
                await asyncio.sleep(typing_delay)
                sent = await adapter.send_reply(chat_id, part)
                if not sent:
                    await adapter.notify_operator(
                        f"⚠️ Failed to deliver message to {user_name} (ID: {chat_id}) "
                        "after 3 FloodWait retries."
                    )
        else:
            typing_delay = (len(ai_response) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
            await adapter.show_typing(chat_id)
            log.info(
                f"Simulating typing {typing_delay:.1f}s "
                f"(message length: {len(ai_response)} chars)"
            )
            await asyncio.sleep(typing_delay)
            sent = await adapter.send_reply(chat_id, ai_response)
            if not sent:
                await adapter.notify_operator(
                    f"⚠️ Failed to deliver message to {user_name} (ID: {chat_id}) "
                    "after 3 FloodWait retries."
                )

        state.last_reply_times[chat_id] = datetime.datetime.now(datetime.timezone.utc)
        record_event("reply_sent", {"chat_id": chat_id, "ladder": "|||" in ai_response})
        log.info("Full reply sent.")
    except asyncio.CancelledError:
        _log.info(f"Task for user {chat_id} cancelled.", chat_id=chat_id)
    except Exception as e:
        _log.error(
            f"Error in dialogue task for user {chat_id}: {e}", chat_id=chat_id
        )
        import traceback
        _log.error(traceback.format_exc())
    finally:
        state.active_dialogue_tasks.pop(chat_id, None)
        state.message_buffers.pop(chat_id, None)
