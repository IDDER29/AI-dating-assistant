# Plan 1 — Data Safety Foundation

_Week: 1a | Prerequisite: None | Must complete before: Plans 2, 3, 4, 5, 6_

> **Goal:** Eliminate all data loss scenarios. Make storage safe, recoverable, and non-blocking.
> This plan must be executed first. Every other plan builds on reliable storage.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-01 | Non-atomic write destroys history on crash |
| ISSUE-02 | Corrupt JSON recovery overwrites instead of preserving |
| ISSUE-03 | `save_histories()` hidden inside AI generation function |
| ISSUE-04 | `save_histories()` blocks the asyncio event loop |
| ISSUE-05 | No data retention — files grow forever |

---

## Task 1.1 — Atomic JSON Write

**Status:** ⬜ Not started
**File:** `src/storage.py`
**Estimated effort:** 30 minutes
**Depends on:** Nothing

### Problem
`save_json_data()` truncates the file immediately on open (`"w"` mode). Any crash between truncation and write completion leaves a zero-byte or partial JSON file. Recovery silently overwrites with `{}` — destroying all history.

### Root cause
Standard Python file write with no crash-safety.

### Implementation

**Step 1:** Add `import os` at the top of `storage.py`.

**Step 2:** Replace the body of `save_json_data()`:

```python
def save_json_data(filepath: str | Path, data):
    path = Path(filepath)
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())      # force OS buffer flush to disk
        tmp_path.replace(path)        # atomic rename on POSIX
    except IOError as e:
        logging.error(f"Error saving {path}: {e}")
        tmp_path.unlink(missing_ok=True)   # clean up partial tmp file
```

**Step 3:** Verify `os` is imported at the top of `storage.py`.

### Verification
```bash
# Start bot, generate 2-3 conversation turns
# Then kill with SIGKILL (not SIGINT):
kill -9 <pid>
# Restart — conversation history must be intact
cat data/conversation_histories.json   # must be valid JSON, not {}
```

---

## Task 1.2 — Preserve Corrupt File on Load Failure

**Status:** ⬜ Not started
**File:** `src/storage.py`
**Estimated effort:** 20 minutes
**Depends on:** Task 1.1

### Problem
When `load_json_data()` encounters `JSONDecodeError`, it overwrites the corrupt file with `{}` — destroying all data permanently. There is no backup, no manual recovery path.

A `UnicodeDecodeError` (file saved in wrong encoding) is not caught at all — it propagates to `main.py`'s crash handler, which calls `save_histories()` with an empty state, also overwriting the file with `{}`.

### Implementation

**Step 1:** Add `from datetime import datetime` to `storage.py` imports.

**Step 2:** Replace the `JSONDecodeError` handler in `load_json_data()`:

```python
except (json.JSONDecodeError, UnicodeDecodeError) as e:
    backup_path = path.with_suffix(
        f".corrupt.{int(datetime.now().timestamp())}.json"
    )
    try:
        path.rename(backup_path)
        logging.error(
            f"[STORAGE] Corrupt file at {path}: {e}. "
            f"Backed up to {backup_path}. Starting fresh."
        )
    except OSError as rename_err:
        logging.error(
            f"[STORAGE] Corrupt file at {path}: {e}. "
            f"Could not back up ({rename_err}). File will be overwritten."
        )
    # fall through to create new file with defaults
```

### Verification
```bash
# Corrupt the JSON file manually:
echo "{{broken" > data/conversation_histories.json
# Restart bot
# Verify: a .corrupt.<timestamp>.json backup file exists
# Verify: bot starts fresh with empty histories (no crash)
ls data/
```

---

## Task 1.3 — Move `save_histories()` Off the Event Loop

**Status:** ⬜ Not started
**Files:** `src/ai_client.py`, `src/dialog.py`
**Estimated effort:** 30 minutes
**Depends on:** Task 1.1 (atomic write makes async save safe)

### Problem
`generate_conversation_response()` calls `save_histories(state)` synchronously inside the asyncio event loop thread. This blocks all other coroutines during disk I/O.
Additionally, persistence is a hidden side effect of a generation function — the caller cannot opt out of it.

### Implementation

**Step 1:** Remove `save_histories(state)` from the end of `generate_conversation_response()` in `ai_client.py`:

```python
# REMOVE this line from generate_conversation_response():
save_histories(state)
```

**Step 2:** Remove the `save_histories` import from `ai_client.py` if it is no longer used there.

**Step 3:** Add a background persist helper to `dialog.py`:

```python
# dialog.py — add at module level:
async def _persist_histories(state):
    """Persist conversation histories off the event loop."""
    await asyncio.to_thread(save_histories, state)
```

