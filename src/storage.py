import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import HISTORY_PATH, MEMORY_PATH, WHITELIST_PATH


def load_json_data(filepath: str | Path, default_data):
    """Load JSON data, creating the file if missing or invalid."""
    path = Path(filepath)
    if path.exists() and path.stat().st_size > 0:
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            backup_path = path.with_suffix(
                f".corrupt.{int(datetime.now().timestamp())}.json"
            )
            try:
                path.rename(backup_path)
                logging.error(
                    f"[STORAGE] Corrupt file at {path}: {e}. "
                    f"Backed up to {backup_path}. Starting fresh."
                )
            except OSError as rename_err:
                logging.error(
                    f"[STORAGE] Corrupt file at {path}: {e}. "
                    f"Could not back up ({rename_err}). File will be overwritten."
                )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Created new file {path} with default data.")
        return default_data
    except IOError as e:
        logging.error(f"Failed to create/write file {path}: {e}")
        return default_data


def save_json_data(filepath: str | Path, data):
    """Persist JSON data to disk atomically."""
    path = Path(filepath)
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except IOError as e:
        logging.error(f"Error saving {path}: {e}")
        tmp_path.unlink(missing_ok=True)


def load_histories(state):
    state.conversation_histories = load_json_data(HISTORY_PATH, {})
    logging.info("Conversation histories loaded.")


def save_histories(state):
    save_json_data(HISTORY_PATH, state.conversation_histories)
    logging.info("Conversation histories saved.")


def prune_stale_histories(state, max_age_days: int = 90) -> int:
    """Remove conversation entries whose last turn is older than max_age_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stale_ids = []

    for user_id, turns in state.conversation_histories.items():
        if not turns:
            stale_ids.append(user_id)
            continue
        last_ts_str = turns[-1].get("timestamp")
        if not last_ts_str:
            continue
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            if last_ts < cutoff:
                stale_ids.append(user_id)
        except ValueError:
            pass

    for user_id in stale_ids:
        del state.conversation_histories[user_id]

    if stale_ids:
        logging.info(
            f"[STORAGE] Pruned {len(stale_ids)} stale conversations "
            f"(older than {max_age_days} days)."
        )
    return len(stale_ids)


def load_memories(state):
    state.conversation_memories = load_json_data(MEMORY_PATH, {})
    logging.info("Conversation memories loaded.")


def save_memories(state):
    save_json_data(MEMORY_PATH, state.conversation_memories)


def load_whitelist(state):
    whitelist_list = load_json_data(WHITELIST_PATH, [])
    state.whitelist_ids = set(whitelist_list)
    logging.info(
        f"Whitelist loaded. Users in list: {len(state.whitelist_ids)}."
    )
