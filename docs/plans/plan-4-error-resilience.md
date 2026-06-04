# Plan 4 — Error Handling & Resilience

_Week: 2 | Prerequisite: Plan 1 | Can run parallel to Plan 3_

> **Goal:** Eliminate all silent failure modes. The system must never lose a message,
> hang silently, or degrade without the operator knowing.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-18 | FloodWait uncaught — Telegram rate-limited messages silently lost |
| ISSUE-19 | No per-user rate limiting — single user can exhaust API quota |
| ISSUE-20 | `|||`-only AI response sends nothing with no log (covered by Plan 2 Task 2.5) |

---

## Task 4.1 — FloodWait Handler with Retry

**Status:** ⬜ Not started
**Files:** `src/utils.py`, `src/leomatch.py`, `src/dialog.py`
**Estimated effort:** 1 hour
**Depends on:** Nothing (independent)

### Problem
`pyrogram.errors.FloodWait` is raised when Telegram rate-limits the account. It carries `.x` — the number of seconds to wait. The codebase has no handler for it anywhere. When raised, it propagates to the background task's `except Exception` handler, which logs an error and exits. The message is never sent; the user never receives a reply.

This can happen under normal operating conditions if:
- The Scout sends actions too rapidly (even with the 70-second cooldown)
- Multiple conversations send messages simultaneously
- The ladder-send splits a response into many rapid parts

### Implementation

**Step 1:** Add `safe_send_message()` to `src/utils.py`:

```python
# utils.py — add imports:
import asyncio
import logging

# utils.py — add function:
async def safe_send_message(client, chat_id, text: str, retries: int = 3) -> bool:
    """
    Send a Telegram message with FloodWait handling and retry.
    Returns True on success, False after all retries exhausted.
    """
    try:
        from pyrogram.errors import FloodWait
    except ImportError:
        # Fallback if import path changes
        FloodWait = None

    for attempt in range(1, retries + 1):
        try:
            await client.send_message(chat_id, text)
            return True
        except Exception as e:
            # Check if it's a FloodWait by class name (handles import path variations)
            if FloodWait and isinstance(e, FloodWait):
                wait_seconds = e.x + 1
                logging.warning(
                    f"[TELEGRAM] FloodWait {wait_seconds}s on send to {chat_id} "
                    f"(attempt {attempt}/{retries}). Waiting..."
                )
                await asyncio.sleep(wait_seconds)
            elif "FloodWait" in type(e).__name__:
                # Fallback string match
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

    logging.error(f"[TELEGRAM] Failed to send message to {chat_id} after {retries} retries.")
    return False
```

**Step 2:** Update `dialog.py` — replace all `client.send_message()` calls with `safe_send_message()`:

```python
# dialog.py — add import:
from utils import safe_send_message

# In process_dialogue_task(), ladder send:
# REPLACE: await client.send_message(chat_id, part)
# WITH:
await safe_send_message(client, chat_id, part)

# In process_dialogue_task(), single send:
# REPLACE: await client.send_message(chat_id, ai_response)
# WITH:
await safe_send_message(client, chat_id, ai_response)
```

**Step 3:** Update `leomatch.py` — replace all `client.send_message()` calls:

```python
# leomatch.py — add import:
from utils import safe_send_message

# Replace each client.send_message(BOT_USERNAME, ...) with:
await safe_send_message(client, BOT_USERNAME, ...)
```

Affected lines in `leomatch.py`:
- `await client.send_message(BOT_USERNAME, "1")` (menu navigation)
- `await client.send_message(BOT_USERNAME, "💌 / 📹")` (like)
- `await client.send_message(BOT_USERNAME, "👎")` (dislike)
- `await client.send_message(BOT_USERNAME, intro_message)` (opener — already handled in Plan 3 Task 3.1 try/except, but use `safe_send_message` for consistency)

### Verification
```bash
# Test 1: Normal operation — verify all messages still send correctly
# Test 2: Simulate FloodWait by wrapping the send in a mock that raises
#   FloodWait(30) on first call, succeeds on second
#   Verify: 30s sleep logged, retry succeeds, message delivered
# Test 3: All retries fail — verify: error logged, function returns False, no crash
```

---

## Task 4.2 — Per-User Reply Rate Limiting

**Status:** ⬜ Not started
**Files:** `src/state.py`, `src/dialog.py`, `src/config.py`
**Estimated effort:** 45 minutes
**Depends on:** Nothing (independent)

### Problem
A single user sending rapid messages can generate one Gemini API call per 8 seconds (grace period + minimum delay). On the free tier (15 RPM), a single user sending messages every 8 seconds for 2 minutes exhausts the entire quota, degrading all other conversations. On the paid tier, this is a direct financial cost.

