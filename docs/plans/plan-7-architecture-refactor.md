# Plan 7 — Architecture Refactor

_Week: 4 | Prerequisite: All prior plans complete | Final plan_

> **Goal:** Improve long-term maintainability, reduce coupling, add test coverage.
> Execute last — refactor code that is already correct and stable.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-25 | `config.py` mixes secrets, constants, and prompts |
| ISSUE-26 | No Telegram interface abstraction — Pyrogram calls scattered |
| ISSUE-27 | `BotState` is an untyped shared mutable blob |
| ISSUE-28 | No test infrastructure of any kind |
| ISSUE-29 | Credentials stored unencrypted at rest |

---

## Task 7.1 — Split `config.py` into Focused Files

**Status:** ✅ Done
**Files:** `src/credentials.py` (new), `src/settings.py` (new), `src/prompts/` (new dir), `src/config.py` (deprecated)
**Estimated effort:** 2 hours
**Depends on:** Plan 3 complete (prompts must be finalized before moving them)

### Problem
`config.py` is 138 lines combining: API credentials, 17 behavioral constants, 85 lines of natural language AI prompts, a compiled regex, and a domain knowledge set. Change rates are different. Audiences are different. Security classifications are different.

### Implementation

**Step 1:** Create directory structure:
```
src/
├── credentials.py        # secrets only — add to .gitignore
├── settings.py           # constants, paths, patterns — safe to commit
└── prompts/
    ├── first_message.txt  # FIRST_MESSAGE_PROMPT content
    └── conversation.txt   # CONVERSATION_SYSTEM_PROMPT content
```

**Step 2:** Create `src/credentials.py`:

```python
"""
Environment-sourced credentials. Never commit this file.
Add to .gitignore: credentials.py
"""
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
```

**Step 3:** Create `src/settings.py` — move all constants and paths here:

```python
"""
Application settings and behavioral constants.
All values here are safe to version-control.
"""
from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_PATH = DATA_DIR / "conversation_histories.json"
WHITELIST_PATH = DATA_DIR / "whitelist.json"
MEMORY_PATH = DATA_DIR / "conversation_memories.json"
LOG_FILE_PATH = BASE_DIR / "ai_bot_logs.txt"
STATS_PATH = DATA_DIR / "stats.json"

SESSION_NAME = "ai_dating_user"
BOT_USERNAME = "leomatchbot"

ACTION_COOLDOWN_SECONDS = 70
MAX_HISTORY_LENGTH = 20
GRACE_PERIOD_SECONDS = 7
TYPING_SPEED_CPS = 8
MIN_REPLY_INTERVAL_SEC = 45
MAX_CONVERSATION_AGE_DAYS = 90
HEARTBEAT_INTERVAL_HOURS = 6

# Prompts loaded from plain text files
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
FIRST_MESSAGE_PROMPT = (PROMPTS_DIR / "first_message.txt").read_text(encoding="utf-8")
CONVERSATION_SYSTEM_PROMPT = (PROMPTS_DIR / "conversation.txt").read_text(encoding="utf-8")

ANKET_PATTERN = re.compile(
    r"^(.+?),\s*(\d+),\s*(.+?)(?:[-–—]\s*(.*))?$", re.DOTALL
)
KNOWN_SYSTEM_MESSAGES = {
    "✨🔍", "Like sent, waiting for a response.", "I suggest a deal",
    "Everyone will see this temporary text", "Done", "Maybe later", "Skip",
}
```

**Step 4:** Create `src/prompts/first_message.txt` — paste the `FIRST_MESSAGE_PROMPT` content verbatim (no Python string quotes).

**Step 5:** Create `src/prompts/conversation.txt` — paste the `CONVERSATION_SYSTEM_PROMPT` content verbatim.

**Step 6:** Update `config.py` to re-export everything for backward compatibility during migration:

```python
# config.py — temporary compatibility shim
from settings import *
from credentials import *
```

**Step 7:** Gradually migrate each module's imports from `from config import X` to `from settings import X` or `from credentials import X`. Once all modules are migrated, delete `config.py`.

**Step 8:** Add to `.gitignore`:
```
src/credentials.py
```

### Verification
```bash
# After migration, run full bot smoke test
# python3 src/main.py — verify startup, profile processing, conversation reply
# Edit src/prompts/conversation.txt — change one line of the persona
# Restart bot — verify the change is picked up without code change
# Verify: credentials.py is not tracked by git (git status)
```

---

## Task 7.2 — TelegramAdapter

**Status:** ✅ Done
**File:** `src/telegram_adapter.py` (new)
**Estimated effort:** 2 hours
**Depends on:** Plan 4 Task 4.1 (`safe_send_message` in utils.py)

### Problem
Direct `client.send_message()`, `client.send_chat_action()`, and `client.read_chat_history()` calls are scattered across `leomatch.py`, `dialog.py`, and `app.py`. Replacing Pyrogram requires finding and changing every call site across multiple files with no single isolation point.

### Implementation

