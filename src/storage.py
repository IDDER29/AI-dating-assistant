import json
import logging
from pathlib import Path

from config import HISTORY_PATH, WHITELIST_PATH


def load_json_data(filepath: str | Path, default_data):
    """Load JSON data, creating the file if missing or invalid."""
    path = Path(filepath)
    if path.exists() and path.stat().st_size > 0:
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logging.error(
                f"Ошибка декодирования JSON в {path}: {e}. Файл будет перезаписан."
            )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Создан новый файл {path} с данными по умолчанию.")
        return default_data
    except IOError as e:
        logging.error(f"Не удалось создать/записать файл {path}: {e}")
        return default_data


def save_json_data(filepath: str | Path, data):
    """Persist JSON data to disk."""
    path = Path(filepath)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        logging.error(f"Ошибка сохранения {path}: {e}")


def load_histories(state):
    state.conversation_histories = load_json_data(HISTORY_PATH, {})
    logging.info("Истории диалогов загружены.")


def save_histories(state):
    save_json_data(HISTORY_PATH, state.conversation_histories)
    logging.info("Истории диалогов сохранены.")


def load_whitelist(state):
    whitelist_list = load_json_data(WHITELIST_PATH, [])
    state.whitelist_ids = set(whitelist_list)
    logging.info(
        f"Белый список загружен. Пользователей в списке: {len(state.whitelist_ids)}."
    )
