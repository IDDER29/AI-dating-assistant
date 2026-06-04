# Plan 10 — Production Hardening

_Week: 6 | Prerequisite: Plans 1, 4, 7, 8 complete | Must complete before: Plan 11_

> **Goal:** Make the system safe to run under a process supervisor (systemd, Docker,
> supervisord) without data loss on shutdown, and resilient to the external dependencies
> it relies on. Fix the Pyrogram lifetime bug. Migrate off an unmaintained library.
> Give the operator a deployment configuration that survives server restarts.

---

## Context: What This Plan Operates On

After Plans 1–9, the codebase's runtime behavior on shutdown is:

```
SIGTERM received
  → _handle_sigterm() raises KeyboardInterrupt
  → asyncio.run(run()) receives KeyboardInterrupt
  → All running coroutines are cancelled (no await for completion)
  → Active dialogue tasks: may be sleeping for up to 3 hours, or awaiting Gemini
  → save_histories() is called once in main.py's except KeyboardInterrupt
  → Bot exits
```

**Problems:**
1. Active `process_dialogue_task()` coroutines are cancelled abruptly — their `finally` blocks run but in-progress work (a partially generated response, an ongoing Gemini call) is abandoned
2. Background `_persist_histories()` tasks spawned via `asyncio.create_task()` are cancelled mid-write
3. The `message` object captured in `process_dialogue_task()`'s closure (for the `message.from_user.first_name` reference) was fetched by Pyrogram hours ago — Pyrogram may have cleaned it up

Additionally:
- `pyrogram 2.0.106` is unmaintained — receives no security patches, may break on Telegram API changes
- No `systemd` unit file exists — deployment is manual (tmux session), not supervised

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| PROD-01 | In-flight dialogue tasks abandoned on shutdown — in-progress work lost |
| PROD-02 | Background persist tasks cancelled mid-write on shutdown |
| PROD-03 | Pyrogram message object lifetime: captured for up to 3-hour task closure |
| PROD-04 | Pyrogram 2.0.106 is unmaintained — security risk and Telegram API breakage risk |
| PROD-05 | No systemd unit file — deployment is manual, no auto-restart on crash |

---

## Task 10.1 — Graceful Shutdown of In-Flight Tasks

**Status:** ⬜ Not started
**Files:** `src/main.py`, `src/app.py`
**Estimated effort:** 2 hours
**Depends on:** Plan 1 complete (storage layer is safe)

### Problem
When SIGTERM is received, `_handle_sigterm()` raises `KeyboardInterrupt`. Python's `asyncio.run()` catches this by cancelling all running tasks, but cancelled `asyncio.Task` objects are not awaited — their work is dropped. The `finally` blocks in `process_dialogue_task()` do execute (cleaning up `active_dialogue_tasks` dict), but:

- An in-progress Gemini API call (which runs in a thread via `asyncio.to_thread`) cannot be cancelled — the OS thread continues running but its result is discarded
- A task sleeping for a 2-hour reply delay loses its position — the user will get no reply until the bot restarts and the next message arrives
- The `_persist_histories()` background task that was in-flight is killed before completing its write

The most important invariant to preserve: **conversation histories and memories must be fully written to disk before the process exits.**

### Root Cause
The SIGTERM handler (Plan 1) was a minimal fix — route to KeyboardInterrupt. It does not give in-flight async work time to complete.

### Implementation

**Step 1:** Replace the `run()` function in `src/app.py` to hold a reference to the app state at the module level, accessible for graceful shutdown.

The module-level `_STATE` already exists. No change needed here.

**Step 2:** Add a `shutdown_gracefully()` async function to `src/app.py`:

