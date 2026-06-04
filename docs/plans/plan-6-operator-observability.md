# Plan 6 — Operator Control & Observability

_Week: 2 | Prerequisite: Plan 1 | Can run parallel to Plans 3 + 4_

> **Goal:** Transform the system from a black box into a tool the operator can see and control.
> The operator must receive proactive signals — not hunt through log files.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-22 | No operator notification channel — events invisible unless logs are tailed |
| ISSUE-23 | No heartbeat — silent hangs are undetectable |
| ISSUE-32 | Whitelist requires restart — time-sensitive takeover is slow |
| ISSUE-33 | All tuning requires code changes — persona and delays need restarts |

---

## Task 6.1 — Operator Notification Channel

**Status:** ✅ Done
**File:** `src/operator_notify.py` (new)
**Estimated effort:** 20 minutes
**Depends on:** Nothing (independent)

### Problem
The operator has no proactive communication channel from the bot. Meeting suggestions, API errors, rate limits, data corruption, and other critical events are only visible by actively tailing `ai_bot_logs.txt`. The system produces value that is invisible unless searched for.

The Pyrogram client can send messages to the operator's own Telegram "Saved Messages" (the special self-chat every account has) using `client.send_message("me", text)`. This creates a zero-infrastructure notification channel.

### Implementation

**Step 1:** Create `src/operator_notify.py`:

```python
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
```

**Step 2:** Use this function at critical events (these are wired in other plans):

| Event | Plan | Where |
|-------|------|-------|
| Meeting signal detected | Plan 5, Task 5.1 | `dialog.py` |
| All 3 API retries exhausted | Plan 2, Task 2.2 | `ai_client.py` |
| History file corruption detected | Plan 1, Task 1.2 | `storage.py` |
| System heartbeat | Task 6.2 | `app.py` |
| Critical errors | Task 6.3 | Various |

**Step 3:** Add `operator_notify` call in `ai_client.py` when all retries fail. Update `with_rate_limit_handling()` to accept an optional notify callback, or call it from the caller:

```python
# dialog.py — process_dialogue_task(), after getting fallback response:
ai_response = await generate_conversation_response(chat_id, user_message, state)
if ai_response in ("hm, something went wrong, repeat that",):
    await operator_notify(
        client,
        f"⚠️ API failure for {user_name} (ID: {chat_id}). Fallback message sent."
    )
```

### Verification
```bash
# Start bot
# Check that "me" (Saved Messages) receives a message when:
#   1. Called directly: python3 -c "import asyncio; ..."
#      (or add a test call in app.py startup)
# Verify: message appears in Telegram Saved Messages
# Verify: exception during send is caught (not a crash)
```

---

## Task 6.2 — System Heartbeat

**Status:** ✅ Done
**File:** `src/app.py`
**Estimated effort:** 30 minutes
**Depends on:** Task 6.1

### Problem
The bot can hang silently — event loop stalled, Pyrogram disconnected, asyncio task leak — with no external indication. The operator only discovers the problem when conversations stop happening. By then, hours may have passed.

### Implementation

**Step 1:** Add `_heartbeat()` coroutine to `app.py`:

```python
# app.py — add import:
from operator_notify import operator_notify
from config import HEARTBEAT_INTERVAL_HOURS

# app.py — add function:
async def _heartbeat(app_client, state):
    """Send a periodic status message to operator's Saved Messages."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_HOURS * 3600)
        active_count = len(state.active_dialogue_tasks)
        uptime = datetime.datetime.now(datetime.timezone.utc) - state.start_time
        uptime_hours = int(uptime.total_seconds() // 3600)
        uptime_mins = int((uptime.total_seconds() % 3600) // 60)
        history_count = len(state.conversation_histories)
        meeting_count = len(getattr(state, "meeting_signals_detected", set()))

        await operator_notify(
            app_client,
            f"✅ Bot alive\n"
            f"Uptime: {uptime_hours}h {uptime_mins}m\n"
            f"Active conversations: {active_count}\n"
            f"Total conversations: {history_count}\n"
            f"Meetings detected (session): {meeting_count}"
        )
```

**Step 2:** Add `HEARTBEAT_INTERVAL_HOURS = 6` to `config.py`.

