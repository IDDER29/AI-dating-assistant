import asyncio
import logging
from functools import partial

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, EditedMessageHandler

from ai_client import initialize_ai
from config import API_ID, API_HASH, BOT_USERNAME, GEMINI_API_KEY, SESSION_NAME
from dialog import private_chat_handler
from leomatch import leomatch_handler, process_leomatch_message
from logging_setup import setup_logging
from state import BotState
from storage import load_histories, load_whitelist
from utils import get_message_text

_STATE = None


def get_state():
    return _STATE


def initialize_app(state):
    """Validate configuration and initialize Pyrogram client."""
    if not all([API_ID, API_HASH, GEMINI_API_KEY]):
        logging.critical(
            "КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные окружения TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH или GEMINI_API_KEY. Проверьте ваш .env файл."
        )
        raise SystemExit(1)
    state.app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)
    return state.app


async def run():
    """Initialize and run the bot application."""
    global _STATE
    setup_logging()

    state = BotState()
    _STATE = state

    initialize_ai(state)
    initialize_app(state)
    if not state.model or not state.app:
        logging.critical("Приложение не может запуститься из-за ошибки инициализации.")
        return

    load_histories(state)
    load_whitelist(state)

    async with state.app:
        try:
            bot_peer = await state.app.resolve_peer(BOT_USERNAME)
        except Exception as e:
            logging.critical(f"Не удалось найти бота @{BOT_USERNAME}: {e}")
            return

        logging.info("=" * 50)
        logging.info("AI-Ассистент Знакомств (v37.0 'Стабильный Запуск') запущен!")
        logging.info("=" * 50)

        leomatch_cb = partial(leomatch_handler, state=state)
        private_cb = partial(private_chat_handler, state=state)

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
        logging.info(f"[СИСТЕМА] Обработчик для @{BOT_USERNAME} зарегистрирован.")

        state.app.add_handler(
            MessageHandler(
                private_cb,
                filters.private & ~filters.chat(BOT_USERNAME) & ~filters.me,
            )
        )
        logging.info("[СИСТЕМА] Обработчик для личных диалогов зарегистрирован.")

        logging.info(f"[СИСТЕМА] Анализ последнего сообщения от @{BOT_USERNAME}...")
        history = [
            msg async for msg in state.app.get_chat_history(bot_peer.user_id, limit=1)
        ]
        last_message = history[0] if history else None
        if last_message and (text := get_message_text(last_message)):
            await process_leomatch_message(state.app, text, state, is_startup=True)
        else:
            logging.info(f"[{BOT_USERNAME.upper()}] Чат пуст. Отправляю стартовую команду.")
            await state.app.send_message(BOT_USERNAME, "1")

        logging.info("[СИСТЕМА] Запуск завершен. Бот работает в двух режимах.")
        await asyncio.Event().wait()
