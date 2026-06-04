# Failure Analysis — AI Dating Assistant

_Last updated: 2026-06-04_

> This document catalogs every failure mode, error handler, silent failure, dangerous assumption,
> and missing guard in the system. Severity ratings: **Critical** (data loss / system halt),
> **High** (silent misbehavior), **Medium** (degraded function), **Low** (minor / cosmetic).

---

## Table of Contents

1. [Error Handling Inventory](#1-error-handling-inventory)
2. [API Failure Scenarios](#2-api-failure-scenarios)
3. [Filesystem Failure Scenarios](#3-filesystem-failure-scenarios)
4. [Input Validation Edge Cases](#4-input-validation-edge-cases)
5. [Concurrency and Race Conditions](#5-concurrency-and-race-conditions)
6. [Silent Failures Catalog](#6-silent-failures-catalog)
7. [Dangerous Assumptions](#7-dangerous-assumptions)
8. [Missing Error Handling](#8-missing-error-handling)
9. [Failure Interaction Matrix](#9-failure-interaction-matrix)
10. [Severity Summary](#10-severity-summary)

---

## 1. Error Handling Inventory

Every explicit error handler in the codebase:

### `main.py`

```python
except (UserDeactivated, AuthKeyUnregistered) as e:
    logging.critical(f"Authorization error: {e}. Delete .session file and restart.")
```
**What it catches:** Telegram session invalidation — account logged out, banned, or session file corrupted.
**What it does:** Logs critical message. Does NOT call `save_histories()`.
**Gap:** History is not saved. If the session expired mid-conversation, the last few turns are lost.

```python
except KeyboardInterrupt:
    logging.info("Script stopped by user. Saving history...")
    state = get_state()
    if state: save_histories(state)
```
**What it catches:** Ctrl+C (SIGINT).
**What it does:** Saves history, exits cleanly.
**Gap:** Only handles SIGINT. SIGTERM (systemd, Docker stop) is not handled.

```python
except Exception as e:
    logging.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
    state = get_state()
    if state: save_histories(state)
```
**What it catches:** Any unhandled exception from `run()`.
**What it does:** Logs with traceback, saves history.
**Gap:** `save_histories()` itself can throw `IOError` — if it does here, the exception is unhandled and the process exits without saving.

---

### `app.py`

```python
try:
    bot_peer = await state.app.resolve_peer(BOT_USERNAME)
except Exception as e:
    logging.critical(f"Could not find bot @{BOT_USERNAME}: {e}")
    return
```
**What it catches:** @leomatchbot unreachable at startup.
**What it does:** Logs critical, returns from `run()`. Clean shutdown — no crash.
**Gap:** `return` exits the `async with state.app` context, which disconnects Pyrogram. `main.py`'s `asyncio.run(run())` returns normally — no exception, no `save_histories()` called. History state at startup is not saved (though it was just loaded, so nothing is lost).

```python
if not state.model or not state.app:
    logging.critical("Application cannot start due to initialization error.")
    return
```
**What it catches:** Failed AI or Telegram initialization.
**What it does:** Clean early exit before any handlers are registered.

---

### `ai_client.py`

```python
except Exception as e:
    logging.error(f"Failed to configure Google Gemini model: {e}")
    state.model = None
```
**What it catches:** Any exception during `genai.configure()` or `GenerativeModel()`.
**What it does:** Sets `state.model = None`. All generation functions detect this and return fallback strings.
**Quality:** Well-handled. The system degrades gracefully.

```python
except google_exceptions.ResourceExhausted as e:
    retry_delay = 60
    ...
    await asyncio.sleep(retry_delay)
```
**What it catches:** HTTP 429 rate limit from Gemini.
**What it does:** Parses retry-after from error metadata, sleeps, retries (up to 3 attempts).
**Gap:** Only catches `ResourceExhausted`. Other HTTP errors (`ServiceUnavailable` 503, `DeadlineExceeded` 504, network errors) are NOT caught here and propagate up to the caller.

After 3 failed attempts:
```python
logging.error("Failed to execute API request after several attempts.")
return None
```
**What it does:** Returns `None`. Callers return fallback strings.

---

### `leomatch.py`

```python
except asyncio.CancelledError:
    logging.info("[LEOMATCH-TASK] Task cancelled (fresher profile arrived).")
except Exception as e:
    logging.error(f"[LEOMATCH-TASK] Error in profile processing task: {e}", exc_info=True)
```
**What it catches:** Task cancellation (expected) and any other exception in the background task.
**What it does:** Logs and exits the task.
**Gap:** Does NOT clean up `state.leomatch_task`. After an exception, `state.leomatch_task` still holds the reference to the failed task. The next incoming profile card calls `state.leomatch_task.done()` — a done (but failed) task returns `True` for `done()`, so no erroneous cancellation occurs. This is safe but `state.leomatch_task` is never explicitly cleared to `None`.

---

### `dialog.py`

```python
except asyncio.CancelledError:
    logging.info(f"[DISPATCHER] Task for chat with {user_name} cancelled.")
except Exception as e:
    logging.error(f"[DIALOG] Error in dialogue processing task: {e}", exc_info=True)
finally:
    state.active_dialogue_tasks.pop(chat_id, None)
```
**What it catches:** Task cancellation (debounce) and any exception during reply cycle.
**What it does:** Logs, cleans up task dict entry.
**Quality:** The `finally` block is correct — it always runs regardless of how the task ends.
**Gap:** If an exception occurs AFTER the user message is appended to history but BEFORE the model response is appended, the history ends in an orphaned user turn. This is the role-alternation violation described in the data model analysis.

---

### `storage.py`

```python
except json.JSONDecodeError as e:
    logging.error(f"JSON decoding error in {path}: {e}. File will be overwritten.")
```
**What it catches:** Corrupted JSON file on load.
**What it does:** Falls through to create a new file with default data (`{}` for histories, `[]` for whitelist).
**Severity:** **Critical** — this silently destroys all conversation history. The operator gets a log line but no warning before data is gone.

```python
except IOError as e:
    logging.error(f"Failed to create/write file {path}: {e}")
    return default_data
```
**What it catches:** Filesystem errors during file creation.
**What it does:** Returns default data. The file may not exist after this.

```python
except IOError as e:
    logging.error(f"Error saving {path}: {e}")
```
**What it catches:** Filesystem error during save.
**What it does:** Logs. The in-memory state is unaffected. The next save attempt will retry.
**Gap:** No retry mechanism. If the disk is full, every subsequent save attempt also fails silently. The in-memory state continues updating correctly but nothing is persisted.

---

## 2. API Failure Scenarios

### 2.1 Gemini API — HTTP 429 (Rate Limit)

**What happens:** `ResourceExhausted` raised inside `asyncio.to_thread`.
**Recovery:** `with_rate_limit_handling` retries up to 3×, honoring `retry-after` metadata.
**Outcome if all retries fail:** Fallback string returned. User receives `"hm, something went wrong, repeat that"`.
**History side effect:** The user's turn was appended BEFORE the failed call. No model turn is appended. **Orphaned user turn in history.**
**Severity:** Medium for functionality, High for history integrity.

### 2.2 Gemini API — HTTP 503 (Service Unavailable)

**What happens:** `google.api_core.exceptions.ServiceUnavailable` raised.
**Recovery:** **NOT caught by `with_rate_limit_handling`** — only `ResourceExhausted` is caught.
`ServiceUnavailable` propagates out of `with_rate_limit_handling`, out of `generate_conversation_response`, and is caught by `dialog.py`'s `except Exception as e`.
**Outcome:** Task exits with error log. Fallback string is NOT sent. User gets no reply.
**Orphaned user turn:** YES — appended before the failed call, never cleaned up.
**Severity:** High — silent failure from the user's perspective; broken history.

### 2.3 Gemini API — Network Timeout

**What happens:** The `asyncio.to_thread` call to the Gemini SDK may hang indefinitely if there is no timeout configured on the SDK's HTTP client.
**Recovery:** None. The task waits forever in `asyncio.to_thread`.
**Effect:** `state.active_dialogue_tasks[chat_id]` holds a zombie task. If the user sends another message, the zombie task is cancelled (debounce). If the user doesn't send another message, the task hangs forever, consuming a thread pool slot.
**Severity:** High — thread leak under network partition conditions.

```python
# Current code — no timeout:
return await asyncio.to_thread(api_call)

# Correct approach:
return await asyncio.wait_for(asyncio.to_thread(api_call), timeout=30.0)
```

### 2.4 Gemini Model Deprecated

**What happens:** `"gemini-1.5-flash-latest"` resolves to a retired model. API returns an error on every call.
**Recovery:** Depends on error type. If it's `NotFound` (404) or `InvalidArgument`, it is NOT caught and propagates to `except Exception` in the caller.
**Outcome:** Every AI call fails. Every reply is a fallback string or no reply at all.
**Detection:** Only visible in logs. No alerting mechanism exists.
**Severity:** High (silent degradation).

### 2.5 Telegram Network Disconnect

**What happens:** Pyrogram loses TCP connection to Telegram MTProto servers.
**Recovery:** Pyrogram has a built-in reconnect mechanism — it automatically reconnects and re-establishes the session.
**Effect during reconnect:** Incoming messages during the disconnect window may be missed or received in bulk when reconnected (depending on Telegram's update delivery guarantees).
**Pyrogram behavior:** Replays missed updates on reconnect within a short window (typically < 60 seconds of messages are replayed).
**Severity:** Low — Pyrogram handles this transparently.

### 2.6 Telegram Rate Limiting (FloodWait)

**What happens:** Pyrogram throws `FloodWait` exception when the bot sends too many messages too quickly.
**Recovery:** Pyrogram's `send_message` and other methods raise `FloodWait` with a `.x` attribute (seconds to wait). **The codebase does NOT handle `FloodWait`.**
`FloodWait` propagates out of `process_leomatch_message` or `process_dialogue_task`, caught by `except Exception as e` in the respective background task handler.
**Outcome:** Current task fails and is abandoned. The message that triggered FloodWait is not sent. No retry.
**Severity:** High — message loss without notification.

### 2.7 Pyrogram API — resolve_peer Fails at Startup

**What happens:** `@leomatchbot` cannot be found (bot deleted, username changed, network issue).
**Recovery:** Caught explicitly. `logging.critical(...)`, `return` from `run()`.
**Outcome:** Bot does not start. Process exits cleanly. Operator must check logs.
**Severity:** Medium — clean failure, but no automated recovery.

---

## 3. Filesystem Failure Scenarios

### 3.1 conversation_histories.json — Mid-Write Corruption

**Trigger:** Process killed (OOM, SIGKILL, power loss) while `save_json_data` is writing.

```python
with path.open("w", encoding="utf-8") as f:   # FILE TRUNCATED HERE
    json.dump(data, f, ...)                     # PARTIAL WRITE POSSIBLE
```

**What happens:** File is truncated to zero bytes (or partial JSON) before the OS flushes the write buffer.
**Recovery in `load_json_data`:**
```python
if path.exists() and path.stat().st_size > 0:
    try: json.load(f) ...
    except JSONDecodeError: # fall through to overwrite
```
If `stat().st_size > 0` (partial write): `json.load` throws `JSONDecodeError` → file overwritten with `{}`.
If `stat().st_size == 0` (full truncation): condition `size > 0` is False → file overwritten with `{}`.
**Outcome:** All conversation history is destroyed. No backup. No warning beyond a log line.
**Severity:** **Critical.**

### 3.2 conversation_histories.json — Disk Full

**Trigger:** Disk reaches 100% capacity during `save_json_data`.

**What happens:** `path.open("w")` succeeds (truncates file to zero), but `json.dump` throws `IOError` mid-write.
**Recovery:** `except IOError as e: logging.error(...)` — the IOError is caught.
**State of file:** Truncated to zero bytes. The `except` block does not restore original content.
**Outcome:** All history destroyed. In-memory state is intact. Future saves continue failing until disk space is freed.
**Severity:** **Critical** — same data loss as mid-write corruption, but potentially recoverable if disk space is freed quickly and in-memory state is not corrupted.

### 3.3 whitelist.json — File Deleted at Runtime

**Trigger:** Operator deletes `whitelist.json` while the bot is running.

**What happens:** Nothing immediately. `state.whitelist_ids` was loaded into memory at startup and is never re-read.
**Outcome:** Whitelist continues functioning from in-memory set until bot restarts. On restart, `load_whitelist` calls `load_json_data` which creates a new empty `whitelist.json` with `[]`. **All whitelist entries are lost.**
**Severity:** High — silent data loss on restart.

### 3.4 data/ Directory Missing

**Trigger:** `data/` directory deleted.

**What happens:** `load_json_data` calls `path.parent.mkdir(parents=True, exist_ok=True)` before creating files.
**Outcome:** Directory is recreated. Both JSON files are recreated with empty defaults.
**Severity:** Medium — handled correctly for reads, but history/whitelist are lost if they were in the deleted directory.

### 3.5 ai_bot_logs.txt — Write Failure

**Trigger:** Log file write fails (disk full, permissions).

**What happens:** Python's `logging` module silently swallows write errors to file handlers. The `StreamHandler` (stdout) continues working.
**Outcome:** Log entries go to console only. No crash. No indication that file logging stopped.
**Severity:** Low — no functional impact, but debugging becomes harder.

---

## 4. Input Validation Edge Cases

### 4.1 Profile Card with Unusual Formatting

**Input:** `@leomatchbot` sends a profile card with unexpected formatting.

| Variant | `ANKET_PATTERN` result | Outcome |
|---------|----------------------|---------|
| `"Anna, 24, Moscow"` (no description) | Matches — group(4) = None | `description = None` → `len(None.strip())` → **AttributeError** |
| `"Anna, 24, Moscow — "` (empty description) | Matches — group(4) = "" | `len("".strip()) = 0 ≤ 10` → dislike (correct) |
| `"Anna, twenty four, Moscow — ..."` | Does NOT match (\d+ requires digits) | Treated as unrecognized text → logged as warning |
| `"Anna, 24, Moscow\n— description"` | Matches (re.DOTALL handles newlines) | Correct |
| Profile card with emoji in name: `"🌸Anna, 24..."` | Matches (`.+?` matches emoji) | Correct |

**Severity of AttributeError case:** High. `description = match.group(4)` returns `None` when the optional group doesn't match (no `—` separator). The code does:
```python
description = match.group(4)
if description and len(description.strip()) > 10:
```
The `if description and ...` check DOES guard against `None` → `description` is falsy when `None`. **This is actually safe.** The `AttributeError` scenario above was incorrect — `None` is falsy and `len()` is never called. The code handles this correctly.

### 4.2 Opener Generation — Profile Description Edge Cases

| Input to `generate_first_message` | Processing |
|----------------------------------|-----------|
| Profile with description < 15 chars (e.g., `"Anna, 24, Moscow — hi"`) | `profile_text` substituted with "Profile description is short or meaningless" — correct |
| Profile with no description (group(4) = None) | `match.group(4)` is None → `profile_text = ""` → len 0 < 15 → substituted — correct |
| `anket_text` doesn't match ANKET_PATTERN at all | `match = None` → `match.group(4)` → **AttributeError on None** |

**Severity:** Medium. `generate_first_message` is only called from `process_leomatch_message` after `ANKET_PATTERN.match(text)` already succeeded and stored the text. The text passed to `generate_first_message` is always `state.last_seen_anket_text`, which was set only when the pattern matched. So this AttributeError path is unreachable in normal operation — but it would occur if `generate_first_message` were ever called with arbitrary text.

### 4.3 Gemini Response Longer Than 300 Characters (First Message)

```python
if len(intro_message) > 300:
    intro_message = "your profile caught my eye, but my brain is striking today..."
```
**Handled correctly.** Fallback is used. The fallback itself is 100 characters — well within limit.

### 4.4 Gemini Response Containing Only `|||`

**Input:** AI returns `"|||"`
```python
parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
```
`"|||".split("|||")` = `["", ""]` → `[p.strip() for p in ["", ""] if p.strip()]` = `[]`

**Outcome:** `parts` is an empty list. The `for part in parts` loop executes zero times. **No message is sent.** The user gets no reply. History contains a model turn with `"|||"` as content.
**Severity:** Medium — silent no-op. User never gets a response. No log line indicates this happened.

### 4.5 Gemini Response Containing `|||` at Start or End

**Input:** `"|||hello"` or `"hello|||"`
```python
"|||hello".split("|||") = ["", "hello"]
[p.strip() for p in ["", "hello"] if p.strip()] = ["hello"]
```
**Outcome:** Empty parts filtered. Single message `"hello"` sent. Correct.

### 4.6 Message Text Is `None` (No Text, No Caption)

```python
user_message = get_message_text(message)
if not user_message:
    logging.warning(...)
    return
```
**Handled.** Sticker, photo without caption, voice message, etc. — all produce `None` from `get_message_text`. The task exits without sending a reply. **However, the user's message was already added to history before this check in some paths.**

In `generate_conversation_response`, the check is:
```python
user_message = get_message_text(message)
if not user_message:
    logging.warning(...)
    return  # ← returns before appending to history
```
Wait — the `get_message_text` check and the history append are in **different functions**. The flow is:
1. `process_dialogue_task` calls `get_message_text(message)` → checks for None → returns if None
2. Only if not None: calls `generate_conversation_response(chat_id, user_message, state)`
3. `generate_conversation_response` then appends to history

So non-text messages are handled correctly — history is not corrupted.

### 4.7 Extremely Long User Message

No character limit is enforced on incoming messages. A user could send a message with thousands of characters. This contributes to a history entry with a very large `parts[0]` string. When this is included in the Gemini API payload, it could push the total context toward the model's token limit, especially if several long messages exist in the 20-turn window.
**Severity:** Low at current scale — Gemini Flash has a large context window (1M tokens). Would require pathologically long messages to matter.

### 4.8 User ID Collision Between String and Integer Contexts

A user with ID `123` would be stored in `conversation_histories` under key `"123"` (string) and in `whitelist_ids` as `123` (integer). The whitelist check is:
```python
if chat_id in state.whitelist_ids:  # chat_id is int, whitelist_ids is Set[int]
```
Correct — integer comparison on integers.

The history lookup is:
```python
chat_id_str = str(chat_id)
state.conversation_histories[chat_id_str]
```
Correct — string key lookup.

These two are never compared against each other in code, so no collision risk exists. **However**, if a developer ever tries to cross-reference them (e.g., "does this whitelisted user have history?"), the type mismatch is a trap.

---

## 5. Concurrency and Race Conditions

### 5.1 History Dict Mutated During asyncio.to_thread

**Scenario:** Two conversations (Anna and Barb) both complete their AI calls at almost the same time.

```
T=0ms:  Anna's to_thread Gemini call completes (OS thread A)
T=1ms:  Barb's to_thread Gemini call completes (OS thread B)
```

Both threads attempt to return their results to the asyncio event loop. The event loop processes them sequentially (cooperative scheduling ensures only one coroutine runs at a time), but the Gemini call itself ran in a real OS thread.

**The actual execution:**
- Thread A returns → event loop resumes Anna's coroutine → appends Anna's turn → `save_histories()`
- Thread B returns → event loop resumes Barb's coroutine → appends Barb's turn → `save_histories()`

Because the event loop is single-threaded and `asyncio.to_thread` only runs the blocking call in a thread (not the Python state mutations), all mutations to `state.conversation_histories` happen in the event loop thread sequentially. **No race condition on the dict.**

**The real risk:** `save_histories()` performs file I/O. If the file I/O call itself were not blocking (it is, via synchronous `open`/`write`), two simultaneous writes would interleave. But since all of this runs in the single event loop thread (not in threads), the saves are sequential.

**Verdict:** No race condition. The asyncio single-thread model protects all in-memory state. ✓

### 5.2 leomatch_task Reference — Check-Then-Act Gap

```python
if state.leomatch_task and not state.leomatch_task.done():
    state.leomatch_task.cancel()
state.leomatch_task = asyncio.create_task(...)
```

In asyncio, this entire block runs atomically (no `await` between check and assign). No other coroutine can run between these lines. **No TOCTOU race condition.** ✓

### 5.3 active_dialogue_tasks — Check-Then-Act Gap

```python
if chat_id in state.active_dialogue_tasks:
    state.active_dialogue_tasks[chat_id].cancel()
task = asyncio.create_task(process_dialogue_task(...))
state.active_dialogue_tasks[chat_id] = task
```

Same reasoning — no `await` between check and update. Atomic in the event loop. **No race condition.** ✓

### 5.4 Task Cancellation During finally Block

**Scenario:** A task is in its `finally` block executing `state.active_dialogue_tasks.pop(chat_id, None)` when another coroutine tries to cancel it.

In asyncio, cancellation is cooperative. `CancelledError` is only delivered at `await` points. The `finally` block contains no `await` — it's a synchronous dict operation. **The `finally` block always runs to completion even if the task is cancelled.** ✓

### 5.5 save_histories Called Concurrently From Multiple Paths

`save_histories` can be called from:
1. `ai_client.generate_conversation_response()` — after every AI reply
2. `main.py` `except KeyboardInterrupt` — on Ctrl+C
3. `main.py` `except Exception` — on crash

Can (1) and (2) happen simultaneously? `KeyboardInterrupt` is raised in the event loop thread at an `await` point. If the event loop is inside `asyncio.to_thread` (Gemini API call), the `KeyboardInterrupt` is deferred until the `to_thread` call returns. By the time Python processes the interrupt, the `to_thread` call has completed and `generate_conversation_response` may or may not have called `save_histories` already.

**Scenario:** `to_thread` returns just before `KeyboardInterrupt` fires. `generate_conversation_response` calls `save_histories()`. Then `KeyboardInterrupt` fires, propagates to `main.py`, which calls `save_histories()` again.

**Outcome:** Two sequential file writes of the same data. Second write wins. No data loss, no corruption. This is benign because asyncio is single-threaded. ✓

### 5.6 Orphaned User Turn on API Failure (Logical Race)

This is not a concurrency race but a logical state inconsistency:

```python
# In generate_conversation_response:
state.conversation_histories[chat_id_str].append(user_turn)  # APPENDED
result = await with_rate_limit_handling(...)                  # CAN FAIL
if result:
    state.conversation_histories[chat_id_str].append(model_turn)
    save_histories()
    return cleaned_response
return fallback_message   # ← user turn is in history, no model turn
```

After a fallback return:
- History: `[..., user_turn]` — ends on user role
- Next call: `[..., user_turn, next_user_turn]` — two consecutive user roles
- Gemini receives two consecutive user turns → produces unpredictable output

**Severity:** High — silent history corruption that compounds over time.

---

## 6. Silent Failures Catalog

These failures produce no error visible to the user or operator unless logs are actively monitored.

| # | Scenario | Visible symptom | Log level |
|---|---------|----------------|-----------|
| 1 | Gemini API 503 — task abandoned | User gets no reply | ERROR |
| 2 | Gemini timeout — task hangs | No reply until user sends another message (debounce reset) | None |
| 3 | `|||`-only response — no message sent | User gets no reply | None |
| 4 | Opener skipped after restart (pending profile lost) | Mutual match gets no message | WARNING |
| 5 | History destroyed by corrupt JSON on load | All conversation context gone; bot starts fresh with everyone | ERROR |
| 6 | FloodWait exception — message lost | Bot fails to send, retries never happen | ERROR |
| 7 | Gemini model deprecated — all replies are fallback strings | Conversations become generic/incoherent | ERROR |
| 8 | Disk full — saves silently fail | In-memory state correct; disk not updated | ERROR |
| 9 | Orphaned user turn after API failure | Next Gemini response subtly off-context | None |
| 10 | Second like sent on same profile after restart | @leomatchbot may handle silently or show an error | None |
| 11 | Whitelist not reloaded while running | New whitelist entries ignored until restart | None |
| 12 | `cleanup_ai_response` removes content-bearing dashes | Response meaning altered without notification | None |

---

## 7. Dangerous Assumptions

### Assumption 1 — `state.last_seen_anket_text` is always fresh when "write message" arrives

**Code:**
```python
if "Write a message for this user" in text:
    if state.last_seen_anket_text:
        intro = await generate_first_message(state.last_seen_anket_text, state)
```

**Assumption:** The stored profile text belongs to the user for whom the "write message" prompt was just received.

**Why it can be wrong:**
- Profile A is liked → `last_seen_anket_text` = Profile A text
- Profile B is liked before A's match arrives → `last_seen_anket_text` = Profile B text (overwritten)
- Profile A's mutual match arrives → "write message" prompt received
- Opener is generated using **Profile B's description** for **Profile A's user**

The opener references the wrong person's profile. Anna gets an opener about Barb's hobbies.
**Severity:** High — silent content error with no indication.

---

### Assumption 2 — Pyrogram message objects are valid for the entire task lifetime

**Code:**
```python
task = asyncio.create_task(process_dialogue_task(client, message, state))
```

The `message` object is captured in the task closure at creation time. The task may sleep for up to 3 hours (long mode). During this time:

```python
# Inside process_dialogue_task, after the 3-hour sleep:
user_message = get_message_text(message)
# message.from_user.first_name used throughout for logging
```

**Assumption:** The Pyrogram `Message` object remains valid in memory for up to 3 hours.

Pyrogram holds all received update objects in memory until they are garbage-collected. As long as the task closure holds a reference to `message`, it won't be GC'd. **However**, if Pyrogram's internal update cache has a memory limit and evicts old messages, the object could become stale. This behavior is undocumented.

**In practice:** For typical message objects with simple text, this is safe. For messages containing media objects (photos, documents), the media data may be separately managed and could become invalid.
**Severity:** Low-Medium — unlikely to trigger but unverifiable without testing long-mode delays.

---

### Assumption 3 — JSON files are always valid UTF-8

**Code:**
```python
with path.open("r", encoding="utf-8") as f:
    return json.load(f)
```

**Assumption:** The file was written as UTF-8 and has not been corrupted by a non-UTF-8 write (e.g., direct editing in a Windows editor that saved as Windows-1251).

If the file is saved in a different encoding, `open(..., encoding="utf-8")` raises `UnicodeDecodeError`. This is NOT caught by `except json.JSONDecodeError`. It propagates up through `load_json_data`, through `load_histories`, out of `app.run()`, and is caught by `main.py`'s `except Exception` — which then calls `save_histories()` with an empty (just-initialized) `state.conversation_histories`, **overwriting the corrupted file with `{}`**.

**Severity:** High — a misconfigured editor destroys all history with no clear error message.

---

### Assumption 4 — `@leomatchbot` message format never changes

The entire Scout pipeline is built around:
```python
ANKET_PATTERN = re.compile(r"^(.+?),\s*(\d+),\s*(.+?)(?:[-–—]\s*(.*))?$", re.DOTALL)
KNOWN_SYSTEM_MESSAGES = {"✨🔍", "Like sent, waiting for a response.", ...}
```

And hardcoded strings:
```python
"Write a message for this user"
"1. View profiles"
"💌 / 📹"
"👎"
```

**Assumption:** `@leomatchbot`'s message format, button texts, and navigation commands remain unchanged indefinitely.

**Risk:** `@leomatchbot` is a third-party service with no SLA, no public API documentation, and no change notifications. A single redesign of the bot's interface (new language, changed button format, restructured profile cards) silently breaks the Scout pipeline. The system continues running but sends wrong commands or processes no profiles.

**Detection:** Only detectable by monitoring logs for `"[LEOMATCH-EXECUTOR] Unrecognized text"` warnings. No automated alerting.
**Severity:** High — silent and total Scout failure on any @leomatchbot update.

---

### Assumption 5 — Gemini always returns `result.text` as a string

**Code:**
```python
if result and hasattr(result, "text"):
    return cleanup_ai_response(getattr(result, "text"))
return fallback_message
```

**Assumption:** If the result object exists and has a `.text` attribute, that attribute is a non-empty string.

**What could go wrong:**
- `result.text` could be `None` if the model's response was blocked by safety filters
- `result.text` could be an empty string `""` if the model returned an empty completion
- `cleanup_ai_response("")` returns `""` — an empty string
- Sending `client.send_message(chat_id, "")` — Telegram rejects empty messages, raising an exception
- That exception propagates out of `process_dialogue_task`, caught by `except Exception`, task exits, user gets no reply

**Severity:** Medium — if Gemini's safety filters trigger on a conversation, the user gets no reply and no indication of why.

---

### Assumption 6 — The `data/` directory is writable

`storage.py` calls `path.parent.mkdir(parents=True, exist_ok=True)` before writes but this call itself can throw `PermissionError` if the filesystem is read-only or the process lacks write permissions. `PermissionError` is not `IOError`'s subclass in all Python versions.

Actually, `PermissionError` IS a subclass of `OSError` which IS `IOError` (they are aliases in Python 3). So the `except IOError` block catches it. **Safe.** ✓

---

## 8. Missing Error Handling

These are failure scenarios the code does not handle at all:

### Missing 1 — No `FloodWait` handler (Severity: High)

`pyrogram.errors.FloodWait` is raised by Pyrogram when Telegram rate-limits the account. It carries a `.x` attribute (seconds to wait). The bot sends messages at:
- Every profile like/dislike (every 70 seconds under load)
- Every conversation reply

Neither `leomatch.py` nor `dialog.py` catches `FloodWait`. It propagates to the background task's `except Exception` handler, which logs it and exits the task. The message that triggered it is lost.

**Fix:**
```python
from pyrogram.errors import FloodWait

try:
    await client.send_message(chat_id, text)
except FloodWait as e:
    await asyncio.sleep(e.x)
    await client.send_message(chat_id, text)
```

### Missing 2 — No timeout on Gemini API calls (Severity: High)

`asyncio.to_thread` has no timeout. A hanging Gemini request blocks the thread pool slot indefinitely.

**Fix:**
```python
return await asyncio.wait_for(asyncio.to_thread(api_call), timeout=30.0)
```
With `asyncio.TimeoutError` caught and treated like a failed attempt.

### Missing 3 — No handling for non-ResourceExhausted Gemini errors (Severity: High)

`with_rate_limit_handling` only catches `ResourceExhausted`. `ServiceUnavailable`, `DeadlineExceeded`, `InternalServerError`, and `ConnectionError` all propagate unhandled.

**Fix:**
```python
except (google_exceptions.ResourceExhausted,
        google_exceptions.ServiceUnavailable,
        google_exceptions.DeadlineExceeded,
        google_exceptions.InternalServerError) as e:
    # existing retry logic
```

### Missing 4 — No orphaned user turn cleanup (Severity: High)

After a failed API call that returns the fallback string, the user's turn remains in history with no corresponding model turn. The next interaction appends another user turn, producing consecutive user turns in the history.

**Fix:**
```python
state.conversation_histories[chat_id_str].append(user_turn)
try:
    result = await with_rate_limit_handling(...)
    if result and hasattr(result, "text"):
        ...
        return cleaned
    else:
        # Remove the user turn we just appended — call failed
        state.conversation_histories[chat_id_str].pop()
        return fallback_message
except Exception:
    state.conversation_histories[chat_id_str].pop()
    raise
```

### Missing 5 — No SIGTERM handler (Severity: Medium)

Documented in engineering decisions. Process managers send SIGTERM before SIGKILL. Without a handler, history is not saved on managed shutdown.

### Missing 6 — No empty AI response guard before send (Severity: Medium)

```python
# Missing check before send:
if not ai_response:
    logging.warning("[DIALOG] AI returned empty response. Skipping send.")
    return
```

### Missing 7 — No health check or watchdog (Severity: Low)

The process can become a "zombie" — running but not processing events — if Pyrogram's reconnect fails silently or if the event loop becomes starved by a blocking call. No external health signal exists.

### Missing 8 — No startup validation of prompt format strings (Severity: Low)

`FIRST_MESSAGE_PROMPT` contains `{profile_text}`. If a developer edits this constant and accidentally removes or misspells the placeholder, `str.format(profile_text=...)` either silently ignores it (if placeholder removed) or raises `KeyError` (if misspelled). The `KeyError` would propagate through `generate_first_message` to `process_leomatch_message`'s `except Exception` handler in `process_leomatch_task`, logging an error but producing no opener.

---

## 9. Failure Interaction Matrix

Some failures compound each other:

| Initial Failure | Triggered By | Compound Effect |
|----------------|-------------|----------------|
| Disk full | Any | `save_histories()` fails silently → in-memory state diverges from disk → next restart uses stale history |
| API call fails → orphaned user turn | Any API error | Next AI response is off-context → user confusion → more messages → more orphaned turns |
| Crash during JSON write | OOM / power | File corrupted → history destroyed → next restart treats all users as strangers |
| Long-mode delay task (3h) | New session | If bot restarts during 3h sleep → task gone → user never gets reply → user re-sends → new session → another delay roll |
| Multiple rapid likes before match | Active Scout | Wrong profile text used for opener → opener references wrong person |
| @leomatchbot format change | Bot update | All profiles treated as unrecognized → `last_seen_anket_text` never set → all openers skipped indefinitely |

---

## 10. Severity Summary

| Severity | Count | Issues |
|----------|-------|--------|
| **Critical** | 2 | Non-atomic JSON write (data loss on crash); JSONDecodeError recovery destroys history |
| **High** | 8 | Missing FloodWait handler; missing API timeout; non-ResourceExhausted errors uncaught; orphaned user turns; Pyrogram abandoned (security); @leomatchbot format assumption; wrong profile text for opener; UnicodeDecodeError destroys history |
| **Medium** | 5 | Missing SIGTERM handler; empty AI response crash path; Gemini model deprecation; no reply on 503; missing opener after restart |
| **Low** | 4 | No empty response guard before send; no health check; no prompt format validation; log file write failure |

**The three changes with the highest combined impact:**
1. **Atomic JSON write** — eliminates Critical #1 and contributes to Critical #2 recovery
2. **Catch all Gemini error types + add timeout** — eliminates High #2, #3, and Medium #3
3. **FloodWait handler** — eliminates High #1 (message loss on Telegram rate limiting)
