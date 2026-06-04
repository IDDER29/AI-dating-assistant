"""
Sends proactive notifications to the operator's Telegram Saved Messages.
All calls are fire-and-forget — failures are logged but never raise.
"""
import logging


async def operator_notify(client, message: str):
    """
    Send a notification to the operator's Saved Messages ("me").
    Safe to call from anywhere — exceptions are caught and logged.
    """
    try:
        await client.send_message("me", f"🤖 {message}")
        logging.debug(f"[OPERATOR] Notification sent: {message[:80]}")
    except Exception as e:
        logging.error(f"[OPERATOR] Failed to send notification: {e}")
