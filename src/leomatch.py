import asyncio
import datetime
import logging

from ai_client import generate_first_message
from config import (
    ACTION_COOLDOWN_SECONDS,
    ANKET_PATTERN,
    BOT_USERNAME,
    KNOWN_SYSTEM_MESSAGES,
)
from utils import get_message_text


async def leomatch_handler(client, message, state):
    """Dispatch messages coming from the dating bot."""
    event_type = "ОТРЕДАКТИРОВАНО" if message.edit_date else "НОВОЕ"
    logging.info(f"[ДАЙВИНЧИК-ДИСПЕТЧЕР] Получено событие (Тип: {event_type})")
    text = get_message_text(message)
    if not text:
        logging.info("[ДАЙВИНЧИК-ДИСПЕТЧЕР] Пустое событие, игнорирую.")
        return

    if ANKET_PATTERN.match(text):
        if state.leomatch_task and not state.leomatch_task.done():
            state.leomatch_task.cancel()
            logging.info(
                "[ДАЙВИНЧИК-ДИСПЕТЧЕР] Пришла новая анкета. Старая задача отменена."
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
                f"[ДАЙВИНЧИК-ЗАДАЧА] КД активен. Ожидаю {wait_time:.1f} сек..."
            )
            await asyncio.sleep(wait_time)

        text = get_message_text(message)
        logging.info("[ДАЙВИНЧИК-ЗАДАЧА] КД прошел. Обрабатываю последнюю анкету.")
        await process_leomatch_message(client, text, state)
    except asyncio.CancelledError:
        logging.info(
            "[ДАЙВИНЧИК-ЗАДАЧА] Задача отменена (пришла более свежая анкета)."
        )
    except Exception as e:
        logging.error(
            f"[ДАЙВИНЧИК-ЗАДАЧА] Ошибка в задаче обработки анкеты: {e}",
            exc_info=True,
        )


async def process_leomatch_message(client, text: str, state, is_startup: bool = False):
    """Execute direct actions in the dating bot."""
    logging.info(f"[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Анализ текста: \"{text[:120]}\"")

    if any(phrase in text for phrase in KNOWN_SYSTEM_MESSAGES):
        logging.info(
            "[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Обнаружено системное/рекламное сообщение. Игнорирую."
        )
        return

    if "1. Смотреть анкеты" in text:
        logging.info("[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Главное меню. Нажимаю '1'.")
        await asyncio.sleep(2)
        await client.send_message(BOT_USERNAME, "1")
        return

    match = ANKET_PATTERN.match(text)
    if match:
        state.last_seen_anket_text = text
        logging.info(
            f"[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Анкета '{match.group(1).strip()}' сохранена в память."
        )
        description = match.group(4)
        if description and len(description.strip()) > 10:
            logging.info("[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Анкета с описанием. Лайкаю...")
            await asyncio.sleep(3)
            await client.send_message(BOT_USERNAME, "💌 / 📹")
        else:
            logging.info("[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Анкета без описания. Дизлайкаю...")
            await asyncio.sleep(3)
            await client.send_message(BOT_USERNAME, "👎")
        state.last_action_time = datetime.datetime.now(datetime.timezone.utc)
        logging.info(
            f"[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Кулдаун на {ACTION_COOLDOWN_SECONDS} сек. запущен."
        )
        return

    if "Напиши сообщение для этого пользователя" in text:
        if state.last_seen_anket_text:
            logging.info("[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Запрос на сообщение. Генерирую...")
            intro_message = await generate_first_message(state.last_seen_anket_text, state)
            if len(intro_message) > 300:
                logging.warning(
                    "[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] AI сгенерировал слишком длинное сообщение "
                    f"({len(intro_message)} симв). Использую запасной вариант."
                )
                intro_message = (
                    "твоя анкета зацепила, но мой мозг сегодня бастует и пишет поэмы) "
                    "расскажи что-нибудь о себе, чего там нет"
                )
            await asyncio.sleep(5)
            await client.send_message(BOT_USERNAME, intro_message)
            state.last_seen_anket_text = None
            logging.info("[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Сообщение отправлено, память очищена.")
        else:
            logging.warning(
                "[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Запрос на сообщение, но анкета не найдена в памяти. "
                "Игнорирую."
            )
        return

    if not is_startup:
        logging.warning(f"[ДАЙВИНЧИК-ИСПОЛНИТЕЛЬ] Нераспознанный текст: '{text}'")