**Step 1:** Create `src/telegram_adapter.py`:

```python
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
```

**Step 2:** Update `app.py` to create and store the adapter, passing it via `partial()`:

```python
# app.py
from telegram_adapter import TelegramAdapter

# In run(), after creating the Pyrogram client:
adapter = TelegramAdapter(state.app, BOT_USERNAME)

# Update partial bindings:
leomatch_cb = partial(leomatch_handler, state=state, adapter=adapter)
private_cb  = partial(private_chat_handler, state=state, adapter=adapter)
```

**Step 3:** Update `leomatch.py` and `dialog.py` handler signatures to accept `adapter` and use it:

```python
# leomatch.py — handler signature:
async def leomatch_handler(client, message, state, adapter):
    ...
    await adapter.like_profile()           # instead of client.send_message(...)
    await adapter.dislike_profile()
    await adapter.navigate_to_profiles()
    await adapter.send_opener(text)

# dialog.py — handler signature:
async def private_chat_handler(client, message, state, adapter):
    ...
    await adapter.mark_read(chat_id)
    await adapter.show_typing(chat_id)
    await adapter.send_reply(chat_id, text)
```

### Verification
```bash
# Full smoke test after refactor:
# - Profile card → like → opener sent
# - Private message → read receipt → reply with typing indicator
# - All existing behavior preserved, no regressions
```

---

## Task 7.3 — Replace PendingProfile String with Typed Dataclass

**Status:** ✅ Done
**Files:** `src/state.py`, `src/leomatch.py`
**Estimated effort:** 1 hour
**Depends on:** Nothing (independent, but do after Plan 3 Task 3.1 to avoid conflicts)

### Problem
`state.last_seen_anket_text: Optional[str]` represents a domain concept (a profile being held between two events) as an untyped nullable string. No timestamp, no ownership semantics, no documentation of its lifecycle. The pattern is invisible to readers of the code.

### Implementation

**Step 1:** Add `PendingMatch` dataclass to `state.py`:

```python
# state.py — add before BotState:
import datetime

@dataclass
class PendingMatch:
    anket_text: str                          # full raw profile card text
    liked_at: str                            # ISO timestamp
    description: str = ""                   # extracted description (convenience)
    opener_text: Optional[str] = None       # filled after opener is generated
```

**Step 2:** Replace `last_seen_anket_text` in `BotState`:

```python
# state.py — in BotState, replace:
# last_seen_anket_text: Optional[str] = None

# WITH:
pending_match: Optional[PendingMatch] = None
```

**Step 3:** Update all access in `leomatch.py`:

```python
# When profile arrives:
state.pending_match = PendingMatch(
    anket_text=text,
    liked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    description=(match.group(4) or "").strip()
)

# When "write message" arrives:
if state.pending_match:
    intro_message = await generate_first_message(state.pending_match.anket_text, state)
    # ... send opener ...
    state.pending_match = None  # clear after confirmed send

# In generate_first_message call site:
# Can now use state.pending_match.description directly instead of re-parsing
```

### Verification
```bash
# Profile card arrives → verify state.pending_match is populated with correct fields
# Opener sent → verify state.pending_match is cleared
# Bot restart → verify state.pending_match is None (not persisted, reset on boot)
```

---

## Task 7.4 — Unit Test Suite Foundation

**Status:** ✅ Done
**Directory:** `tests/` (new)
**Estimated effort:** 3 hours
**Depends on:** Task 7.1 (settings split makes imports cleaner)

### Problem
Zero tests exist. The most change-prone elements (regex, cleanup function, output validator, meeting detector, ladder split, history assembly) have no automated coverage. Every code change requires manual verification by running the full bot.

### Implementation

**Step 1:** Add `pytest` and `pytest-asyncio` to `requirements.txt`.

**Step 2:** Create `tests/` directory with `conftest.py`:

```python
# tests/conftest.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
```

**Step 3:** Create `tests/test_ai_client.py`:

```python
import pytest
from ai_client import cleanup_ai_response

def test_cleanup_removes_em_dash():
    assert cleanup_ai_response("hello — world") == "hello  world"

def test_cleanup_removes_en_dash():
    assert cleanup_ai_response("hello – world") == "hello  world"

def test_cleanup_strips_trailing_period():
    assert cleanup_ai_response("hello.") == "hello"

def test_cleanup_strips_trailing_question_mark():
    assert cleanup_ai_response("really?") == "really"

def test_cleanup_strips_trailing_exclamation():
    assert cleanup_ai_response("wow!") == "wow"

def test_cleanup_collapses_spaces():
    assert cleanup_ai_response("hello   world") == "hello world"

def test_cleanup_fixes_space_before_comma():
    assert cleanup_ai_response("hello ,world") == "hello,world"

def test_cleanup_preserves_closing_paren():
    # Persona uses ) as a smirk — must not be stripped
    assert cleanup_ai_response("sure)") == "sure)"
```

**Step 4:** Create `tests/test_settings.py`:

