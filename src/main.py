"""
AI Assistant for Telegram Dating Bot
=========================================

Entry point. Registers OS signal handlers, runs the application, and
ensures a graceful shutdown (all data saved) on any exit signal.
"""
import asyncio
import logging
import pathlib
import signal
import stat

from pyrogram.errors import UserDeactivated, AuthKeyUnregistered

from app import get_state, run, shutdown_gracefully
from logging_setup import setup_logging


def _check_file_permissions():
    """
    Warn at startup if sensitive files have group- or world-readable permissions.
    Best-effort — warnings only, never blocks startup.
    Skipped on Windows (different permission model).
    """
    import sys
    if sys.platform == "win32":
        return
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


async def _run_with_graceful_shutdown():
    """Wrap run() so KeyboardInterrupt triggers graceful shutdown before exit."""
    try:
        await run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.info("[SYSTEM] Shutdown signal received. Starting graceful shutdown...")
        state = get_state()
        if state:
            await shutdown_gracefully(state)
        raise


if __name__ == "__main__":
    setup_logging()
    _check_file_permissions()

    # Log which Telegram library is running (pyrogram vs pyrofork)
    try:
        import pyrogram
        logging.info(f"[SYSTEM] Telegram library: pyrogram {pyrogram.__version__}")
    except Exception:
        pass

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sighup)
    signal.signal(signal.SIGUSR1, _handle_sigusr1)

    try:
        asyncio.run(_run_with_graceful_shutdown())
    except (UserDeactivated, AuthKeyUnregistered) as e:
        logging.critical(
            f"Authorization error: {e}. Delete .session file and restart."
        )
    except KeyboardInterrupt:
        pass  # graceful shutdown already handled inside _run_with_graceful_shutdown
    except Exception as e:
        logging.critical(
            f"An unexpected critical error occurred: {e}", exc_info=True
        )
        # Emergency save if graceful shutdown did not run
        state = get_state()
        if state:
            from storage import save_histories
            save_histories(state)
