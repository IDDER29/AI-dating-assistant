import asyncio
import datetime
import logging
from functools import partial

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, EditedMessageHandler

from ai_client import initialize_ai
from credentials import API_ID, API_HASH, GEMINI_API_KEY
from settings import (
    BOT_USERNAME,
    HEARTBEAT_INTERVAL_HOURS,
    MAX_CONVERSATION_AGE_DAYS,
    SESSION_NAME,
)
from dialog import private_chat_handler
from leomatch import leomatch_handler, process_leomatch_message
from logging_setup import setup_logging
from operator_notify import operator_notify
from state import BotState
from storage import load_histories, load_memories, load_whitelist, prune_stale_histories, save_histories
from telegram_adapter import TelegramAdapter
from utils import get_message_text

_STATE = None


def get_state():
    return _STATE


def initialize_app(state):
    """Validate configuration and initialize Pyrogram client."""
    if not all([API_ID, API_HASH, GEMINI_API_KEY]):
        logging.critical(
            "CRITICAL ERROR: Missing environment variables TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH, or GEMINI_API_KEY. Check your .env file."
        )
        raise SystemExit(1)
    state.app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)
    return state.app


async def _heartbeat(app_client, state):
    """Send a periodic status message to operator's Saved Messages."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_HOURS * 3600)
        active_count = len(state.active_dialogue_tasks)
        uptime = datetime.datetime.now(datetime.timezone.utc) - state.start_time
        uptime_hours = int(uptime.total_seconds() // 3600)
        uptime_mins = int((uptime.total_seconds() % 3600) // 60)
        history_count = len(state.conversation_histories)
        meeting_count = len(getattr(state, "meeting_signals_detected", set()))

        model_name = getattr(state, "active_model_name", "unknown")
        from stats import get_api_stats_summary
        api_stats = get_api_stats_summary(hours=HEARTBEAT_INTERVAL_HOURS)

        await operator_notify(
            app_client,
            f"✅ Bot alive\n"
            f"Uptime: {uptime_hours}h {uptime_mins}m\n"
            f"Model: {model_name}\n"
            f"Active conversations: {active_count}\n"
            f"Total conversations: {history_count}\n"
            f"Meetings detected (session): {meeting_count}\n"
            f"API calls (last {HEARTBEAT_INTERVAL_HOURS}h): {api_stats['calls']} "
            f"({api_stats['failures']} failed, ~{api_stats['total_tokens']:,} tokens)"
        )


async def run():
    """Initialize and run the bot application."""
    global _STATE
    setup_logging()

    state = BotState()
    _STATE = state

    initialize_ai(state)
    initialize_app(state)
    if not state.model or not state.app:
        logging.critical("Application cannot start due to initialization error.")
        return

    load_histories(state)
    pruned = prune_stale_histories(state, MAX_CONVERSATION_AGE_DAYS)
    if pruned > 0:
        save_histories(state)
    load_memories(state)
    load_whitelist(state)

    async with state.app:
        adapter = TelegramAdapter(state.app, BOT_USERNAME)

        try:
            bot_peer = await adapter.resolve_peer(BOT_USERNAME)
        except Exception as e:
            logging.critical(f"Could not find bot @{BOT_USERNAME}: {e}")
            return

        logging.info("=" * 50)
        logging.info("AI Dating Assistant (v37.0 'Stable Launch') started!")
        logging.info("=" * 50)

        leomatch_cb = partial(leomatch_handler, state=state, adapter=adapter)
        private_cb = partial(private_chat_handler, state=state, adapter=adapter)

        state.app.add_handler(
            MessageHandler(
                leomatch_cb,
                filters.private & filters.chat(BOT_USERNAME) & ~filters.me,
            )
        )
        state.app.add_handler(
            EditedMessageHandler(
                leomatch_cb,
                filters.private & filters.chat(BOT_USERNAME) & ~filters.me,
            )
        )
        logging.info(f"[SYSTEM] Handler for @{BOT_USERNAME} registered.")

        state.app.add_handler(
            MessageHandler(
                private_cb,
                filters.private & ~filters.chat(BOT_USERNAME) & ~filters.me,
            )
        )
        logging.info("[SYSTEM] Handler for private dialogues registered.")

        await adapter.notify_operator(
            f"🚀 Bot started\n"
            f"Conversations loaded: {len(state.conversation_histories)}\n"
            f"Whitelist entries: {len(state.whitelist_ids)}"
        )

        logging.info(f"[SYSTEM] Analyzing last message from @{BOT_USERNAME}...")
        last_message = await adapter.get_last_bot_message()
        if last_message and (text := get_message_text(last_message)):
            await process_leomatch_message(state.app, text, state, adapter=adapter, is_startup=True)
        else:
            logging.info(f"[{BOT_USERNAME.upper()}] Chat is empty. Sending start command.")
            await adapter.navigate_to_profiles()

        asyncio.create_task(_heartbeat(state.app, state))
        logging.info(
            f"[SYSTEM] Startup complete. Bot is running. "
            f"Heartbeat every {HEARTBEAT_INTERVAL_HOURS}h."
        )
        await asyncio.Event().wait()
