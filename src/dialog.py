import asyncio
import datetime
import logging
import random

from ai_client import generate_conversation_response
from settings import (
    GRACE_PERIOD_SECONDS,
    MIN_REPLY_INTERVAL_SEC,
    TYPING_SPEED_CPS,
    compute_reply_delay,
)
from meeting_detector import detect_meeting_signal
from operator_notify import operator_notify
from stats import record_event
from storage import save_histories
from utils import get_message_text


async def _persist_histories(state):
    """Persist conversation histories off the event loop."""
    await asyncio.to_thread(save_histories, state)


async def private_chat_handler(client, message, state, adapter):
    """Dispatch incoming private messages."""
    chat_id = message.chat.id

    if chat_id in state.whitelist_ids:
        logging.info(
            f"[DISPATCHER] User {message.from_user.first_name} (ID: {chat_id}) "
            "is in whitelist. Ignoring."
        )
        return

    await adapter.mark_read(chat_id)
    logging.info(
        f"[DISPATCHER] Message from {message.from_user.first_name} marked as read."
    )

    # Accumulate message text for burst detection
    text = get_message_text(message)
    if text:
        if chat_id not in state.message_buffers:
            state.message_buffers[chat_id] = []
        state.message_buffers[chat_id].append(text)

    if chat_id in state.active_dialogue_tasks:
        state.active_dialogue_tasks[chat_id].cancel()
        logging.info(
            f"[DISPATCHER] User {message.from_user.first_name} wrote again. "
            "Timer restarted."
        )

    task = asyncio.create_task(process_dialogue_task(client, message, state, adapter))
    state.active_dialogue_tasks[chat_id] = task


async def process_dialogue_task(client, message, state, adapter):
    """Background task for a full reply cycle."""
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    try:
        logging.info(
            f"[DIALOG] Waiting {GRACE_PERIOD_SECONDS} sec. in case {user_name} is typing more..."
        )
        await asyncio.sleep(GRACE_PERIOD_SECONDS)

        # Collect all buffered messages accumulated during the grace period
        buffered = state.message_buffers.pop(chat_id, [])
        if buffered:
            user_message = "\n".join(buffered)
            if len(buffered) > 1:
                logging.info(
                    f"[DIALOG] Combined {len(buffered)} buffered messages for {user_name}."
                )
        else:
            user_message = get_message_text(message)
            if not user_message:
                logging.warning(
                    f"[DIALOG] No message content for {user_name}. Cancelling."
                )
                return

        # Meeting signal detection
        if detect_meeting_signal(user_message):
            logging.info(
                f"[MEETING] 🎯 Meeting signal detected from {user_name} (ID: {chat_id})!"
            )
            state.meeting_signals_detected.add(chat_id)
            record_event("meeting_signal", {"chat_id": chat_id, "user_name": user_name})
            await adapter.notify_operator(
                f"🎯 MEETING SUGGESTED\n\n"
                f"User: {user_name} (ID: {chat_id})\n"
                f"Message: \"{user_message[:300]}\"\n\n"
                f"➡️ Add ID {chat_id} to whitelist.json, then:\n"
                f"   kill -HUP <pid>   (to take over without restart)"
            )

        # Compute natural reply delay based on gap since last message
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
        logging.info(
            f"[DIALOG] Reply for {user_name} in ~{delay // 60}m {delay % 60}s "
            f"(gap: {gap_seconds:.0f}s)."
        )
        await asyncio.sleep(delay)

        # Per-user rate limit: prevent one user from flooding the API
        last_reply = state.last_reply_times.get(chat_id)
        if last_reply:
            elapsed = (
                datetime.datetime.now(datetime.timezone.utc) - last_reply
            ).total_seconds()
            if elapsed < MIN_REPLY_INTERVAL_SEC:
                logging.info(
                    f"[DIALOG] Rate limiting {user_name}: "
                    f"only {elapsed:.0f}s since last reply "
                    f"(min: {MIN_REPLY_INTERVAL_SEC}s). Skipping."
                )
                return

        logging.info(f"[DIALOG] Time is up. Generating reply for {user_name}...")

        # Track new conversations
        if not state.conversation_histories.get(chat_id_str):
            record_event("conversation_started", {"chat_id": chat_id})

        ai_response = await generate_conversation_response(chat_id, user_message, state)
        asyncio.create_task(_persist_histories(state))

        if not ai_response or not ai_response.strip():
            logging.warning(
                f"[DIALOG] Received empty AI response for {user_name}. Skipping send."
            )
            await adapter.notify_operator(
                f"⚠️ API failure for {user_name} (ID: {chat_id}). Fallback message sent."
            )
            return

        if "|||" in ai_response:
            logging.info(f"[DIALOG] Reply for {user_name} will be sent in 'ladder' mode.")
            parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
            if not parts:
                logging.warning(
                    f"[DIALOG] Ladder split produced no parts for {user_name}. Skipping send."
                )
                return
            for part in parts:
                typing_delay = (len(part) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
                await adapter.show_typing(chat_id)
                logging.info(
                    f"[DIALOG] Simulating typing {typing_delay:.1f}s for part: '{part}'"
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
            logging.info(
                f"[DIALOG] Simulating typing {typing_delay:.1f}s for message: '{ai_response}'"
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
        logging.info(f"[DIALOG] Full reply for {user_name} sent.")
    except asyncio.CancelledError:
        logging.info(f"[DISPATCHER] Task for chat with {user_name} cancelled.")
    except Exception as e:
        logging.error(f"[DIALOG] Error in dialogue processing task: {e}", exc_info=True)
    finally:
        state.active_dialogue_tasks.pop(chat_id, None)
        state.message_buffers.pop(chat_id, None)