```python
# app.py — add after the _heartbeat function:

async def shutdown_gracefully(state):
    """
    Cancel all active dialogue tasks, wait for them to finish (up to 10s),
    then save all data to disk.
    Called from the SIGTERM handler path before the process exits.
    """
    logging.info(
        f"[SHUTDOWN] Graceful shutdown initiated. "
        f"Active dialogue tasks: {len(state.active_dialogue_tasks)}"
    )

    # 1. Cancel all active dialogue tasks
    tasks = list(state.active_dialogue_tasks.values())
    if tasks:
        for task in tasks:
            task.cancel()
        # Give tasks up to 10 seconds to finish their finally blocks
        done, pending = await asyncio.wait(tasks, timeout=10.0)
        if pending:
            logging.warning(
                f"[SHUTDOWN] {len(pending)} task(s) did not finish within 10s. "
                "Proceeding with shutdown anyway."
            )
        else:
            logging.info("[SHUTDOWN] All dialogue tasks completed cleanly.")

    # 2. Cancel the leomatch task if running
    if state.leomatch_task and not state.leomatch_task.done():
        state.leomatch_task.cancel()
        try:
            await asyncio.wait_for(state.leomatch_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # 3. Wait for any pending persist tasks (these are short — < 1s on disk)
    # Gather all tasks named "_persist_histories"
    all_tasks = [t for t in asyncio.all_tasks()
                 if not t.done() and "_persist_histories" in t.get_name()]
    if all_tasks:
        await asyncio.wait(all_tasks, timeout=5.0)

    # 4. Final authoritative save
    from storage import save_histories, save_memories
    save_histories(state)
    save_memories(state)
    logging.info("[SHUTDOWN] History and memories saved. Shutdown complete.")
```

**Step 3:** Modify the SIGTERM/KeyboardInterrupt flow in `main.py` to call `shutdown_gracefully()`.

The challenge: `_handle_sigterm()` is a synchronous signal handler and cannot call async functions directly. The solution is to set a flag that the `run()` function checks, or — cleaner — to run the graceful shutdown inside the event loop before it exits.

Replace the current `main.py` structure:

```python
# main.py — full replacement:

"""
AI Assistant for Telegram Dating Bot
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
    """Warn if sensitive files have world/group-readable permissions."""
    sensitive = [
        pathlib.Path(".env"),
        pathlib.Path("ai_dating_user.session"),
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
        for line in lines:
            line = line.strip()
            if line.isdigit():
                result = delete_user_data(state, int(line))
                logging.info(f"[SYSTEM] Deleted user {line}: {result}")
        delete_file.unlink()
        logging.info(f"[SYSTEM] Processed {len(lines)} deletion request(s).")
    except Exception as e:
        logging.error(f"[SYSTEM] Error processing deletion requests: {e}")


async def _run_with_graceful_shutdown():
    """Wrap run() so KeyboardInterrupt triggers graceful shutdown."""
    try:
        await run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.info("[SYSTEM] Shutdown signal received.")
        state = get_state()
        if state:
            await shutdown_gracefully(state)
        raise


if __name__ == "__main__":
    setup_logging()
    _check_file_permissions()
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
        # Emergency save — graceful shutdown may not have run
        state = get_state()
        if state:
            from storage import save_histories
            save_histories(state)
```

**Step 4:** Export `shutdown_gracefully` from `app.py`:

```python
# app.py — ensure shutdown_gracefully is importable at module level (no changes needed,
# it is already defined at module level after the _heartbeat function)
```

### Verification
```bash
# Test 1: Clean SIGTERM during idle state
# Start bot. Let it reach idle state (waiting for messages).
# kill -TERM <pid>
# Verify logs:
#   "[SHUTDOWN] Graceful shutdown initiated. Active dialogue tasks: 0"
#   "[SHUTDOWN] History and memories saved. Shutdown complete."
# Verify: data files are valid JSON (not zero-byte or truncated)

# Test 2: SIGTERM during active dialogue delay
# Start bot. Have a user send a message.
# While the bot is sleeping in process_dialogue_task(), send SIGTERM.
# Verify logs:
#   "[SHUTDOWN] Graceful shutdown initiated. Active dialogue tasks: 1"
#   "[DISPATCHER] Task for chat with <name> cancelled."  ← from task's CancelledError
#   "[SHUTDOWN] History and memories saved."
# Verify: conversation_histories.json is valid and intact

# Test 3: SIGTERM during Gemini API call
# (Hard to test without mock. Verify the 10s wait timeout message appears
#  if the API call takes longer than 10s)
```

