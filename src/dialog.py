import asyncio
import datetime
import logging
import random

from pyrogram import enums

from ai_client import generate_conversation_response
from config import (
    GRACE_PERIOD_SECONDS,
    TYPING_SPEED_CPS,
    compute_reply_delay,
)
from storage import save_histories
from utils import get_message_text


async def _persist_histories(state):
    """Persist conversation histories off the event loop."""
    await asyncio.to_thread(save_histories, state)


async def private_chat_handler(client, message, state):
    """Dispatch incoming private messages."""
    chat_id = message.chat.id

    if chat_id in state.whitelist_ids:
        logging.info(
            f"[DISPATCHER] User {message.from_user.first_name} (ID: {chat_id}) "
            "is in whitelist. Ignoring."
        )
        return

    await client.read_chat_history(chat_id)
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

    task = asyncio.create_task(process_dialogue_task(client, message, state))
    state.active_dialogue_tasks[chat_id] = task


async def process_dialogue_task(client, message, state):
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

        logging.info(f"[DIALOG] Time is up. Generating reply for {user_name}...")

        ai_response = await generate_conversation_response(chat_id, user_message, state)
        asyncio.create_task(_persist_histories(state))

        if not ai_response or not ai_response.strip():
            logging.warning(
                f"[DIALOG] Received empty AI response for {user_name}. Skipping send."
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
                await client.send_chat_action(chat_id, enums.ChatAction.TYPING)
                logging.info(
                    f"[DIALOG] Simulating typing {typing_delay:.1f}s for part: '{part}'"
                )
                await asyncio.sleep(typing_delay)
                await client.send_message(chat_id, part)
        else:
            typing_delay = (len(ai_response) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
            await client.send_chat_action(chat_id, enums.ChatAction.TYPING)
            logging.info(
                f"[DIALOG] Simulating typing {typing_delay:.1f}s for message: '{ai_response}'"
            )
            await asyncio.sleep(typing_delay)
            await client.send_message(chat_id, ai_response)

        logging.info(f"[DIALOG] Full reply for {user_name} sent.")
    except asyncio.CancelledError:
        logging.info(f"[DISPATCHER] Task for chat with {user_name} cancelled.")
    except Exception as e:
        logging.error(f"[DIALOG] Error in dialogue processing task: {e}", exc_info=True)
    finally:
        state.active_dialogue_tasks.pop(chat_id, None)
        state.message_buffers.pop(chat_id, None)
