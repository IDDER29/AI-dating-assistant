import asyncio
import datetime
import logging
import random

from pyrogram import enums

from ai_client import generate_conversation_response
from config import (
    GRACE_PERIOD_SECONDS,
    REPLY_DELAY_CONFIG,
    SESSION_TIMEOUT_MINUTES,
    TYPING_SPEED_CPS,
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

        chat_id_str = str(chat_id)
        is_new_session = True
        if chat_id_str in state.conversation_histories and state.conversation_histories[chat_id_str]:
            last_msg_timestamp_str = state.conversation_histories[chat_id_str][-1].get(
                "timestamp"
            )
            if last_msg_timestamp_str:
                last_msg_time = datetime.datetime.fromisoformat(last_msg_timestamp_str)
                time_since_last_msg = (
                    datetime.datetime.now(datetime.timezone.utc) - last_msg_time
                ).total_seconds()
                if time_since_last_msg < SESSION_TIMEOUT_MINUTES * 60:
                    is_new_session = False

        delay_config = REPLY_DELAY_CONFIG["active_session"]
        mode = "active_session"
        if is_new_session:
            logging.info(f"[DIALOG] Detected NEW session with {user_name}.")
            rand = random.random()
            config_new = REPLY_DELAY_CONFIG["new_session"]
            if rand < config_new["long"]["chance"]:
                mode = "long"
                delay_config = config_new["long"]
            elif rand < config_new["long"]["chance"] + config_new["medium"]["chance"]:
                mode = "medium"
                delay_config = config_new["medium"]
            else:
                mode = "fast"
                delay_config = config_new["fast"]
        else:
            logging.info(f"[DIALOG] Continuing ACTIVE session with {user_name}.")

        delay = random.randint(delay_config["min_sec"], delay_config["max_sec"])
        logging.info(
            f"[DIALOG] Reply for {user_name} will be sent in ~{delay // 60}m "
            f"{delay % 60}s (mode: {mode})."
        )
        await asyncio.sleep(delay)

        logging.info(f"[DIALOG] Time is up. Generating reply for {user_name}...")
        user_message = get_message_text(message)
        if not user_message:
            logging.warning(
                f"[DIALOG] Last message from {user_name} has no text. Cancelling."
            )
            return

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