**Step 4:** In `process_dialogue_task()`, after `ai_response` is received and appended to history, create the persist task:

```python
# After: state.conversation_histories[...].append(model_turn)
asyncio.create_task(_persist_histories(state))
```

**Step 5:** Add `from storage import save_histories` to `dialog.py` imports (if not already present).

### Verification
```bash
# Start bot, send a test message, wait for reply
# Check that reply arrives without delay
# Check that conversation_histories.json is updated
# No blocking visible in logs (no long pauses between log lines)
```

---

## Task 1.4 — Add SIGTERM Handler

**Status:** ⬜ Not started
**File:** `src/main.py`
**Estimated effort:** 15 minutes
**Depends on:** Nothing (independent)

### Problem
`SIGTERM` (sent by systemd, Docker, supervisord) terminates the process immediately with no save. Only `SIGINT` (Ctrl+C) is handled. Every managed deployment discards all in-flight conversation turns.

### Implementation

**Step 1:** Add `import signal` to the imports in `main.py`.

**Step 2:** Add the handler function before the `if __name__ == "__main__"` block:

```python
def _handle_sigterm(signum, frame):
    """Route SIGTERM through the existing KeyboardInterrupt handler."""
    raise KeyboardInterrupt
```

**Step 3:** Register the handler at the start of the `if __name__ == "__main__"` block, before `asyncio.run(run())`:

```python
if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        asyncio.run(run())
    ...
```

### Verification
```bash
# Start bot, generate conversation turns
# Send SIGTERM:
kill -TERM <pid>
# Verify: "Script stopped by user. Saving history..." appears in logs
# Verify: conversation_histories.json is updated with latest turns
```

---

## Task 1.5 — Add Stale Conversation Pruning

**Status:** ⬜ Not started
**Files:** `src/storage.py`, `src/app.py`, `src/config.py`
**Estimated effort:** 45 minutes
**Depends on:** Task 1.1

### Problem
`conversation_histories.json` accumulates user entries forever. No TTL, no archival, no cleanup. Over months, the file grows large, slowing startup parse time and increasing in-memory footprint.

### Implementation

**Step 1:** Add `MAX_CONVERSATION_AGE_DAYS = 90` to `src/config.py`.

**Step 2:** Add `prune_stale_histories()` to `storage.py`:

```python
# storage.py — add imports at top:
from datetime import timezone, timedelta

def prune_stale_histories(state, max_age_days: int = 90) -> int:
    """
    Remove conversation entries whose last turn is older than max_age_days.
    Returns the number of entries pruned.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stale_ids = []

    for user_id, turns in state.conversation_histories.items():
        if not turns:
            stale_ids.append(user_id)
            continue
        last_ts_str = turns[-1].get("timestamp")
        if not last_ts_str:
            continue
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            if last_ts < cutoff:
                stale_ids.append(user_id)
        except ValueError:
            pass  # unparseable timestamp — leave entry alone

    for user_id in stale_ids:
        del state.conversation_histories[user_id]

    if stale_ids:
        logging.info(
            f"[STORAGE] Pruned {len(stale_ids)} stale conversations "
            f"(older than {max_age_days} days)."
        )
    return len(stale_ids)
```

**Step 3:** Call in `app.py`, after `load_histories(state)`:

```python
# app.py — in run(), after load_histories(state):
from storage import prune_stale_histories
from config import MAX_CONVERSATION_AGE_DAYS

pruned = prune_stale_histories(state, MAX_CONVERSATION_AGE_DAYS)
if pruned > 0:
    save_histories(state)   # persist the pruned state immediately
```

### Verification
```bash
# Manually add an old entry to conversation_histories.json:
# Set its last turn timestamp to 91+ days ago
# Restart bot
# Verify: the old entry is gone from the file after restart
```

---

## Completion Checklist

```
[ ] Task 1.1 — Atomic write implemented and verified with SIGKILL test
[ ] Task 1.2 — Corrupt file backup verified (manual corruption test)
[ ] Task 1.3 — save_histories removed from ai_client.py, background task in dialog.py
[ ] Task 1.4 — SIGTERM handler verified (kill -TERM test)
[ ] Task 1.5 — Pruning verified (old timestamp test)
[ ] Full bot smoke test — start → profile → conversation → reply → stop
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- History is never lost on crash or managed shutdown
- Corrupt files are preserved for manual inspection, not silently destroyed
- Event loop is never blocked by disk I/O
- Storage grows at a bounded rate
- **Plans 2, 4, and 6 can now be started**
