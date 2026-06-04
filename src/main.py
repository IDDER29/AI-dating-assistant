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
import signal

from pyrogram.errors import UserDeactivated, AuthKeyUnregistered

from app import get_state, run
from storage import save_histories


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


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sighup)
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
