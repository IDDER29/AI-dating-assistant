"""
AI Assistant for Telegram Dating Bot
=========================================

This script automates interaction with the Telegram dating bot (@leomatchbot),
using the Google Gemini model to generate human-like responses and lead dialogues.

Author: polikhronidi dev
Version: 1.1.0 (Public Release)
"""
import asyncio
import logging
import pathlib
import signal
import stat

from pyrogram.errors import UserDeactivated, AuthKeyUnregistered

from app import get_state, run
from storage import save_histories


def _check_file_permissions():
    """
    Warn at startup if sensitive files have group- or world-readable permissions.
    Best-effort — warnings only, never blocks startup.
    Skipped on Windows (no POSIX permission bits).
    """
    import sys
    if sys.platform == "win32":
        return  # Windows has different permission model; skip silently
    sensitive = [
        pathlib.Path(".env"),
        pathlib.Path("ai_dating_user.session"),
        pathlib.Path("ai_dating_user.session-journal"),
    ]
    for path in sensitive:
        if not path.exists():
            continue
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
            logging.warning(
                f"[SECURITY] {path} has permissive permissions "
                f"({oct(mode & 0o777)}). Recommended: chmod 600 {path}"
            )


def _handle_sigterm(signum, frame):
    raise KeyboardInterrupt


def _handle_sighup(signum, frame):
    """Reload the whitelist from disk without restarting."""
    state = get_state()
    if state:
        from storage import load_whitelist
        load_whitelist(state)
        logging.info(
            f"[SYSTEM] Whitelist reloaded via SIGHUP. "
            f"Users in list: {len(state.whitelist_ids)}"
        )
    else:
        logging.warning("[SYSTEM] SIGHUP received but state not initialized yet.")


def _handle_sigusr1(signum, frame):
    """Process data deletion requests from data/delete_requests.txt."""
    state = get_state()
    if not state:
        logging.warning("[SYSTEM] SIGUSR1 received but state not initialized.")
        return
    delete_file = pathlib.Path(__file__).parent.parent / "data" / "delete_requests.txt"
    if not delete_file.exists():
        logging.info("[SYSTEM] SIGUSR1: no delete_requests.txt found.")
        return
    try:
        lines = delete_file.read_text(encoding="utf-8").strip().splitlines()
        from storage import delete_user_data
        processed = 0
        for line in lines:
            line = line.strip()
            if line.isdigit():
                result = delete_user_data(state, int(line))
                logging.info(f"[SYSTEM] Deleted data for user {line}: {result}")
                processed += 1
        delete_file.unlink()
        logging.info(f"[SYSTEM] Processed {processed} deletion request(s). File removed.")
    except Exception as e:
        logging.error(f"[SYSTEM] Error processing deletion requests: {e}")


if __name__ == "__main__":
    _check_file_permissions()
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sighup)
    signal.signal(signal.SIGUSR1, _handle_sigusr1)
    try:
        asyncio.run(run())
    except (UserDeactivated, AuthKeyUnregistered) as e:
        logging.critical(
            f"Authorization error: {e}. Delete .session file and restart."
        )
    except KeyboardInterrupt:
        logging.info("Script stopped by user. Saving history...")
        state = get_state()
        if state:
            save_histories(state)
    except Exception as e:
        logging.critical(
            f"An unexpected critical error occurred: {e}", exc_info=True
        )
        state = get_state()
        if state:
            save_histories(state)
