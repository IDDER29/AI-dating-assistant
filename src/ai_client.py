import asyncio
import datetime
import logging
import re

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from config import (
    ANKET_PATTERN,
    CONVERSATION_SYSTEM_PROMPT,
    FIRST_MESSAGE_PROMPT,
    GEMINI_API_KEY,
    MAX_HISTORY_LENGTH,
)
from storage import save_histories


def initialize_ai(state):
    """Initialize the Gemini model."""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        state.model = genai.GenerativeModel("gemini-1.5-flash-latest")
        logging.info("Модель Google Gemini успешно инициализирована.")
    except Exception as e:
        logging.error(f"Не удалось настроить модель Google Gemini: {e}")
        state.model = None


def cleanup_ai_response(text: str) -> str:
    """Clean AI output from unwanted punctuation and whitespace."""
    cleaned_text = text.replace("–", " ").replace("—", " ")
    cleaned_text = cleaned_text.strip().rstrip(".?!")
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)
    cleaned_text = cleaned_text.replace(" ,", ",")
    return cleaned_text.strip()


async def with_rate_limit_handling(api_call):
    """Wrap API calls to handle 429 rate limits."""
    for attempt in range(3):
        try:
            return await asyncio.to_thread(api_call)
        except google_exceptions.ResourceExhausted as e:
            retry_delay = 60
            if hasattr(e, "error") and hasattr(e.error, "metadata"):
                for meta in e.error.metadata:
                    if meta[0] == "retry-delay":
                        retry_delay = int(meta[1].seconds) + 1
                        break
            logging.warning(
                f"Достигнут лимит API. Повторная попытка через {retry_delay} секунд..."
            )
            await asyncio.sleep(retry_delay)
    logging.error("Не удалось выполнить запрос к API после нескольких попыток.")
    return None


async def generate_first_message(anket_text: str, state) -> str:
    """Generate the first message for a new profile."""
    fallback_message = "твоя анкета показалась мне очень интересной, побалакаем?"
    if not state.model:
        return fallback_message

    match = ANKET_PATTERN.match(anket_text)
    profile_text = match.group(4).strip() if match and match.group(4) else ""

    if len(profile_text) < 15:
        profile_text = "Описание в анкете короткое или бессмысленное"

    prompt = FIRST_MESSAGE_PROMPT.format(profile_text=profile_text)
    response = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))

    return cleanup_ai_response(response.text) if response else fallback_message


async def generate_conversation_response(chat_id: int, user_message: str, state) -> str:
    """Generate a contextual reply in an existing dialog."""
    fallback_message = "хм, что-то пошло не так, повтори"
    if not state.model:
        return fallback_message

    chat_id_str = str(chat_id)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if chat_id_str not in state.conversation_histories:
        state.conversation_histories[chat_id_str] = []

    state.conversation_histories[chat_id_str].append(
        {"role": "user", "parts": [user_message], "timestamp": now_iso}
    )
    if len(state.conversation_histories[chat_id_str]) > MAX_HISTORY_LENGTH:
        state.conversation_histories[chat_id_str] = state.conversation_histories[
            chat_id_str
        ][-MAX_HISTORY_LENGTH:]

    history_for_api = [
        {"role": msg["role"], "parts": msg["parts"]}
        for msg in state.conversation_histories[chat_id_str]
    ]
    full_prompt_history = [
        {"role": "user", "parts": [CONVERSATION_SYSTEM_PROMPT]},
        {"role": "model", "parts": ["понял, я готов. без точек и лишней фигни"]},
    ] + history_for_api

    chat_session = state.model.start_chat(history=full_prompt_history[:-1])
    response = await with_rate_limit_handling(
        lambda: chat_session.send_message(full_prompt_history[-1]["parts"])
    )

    if response:
        ai_response = cleanup_ai_response(response.text)
        state.conversation_histories[chat_id_str].append(
            {
                "role": "model",
                "parts": [ai_response],
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )
        save_histories(state)
        return ai_response

    return fallback_message