**Step 3:** Start the heartbeat task in `run()`, before `asyncio.Event().wait()`:

```python
# app.py — in run(), just before asyncio.Event().wait():
asyncio.create_task(_heartbeat(state.app, state))
logging.info("[SYSTEM] Heartbeat task started.")
```

**Step 4:** Also send a startup notification so the operator knows the bot is running:

```python
# app.py — after registering handlers, before startup replay:
await operator_notify(
    state.app,
    f"🚀 Bot started\n"
    f"Conversations loaded: {len(state.conversation_histories)}\n"
    f"Whitelist entries: {len(state.whitelist_ids)}"
)
```

### Verification
```bash
# Start bot — verify startup notification arrives in Saved Messages
# Set HEARTBEAT_INTERVAL_HOURS = 0.017 (about 60 seconds) for testing
# Wait 60s — verify heartbeat notification arrives
# Restore HEARTBEAT_INTERVAL_HOURS = 6
```

---

## Task 6.3 — Critical Event Notifications

**Status:** ✅ Done
**Files:** `src/storage.py`, `src/ai_client.py`, `src/dialog.py`
**Estimated effort:** 45 minutes
**Depends on:** Task 6.1

### Problem
Several critical events occur silently with only a log line:
- History file corruption (operator's data is gone — they need to act)
- All API retries exhausted (conversations are broken — operator should know)
- FloodWait repeated failures (bot is being rate-limited — may need cooldown)

### Implementation

**Step 1:** In `storage.py`, add notification after file corruption is backed up (requires passing `client` to `load_json_data`, or using a callback pattern).

**Simpler approach** — log at critical level and let the operator configure log alerts, or use a global async notification queue:

```python
# app.py — add a simple notification queue:
_notify_queue: asyncio.Queue = None

async def _notification_worker(client):
    """Drains the notification queue and sends messages."""
    global _notify_queue
    while True:
        msg = await _notify_queue.get()
        await operator_notify(client, msg)
        _notify_queue.task_done()

# In run(), before asyncio.Event().wait():
_notify_queue = asyncio.Queue()
asyncio.create_task(_notification_worker(state.app))
```

```python
# storage.py — in load_json_data, after renaming corrupt file:
# Push to notification queue (import from app is a circular dependency — use event or log)
# Simplest: use a module-level flag checked at startup
logging.critical(
    f"[STORAGE] ⚠️ CORRUPT DATA FILE backed up to {backup_path}. "
    "History has been reset. Check the backup file."
)
# The startup notification in Task 6.2 will alert the operator on next start
```

```python
# ai_client.py — in with_rate_limit_handling(), after all retries exhausted:
logging.error("[AI] ⚠️ All 3 API retries exhausted. Returning None.")
# Caller in dialog.py detects fallback and can send notification (Task 6.1 Step 3)
```

```python
# dialog.py — FloodWait notification (if all retries fail in safe_send_message):
# safe_send_message returns False → log and optionally notify
result = await safe_send_message(client, chat_id, text)
if not result:
    await operator_notify(
        client,
        f"⚠️ Failed to deliver message to {user_name} (ID: {chat_id}) "
        "after 3 FloodWait retries."
    )
```

### Verification
```bash
# Verify startup notification (from Task 6.2) arrives
# Verify heartbeat arrives after interval
# Simulate API failure — verify "API failure for..." notification
# Simulate FloodWait failure — verify "Failed to deliver..." notification
```

---

## Completion Checklist

```
[x] Task 6.1 — operator_notify.py created; wired in dialog.py for API failure
[x] Task 6.2 — _heartbeat() in app.py; HEARTBEAT_INTERVAL_HOURS=6 in config.py; startup notification sent
[x] Task 6.3 — FloodWait delivery failure notifies operator; API fallback notifies operator
[x] SIGHUP whitelist reload (Plan 4 Task 4.3 — done)
[ ] Manual verification tests
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- Operator receives a startup notification confirming the bot is alive
- Operator receives hourly/configurable heartbeat with live stats
- Critical failures are surfaced proactively, not discovered later
- Whitelist management requires no bot downtime
- **Plan 5 (product intelligence) can now be started**
- **The system is no longer a black box**