```python
import re
import pytest
from settings import ANKET_PATTERN

class TestAnketPattern:
    def test_matches_full_profile(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow — I love hiking")
        assert m is not None
        assert m.group(1) == "Anna"
        assert m.group(2) == "24"
        assert m.group(3) == "Moscow"
        assert m.group(4) == "I love hiking"

    def test_matches_no_description(self):
        m = ANKET_PATTERN.match("Boris, 30, SPb")
        assert m is not None
        assert m.group(4) is None

    def test_matches_multiline_description(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow — I love\nhiking")
        assert m is not None
        assert "hiking" in m.group(4)

    def test_no_match_text_age(self):
        m = ANKET_PATTERN.match("Anna, twenty four, Moscow — description")
        assert m is None

    def test_matches_em_dash(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow — desc")
        assert m is not None

    def test_matches_en_dash(self):
        m = ANKET_PATTERN.match("Anna, 24, Moscow – desc")
        assert m is not None
```

**Step 5:** Create `tests/test_output_validator.py`:

```python
import pytest
from output_validator import validate_response

def test_valid_short_response():
    assert validate_response("hey, how are you)").valid

def test_empty_string_invalid():
    assert not validate_response("").valid

def test_whitespace_only_invalid():
    assert not validate_response("   ").valid

def test_too_long_invalid():
    assert not validate_response("x" * 601).valid

def test_prompt_leak_dossier():
    assert not validate_response("as per my dossier instructions").valid

def test_prompt_leak_ai_avatar():
    assert not validate_response("you are the ai avatar of a real guy").valid

def test_too_many_ladder_parts():
    assert not validate_response("a ||| b ||| c ||| d ||| e").valid

def test_exactly_max_ladder_parts_valid():
    assert validate_response("a ||| b ||| c ||| d").valid
```

**Step 6:** Create `tests/test_meeting_detector.py`:

```python
import pytest
from meeting_detector import detect_meeting_signal

class TestMeetingSignals:
    def test_russian_meet(self):
        assert detect_meeting_signal("давай встретимся в кофейне")

    def test_russian_coffee(self):
        assert detect_meeting_signal("выпьем кофе как-нибудь?")

    def test_english_meet(self):
        assert detect_meeting_signal("let's meet up sometime")

    def test_english_coffee(self):
        assert detect_meeting_signal("want to grab coffee?")

    def test_negative_normal_message(self):
        assert not detect_meeting_signal("how are you today?")

    def test_negative_empty(self):
        assert not detect_meeting_signal("")

    def test_negative_none(self):
        assert not detect_meeting_signal(None)

    def test_case_insensitive(self):
        assert detect_meeting_signal("ДАВАЙ ВСТРЕТИМСЯ")
        assert detect_meeting_signal("LET'S MEET")
```

**Step 7:** Create `tests/test_utils.py`:

```python
import pytest
from unittest.mock import MagicMock
from utils import get_message_text

def test_returns_text_field():
    msg = MagicMock()
    msg.text = "hello"
    msg.caption = None
    assert get_message_text(msg) == "hello"

def test_returns_caption_when_no_text():
    msg = MagicMock()
    msg.text = None
    msg.caption = "photo caption"
    assert get_message_text(msg) == "photo caption"

def test_returns_none_when_both_empty():
    msg = MagicMock()
    msg.text = None
    msg.caption = None
    assert get_message_text(msg) is None

def test_text_takes_priority():
    msg = MagicMock()
    msg.text = "text content"
    msg.caption = "caption content"
    assert get_message_text(msg) == "text content"
```

**Step 8:** Run tests:

```bash
cd AI-dating-assistant
pip install pytest pytest-asyncio
pytest tests/ -v
```

### Verification
```bash
# All tests pass on clean run:
pytest tests/ -v
# ✅ tests/test_ai_client.py::test_cleanup_removes_em_dash PASSED
# ✅ tests/test_settings.py::TestAnketPattern::test_matches_full_profile PASSED
# ... all tests green
```

---

## Completion Checklist

```
[x] Task 7.1 — credentials.py, settings.py, prompts/*.txt created; config.py is now a shim; all 6 modules migrated
[x] Task 7.2 — telegram_adapter.py created; app.py creates adapter and passes via partial; leomatch.py and dialog.py use adapter exclusively
[x] Task 7.3 — PendingMatch dataclass in state.py; last_seen_anket_text replaced with pending_match throughout leomatch.py
[x] Task 7.4 — 36 tests, 36 passed; conftest stubs external deps; covers cleanup, regex, validator, meeting detector, utils
[x] Security — .gitignore created with src/credentials.py, *.session, data/, .env
[ ] Final end-to-end smoke test
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- Persona can be edited by non-developers without touching Python files
- Credentials are separated from application logic
- The Pyrogram library can be replaced in one file
- All key domain objects are typed and self-documenting
- Pure functions have automated test coverage
- Regressions in regex, cleanup, validation, and meeting detection are caught immediately
- **The system is maintainable, extensible, and observable**