---

## Task 10.2 — Fix Message Object Lifetime in Dialogue Tasks

**Status:** ⬜ Not started
**Files:** `src/dialog.py`
**Estimated effort:** 1 hour
**Depends on:** Nothing (independent)

### Problem
`process_dialogue_task()` captures the full Pyrogram `message` object in its closure:

```python
async def process_dialogue_task(client, message, state, adapter):
    chat_id = message.chat.id          # used immediately — safe
    user_name = message.from_user.first_name  # used throughout the task — RISK
    ...
    await asyncio.sleep(delay)          # up to 3 hours
    ...
    # After 3 hours, still accessing message object:
    user_message = get_message_text(message)   # accesses message.text
```

Pyrogram message objects are tied to the client's session and can be garbage-collected or cleaned up by Pyrogram's internal session management. After a 3-hour sleep, the `message` object's internal state may be stale or invalid.

Additionally, `get_message_text(message)` is called AFTER the grace period and delay sleep, but the buffer mechanism (Plan 3 Task 3.2) already collected the message text into `state.message_buffers[chat_id]` — so `get_message_text(message)` is only the fallback when the buffer is empty. This means the message object is accessed after up to 3 hours of sleep.

### Root Cause
The task was designed to pass the whole `message` object. When burst accumulation was added (Plan 3), the primary path moved to the buffer, but the fallback still reads from the closure-captured `message`.

### Implementation

**Step 1:** In `private_chat_handler()`, extract all needed data from the message immediately at dispatch time and pass it directly to `process_dialogue_task()` instead of the full message object:

```python
# dialog.py — private_chat_handler():

async def private_chat_handler(client, message, state, adapter):
    """Dispatch incoming private messages."""
    chat_id = message.chat.id
    # Extract all needed fields immediately — before the closure is created
    user_name = message.from_user.first_name if message.from_user else "Unknown"

    if chat_id in state.whitelist_ids:
        logging.info(
            f"[DISPATCHER] User {user_name} (ID: {chat_id}) "
            "is in whitelist. Ignoring."
        )
        return

    await adapter.mark_read(chat_id)
    logging.info(f"[DISPATCHER] Message from {user_name} marked as read.")

    # Accumulate message text for burst detection
    text = get_message_text(message)
    if text:
        if chat_id not in state.message_buffers:
            state.message_buffers[chat_id] = []
        state.message_buffers[chat_id].append(text)

    if chat_id in state.active_dialogue_tasks:
        state.active_dialogue_tasks[chat_id].cancel()
        logging.info(
            f"[DISPATCHER] User {user_name} wrote again. Timer restarted."
        )

    # Pass extracted scalar values — NOT the message object
    task = asyncio.create_task(
        process_dialogue_task(client, chat_id, user_name, state, adapter)
    )
    state.active_dialogue_tasks[chat_id] = task
```

**Step 2:** Update `process_dialogue_task()` signature to accept `chat_id` and `user_name` directly instead of the `message` object:

```python
# dialog.py — replace process_dialogue_task signature and internal usage:

async def process_dialogue_task(client, chat_id: int, user_name: str, state, adapter):
    """Background task for a full reply cycle."""
    # chat_id and user_name are now scalar values — no lifetime risk
    try:
        logging.info(
            f"[DIALOG] Waiting {GRACE_PERIOD_SECONDS} sec. in case "
            f"{user_name} is typing more..."
        )
        await asyncio.sleep(GRACE_PERIOD_SECONDS)

        # Collect all buffered messages accumulated during the grace period
        buffered = state.message_buffers.pop(chat_id, [])
        if buffered:
            user_message = "\n".join(buffered)
            if len(buffered) > 1:
                logging.info(
                    f"[DIALOG] Combined {len(buffered)} buffered messages for {user_name}."
                )
        else:
            # No buffer — this happens if the handler ran but text was None
            # (e.g., media-only message with no caption)
            logging.warning(
                f"[DIALOG] No buffered messages for {user_name}. Cancelling."
            )
            return

        # ... rest of function unchanged, but no more `message` references ...
```

