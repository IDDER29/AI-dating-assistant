"""
Wraps all direct Pyrogram client interactions.
Replace this class to swap the Telegram library without touching business logic.
"""
import logging

from pyrogram import enums

from utils import safe_send_message


class TelegramAdapter:

    def __init__(self, client, bot_username: str):
        self._client = client
        self._bot = bot_username

    # ── Scout actions ────────────────────────────────────────
    async def like_profile(self):
        await safe_send_message(self._client, self._bot, "💌 / 📹")

    async def dislike_profile(self):
        await safe_send_message(self._client, self._bot, "👎")

    async def navigate_to_profiles(self):
        await safe_send_message(self._client, self._bot, "1")

    async def send_opener(self, text: str) -> bool:
        return await safe_send_message(self._client, self._bot, text)

    # ── Interlocutor actions ─────────────────────────────────
    async def send_reply(self, chat_id: int, text: str) -> bool:
        return await safe_send_message(self._client, chat_id, text)

    async def show_typing(self, chat_id: int):
        try:
            await self._client.send_chat_action(chat_id, enums.ChatAction.TYPING)
        except Exception as e:
            logging.warning(f"[TELEGRAM] Failed to set typing action: {e}")

    async def mark_read(self, chat_id: int):
        try:
            await self._client.read_chat_history(chat_id)
        except Exception as e:
            logging.warning(f"[TELEGRAM] Failed to mark read for {chat_id}: {e}")

    # ── Operator notifications ───────────────────────────────
    async def notify_operator(self, text: str):
        try:
            await self._client.send_message("me", f"🤖 {text}")
        except Exception as e:
            logging.error(f"[TELEGRAM] Operator notify failed: {e}")

    # ── Startup utilities ────────────────────────────────────
    async def get_last_bot_message(self):
        try:
            history = [
                msg async for msg in self._client.get_chat_history(
                    self._bot, limit=1
                )
            ]
            return history[0] if history else None
        except Exception as e:
            logging.error(f"[TELEGRAM] Failed to get bot history: {e}")
            return None

    async def resolve_peer(self, username: str):
        return await self._client.resolve_peer(username)
