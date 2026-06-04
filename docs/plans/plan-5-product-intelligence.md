# Plan 5 — Product Intelligence Layer

_Week: 3 | Prerequisite: Plans 2 + 3 + 6 complete | Must complete before: Plan 7_

> **Goal:** Make the system aware of its own outcomes.
> The product's goal (meeting suggestion) must be detected, recorded, and surfaced.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-21 | No meeting detection — the product goal is unobservable |
| ISSUE-22 | No operator notification channel |
| ISSUE-23 | No system heartbeat — silent hangs are undetectable |
| ISSUE-24 | No goal tracking — system effectiveness is unmeasured |

---

## Task 5.1 — Meeting Signal Detection

**Status:** ⬜ Not started
**Files:** `src/meeting_detector.py` (new), `src/dialog.py`
**Estimated effort:** 1.5 hours
**Depends on:** Plan 6 Task 6.1 (operator notification channel must exist)

### Problem
"Make the match suggest a meeting" is the entire purpose of the system. There is no code to detect this event. The operator must manually monitor dozens of conversations to find the moment of success. The system produces value that is invisible.

### Implementation

**Step 1:** Create `src/meeting_detector.py`:

```python
"""
Detects when a user suggests a real-world meeting in a conversation message.
"""

# Russian meeting signals
SIGNALS_RU = [
    "встретимся", "встретиться", "увидимся", "увидеться",
    "давай встретимся", "предлагаю встретиться", "пойдем куда-нибудь",
    "сходим", "когда ты свободен", "когда ты свободна",
    "выпьем кофе", "попьем кофе", "кофе вместе",
    "погулять вместе", "давай погуляем",
    "встреча", "встретиться лично", "увидеться вживую",
]

# English meeting signals
SIGNALS_EN = [
    "let's meet", "want to meet", "we should meet",
    "meet up", "hang out", "get together",
    "grab coffee", "get coffee", "coffee sometime",
    "when are you free", "are you free",
    "let's get together", "in person", "face to face",
    "go for a walk", "take a walk",
]

ALL_SIGNALS = SIGNALS_RU + SIGNALS_EN


def detect_meeting_signal(text: str) -> bool:
    """
    Returns True if the text contains a meeting suggestion signal.
    Case-insensitive, checks for substring matches.
    """
    if not text:
        return False
    lower = text.lower()
    return any(signal in lower for signal in ALL_SIGNALS)
```

**Step 2:** In `dialog.py`, `process_dialogue_task()`, check for meeting signal after receiving the user's message and before generating a reply:

```python
# dialog.py — add import:
from meeting_detector import detect_meeting_signal
from operator_notify import operator_notify  # from Plan 6 Task 6.1
from stats import record_event              # from Task 5.3

# In process_dialogue_task(), after retrieving user_message:

if detect_meeting_signal(user_message):
    logging.info(
        f"[MEETING] 🎯 Meeting signal detected from {user_name} (ID: {chat_id})!"
    )
    # Add to goal tracking
    state.meeting_signals_detected.add(chat_id)  # from Task 5.2

    # Record the stat
    record_event("meeting_signal", {"chat_id": chat_id, "user_name": user_name})

    # Notify operator via Telegram Saved Messages
    await operator_notify(
        client,
        f"🎯 MEETING SUGGESTED\n\n"
        f"User: {user_name} (ID: {chat_id})\n"
        f"Message: \"{user_message[:300]}\"\n\n"
        f"➡️ Add ID {chat_id} to whitelist.json, then:\n"
        f"   kill -HUP <pid>   (to take over without restart)"
    )
```

### Verification
```bash
# Test with Russian and English meeting signals:
# "давай встретимся" → should detect
# "let's grab coffee" → should detect
# "how are you today" → should NOT detect
# Verify: operator notification arrives in Saved Messages
# Verify: stats.json contains meeting_signal event
```

---

## Task 5.2 — Goal Tracking State

**Status:** ⬜ Not started
**Files:** `src/state.py`, `src/dialog.py`
**Estimated effort:** 30 minutes
**Depends on:** Task 5.1

### Problem
No aggregate data exists about which conversations have achieved the goal. The operator cannot see a summary of progress or historical success rate.

### Implementation

**Step 1:** Add `meeting_signals_detected` to `BotState` in `state.py`:

```python
# state.py
from typing import Set
meeting_signals_detected: Set[int] = field(default_factory=set)
# Set of chat_ids where a meeting signal has been detected
```

**Step 2:** The population of this set is handled in Task 5.1 (`state.meeting_signals_detected.add(chat_id)`).

