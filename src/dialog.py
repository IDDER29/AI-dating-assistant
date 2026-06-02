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
from utils import get_message_text


async def private_chat_handler(client, message, state):
    """Dispatch incoming private messages."""
    chat_id = message.chat.id

    if chat_id in state.whitelist_ids:
        logging.info(
            f"[ДИСПЕТЧЕР] Пользователь {message.from_user.first_name} (ID: {chat_id}) "
            "в белом списке. Игнорирую."
        )
        return

    await client.read_chat_history(chat_id)
    logging.info(
        f"[ДИСПЕТЧЕР] Сообщение от {message.from_user.first_name} помечено как прочитанное."
    )

    if chat_id in state.active_dialogue_tasks:
        state.active_dialogue_tasks[chat_id].cancel()
        logging.info(
            f"[ДИСПЕТЧЕР] Пользователь {message.from_user.first_name} написал снова. "
            "Таймер перезапущен."
        )

    task = asyncio.create_task(process_dialogue_task(client, message, state))
    state.active_dialogue_tasks[chat_id] = task


async def process_dialogue_task(client, message, state):
    """Background task for a full reply cycle."""
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    try:
        logging.info(
            f"[ДИАЛОГ] Ожидаю {GRACE_PERIOD_SECONDS} сек. на случай, если {user_name} дописывает..."
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
            logging.info(f"[ДИАЛОГ] Обнаружена НОВАЯ сессия с {user_name}.")
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
            logging.info(f"[ДИАЛОГ] Продолжается АКТИВНАЯ сессия с {user_name}.")

        delay = random.randint(delay_config["min_sec"], delay_config["max_sec"])
        logging.info(
            f"[ДИАЛОГ] Ответ для {user_name} будет отправлен через ~{delay // 60}м "
            f"{delay % 60}с (режим: {mode})."
        )
        await asyncio.sleep(delay)

        logging.info(f"[ДИАЛОГ] Время вышло. Генерирую ответ для {user_name}...")
        user_message = get_message_text(message)
        if not user_message:
            logging.warning(
                f"[ДИАЛОГ] Последнее сообщение от {user_name} без текста. Отмена."
            )
            return

        ai_response = await generate_conversation_response(chat_id, user_message, state)

        if "|||" in ai_response:
            logging.info(f"[ДИАЛОГ] Ответ для {user_name} будет отправлен 'лесенкой'.")
            parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
            for part in parts:
                typing_delay = (len(part) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
                await client.send_chat_action(chat_id, enums.ChatAction.TYPING)
                logging.info(
                    f"[ДИАЛОГ] Имитация печати {typing_delay:.1f}с для части: '{part}'"
                )
                await asyncio.sleep(typing_delay)
                await client.send_message(chat_id, part)
        else:
            typing_delay = (len(ai_response) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
            await client.send_chat_action(chat_id, enums.ChatAction.TYPING)
            logging.info(
                f"[ДИАЛОГ] Имитация печати {typing_delay:.1f}с для сообщения: '{ai_response}'"
            )
            await asyncio.sleep(typing_delay)
            await client.send_message(chat_id, ai_response)

        logging.info(f"[ДИАЛОГ] Полный ответ для {user_name} отправлен.")
    except asyncio.CancelledError:
        logging.info(f"[ДИСПЕТЧЕР] Задача для чата с {user_name} отменена.")
    except Exception as e:
        logging.error(f"[ДИАЛОГ] Ошибка в задаче обработки диалога: {e}", exc_info=True)
    finally:
        state.active_dialogue_tasks.pop(chat_id, None)
