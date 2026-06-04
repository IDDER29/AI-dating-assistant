import asyncio
import logging


def get_message_text(message) -> str | None:
    """Extract text from message text or caption."""
    return message.text or message.caption


async def safe_send_message(client, chat_id, text: str, retries: int = 3) -> bool:
    """
    Send a Telegram message with FloodWait handling and retry.
    Returns True on success, False after all retries exhausted.
    """
    try:
        from pyrogram.errors import FloodWait
    except ImportError:
        FloodWait = None

    for attempt in range(1, retries + 1):
        try:
            await client.send_message(chat_id, text)
            return True
        except Exception as e:
            if FloodWait and isinstance(e, FloodWait):
                wait_seconds = e.x + 1
                logging.warning(
                    f"[TELEGRAM] FloodWait {wait_seconds}s on send to {chat_id} "
                    f"(attempt {attempt}/{retries}). Waiting..."
                )
                await asyncio.sleep(wait_seconds)
            elif "FloodWait" in type(e).__name__:
                wait_seconds = getattr(e, "x", 30) + 1
                logging.warning(
                    f"[TELEGRAM] FloodWait {wait_seconds}s (attempt {attempt}/{retries})"
                )
                await asyncio.sleep(wait_seconds)
            else:
                logging.error(
                    f"[TELEGRAM] send_message to {chat_id} failed: {e} "
                    f"(attempt {attempt}/{retries})"
                )
                if attempt == retries:
                    return False
                await asyncio.sleep(2)

    logging.error(
        f"[TELEGRAM] Failed to send message to {chat_id} after {retries} retries."
    )
    return False