**Step 3:** Include meeting count in the heartbeat (Plan 6 Task 6.2):

```python
# The heartbeat message will include:
f"Meetings suggested: {len(state.meeting_signals_detected)}"
```

**Step 4:** Log a summary at startup and periodically:

```python
# app.py — after loading histories:
# (Once meeting_signals are persisted in a future iteration, load them here)
logging.info(f"[SYSTEM] Goal tracking initialized. 0 meeting signals in current session.")
```

### Verification
```bash
# Trigger a meeting signal (Task 5.1 test)
# Verify: state.meeting_signals_detected contains the chat_id
# Trigger heartbeat (reduce interval to 60s for testing)
# Verify: heartbeat message includes "Meetings suggested: 1"
```

---

## Task 5.3 — Minimal Stats Recording

**Status:** ⬜ Not started
**Files:** `src/stats.py` (new), `src/leomatch.py`, `src/dialog.py`, `src/ai_client.py`
**Estimated effort:** 1 hour
**Depends on:** Plan 1 Task 1.1 (atomic write should inform stats write pattern)

### Problem
The system generates no aggregate data about its own performance. Opener effectiveness, conversation start rate, meeting signal rate, API fallback rate, and profile filter decisions are all invisible. The operator cannot improve the system without guesswork.

### Implementation

**Step 1:** Create `src/stats.py`:

```python
"""
Minimal event-based stats recorder.
Appends events to data/stats.json, capped at 2000 entries.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

STATS_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.json"
MAX_STATS_ENTRIES = 2000


def record_event(event_type: str, metadata: dict = None):
    """
    Append a timestamped event to stats.json.
    Non-blocking — failures are logged but do not affect the caller.
    """
    entry = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metadata or {})
    }
    try:
        existing = []
        if STATS_PATH.exists() and STATS_PATH.stat().st_size > 0:
            with STATS_PATH.open("r", encoding="utf-8") as f:
                existing = json.load(f)

        existing.append(entry)
        # Keep bounded
        if len(existing) > MAX_STATS_ENTRIES:
            existing = existing[-MAX_STATS_ENTRIES:]

        tmp = STATS_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        tmp.replace(STATS_PATH)

    except Exception as e:
        logging.error(f"[STATS] Failed to record event '{event_type}': {e}")
```

**Step 2:** Add `record_event()` calls at key moments:

```python
# leomatch.py — profile liked:
record_event("profile_liked", {"has_description": bool(description)})

# leomatch.py — profile disliked:
record_event("profile_disliked", {"reason": "no_description" if not description else "ai_rejected"})

# leomatch.py — opener sent:
record_event("opener_sent", {"length": len(intro_message)})

# dialog.py — new conversation started (first reply):
if chat_id_str not in state.conversation_histories or not state.conversation_histories[chat_id_str]:
    record_event("conversation_started", {"chat_id": chat_id})

# dialog.py — after reply sent:
record_event("reply_sent", {"chat_id": chat_id, "ladder": "|||" in ai_response})

# ai_client.py — after fallback returned:
record_event("api_fallback", {"chat_id": chat_id, "reason": "all_retries_exhausted"})

# meeting_detector (Task 5.1) — on meeting signal:
record_event("meeting_signal", {"chat_id": chat_id, "user_name": user_name})
```

**Step 3:** Create `data/stats.json` path directory if it doesn't exist (handled by `record_event`'s try/except through `STATS_PATH.parent.mkdir`). Add `STATS_PATH.parent.mkdir(parents=True, exist_ok=True)` before the write.

### Verification
```bash
# Run bot through a full flow: profile card → like → opener → reply → conversation
# cat data/stats.json | python3 -m json.tool | head -50
# Verify events appear: profile_liked, opener_sent, conversation_started, reply_sent
# Trigger API failure — verify: api_fallback event recorded
# Trigger meeting signal — verify: meeting_signal event recorded
```

---

## Completion Checklist

```
[ ] Task 5.1 — Meeting signal detection: Russian + English signals tested, notification received
[ ] Task 5.2 — Goal tracking state: meeting count appears in heartbeat
[ ] Task 5.3 — Stats recording: all event types verified in stats.json
[ ] End-to-end test: profile → opener → conversation → meeting signal → operator notified
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- The operator is proactively notified when a meeting is suggested
- The system can be evaluated for effectiveness (conversion rate visible in stats)
- Meeting signals are tracked per session
- API failure rate, like/dislike rate, and opener volume are measurable
- **The system's product goal is now observable for the first time**
