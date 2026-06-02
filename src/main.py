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

from pyrogram.errors import UserDeactivated, AuthKeyUnregistered

from app import get_state, run
from storage import save_histories


if __name__ == "__main__":
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