Additionally, the human-simulation goal is violated — a real person would not reply to the same user every 8 seconds regardless of how fast they message.

### Implementation

**Step 1:** Add `MIN_REPLY_INTERVAL_SEC` to `config.py`:

```python
# config.py
MIN_REPLY_INTERVAL_SEC = 45  # minimum seconds between replies to the same user
```

**Step 2:** Add `last_reply_times` to `BotState` in `state.py`:

```python
# state.py
last_reply_times: Dict[int, Any] = field(default_factory=dict)
# {chat_id: datetime} — tracks when each user last received a reply
```

**Step 3:** In `dialog.py`, `process_dialogue_task()`, add the rate limit check before the AI call — after the delay sleep, before generation:

```python
# dialog.py — add imports:
import datetime
from config import MIN_REPLY_INTERVAL_SEC

# In process_dialogue_task(), after await asyncio.sleep(delay):
last_reply = state.last_reply_times.get(chat_id)
if last_reply:
    elapsed = (
        datetime.datetime.now(datetime.timezone.utc) - last_reply
    ).total_seconds()
    if elapsed < MIN_REPLY_INTERVAL_SEC:
        logging.info(
            f"[DIALOG] Rate limiting {user_name}: "
            f"only {elapsed:.0f}s since last reply (min: {MIN_REPLY_INTERVAL_SEC}s). "
            "Skipping this reply cycle."
        )
        return
```

**Step 4:** Update `last_reply_times` after successful message send in `process_dialogue_task()`:

```python
# After successful send (both single and ladder modes):
state.last_reply_times[chat_id] = datetime.datetime.now(datetime.timezone.utc)
logging.info(f"[DIALOG] Full reply for {user_name} sent.")
```

**Step 5:** Add cleanup in `finally` block to prevent unbounded growth of `last_reply_times`:

```python
# Optionally prune entries older than 24h in a periodic task
# For now, the dict grows at 1 entry per unique user — manageable
```

### Verification
```bash
# Test: Send messages every 5 seconds for 2 minutes
# Verify: Only one reply generated per MIN_REPLY_INTERVAL_SEC
# Test: Send one message, wait MIN_REPLY_INTERVAL_SEC, send another
# Verify: Both receive replies
# Test: Two different users sending simultaneously
# Verify: Both receive replies (rate limit is per-user, not global)
```

---

## Task 4.3 — SIGHUP Whitelist Hot-Reload

**Status:** ⬜ Not started
**File:** `src/main.py`
**Estimated effort:** 30 minutes
**Depends on:** Plan 1 Task 1.4 (signal handler pattern established)

### Problem
The whitelist is loaded once at startup. Changes to `whitelist.json` require stopping and restarting the bot. During the restart window (30–60 seconds), the AI may respond to conversations the operator needs to control. The most time-sensitive operator action has the most friction.

### Implementation

**Step 1:** In `main.py`, add a SIGHUP handler after the SIGTERM handler:

```python
# main.py — add after _handle_sigterm:

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
```

**Step 2:** Register the handler in the `if __name__ == "__main__"` block:

```python
if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sighup)   # ← add this
    try:
        asyncio.run(run())
    ...
```

**Step 3:** Document the operator workflow:

```bash
# To add a user to whitelist without restarting:
# 1. Edit data/whitelist.json — add their Telegram user ID
# 2. Find the bot's PID:  pgrep -f "python.*main.py"
# 3. Send SIGHUP:         kill -HUP <pid>
# 4. Verify in logs:      "[SYSTEM] Whitelist reloaded via SIGHUP."
```

Add this workflow to the deployment notes in `docs/TECHNICAL-REFERENCE.md` §14.

### Verification
```bash
# Start bot
# Remove all entries from whitelist.json (so a test user gets AI responses)
# Start a conversation as the test user — verify AI replies
# Add the test user's ID to whitelist.json
# Send SIGHUP: kill -HUP <pid>
# Verify log: "Whitelist reloaded via SIGHUP. Users in list: 1"
# Send another message as test user — verify it is now ignored by AI
```

---

## Completion Checklist

```
[ ] Task 4.1 — FloodWait handler: all send_message() calls replaced, retry verified
[ ] Task 4.2 — Per-user rate limit: verified for rapid-fire messages, independent users
[ ] Task 4.3 — SIGHUP whitelist reload: verified without restart
[ ] Full smoke test: send many rapid messages to same user, verify rate limiting
[ ] Full smoke test: send FloodWait scenario, verify retry and recovery
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- No messages are silently lost due to Telegram rate limiting
- A single user cannot exhaust the Gemini API quota
- Whitelist can be updated without bot downtime
- The system is significantly more resilient to real-world operating conditions