Note: Remove the `from utils import get_message_text` call inside `process_dialogue_task` since `message` is no longer available there. The `get_message_text` call in `private_chat_handler` already extracts the text into the buffer.

**Step 3:** Update the `finally` block — remove `message` references (already removed since we don't have it):

```python
    finally:
        state.active_dialogue_tasks.pop(chat_id, None)
        state.message_buffers.pop(chat_id, None)
```

### Verification
```bash
# Test 1: Normal short conversation (< 1 min delay)
# Send a message. Verify: reply arrives correctly, user_name logged correctly.

# Test 2: Media message (photo with no caption)
# Send a photo with no text caption.
# Verify: log shows "No buffered messages... Cancelling." — no crash.

# Test 3: Burst messages
# Send 3 messages in 5 seconds.
# Verify: all 3 appear in combined user_message sent to AI.
# Verify: no message object access after grace period.

# Test 4: Long delay scenario (set MIN_REPLY_INTERVAL to 0, delay to 5s for testing)
# Verify task runs to completion without touching the original message object.
```

---

## Task 10.3 — Migrate from Pyrogram to Pyrofork

**Status:** ⬜ Not started
**Files:** `requirements.txt`, `src/telegram_adapter.py`, `src/main.py`
**Estimated effort:** 1.5 hours
**Depends on:** Plan 7 Task 7.2 complete (TelegramAdapter in place)

### Problem
The project uses `pyrogram==2.0.106` (last released 2023). The project is effectively abandoned — the maintainer has not merged pull requests or released updates since 2023. This creates two risks:

1. **Security**: No patches for vulnerabilities in Pyrogram's MTProto implementation or dependencies
2. **Compatibility**: Telegram updates its MTProto protocol. When it does, Pyrogram will silently fail or break. There is no official fix path.

`pyrofork` is a community-maintained fork of Pyrogram that has continued receiving updates, bug fixes, and compatibility patches. It is API-compatible — imports use the same `pyrogram` namespace (the package installs as `pyrofork` but is imported as `pyrogram` after installation in most configurations).

**Important**: `pyrofork` installs as `pyrogram` — it replaces the `pyrogram` package at the import level. The switch is transparent to all code that imports `from pyrogram import ...`.

### Root Cause
Pyrogram was the standard choice when the project was created. The abandonment post-dates the initial development. `TelegramAdapter` (Plan 7) already isolates all Pyrogram calls to a single module, making migration straightforward.

### Implementation

**Step 1:** Update `requirements.txt` — replace `pyrogram` and `tgcrypto` with `pyrofork`:

```
google-generativeai
pyrofork
tgcrypto
python-dotenv
pytest
pytest-asyncio
```

Note: `tgcrypto` remains — `pyrofork` uses it the same way Pyrogram does for MTProto encryption.

**Step 2:** Run the migration:

```bash
pip uninstall pyrogram -y
pip install pyrofork tgcrypto
```

**Step 3:** Verify all imports still work. The key imports in the codebase are:

- `from pyrogram import Client, filters` — `app.py`
- `from pyrogram import enums` — `telegram_adapter.py`
- `from pyrogram.handlers import MessageHandler, EditedMessageHandler` — `app.py`
- `from pyrogram.errors import UserDeactivated, AuthKeyUnregistered` — `main.py`
- `from pyrogram.errors import FloodWait` — `utils.py`

All of these work unchanged with `pyrofork` because it installs as the `pyrogram` package.

**Step 4:** Add a startup version log so the operator knows which library is running:

```python
# app.py — in run(), right after setup_logging():
import pyrogram
logging.info(f"[SYSTEM] Pyrogram library: {pyrogram.__version__} ({pyrogram.__package__ or 'pyrogram'})")
```

**Step 5:** Update the conftest.py stubs in `tests/conftest.py` to mock `pyrofork` as well as `pyrogram` (in case pyrofork installs differently):

```python
# tests/conftest.py — add after existing pyrogram stub:
# pyrofork installs as "pyrogram" so no additional stub is needed
# but if running tests in an environment where pyrofork is installed,
# the real pyrogram import will be used. The stub is only needed when
# NEITHER package is installed (pure unit test environment).
```

No code change needed — the stubs in `conftest.py` already mock `pyrogram`.

### Verification
```bash
# Step 1: Migration
pip uninstall pyrogram -y
pip install pyrofork tgcrypto
python -c "import pyrogram; print(pyrogram.__version__)"
# Should print pyrofork's version (e.g., 2.1.x or similar)

# Step 2: Run unit tests — should still pass
python -m pytest tests/ -v
# Expected: 36 passed

# Step 3: Full smoke test
python src/main.py
# Bot should start, connect to Telegram, and respond to messages normally
# Log should show: "[SYSTEM] Pyrogram library: X.Y.Z"

# Step 4: Verify FloodWait still works
# The pyrofork FloodWait exception interface is compatible with Pyrogram
# utils.py: from pyrogram.errors import FloodWait — still works
```

---

## Task 10.4 — Systemd Service Unit

**Status:** ⬜ Not started
**Files:** `deploy/ai-dating-assistant.service` (new file), `docs/DEPLOYMENT.md` (new file)
**Estimated effort:** 45 minutes
**Depends on:** Task 10.1 (graceful shutdown must work before setting RestartSec policy)

### Problem
The bot runs in a tmux session. This means:
- The bot stops if the tmux session is killed (server SSH timeout, accidental detach)
- The bot does not restart automatically on crash
- There is no standard log collection (systemd journal vs. file)
- Deployment steps are not documented

### Implementation

**Step 1:** Create `deploy/ai-dating-assistant.service`:

```ini
# deploy/ai-dating-assistant.service
# Systemd unit file for the AI Dating Assistant bot.
#
# Installation:
#   sudo cp deploy/ai-dating-assistant.service /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable ai-dating-assistant
#   sudo systemctl start ai-dating-assistant
#
# Operations:
#   sudo systemctl status ai-dating-assistant   # check status
#   sudo systemctl stop ai-dating-assistant     # sends SIGTERM → graceful shutdown
#   sudo journalctl -u ai-dating-assistant -f   # follow logs
#   sudo kill -HUP $(systemctl show -p MainPID ai-dating-assistant | cut -d= -f2)
#     # reload whitelist without restart

[Unit]
Description=AI Dating Assistant Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=developer
WorkingDirectory=/home/developer/AI-dating-assistant
ExecStart=/usr/bin/python3 src/main.py
Restart=on-failure
RestartSec=30s
# Grace period for shutdown — must be > shutdown_gracefully timeout (10s dialogue + 5s leomatch)
TimeoutStopSec=30s
# Environment
EnvironmentFile=/home/developer/AI-dating-assistant/.env
# Logging — redirect to systemd journal AND the rotating file via logging_setup.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ai-dating-assistant
# Security hardening (optional but recommended)
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Step 2:** Create `docs/DEPLOYMENT.md`:

```markdown
# Deployment Guide

## Prerequisites
- Python 3.11+
- pip packages installed: `pip install -r requirements.txt`
- `.env` file with TELEGRAM_API_ID, TELEGRAM_API_HASH, GEMINI_API_KEY
- Session file `ai_dating_user.session` (created on first run via interactive login)

## First-Time Setup (run once on a new server)

### 1. Clone and install
```bash
cd /home/developer
git clone <repo-url> AI-dating-assistant
cd AI-dating-assistant
pip install -r requirements.txt
```

### 2. Create .env
```bash
cat > .env << EOF
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
GEMINI_API_KEY=your_gemini_key
EOF
chmod 600 .env
```

### 3. Create Telegram session (interactive — must run once manually)
```bash
python src/main.py
# Follow Pyrogram's interactive login: enter phone, verification code
# Session file ai_dating_user.session is created
# Ctrl+C after successful login
chmod 600 ai_dating_user.session
```

### 4. Install systemd service
```bash
sudo cp deploy/ai-dating-assistant.service /etc/systemd/system/
# Edit the service file to set correct User= and WorkingDirectory= paths
sudo systemctl daemon-reload
sudo systemctl enable ai-dating-assistant
sudo systemctl start ai-dating-assistant
```

## Operations Reference

| Action | Command |
|--------|---------|
| Start | `sudo systemctl start ai-dating-assistant` |
| Stop (graceful) | `sudo systemctl stop ai-dating-assistant` |
| Restart | `sudo systemctl restart ai-dating-assistant` |
| Status | `sudo systemctl status ai-dating-assistant` |
| Follow logs | `sudo journalctl -u ai-dating-assistant -f` |
| Reload whitelist | `kill -HUP $(systemctl show -p MainPID ai-dating-assistant \| cut -d= -f2)` |
| Delete user data | `echo "CHAT_ID" > data/delete_requests.txt && kill -USR1 <pid>` |
| Update code | `git pull && sudo systemctl restart ai-dating-assistant` |

## Troubleshooting

**Bot stops after a few hours:**
- Check logs: `sudo journalctl -u ai-dating-assistant --since "2 hours ago"`
- Common: Telegram session expired → delete .session, re-run interactive login

**"Authorization error" in logs:**
- Session file invalid or account banned
- Steps: `sudo systemctl stop ai-dating-assistant`, delete .session, re-run manual login

**API fallback messages being sent:**
- Gemini API key exhausted or invalid
- Check: GEMINI_API_KEY in .env, usage at aistudio.google.com
```

### Verification
```bash
# Install on server (or test locally with systemd on Linux):
sudo cp deploy/ai-dating-assistant.service /etc/systemd/system/
# Edit paths as needed
sudo systemctl daemon-reload
sudo systemctl start ai-dating-assistant
sudo systemctl status ai-dating-assistant
# Should show: Active: active (running)

# Test auto-restart:
sudo kill -9 $(systemctl show -p MainPID ai-dating-assistant | cut -d= -f2)
sleep 35   # wait for RestartSec=30 + startup
sudo systemctl status ai-dating-assistant
# Should show: Active: active (running) (restarted)

# Test graceful shutdown:
sudo systemctl stop ai-dating-assistant
# Should show in logs:
#   "[SHUTDOWN] Graceful shutdown initiated."
#   "[SHUTDOWN] History and memories saved."
```

---

## Completion Checklist

```
[ ] Task 10.1 — Graceful shutdown: SIGTERM waits for tasks, saves data, verified with active task
[ ] Task 10.2 — Message lifetime: process_dialogue_task accepts chat_id/user_name, no message object
[ ] Task 10.3 — pyrofork migration: pip install done, tests pass, smoke test passes
[ ] Task 10.4 — Systemd unit: service file created, starts/stops correctly, auto-restart verified
[ ] pytest: all existing tests pass after changes
[ ] Integration smoke test: start → conversation → SIGTERM → verify data intact
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- SIGTERM triggers graceful shutdown: active tasks are cancelled cleanly, all data saved before exit
- No message object is held in task closures for hours — Pyrogram memory management issue eliminated
- Library is maintained by an active community — security patches and Telegram compatibility updates available
- Systemd unit enables auto-restart on crash, standard log management, and supervised deployment
- Operator has a documented deployment guide and operations reference
- **Plan 11 (code quality) can now be built on a solid production foundation**
