"""
AI-Ассистент для Telegram-бота знакомств
=========================================

Этот скрипт автоматизирует взаимодействие с Telegram-ботом для знакомств (@leomatchbot),
используя модель Google Gemini для генерации человекоподобных ответов и ведения диалогов.

Автор: polikhronidi dev
Версия: 1.1.0 (Публичный релиз)
"""
import asyncio
import logging

from pyrogram.errors import UserDeactivated, AuthKeyUnregistered

from app import get_state, run
from storage import save_histories


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (UserDeactivated, AuthKeyUnregistered) as e:
        logging.critical(
            f"Ошибка авторизации: {e}. Удалите .session файл и перезапуститесь."
        )
    except KeyboardInterrupt:
        logging.info("Скрипт остановлен пользователем. Сохранение истории...")
        state = get_state()
        if state:
            save_histories(state)
    except Exception as e:
        logging.critical(
            f"Произошла непредвиденная критическая ошибка: {e}", exc_info=True
        )
        state = get_state()
        if state:
            save_histories(state)
