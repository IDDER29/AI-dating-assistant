# Improvement Blueprint — AI Dating Assistant

_Version: 1.0 | Created: 2026-06-04_

> Phase 1: Full issue extraction, root cause analysis, grouped categories,
> and a complete actionable execution plan.
> Source: All documents in docs/analysis/ + docs/SYNTHESIS.md + docs/TECHNICAL-REFERENCE.md

---

## Table of Contents

- [Part A — Issue Catalog](#part-a--issue-catalog)
  - [A1. Data Integrity & Persistence](#a1-data-integrity--persistence)
  - [A2. AI Integration & Output Quality](#a2-ai-integration--output-quality)
  - [A3. Conversation Logic & Flow Correctness](#a3-conversation-logic--flow-correctness)
  - [A4. Error Handling & Resilience](#a4-error-handling--resilience)
  - [A5. Product Intelligence & Observability](#a5-product-intelligence--observability)
  - [A6. Architecture & Coupling](#a6-architecture--coupling)
  - [A7. Security & Credentials](#a7-security--credentials)
  - [A8. Performance & Scalability](#a8-performance--scalability)
  - [A9. Operator UX & Control](#a9-operator-ux--control)
- [Part B — Execution Plan](#part-b--execution-plan)
  - [Epic 1 — Data Safety Foundation](#epic-1--data-safety-foundation)
  - [Epic 2 — AI Integration Correctness](#epic-2--ai-integration-correctness)
  - [Epic 3 — Conversation Flow Completeness](#epic-3--conversation-flow-completeness)
  - [Epic 4 — Error Handling & Resilience](#epic-4--error-handling--resilience)
  - [Epic 5 — Product Intelligence Layer](#epic-5--product-intelligence-layer)
  - [Epic 6 — Operator Control & Observability](#epic-6--operator-control--observability)
  - [Epic 7 — Architecture Refactor](#epic-7--architecture-refactor)
- [Part C — Dependency Map & Execution Order](#part-c--dependency-map--execution-order)

---

# Part A — Issue Catalog

---

## A1. Data Integrity & Persistence

---

### ISSUE-01 — Non-atomic JSON write destroys all history on crash

**Description:**
`save_json_data()` opens the file in write mode (`"w"`), which truncates it to zero bytes immediately. The full JSON is then written. Any process interruption between truncation and write completion (OOM kill, power loss, SIGKILL) leaves a zero-byte or partial JSON file. On next startup, `load_json_data()` detects invalid JSON and silently overwrites with `{}` — destroying every conversation turn ever stored.

**Root cause:** Standard Python file write pattern without crash-safety awareness. No temporary file staging.

**Impact:** Total, silent, unrecoverable data loss. The system's only memory of every relationship is destroyed. The operator has no indication this occurred beyond a single log line.

**Improvement needed:** Atomic write using write-to-temp-then-rename, which is guaranteed atomic at the OS level on POSIX systems.

**Implementation:**
```python
# storage.py — replace save_json_data body:
def save_json_data(filepath: str | Path, data):
    path = Path(filepath)
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())  # guarantee OS buffer flush
        tmp_path.replace(path)   # atomic on POSIX (rename syscall)
    except IOError as e:
        logging.error(f"Error saving {path}: {e}")
        tmp_path.unlink(missing_ok=True)  # clean up partial tmp
```
Add `import os` at top of `storage.py`.

---

### ISSUE-02 — Corrupted JSON recovery destroys data instead of preserving it

**Description:**
When `load_json_data()` encounters a `JSONDecodeError`, it creates a new empty file and returns the default value (`{}`). There is no backup, no rename, no operator warning beyond a log line. The operator loses all history permanently with zero chance of manual recovery.

**Root cause:** Recovery logic was written to guarantee a valid return value, not to preserve existing data.

**Impact:** Any corruption event (partial write, manual edit error, encoding issue) causes total permanent data loss.

**Improvement needed:** Before overwriting, rename the corrupt file to a timestamped backup. Alert the operator.

**Implementation:**
```python
# storage.py — in load_json_data, replace the JSONDecodeError handler:
except json.JSONDecodeError as e:
    backup_path = path.with_suffix(f".corrupt.{int(datetime.now().timestamp())}.json")
    try:
        path.rename(backup_path)
        logging.error(
            f"JSON decoding error in {path}: {e}. "
            f"Corrupt file saved as {backup_path}. Starting fresh."
        )
    except OSError:
        logging.error(f"JSON decoding error in {path}: {e}. Could not back up file.")
```
Also add `UnicodeDecodeError` to the exception tuple — a file saved in wrong encoding raises this, not `JSONDecodeError`, and currently propagates all the way to `main.py`'s crash handler (which then calls `save_histories` with an empty state, overwriting the corrupt file with `{}`).

---

### ISSUE-03 — `save_histories()` called inside `generate_conversation_response()` — hidden side effect

**Description:**
`ai_client.generate_conversation_response()` calls `save_histories(state)` internally. The caller (`dialog.py`) is unaware this happens. This makes the AI generation function impure (it has a disk I/O side effect), makes it untestable without a real filesystem, and prevents the caller from controlling when persistence occurs.

**Root cause:** Convenience — the generation function had all the context needed to save, so saving was placed there.

**Impact:** Architectural coupling that blocks testability; blocks moving persistence to a background thread; creates unexpected behavior when the function is reused in any non-persistence context.

**Improvement needed:** Remove `save_histories()` from `generate_conversation_response()`. Call it explicitly from `dialog.py` after generation, off the event loop.

**Implementation:**
```python
# ai_client.py — remove line:
save_histories(state)

# dialog.py — in process_dialogue_task(), after AI call:
ai_response = await generate_conversation_response(chat_id, user_message, state)
asyncio.create_task(_persist_histories(state))  # non-blocking

async def _persist_histories(state):
    await asyncio.to_thread(save_histories, state)
```

---

### ISSUE-04 — `save_histories()` blocks the asyncio event loop

**Description:**
`storage.save_json_data()` performs synchronous file I/O inside the asyncio event loop thread. While the file is being written, no other coroutine can run — Pyrogram cannot dispatch events, typing timers cannot fire, and read receipts are delayed. At current scale the block is < 5ms. As conversation count grows, this becomes tens to hundreds of milliseconds.

**Root cause:** `save_histories()` was never wrapped in `asyncio.to_thread`. After ISSUE-03 is fixed, this becomes a one-line change.

**Impact:** Event loop starvation under load. Timing jitter in all human-simulation features (read receipts, typing delays) that are core to the product's behavioral goal.

**Implementation:**
Resolved by ISSUE-03's fix — `_persist_histories()` already runs via `asyncio.to_thread`.

---

### ISSUE-05 — No data retention or housekeeping — files grow forever

**Description:**
`conversation_histories.json` accumulates an entry for every Telegram user who has ever messaged the account. User keys are never removed. After months of operation, the file contains hundreds of entries for conversations that ended long ago, growing startup parse time and in-memory footprint indefinitely.

**Root cause:** No retention policy was designed. The sliding window (20 turns per conversation) was the only size constraint considered.

**Impact:** Gradual performance degradation. Startup becomes slower. In-memory dict grows. Backup and transfer become harder.

**Improvement needed:** A configurable conversation TTL — if no new turns have been added in N days, the entry is eligible for archival or removal.

**Implementation:**
```python
# storage.py — add function:
def prune_stale_histories(state, max_age_days: int = 90):
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stale = []
    for user_id, turns in state.conversation_histories.items():
        if not turns:
            stale.append(user_id)
            continue
        last_ts_str = turns[-1].get("timestamp")
        if last_ts_str:
            last_ts = datetime.fromisoformat(last_ts_str)
            if last_ts < cutoff:
                stale.append(user_id)
    for user_id in stale:
        del state.conversation_histories[user_id]
    if stale:
        logging.info(f"[STORAGE] Pruned {len(stale)} stale conversations.")
```
Call at startup after `load_histories()`, configurable via `settings.py`.

---

## A2. AI Integration & Output Quality

---

### ISSUE-06 — `system_instruction=` unused — 800 tokens wasted per call

**Description:**
The Gemini SDK's `GenerativeModel` constructor accepts a `system_instruction=` parameter that sets the model's system context once at initialization. Instead, the system injects the full `CONVERSATION_SYSTEM_PROMPT` (~800 tokens) as a fake `user`/`model` exchange at position 0 of the history payload on every single API call. This wastes ~800 tokens per request and creates a fragile workaround that can break silently if Gemini changes how early history turns are processed.

**Root cause:** Either the `system_instruction` parameter was unknown to the developer, or it was not available in an earlier SDK version.

**Impact:** ~44% unnecessary token cost per conversation reply. The fake exchange can be quoted back by the AI. The persona can be silently disabled by a model update. The history assembly code is more complex than necessary.

**Improvement needed:** Use `system_instruction=` at model initialization. Remove the fake exchange injection entirely.

**Implementation:**
```python
# ai_client.py — initialize_ai():
state.model = genai.GenerativeModel(
    "gemini-1.5-flash-latest",
    system_instruction=CONVERSATION_SYSTEM_PROMPT
)

# ai_client.py — generate_conversation_response() — remove these lines:
full_prompt_history = [
    {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
    {"role": "model", "parts": ["understood, I'm ready. no periods and no extra stuff"]},
]
full_prompt_history.extend(history_for_api)

# Replace with:
full_prompt_history = history_for_api  # just the actual conversation
```
Verify behavior in test conversation before deploying — the response style may change slightly with proper system instruction placement.

---

### ISSUE-07 — AI output has no validation layer before delivery

**Description:**
`result.text` is cleaned for punctuation and forwarded directly to `client.send_message()`. There is no guard against: empty responses (Gemini safety filter triggered), excessively long responses (persona says 1–3 sentences), responses containing the system prompt verbatim (prompt leakage), responses with an unreasonable number of `|||` separators (causes flooding), or responses in a wrong language.

**Root cause:** The developer trusted Gemini's instruction-following as the only quality control.

**Impact:** Invalid AI output reaches real users with no circuit breaker. Safety filter blocks produce zero-length messages (Pyrogram raises on empty send). Prompt leakage confirms bot status. Excessive `|||` parts trigger Telegram FloodWait.

**Improvement needed:** An `OutputValidator` that gates every response before delivery.

**Implementation:**
```python
# src/output_validator.py
import re
from dataclasses import dataclass

MAX_RESPONSE_CHARS = 600
MAX_LADDER_PARTS = 4
PROMPT_LEAK_MARKERS = [
    "dossier", "your task is to", "anti-deanon",
    "communication rules", "system prompt", "you are the ai avatar"
]

@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""

def validate_response(text: str) -> ValidationResult:
    if not text or not text.strip():
        return ValidationResult(False, "empty response")
    if len(text) > MAX_RESPONSE_CHARS:
        return ValidationResult(False, f"too long ({len(text)} chars)")
    parts = [p for p in text.split("|||") if p.strip()]
    if len(parts) > MAX_LADDER_PARTS:
        return ValidationResult(False, f"too many ladder parts ({len(parts)})")
    lower = text.lower()
    for marker in PROMPT_LEAK_MARKERS:
        if marker in lower:
            return ValidationResult(False, f"prompt leak marker: '{marker}'")
    return ValidationResult(True)
```

```python
# ai_client.py — after cleanup_ai_response():
from output_validator import validate_response

result_text = cleanup_ai_response(getattr(result, "text"))
validation = validate_response(result_text)
if not validation.valid:
    logging.warning(f"[AI] Response failed validation: {validation.reason}. Using fallback.")
    # pop the orphaned user turn (see ISSUE-10)
    state.conversation_histories[chat_id_str].pop()
    return fallback_message
```

---

### ISSUE-08 — Gemini API timeout not set — network partition hangs thread indefinitely

**Description:**
`asyncio.to_thread(api_call)` has no timeout. If the Gemini API or the network becomes unresponsive, the OS thread waits indefinitely. The task cannot be properly cancelled while its thread is blocked. The conversation task holds its `active_dialogue_tasks` slot, but the task itself is unkillable from within Python.

**Root cause:** `asyncio.to_thread` does not support timeout directly. The developer did not add `asyncio.wait_for` around it.

**Impact:** Thread pool slot consumed indefinitely. Conversation never receives a reply. `active_dialogue_tasks` entry not cleaned up until user sends another message. Under sustained network issues, all thread pool slots can be exhausted.

**Implementation:**
```python
# ai_client.py — with_rate_limit_handling():
async def with_rate_limit_handling(api_call, timeout_sec: float = 30.0):
    for attempt in range(3):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(api_call),
                timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            logging.warning(f"[AI] API call timed out (attempt {attempt + 1})")
            # treat timeout as a retryable error, wait before retry
            await asyncio.sleep(10)
        except google_exceptions.ResourceExhausted as e:
            # existing rate limit logic
            ...
        except (google_exceptions.ServiceUnavailable,
                google_exceptions.DeadlineExceeded,
                google_exceptions.InternalServerError) as e:
            logging.warning(f"[AI] Retryable API error: {e} (attempt {attempt + 1})")
            await asyncio.sleep(15)
    logging.error("Failed to execute API request after 3 attempts.")
    return None
```

---

### ISSUE-09 — Only HTTP 429 is caught — all other API errors propagate unhandled

**Description:**
`with_rate_limit_handling` catches only `google_exceptions.ResourceExhausted`. HTTP 503 (`ServiceUnavailable`), 504 (`DeadlineExceeded`), 500 (`InternalServerError`), and network connection errors all propagate out of the function uncaught. They reach `dialog.py`'s `except Exception` handler, which logs the error and exits the task — leaving an orphaned user turn in history (see ISSUE-10) and silently sending no reply.

**Root cause:** Narrow exception handling focused on the known production failure mode (rate limiting) without covering the broader retryable error surface.

**Implementation:** Resolved by ISSUE-08's implementation — adds all retryable error types to the catch block.

---

### ISSUE-10 — Orphaned user turn on any API failure corrupts conversation history

**Description:**
In `generate_conversation_response()`, the user's turn is appended to `state.conversation_histories[chat_id_str]` before the Gemini API call is made. If the call fails (any error, after all retries), the function returns the fallback string but does NOT remove the appended user turn. On the next AI call, Gemini receives two consecutive `"user"` turns — violating the alternating-role invariant the API expects. Output quality degrades silently and permanently for that conversation.

**Root cause:** The append was placed before the API call for logging/debugging convenience. No rollback was implemented.

**Impact:** Every API failure causes permanent, silent conversation history corruption. This compounds — multiple failures produce multiple consecutive user turns that increasingly confuse the model.

**Implementation:**
```python
# ai_client.py — generate_conversation_response():
state.conversation_histories[chat_id_str].append(user_turn)
try:
    # ... build history, call API ...
    if result and hasattr(result, "text"):
        ai_response = cleanup_ai_response(result.text)
        validation = validate_response(ai_response)
        if not validation.valid:
            state.conversation_histories[chat_id_str].pop()  # rollback
            return fallback_message
        state.conversation_histories[chat_id_str].append(model_turn)
        return ai_response
    else:
        state.conversation_histories[chat_id_str].pop()  # rollback
        return fallback_message
except Exception as e:
    state.conversation_histories[chat_id_str].pop()  # rollback on any exception
    logging.error(f"[AI] Exception in generation: {e}", exc_info=True)
    return fallback_message
```

---

### ISSUE-11 — Prompt cache not used — system prompt re-serialized on every call

**Description:**
After fixing ISSUE-06 (using `system_instruction=`), the system prompt is handled correctly at the model level. However, the Gemini API also supports explicit `CachedContent` for multi-turn sessions where the same prefix is used repeatedly. For high-frequency use, enabling the cache API reduces latency (cached tokens skip inference) and cost (cached tokens priced lower).

**Root cause:** Not implemented; requires deliberate use of the caching API.

**Impact:** Suboptimal API cost and latency at volume. At current single-operator scale, the impact is financial (minor) rather than functional.

**Implementation:**
This is a post-ISSUE-06 optimization. After confirming `system_instruction=` works correctly, evaluate Gemini's `caching` module for the system prompt. Deferred to Epic 2 Task 5.

---

## A3. Conversation Logic & Flow Correctness

---

### ISSUE-12 — Opener never stored — every conversation starts amnesiac

**Description:**
The opener (first message to a match) is generated by the Scout pipeline via `generate_first_message()` and sent through `@leomatchbot`. It is never written to `conversation_histories`. When the match replies and the Interlocutor activates, the AI has no knowledge of what was said first. If the match references the opener ("yes I do love hiking!"), the AI cannot explain what prompted it, cannot build on it, and may produce a contextually incoherent response.

**Root cause:** The Scout pipeline and Interlocutor pipeline have no communication channel. The opener is sent as a bot command to `@leomatchbot`; the user's Telegram ID is unknown at that point (it only becomes known when they message back).

**Impact:** Every conversation starts with a factual inconsistency. The AI's first impression cannot be referenced or built upon. This is the highest-impact product deficiency by user value.

**Implementation approach:** Store openers in a temporary buffer, inject on first reply.

```python
# state.py — add to BotState:
sent_openers: list = field(default_factory=list)
# Each entry: {"text": str, "sent_at": datetime}

# leomatch.py — after sending opener:
await client.send_message(BOT_USERNAME, intro_message)
state.sent_openers.append({
    "text": intro_message,
    "sent_at": datetime.now(timezone.utc).isoformat()
})
# Keep only last 5 (in case of rapid matches)
state.sent_openers = state.sent_openers[-5:]
state.last_seen_anket_text = None

# ai_client.py — generate_conversation_response(), at top:
# If this is a brand-new conversation AND we have a recent opener:
if chat_id_str not in state.conversation_histories or not state.conversation_histories[chat_id_str]:
    if state.sent_openers:
        recent = state.sent_openers.pop(0)  # FIFO: oldest unmatched opener
        state.conversation_histories[chat_id_str] = [{
            "role": "model",
            "parts": [recent["text"]],
            "timestamp": recent["sent_at"]
        }]
        logging.info(f"[AI] Injected opener as first model turn for user {chat_id}")
```

**Limitation acknowledged:** The FIFO matching is approximate — if two mutual matches arrive before either replies, the first reply gets the first opener in the queue. This is better than the current amnesiac state. A perfect match requires `@leomatchbot` to expose the user ID at match time, which it currently does not.

---

### ISSUE-13 — Burst message accumulation missing — only last message sent to AI

**Description:**
The debounce mechanism (cancel-and-replace task) correctly prevents multiple reply cycles for rapid messages. However, each new task captures only the single most recent message. If a user sends three messages in a burst, the AI receives only the third. The first two generate read receipts but their content is invisible to the AI.

**Root cause:** The cancellation discards the previous task entirely. No accumulation buffer exists.

**Impact:** Multi-part thoughts are truncated. "Actually wait / I wanted to ask / do you believe in love at first sight" → the AI only sees the last sentence. Response quality and context fidelity are degraded for users who communicate in bursts (common on mobile).

**Implementation:**
```python
# state.py — add to BotState:
message_buffers: Dict[int, list] = field(default_factory=dict)
# Each entry: list of message text strings, accumulated during grace period

# dialog.py — private_chat_handler():
chat_id = message.chat.id
text = get_message_text(message)
if text:
    if chat_id not in state.message_buffers:
        state.message_buffers[chat_id] = []
    state.message_buffers[chat_id].append(text)

# Cancel existing task, create new one (unchanged)
if chat_id in state.active_dialogue_tasks:
    state.active_dialogue_tasks[chat_id].cancel()
task = asyncio.create_task(process_dialogue_task(client, message, state))
state.active_dialogue_tasks[chat_id] = task

# dialog.py — process_dialogue_task(), after grace period:
await asyncio.sleep(GRACE_PERIOD_SECONDS)

# Collect all buffered messages for this chat
buffered = state.message_buffers.pop(chat_id, [])
if not buffered:
    return
# Combine into single input (join with newline to preserve intent)
combined_message = "\n".join(buffered)
user_message = combined_message  # pass this to generate_conversation_response

# dialog.py — finally block: also clear buffer on cleanup
state.message_buffers.pop(chat_id, None)
```

---

### ISSUE-14 — Profile quality filter uses character count, not content intelligence

**Description:**
The Scout decision to like or dislike a profile is based solely on whether the description is longer than 10 characters. A 70-character meaningless description triggers a like; a 5-character meaningful description ("coder") triggers a dislike. The README claims "filters by quality of description" — the code checks string length.

**Root cause:** AI-based filtering was not implemented, likely to avoid per-profile API cost and latency.

**Impact:** Wasted likes on low-quality profiles. Missed likes on short-but-meaningful profiles. Opener quality degrades when the profile description that informed the opener is low-signal.

**Improvement:** Add a fast AI classification call for profiles that pass the minimum length threshold, using a cheap binary prompt.

**Implementation:**
```python
# ai_client.py — add function:
async def classify_profile_quality(description: str, state) -> bool:
    """Returns True if the profile is worth messaging."""
    if not state.model or len(description.strip()) < 5:
        return len(description.strip()) > 10  # fallback to old logic
    
    prompt = (
        f"Dating profile description: \"{description}\"\n\n"
        "Is this profile worth sending a message to? "
        "Answer only YES or NO. Consider: genuine effort, personality hints, "
        "conversation hooks. Ignore blank, bot-like, or purely transactional profiles."
    )
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
    if result and hasattr(result, "text"):
        return "yes" in result.text.strip().lower()
    return len(description.strip()) > 10  # fallback

# leomatch.py — process_leomatch_message(), replace the like/dislike block:
description = match.group(4) or ""
if description.strip():
    should_like = await classify_profile_quality(description.strip(), state)
else:
    should_like = False

if should_like:
    await client.send_message(BOT_USERNAME, "💌 / 📹")
else:
    await client.send_message(BOT_USERNAME, "👎")
```

---

### ISSUE-15 — Context window silently discards early conversation facts

**Description:**
Conversation history is trimmed to the last 20 turns. Early messages — introductions, stated preferences, disclosed personal details — are permanently discarded after ~10 exchanges. The AI may re-ask questions it already asked, contradict its earlier statements, or fail to reference details the user expects it to remember.

**Root cause:** The sliding window approach is correct for API token management but has no strategy for preserving semantically important information.

**Impact:** Conversation coherence degrades over time. Long conversations feel generic and disconnected. The persona — designed to remember context — demonstrably forgets.

**Improvement:** Maintain a separate "memory" dictionary per user that stores distilled key facts, extracted by the AI, persisted independently of the turn window.

**Implementation:**
```python
# state.py — add to BotState:
conversation_memories: Dict[str, str] = field(default_factory=dict)
# user_id → compact string of key facts: "Name: Anna. Likes hiking. Nurse. From SPb."

# storage.py — add MEMORY_PATH and persist/load conversation_memories
MEMORY_PATH = DATA_DIR / "conversation_memories.json"

# ai_client.py — after appending model turn:
# Every 4 turns, update the memory for this user
turns = state.conversation_histories[chat_id_str]
if len(turns) % 4 == 0 and len(turns) >= 4:
    asyncio.create_task(_update_memory(chat_id_str, turns[-4:], state))

async def _update_memory(chat_id_str: str, recent_turns: list, state):
    existing = state.conversation_memories.get(chat_id_str, "")
    turns_text = "\n".join(
        f"{t['role'].upper()}: {t['parts'][0]}" for t in recent_turns
    )
    prompt = (
        f"Existing memory: {existing}\n\n"
        f"New conversation:\n{turns_text}\n\n"
        "Update the memory with any new key facts about the user "
        "(name, job, hobbies, stated preferences, important things they said). "
        "Be extremely concise. Max 3 sentences. Only facts, no analysis."
    )
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
    if result and hasattr(result, "text"):
        state.conversation_memories[chat_id_str] = result.text.strip()

# ai_client.py — inject memory at start of conversation history build:
memory = state.conversation_memories.get(chat_id_str, "")
if memory:
    # Prepend as a short context note to the first user turn of the API history
    memory_note = f"[Context about this person: {memory}]"
    # Add as the first message in history_for_api
```

---

### ISSUE-16 — SIGTERM not handled — history unsaved on managed process shutdown

**Description:**
The process handles `SIGINT` (Ctrl+C) by calling `save_histories()`. It does not handle `SIGTERM`, which is the signal sent by systemd, Docker, supervisord, and most process managers when requesting a clean shutdown. On `SIGTERM`, the process terminates immediately with no save.

**Root cause:** The developer's deployment context is tmux (operator presses Ctrl+C), so `SIGTERM` was never encountered.

**Impact:** Every planned deployment, restart, or managed shutdown discards all conversation turns since the last successful save.

**Implementation:**
```python
# main.py — after imports:
import signal

def _handle_sigterm(signum, frame):
    raise KeyboardInterrupt  # route through existing KeyboardInterrupt handler

signal.signal(signal.SIGTERM, _handle_sigterm)
```

---

### ISSUE-17 — Opener cleared unconditionally — cleared even when send fails

**Description:**
In `process_leomatch_message()`, `state.last_seen_anket_text = None` is called after `client.send_message()`. If `send_message` raises an exception (FloodWait, network error), the exception propagates and the profile text is still cleared (because `None` assignment is the next line in the finally-less flow). The opener was never sent, but the profile context that would generate it is gone.

**Root cause:** No error handling around the `send_message` call; no acknowledgment-before-clear pattern.

**Impact:** Mutual matches get no opener message. The system silently fails to deliver the first impression — the product's primary conversion mechanism.

**Implementation:**
```python
# leomatch.py — process_leomatch_message(), opener block:
try:
    await asyncio.sleep(5)
    await client.send_message(BOT_USERNAME, intro_message)
    state.last_seen_anket_text = None   # only clear AFTER confirmed send
    logging.info("[LEOMATCH-EXECUTOR] Message sent, memory cleared.")
except Exception as e:
    logging.error(f"[LEOMATCH-EXECUTOR] Failed to send opener: {e}")
    # last_seen_anket_text preserved for retry on next startup replay
```

---

## A4. Error Handling & Resilience

---

### ISSUE-18 — FloodWait uncaught — messages silently lost under Telegram rate limiting

**Description:**
`pyrogram.errors.FloodWait` is raised when Telegram rate-limits the account. It carries a `.x` attribute (seconds to wait). Neither `leomatch.py` nor `dialog.py` catches it. It propagates to the background task's `except Exception` handler, which logs the error and exits the task. The message is never sent.

**Root cause:** FloodWait was not anticipated or not implemented.

**Impact:** Silent message loss. Under load or aggressive Scout behavior, FloodWait will occur and conversations will go unanswered with no operator awareness.

**Implementation:**
```python
# utils.py — add helper:
from pyrogram.errors import FloodWait as PyrFloodWait

async def safe_send_message(client, chat_id, text: str, retries: int = 3):
    for attempt in range(retries):
        try:
            return await client.send_message(chat_id, text)
        except PyrFloodWait as e:
            wait = e.x + 1
            logging.warning(f"[TELEGRAM] FloodWait {wait}s on send to {chat_id}")
            await asyncio.sleep(wait)
    logging.error(f"[TELEGRAM] Failed to send message to {chat_id} after {retries} retries")
    return None
```
Replace all `client.send_message()` calls in `leomatch.py` and `dialog.py` with `safe_send_message()`.

---

### ISSUE-19 — No per-user rate limiting — single user can exhaust API quota

**Description:**
A user sending messages rapidly can generate Gemini API calls at approximately 1 per 8 seconds (grace period only). With the free tier limited to 15 RPM, a single adversarial user can consume the entire quota, degrading all other conversations.

**Root cause:** No per-user throttle was designed.

**Impact:** API quota exhaustion → all conversations receive fallback strings. Financial impact on paid tier.

**Implementation:**
```python
# state.py — add to BotState:
last_reply_times: Dict[int, datetime] = field(default_factory=dict)

# dialog.py — process_dialogue_task(), before AI call:
MIN_REPLY_INTERVAL_SEC = 30

last = state.last_reply_times.get(chat_id)
if last:
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    if elapsed < MIN_REPLY_INTERVAL_SEC:
        logging.info(f"[DIALOG] Rate limiting reply to {user_name} ({elapsed:.0f}s since last)")
        return

state.last_reply_times[chat_id] = datetime.now(timezone.utc)
```

---

### ISSUE-20 — `|||`-only AI response sends no message — silent no-reply

**Description:**
If Gemini returns `"|||"` (only the delimiter, no content), `ai_response.split("|||")` produces `["", ""]`. The list comprehension `[p.strip() for p in parts if p.strip()]` produces `[]`. The `for part in parts` loop runs zero times. No message is sent. No log line indicates this happened. The user receives no reply.

**Root cause:** Edge case in ladder-send parsing not guarded.

**Impact:** Silent no-reply. Covered by ISSUE-07's output validator (empty response detection) and ISSUE-10's rollback. But worth an explicit guard at the delivery site too.

**Implementation:**
```python
# dialog.py — after ai_response is received:
if not ai_response or not ai_response.strip():
    logging.warning(f"[DIALOG] Empty AI response for {user_name}. Skipping send.")
    return

if "|||" in ai_response:
    parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
    if not parts:
        logging.warning(f"[DIALOG] AI response split produced no parts for {user_name}.")
        return
```

---

## A5. Product Intelligence & Observability

---

### ISSUE-21 — No meeting detection — the product's goal is unobservable

**Description:**
The system's defined endpoint — "make the match suggest meeting" — has no implementation. No keyword detection, no state transition, no log entry, no notification. The system runs indefinitely after a meeting is suggested, continuing to generate AI replies to a conversation that the operator should now handle manually.

**Root cause:** The goal was defined as a conversational outcome to be achieved by prompt instruction, not as a system event to be detected and acted upon.

**Impact:** The product's primary value delivery (a warm lead ready to meet) is invisible. The operator must manually monitor dozens of conversations to find the moment of success. The system cannot be evaluated for effectiveness.

**Implementation:**
```python
# src/meeting_detector.py
MEETING_SIGNALS_RU = [
    "встретимся", "встретиться", "увидимся", "увидеться",
    "кофе", "погулять", "когда ты свободен", "когда ты свободна",
    "давай встретимся", "пойдем", "предлагаю встретиться"
]
MEETING_SIGNALS_EN = [
    "meet", "coffee", "walk", "when are you free",
    "let's meet", "let me know when", "hang out", "get together"
]

def detect_meeting_signal(text: str) -> bool:
    lower = text.lower()
    return any(s in lower for s in MEETING_SIGNALS_RU + MEETING_SIGNALS_EN)

# dialog.py — in process_dialogue_task(), after receiving user_message:
from meeting_detector import detect_meeting_signal

if detect_meeting_signal(user_message):
    logging.info(f"[MEETING] 🎯 Meeting signal detected from {user_name} (ID: {chat_id})")
    await operator_notify(
        client,
        f"🎯 MEETING SUGGESTED\nUser: {user_name} (ID: {chat_id})\n"
        f"Message: \"{user_message[:200]}\"\n\n"
        "Add to whitelist to take over manually."
    )
```

---

### ISSUE-22 — No operator notification channel

**Description:**
The operator has no way to receive proactive alerts from the system. Critical events — meeting suggestions, AI errors, rate limits, crashes — are only visible by actively tailing `ai_bot_logs.txt`. The operator could miss the entire point of the system (a meeting suggestion) if they are not monitoring.

**Root cause:** No notification mechanism was built. The system was designed as a passive background process.

**Impact:** The operator cannot benefit from the system's output without active monitoring. The system produces value that is invisible unless searched for.

**Implementation:**
```python
# src/operator_notify.py
import logging

async def operator_notify(client, message: str):
    """Send a message to the operator's Saved Messages (Telegram 'me')."""
    try:
        await client.send_message("me", f"🤖 {message}")
    except Exception as e:
        logging.error(f"[OPERATOR] Failed to send notification: {e}")

# Use at key events:
# 1. Meeting signal detected (ISSUE-21)
# 2. AI validation failure (ISSUE-07)
# 3. All 3 API retries exhausted
# 4. History corruption detected (ISSUE-02)
# 5. Periodic heartbeat (every N hours)
```

---

### ISSUE-23 — No system heartbeat — silent hangs are undetectable

**Description:**
The bot can become unresponsive (event loop stalled, Pyrogram disconnected silently, asyncio task leak) with no external indication. The operator has no way to know the system is alive except by checking if conversations are still happening.

**Root cause:** No watchdog or heartbeat mechanism.

**Impact:** The system may silently stop functioning for hours or days with no operator awareness.

**Implementation:**
```python
# app.py — add to run(), before asyncio.Event().wait():
async def _heartbeat(client, state):
    while True:
        await asyncio.sleep(3600)  # every hour
        active = len(state.active_dialogue_tasks)
        await operator_notify(
            client,
            f"✓ Bot alive | Active conversations: {active} | "
            f"Uptime: {(datetime.now(timezone.utc) - state.start_time)}"
        )

asyncio.create_task(_heartbeat(state.app, state))
```

---

### ISSUE-24 — No goal tracking — system effectiveness is unmeasured

**Description:**
Beyond detecting individual meeting signals (ISSUE-21), the system collects no aggregate performance data: how many conversations were started, how many reached the meeting suggestion stage, how long conversations typically last, which opener styles result in replies.

**Root cause:** No analytics layer was designed.

**Impact:** The operator cannot improve the system without guesswork. Prompt tuning is blind. Profile filter tuning is blind.

**Improvement:** Minimal event logging to a separate `stats.json` file.

**Implementation:**
```python
# src/stats.py
def record_event(event_type: str, metadata: dict = None):
    """Append a stat event to stats.json."""
    entry = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metadata or {})
    }
    stats_path = DATA_DIR / "stats.json"
    try:
        existing = []
        if stats_path.exists():
            with stats_path.open("r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(entry)
        with stats_path.open("w", encoding="utf-8") as f:
            json.dump(existing[-1000:], f, ensure_ascii=False, indent=2)  # keep last 1000
    except Exception as e:
        logging.error(f"[STATS] Failed to record event: {e}")

# Events to record:
# record_event("profile_liked", {"has_description": True})
# record_event("profile_disliked", {"reason": "short_description"})
# record_event("opener_sent")
# record_event("conversation_started", {"chat_id": chat_id})
# record_event("meeting_signal", {"chat_id": chat_id})
# record_event("api_fallback", {"reason": "rate_limit"})
```

---

## A6. Architecture & Coupling

---

### ISSUE-25 — `config.py` mixes secrets, constants, and prompts in one file

**Description:**
`config.py` contains: API credentials, behavioral constants, timing parameters, AI prompts (85 lines of natural language), compiled regex, and domain knowledge sets. These have different change rates, different audiences, and different security classifications.

**Root cause:** Organic growth without separation of concerns.

**Impact:** Editing a prompt requires opening the same file as API key management. A regex update sits next to persona instructions. Non-developer operators cannot safely edit the persona without risk of accidentally touching credential code.

**Implementation:** Split into three files:
```
src/
├── credentials.py     # env var loading only — gitignored
├── settings.py        # behavioral constants only — version-controlled
└── prompts/
    ├── first_message.txt
    └── conversation.txt
```

```python
# credentials.py
from dotenv import load_dotenv
import os
load_dotenv()
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# settings.py — all constants, paths, ANKET_PATTERN, KNOWN_SYSTEM_MESSAGES

# prompts/first_message.txt — raw prompt text, no Python
# prompts/conversation.txt  — raw prompt text, no Python

# settings.py — load prompts:
PROMPTS_DIR = BASE_DIR / "src" / "prompts"
FIRST_MESSAGE_PROMPT = (PROMPTS_DIR / "first_message.txt").read_text(encoding="utf-8")
CONVERSATION_SYSTEM_PROMPT = (PROMPTS_DIR / "conversation.txt").read_text(encoding="utf-8")
```

Update all imports across modules from `from config import X` to `from settings import X` or `from credentials import X` as appropriate.

---

### ISSUE-26 — No Telegram interface abstraction — Pyrogram calls scattered across modules

**Description:**
Direct `client.send_message()`, `client.send_chat_action()`, `client.read_chat_history()` calls exist in `leomatch.py`, `dialog.py`, and `app.py`. Replacing Pyrogram with `pyrofork` or `telethon` requires finding and updating every call site across multiple files.

**Root cause:** No adapter layer was planned.

**Impact:** Tight coupling to a specific library that is unmaintained. Any library migration is a multi-file search-and-replace operation with high regression risk.

**Implementation:**
```python
# src/telegram_adapter.py
class TelegramAdapter:
    def __init__(self, client, bot_username: str):
        self._c = client
        self._bot = bot_username

    async def like_profile(self):
        await safe_send_message(self._c, self._bot, "💌 / 📹")

    async def dislike_profile(self):
        await safe_send_message(self._c, self._bot, "👎")

    async def navigate_main_menu(self):
        await safe_send_message(self._c, self._bot, "1")

    async def send_opener(self, text: str):
        await safe_send_message(self._c, self._bot, text)

    async def send_reply(self, chat_id: int, text: str):
        await safe_send_message(self._c, chat_id, text)

    async def show_typing(self, chat_id: int):
        from pyrogram import enums
        await self._c.send_chat_action(chat_id, enums.ChatAction.TYPING)

    async def mark_read(self, chat_id: int):
        await self._c.read_chat_history(chat_id)

    async def notify_operator(self, text: str):
        await safe_send_message(self._c, "me", text)

    async def get_last_bot_message(self):
        history = [msg async for msg in self._c.get_chat_history(
            await self._c.resolve_peer(self._bot), limit=1
        )]
        return history[0] if history else None
```

---

### ISSUE-27 — BotState is a shared mutable blob — no access control or encapsulation

**Description:**
Every module reads and writes `BotState` fields directly. There are no ownership boundaries, no mutation hooks, no change notifications. A bug that writes the wrong value to any field silently affects all other modules that depend on it.

**Root cause:** Simplicity over correctness; single-developer codebase.

**Impact:** As features are added, debugging cross-module state corruption becomes exponentially harder. The `PendingProfile` concept is an untyped nullable string; the opener buffer is a list; nothing is semantically typed.

**Improvement:** At minimum, replace the naked `last_seen_anket_text` field with a typed `PendingMatch` dataclass. Add clear ownership comments.

**Implementation:**
```python
# state.py — add:
@dataclass
class PendingMatch:
    anket_text: str
    liked_at: str  # ISO timestamp
    opener_text: Optional[str] = None

# Replace in BotState:
# last_seen_anket_text: Optional[str] = None
pending_match: Optional[PendingMatch] = None
```
Update all access sites in `leomatch.py`.

---

### ISSUE-28 — No test infrastructure — every change is unverified

**Description:**
Zero tests of any kind. The most change-prone elements (regex, cleanup function, ladder split, session classification, history assembly) are pure functions with no automated coverage. Every change requires running the full bot to verify behavior.

**Root cause:** Tests were not written during development.

**Impact:** Maintenance velocity degrades over time. Confidence in changes is low. The regex `ANKET_PATTERN` — which will need updating if `@leomatchbot` changes format — cannot be safely modified without running the full system.

**Implementation:** Start with pure function unit tests:
```python
# tests/test_ai_client.py
def test_cleanup_ai_response_removes_dashes():
    from ai_client import cleanup_ai_response
    assert cleanup_ai_response("hello — world") == "hello  world"

def test_cleanup_ai_response_strips_period():
    from ai_client import cleanup_ai_response
    assert cleanup_ai_response("hello.") == "hello"

# tests/test_leomatch.py
def test_anket_pattern_matches_full():
    import re
    from settings import ANKET_PATTERN
    m = ANKET_PATTERN.match("Anna, 24, Moscow — I love hiking")
    assert m and m.group(1) == "Anna"
    assert m.group(4) == "I love hiking"

def test_anket_pattern_no_description():
    from settings import ANKET_PATTERN
    m = ANKET_PATTERN.match("Anna, 24, Moscow")
    assert m and m.group(4) is None

# tests/test_output_validator.py
def test_empty_response_invalid():
    from output_validator import validate_response
    assert not validate_response("").valid

def test_prompt_leak_detected():
    from output_validator import validate_response
    assert not validate_response("your task is to help users").valid
```

---

## A7. Security & Credentials

---

### ISSUE-29 — Credentials stored unencrypted in working directory

**Description:**
`.env` (API keys) and `ai_dating_user.session` (full Telegram account access) sit in the working directory with default filesystem permissions. Any process with read access to the directory can extract them. The session file provides permanent full account access with no expiry.

**Root cause:** Default development setup; no hardening for production.

**Impact:** Single point of total compromise. Server intrusion = Telegram account takeover + Gemini billing fraud.

**Implementation:**
1. Set restrictive permissions: `chmod 600 .env ai_dating_user.session`
2. Move session file outside web-accessible directories
3. Add to `.gitignore` (verify both files are listed)
4. Document session rotation procedure: how to invalidate and re-create the session file
5. Consider storing the API key in the OS keychain rather than `.env` for production

---

### ISSUE-30 — Conversation data of real users transmitted to Google without consent

**Description:**
Every message from real Telegram users is sent to Google's Gemini API as part of the conversation history. These users believe they are in a private human conversation. They have not consented to their messages being processed by a third-party AI service.

**Root cause:** This is a product-level ethical and legal design choice, not a code bug.

**Impact:** Potential GDPR violation (EU users have right to know how their data is processed). Potential Telegram ToS violation. Reputational and legal risk.

**Improvement:** Not implementable as a code change — requires product-level decision. Minimum mitigation: do not log message content; delete histories after N days (ISSUE-05); ensure `data/` is not accessible via any network interface.

---

## A8. Performance & Scalability

---

### ISSUE-31 — AI reply delay constant regardless of conversation position

**Description:**
The reply delay system classifies conversations as "active session" (< 15 min gap) or "new session" (> 15 min gap). This creates a hard binary cliff: 14:59 gap = always fast; 15:01 gap = potentially 3-hour delay. A real person's response speed would vary more naturally based on time of day, conversation momentum, and message content.

**Root cause:** Simple threshold-based classification chosen over continuous model.

**Impact:** Behavioral unnaturalness at the 15-minute boundary. Medium impact — the probabilistic tiers within each category add variation, but the jump between categories is abrupt.

**Improvement:** Replace the binary threshold with a probability curve based on gap length.

**Implementation:**
```python
# settings.py — add:
import math

def compute_reply_delay(gap_seconds: float) -> int:
    """
    Compute reply delay based on gap since last message.
    Smooth curve: short gaps → fast; long gaps → gradually slower.
    """
    if gap_seconds < 300:           # < 5 min: always fast
        return random.randint(15, 60)
    elif gap_seconds < 1800:        # 5–30 min: mostly fast, some medium
        p_medium = (gap_seconds - 300) / 1500  # 0→1 as gap grows
        if random.random() < p_medium:
            return random.randint(300, 900)
        return random.randint(15, 60)
    elif gap_seconds < 86400:       # 30 min–24h: mix of medium and long
        p_long = min(0.3, (gap_seconds - 1800) / 84600 * 0.3)
        if random.random() < p_long:
            return random.randint(3600, 10800)
        return random.randint(300, 900)
    else:                           # > 24h: treat as cold restart
        return random.randint(300, 3600)
```

---

## A9. Operator UX & Control

---

### ISSUE-32 — Whitelist requires restart to take effect

**Description:**
The whitelist is loaded once at startup into `state.whitelist_ids`. Changes to `whitelist.json` are not picked up while the bot is running. The most time-sensitive action (take over a conversation right now) requires: stop → edit → restart, taking 30–60 seconds minimum.

**Root cause:** One-time load was the simplest implementation.

**Impact:** Operator cannot respond quickly to urgent conversations. During the restart window, the AI may respond to a conversation the operator needs to control.

**Implementation:**
```python
# dialog.py — private_chat_handler():
# Check whitelist directly from file every N-th check (polling approach)
# OR: load_whitelist(state) on SIGHUP

# main.py:
import signal

def _handle_sighup(signum, frame):
    state = get_state()
    if state:
        from storage import load_whitelist
        load_whitelist(state)
        logging.info("[SYSTEM] Whitelist reloaded via SIGHUP.")

signal.signal(signal.SIGHUP, _handle_sighup)
```
Operator workflow: `kill -HUP <pid>` after editing `whitelist.json`. No restart needed.

---

### ISSUE-33 — All tuning requires code changes and restart

**Description:**
All behavioral parameters (delays, thresholds, prompts) live in Python source files. Adjusting the persona, changing delay tiers, or modifying the quality filter threshold requires editing source code and restarting the bot. There is no runtime configuration.

**Root cause:** No separation between code and configuration.

**Impact:** Operators who are not developers cannot tune the system. Every experiment requires a deployment cycle. A/B testing different openers is not possible.

**Improvement:** Move prompts to external files (ISSUE-25) and make settings hot-reloadable via SIGHUP (extending ISSUE-32's mechanism).

---

# Part B — Execution Plan

---

## Epic 1 — Data Safety Foundation

**Goal:** Eliminate data loss scenarios. Make the system safe to run 24/7.
**Must come first** — everything built on top depends on reliable storage.

---

### Task 1.1 — Atomic JSON write
**File:** `storage.py`
**Depends on:** Nothing
**Steps:**
1. Add `import os` to `storage.py`
2. Replace `save_json_data` body with write-to-tmp + `tmp.replace(path)` + `os.fsync`
3. Add `tmp_path.unlink(missing_ok=True)` in the except block
4. **Test:** Run bot, kill with SIGKILL mid-conversation, verify JSON is intact

**Estimated effort:** 30 minutes

---

### Task 1.2 — Preserve corrupt file on load failure
**File:** `storage.py`
**Depends on:** 1.1
**Steps:**
1. Import `datetime` in `storage.py`
2. Replace `JSONDecodeError` handler to rename before overwrite
3. Add `UnicodeDecodeError` to the exception tuple
4. **Test:** Corrupt `conversation_histories.json`, restart bot, verify backup file created

**Estimated effort:** 20 minutes

---

### Task 1.3 — Move save_histories off event loop
**Files:** `ai_client.py`, `dialog.py`
**Depends on:** 1.1 (atomic write makes async save safe)
**Steps:**
1. Remove `save_histories(state)` from `generate_conversation_response()`
2. Add `_persist_histories(state)` async function in `dialog.py`
3. Call `asyncio.create_task(_persist_histories(state))` after AI call in `process_dialogue_task`
4. **Test:** Verify conversation turns are saved after each reply; check no event loop blocking

**Estimated effort:** 30 minutes

---

### Task 1.4 — Add SIGTERM handler
**File:** `main.py`
**Depends on:** Nothing
**Steps:**
1. Add `import signal` to `main.py`
2. Add `_handle_sigterm` function
3. Register handler before `asyncio.run(run())`
4. **Test:** `kill -TERM <pid>`, verify history file updated

**Estimated effort:** 15 minutes

---

### Task 1.5 — Add data pruning for stale conversations
**File:** `storage.py`, `app.py`
**Depends on:** 1.1
**Steps:**
1. Add `prune_stale_histories(state, max_age_days=90)` to `storage.py`
2. Add `MAX_CONVERSATION_AGE_DAYS = 90` to `settings.py`
3. Call `prune_stale_histories(state)` in `app.py` after `load_histories(state)`
4. **Test:** Manually set an old timestamp, verify entry is pruned on next startup

**Estimated effort:** 45 minutes

---

## Epic 2 — AI Integration Correctness

**Goal:** Fix all AI interaction bugs. Make the AI integration semantically correct and reliable.
**Depends on:** Epic 1 (save refactor in Task 1.3 must be done before modifying `generate_conversation_response`)

---

### Task 2.1 — Use system_instruction= parameter
**File:** `ai_client.py`
**Depends on:** Nothing (independent of Epic 1)
**Steps:**
1. Update `initialize_ai()` to pass `system_instruction=CONVERSATION_SYSTEM_PROMPT`
2. Remove fake exchange from `generate_conversation_response()` history assembly
3. Update `full_prompt_history` to use only actual conversation turns
4. **Test:** Send a conversation message, verify persona rules are followed, verify token count dropped
5. **Test edge case:** Verify the AI still follows persona after the change

**Estimated effort:** 1 hour (including testing)

---

### Task 2.2 — Add API timeout and extend error handling
**File:** `ai_client.py`
**Depends on:** Nothing
**Steps:**
1. Add `asyncio.wait_for(..., timeout=30.0)` in `with_rate_limit_handling`
2. Add `asyncio.TimeoutError` handler with retry
3. Add `ServiceUnavailable`, `DeadlineExceeded`, `InternalServerError` to exception tuple
4. **Test:** Mock an API timeout (temporarily use a non-existent endpoint), verify retry behavior

**Estimated effort:** 45 minutes

---

### Task 2.3 — Fix orphaned user turn on API failure
**File:** `ai_client.py`
**Depends on:** 2.2 (error handling must be in place)
**Steps:**
1. Wrap the API call block in try/except
2. Add `state.conversation_histories[chat_id_str].pop()` in all failure branches
3. **Test:** Force API failure (invalid key temporarily), verify history is clean after failure

**Estimated effort:** 30 minutes

---

### Task 2.4 — Build OutputValidator
**File:** `src/output_validator.py` (new file)
**Depends on:** 2.3
**Steps:**
1. Create `output_validator.py` with `validate_response(text) -> ValidationResult`
2. Add guards: empty, too long, too many parts, prompt leak markers
3. Import and call in `ai_client.py` after `cleanup_ai_response`
4. On validation failure: log warning, pop user turn (already implemented in 2.3), return fallback
5. **Test:** Feed each failure case, verify fallback returned and history clean

**Estimated effort:** 1 hour

---

### Task 2.5 — Add empty response guard at delivery site
**File:** `dialog.py`
**Depends on:** 2.4
**Steps:**
1. Add early return guard before ladder-split logic
2. **Test:** Confirm no crash or silent send on empty string

**Estimated effort:** 15 minutes

---

## Epic 3 — Conversation Flow Completeness

**Goal:** Close the most impactful product gaps. Make conversations contextually complete.
**Depends on:** Epic 1 complete (reliable storage), Epic 2 complete (correct AI integration)

---

### Task 3.1 — Store opener in conversation history
**Files:** `state.py`, `leomatch.py`, `ai_client.py`
**Depends on:** Epic 1 complete
**Steps:**
1. Add `sent_openers: list` field to `BotState`
2. In `leomatch.py`, after successful `send_message(BOT_USERNAME, intro_message)`, append to `state.sent_openers`
3. Move `state.last_seen_anket_text = None` to after confirmed send (fix ISSUE-17 simultaneously)
4. In `ai_client.generate_conversation_response()`, check for empty history and inject opener if available
5. Keep `sent_openers` bounded to last 5 entries
6. **Test:** Send opener, reply as match, verify AI's first context turn contains the opener

**Estimated effort:** 2 hours

---

### Task 3.2 — Burst message accumulation
**Files:** `state.py`, `dialog.py`
**Depends on:** Nothing (independent)
**Steps:**
1. Add `message_buffers: Dict[int, list]` to `BotState`
2. In `private_chat_handler`, append message text to buffer before creating task
3. In `process_dialogue_task`, collect buffer after grace period using `pop`
4. Concatenate buffered messages with `"\n"` separator as single AI input
5. Clear buffer in `finally` block
6. **Test:** Send 3 rapid messages, verify all three are present in AI input

**Estimated effort:** 1.5 hours

---

### Task 3.3 — Intelligent profile quality filter
**Files:** `ai_client.py`, `leomatch.py`
**Depends on:** 2.1 (system_instruction in place), 2.2 (error handling)
**Steps:**
1. Add `classify_profile_quality(description, state) -> bool` to `ai_client.py`
2. Use a concise binary classification prompt
3. Replace character-count check in `leomatch.process_leomatch_message()` with `await classify_profile_quality()`
4. Keep character-count as fallback if API unavailable
5. **Test:** Test with various profile descriptions; verify borderline cases handled

**Estimated effort:** 2 hours

---

### Task 3.4 — Persistent conversation memory across window
**Files:** `state.py`, `ai_client.py`, `storage.py`, `settings.py`
**Depends on:** Epic 1 complete, 2.1
**Steps:**
1. Add `conversation_memories: Dict[str, str]` to `BotState`
2. Add `MEMORY_PATH` and persist/load in `storage.py`
3. Load memories in `app.py` after `load_histories`
4. Add `_update_memory()` async background task in `ai_client.py`, triggered every 4 turns
5. Inject memory as context prefix in history assembly
6. **Test:** Have a 6+ turn conversation, verify memory is populated, verify memory is referenced in later turns

**Estimated effort:** 3 hours

---

### Task 3.5 — Smooth reply delay curve
**File:** `settings.py`, `dialog.py`
**Depends on:** Nothing
**Steps:**
1. Add `compute_reply_delay(gap_seconds) -> int` to `settings.py`
2. Replace tiered delay logic in `dialog.process_dialogue_task()` with function call
3. **Test:** Verify delay distributions across various gap sizes

**Estimated effort:** 1 hour

---

## Epic 4 — Error Handling & Resilience

**Goal:** Eliminate all silent failures. Make the system observable and self-healing.
**Depends on:** Epic 2 partially (FloodWait handler is independent)

---

### Task 4.1 — FloodWait handler
**File:** `utils.py`, `leomatch.py`, `dialog.py`
**Depends on:** Nothing
**Steps:**
1. Add `safe_send_message(client, chat_id, text, retries=3)` to `utils.py`
2. Replace all `client.send_message()` calls in `leomatch.py` and `dialog.py` with `safe_send_message`
3. **Test:** Trigger FloodWait by rapid sends (or mock), verify retry behavior

**Estimated effort:** 1 hour

---

### Task 4.2 — Per-user rate limiting
**Files:** `state.py`, `dialog.py`
**Depends on:** Nothing
**Steps:**
1. Add `last_reply_times: Dict[int, datetime]` to `BotState`
2. Add `MIN_REPLY_INTERVAL_SEC = 30` to `settings.py`
3. Check and enforce in `process_dialogue_task()` before AI call
4. **Test:** Send messages faster than the limit, verify second reply is skipped

**Estimated effort:** 45 minutes

---

### Task 4.3 — SIGHUP whitelist hot-reload
**File:** `main.py`
**Depends on:** 1.4 (signal handler pattern established)
**Steps:**
1. Add SIGHUP handler in `main.py`
2. Handler calls `load_whitelist(state)` on the current state
3. **Test:** Edit whitelist, send SIGHUP, verify new entry is active without restart

**Estimated effort:** 30 minutes

---

## Epic 5 — Product Intelligence Layer

**Goal:** Make the system aware of its own outcomes.
**Depends on:** Epic 6 Task 6.1 (operator notifications must exist first)

---

### Task 5.1 — Meeting signal detection
**File:** `src/meeting_detector.py` (new), `dialog.py`
**Depends on:** 6.1 (operator notifications)
**Steps:**
1. Create `meeting_detector.py` with `detect_meeting_signal(text) -> bool`
2. Build signal list for Russian + English
3. Call in `process_dialogue_task()` on incoming user message
4. On detection: log prominently + send operator notification
5. Add `record_event("meeting_signal", ...)` (depends on 5.3)
6. **Test:** Send messages with meeting language, verify detection and notification

**Estimated effort:** 1.5 hours

---

### Task 5.2 — Goal tracking state
**Files:** `state.py`, `dialog.py`
**Depends on:** 5.1
**Steps:**
1. Add `meeting_signals_detected: Set[int]` to `BotState`
2. On detection, add `chat_id` to set
3. Log summary periodically
4. **Test:** Verify set is populated on meeting signal

**Estimated effort:** 30 minutes

---

### Task 5.3 — Minimal stats recording
**File:** `src/stats.py` (new)
**Depends on:** 1.1 (atomic write pattern)
**Steps:**
1. Create `stats.py` with `record_event(event_type, metadata)`
2. Add event calls at: opener sent, conversation started, meeting signal, API fallback, profile liked/disliked
3. Keep stats file bounded to last 1000 events
4. **Test:** Run through a profile card flow, verify stats.json populated

**Estimated effort:** 1 hour

---

## Epic 6 — Operator Control & Observability

**Goal:** Make the system's state visible and controllable without log-tailing.
**Depends on:** Nothing (can be done in parallel with other epics)

---

### Task 6.1 — Operator notification channel
**File:** `src/operator_notify.py` (new)
**Depends on:** Nothing
**Steps:**
1. Create `operator_notify.py` with `operator_notify(client, message)` async function
2. Pass `client` or `TelegramAdapter` instance where needed
3. **Test:** Call directly, verify message arrives in Saved Messages

**Estimated effort:** 20 minutes

---

### Task 6.2 — System heartbeat
**File:** `app.py`
**Depends on:** 6.1
**Steps:**
1. Add `_heartbeat()` async function
2. Create task in `run()` before `asyncio.Event().wait()`
3. Emit hourly status: active conversations, uptime, total matches today
4. **Test:** Wait for first heartbeat interval (or reduce to 60s for testing)

**Estimated effort:** 30 minutes

---

### Task 6.3 — Critical event notifications
**Files:** `ai_client.py`, `storage.py`, `dialog.py`
**Depends on:** 6.1
**Steps:**
1. Notify on 3× API retry exhaustion
2. Notify on history corruption detected
3. Notify on meeting signal (done in 5.1)
4. **Test:** Trigger each condition, verify notification received

**Estimated effort:** 45 minutes

---

## Epic 7 — Architecture Refactor

**Goal:** Improve long-term maintainability. Reduce coupling. Enable future extension.
**Depends on:** All prior epics complete (refactor after functionality is correct)

---

### Task 7.1 — Split config.py
**Files:** `credentials.py`, `settings.py`, `src/prompts/` (new structure)
**Depends on:** Epic 3 complete (prompts finalized before moving them)
**Steps:**
1. Create `credentials.py`, `settings.py`, `src/prompts/first_message.txt`, `src/prompts/conversation.txt`
2. Move content to respective files
3. Update all imports across all modules
4. Update `.gitignore` to exclude `credentials.py`
5. **Test:** Full smoke test — bot starts, all features work

**Estimated effort:** 2 hours

---

### Task 7.2 — TelegramAdapter
**File:** `src/telegram_adapter.py` (new)
**Depends on:** 4.1 (FloodWait handler already in utils.py)
**Steps:**
1. Create `TelegramAdapter` class with all Telegram interaction methods
2. Update `leomatch.py`, `dialog.py`, `app.py` to use adapter instead of raw client
3. Update `partial()` bindings in `app.py` to pass adapter
4. **Test:** Full smoke test

**Estimated effort:** 2 hours

---

### Task 7.3 — Replace PendingProfile string with typed dataclass
**Files:** `state.py`, `leomatch.py`
**Depends on:** Nothing
**Steps:**
1. Add `PendingMatch` dataclass to `state.py`
2. Replace `last_seen_anket_text` with `pending_match: Optional[PendingMatch]`
3. Update all access in `leomatch.py`
4. **Test:** Full Scout pipeline smoke test

**Estimated effort:** 1 hour

---

### Task 7.4 — Unit test suite foundation
**Directory:** `tests/` (new)
**Depends on:** 7.1 (settings split makes imports cleaner)
**Steps:**
1. Create `tests/` directory with `conftest.py`
2. Write tests for `cleanup_ai_response`, `get_message_text`, `ANKET_PATTERN`, `validate_response`, `detect_meeting_signal`
3. Add `pytest` to `requirements.txt`
4. **Test:** Run `pytest` — all tests pass

**Estimated effort:** 3 hours

---

# Part C — Dependency Map & Execution Order

```
WEEK 1 — FOUNDATION (Epics 1 + 2 core)
─────────────────────────────────────────────────────
Task 1.1  Atomic write                    [No deps]
Task 1.2  Preserve corrupt file           [After 1.1]
Task 1.4  SIGTERM handler                 [No deps]  ← can parallel with 1.1
Task 4.1  FloodWait handler               [No deps]  ← can parallel
Task 6.1  Operator notification channel   [No deps]  ← can parallel

Task 1.3  Move save off event loop        [After 1.1]
Task 2.1  system_instruction=             [No deps]
Task 2.2  API timeout + error handling    [No deps]  ← can parallel with 2.1
Task 2.3  Orphaned turn fix               [After 2.2]
Task 2.4  OutputValidator                 [After 2.3]
Task 2.5  Empty response guard            [After 2.4]

WEEK 2 — FLOW CORRECTNESS (Epic 3 core + Epic 4)
─────────────────────────────────────────────────────
Task 3.1  Store opener in history         [After 1.3, 2.1]
Task 3.2  Burst message accumulation      [No deps]
Task 4.2  Per-user rate limiting          [No deps]
Task 4.3  SIGHUP whitelist reload         [After 1.4]
Task 6.2  Heartbeat                       [After 6.1]
Task 6.3  Critical event notifications    [After 6.1]

WEEK 3 — INTELLIGENCE + QUALITY (Epics 5 + remaining 3)
─────────────────────────────────────────────────────
Task 1.5  Data pruning                    [After 1.1]
Task 3.3  Profile quality filter          [After 2.1, 2.2]
Task 3.5  Smooth reply delay              [No deps]
Task 5.3  Stats recording                 [After 1.1]
Task 5.1  Meeting signal detection        [After 6.1]
Task 5.2  Goal tracking state             [After 5.1]

WEEK 4 — MEMORY + ARCHITECTURE (Epic 3 remainder + Epic 7)
─────────────────────────────────────────────────────
Task 3.4  Persistent conversation memory  [After 2.1, 1.3, 1.1]
Task 7.3  PendingMatch typed dataclass    [No deps]
Task 7.1  Config split                    [After Epic 3 complete]
Task 7.2  TelegramAdapter                 [After 4.1]
Task 7.4  Unit test suite                 [After 7.1]
```

**Execution principle:** Complete Epic 1 before anything else. Task 1.1 (atomic write) is the single highest-priority change in the entire codebase — it is a precondition for trusting any subsequent data operation. Epic 2 tasks 2.1 through 2.4 form a strict chain and must be executed in order. All other tasks are largely independent and can be parallelized.

**Checkpoints before advancing:**
- After Week 1: Run bot for 24 hours; confirm no data loss; confirm AI replies are persona-correct
- After Week 2: Confirm openers appear in conversation context; confirm burst messages reach AI
- After Week 3: Receive first meeting detection notification in Saved Messages
- After Week 4: Run full pytest suite; zero failures
