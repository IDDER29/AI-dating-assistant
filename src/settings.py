"""
Application settings and behavioral constants.
All values here are safe to version-control.
"""
import random
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_PATH = DATA_DIR / "conversation_histories.json"
MEMORY_PATH = DATA_DIR / "conversation_memories.json"
WHITELIST_PATH = DATA_DIR / "whitelist.json"
LOG_FILE_PATH = BASE_DIR / "ai_bot_logs.txt"
STATS_PATH = DATA_DIR / "stats.json"

SESSION_NAME = "ai_dating_user"
BOT_USERNAME = "leomatchbot"

MAX_CONVERSATION_AGE_DAYS = 90
ACTION_COOLDOWN_SECONDS = 70
MIN_REPLY_INTERVAL_SEC = 45
HEARTBEAT_INTERVAL_HOURS = 6
MAX_HISTORY_LENGTH = 20
GRACE_PERIOD_SECONDS = 7
TYPING_SPEED_CPS = 8

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
FIRST_MESSAGE_PROMPT = (PROMPTS_DIR / "first_message.txt").read_text(encoding="utf-8")
CONVERSATION_SYSTEM_PROMPT = (PROMPTS_DIR / "conversation.txt").read_text(encoding="utf-8")

ANKET_PATTERN = re.compile(
    r"^(.+?),\s*(\d+),\s*(.+?)(?:[-–—]\s*(.*))?$", re.DOTALL
)
KNOWN_SYSTEM_MESSAGES = {
    "✨🔍",
    "Like sent, waiting for a response.",
    "I suggest a deal",
    "Everyone will see this temporary text",
    "Done",
    "Maybe later",
    "Skip",
}


def compute_reply_delay(gap_seconds: float) -> int:
    """
    Compute a natural reply delay based on time since last message.
    Short gaps → fast replies. Longer gaps → increasingly slower replies.
    Returns delay in seconds.
    """
    if gap_seconds < 120:
        return random.randint(15, 45)
    elif gap_seconds < 900:
        return random.randint(15, 90)
    elif gap_seconds < 3600:
        p_medium = min(0.8, (gap_seconds - 900) / 2700)
        if random.random() < p_medium:
            return random.randint(120, 600)
        return random.randint(15, 90)
    elif gap_seconds < 86400:
        p_long = min(0.25, (gap_seconds - 3600) / 82800 * 0.25)
        if random.random() < p_long:
            return random.randint(1800, 7200)
        return random.randint(300, 1200)
    else:
        if random.random() < 0.05:
            return random.randint(3600, 10800)
        return random.randint(300, 1800)
