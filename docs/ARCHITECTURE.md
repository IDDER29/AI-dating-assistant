# System Architecture

This document explains how the AI Dating Assistant works at a technical level —
module responsibilities, data flows, key algorithms, and design decisions.

---

## Table of Contents

1. [High-Level Overview](#high-level-overview)
2. [The Two Pipelines](#the-two-pipelines)
3. [Module Map](#module-map)
4. [Shared State (`BotState`)](#shared-state-botstate)
5. [Data Persistence Layer](#data-persistence-layer)
6. [AI Integration Layer](#ai-integration-layer)
7. [Security & Validation Layer](#security--validation-layer)
8. [Startup Sequence](#startup-sequence)
9. [Shutdown Sequence](#shutdown-sequence)
10. [Key Algorithms](#key-algorithms)
11. [Design Decisions](#design-decisions)

---

## High-Level Overview

```
                    ┌──────────────────────────────────────────┐
                    │          Python asyncio event loop        │
                    │                                           │
  Telegram  ───────►│  ┌──────────────┐  ┌──────────────────┐  │
  (@leomatchbot)    │  │    SCOUT     │  │  INTERLOCUTOR    │  │
                    │  │  (leomatch)  │  │    (dialog)      │  │
  Telegram  ───────►│  └──────┬───────┘  └────────┬─────────┘  │
  (private msgs)    │         │                   │             │
                    │         ▼                   ▼             │
                    │  ┌──────────────────────────────────────┐ │
                    │  │           ai_client.py               │ │
                    │  │  (Gemini API — all calls here)       │ │
                    │  └──────────────────────────────────────┘ │
                    │         │                   │             │
                    │         ▼                   ▼             │
                    │  ┌──────────────────────────────────────┐ │
                    │  │        BotState (shared)             │ │
                    │  │  • conversation_histories            │ │
                    │  │  • conversation_memories             │ │
                    │  │  • sent_openers                      │ │
                    │  │  • whitelist_ids                     │ │
                    │  └──────────────────────────────────────┘ │
                    │         │                                  │
                    │         ▼                                  │
                    │  ┌──────────────────────────────────────┐ │
                    │  │   storage.py (atomic JSON files)     │ │
                    │  │   data/conversation_histories.json   │ │
                    │  │   data/conversation_memories.json    │ │
                    │  └──────────────────────────────────────┘ │
                    └──────────────────────────────────────────┘
```

---

## The Two Pipelines

### Scout Pipeline (`leomatch.py`)

**Trigger:** Any message from `@leomatchbot`

**Flow:**

```
@leomatchbot message arrives
         │
         ▼
   Is it a profile card?
   (ANKET_PATTERN regex)
         │
    YES  │  NO
         │  └──► process_leomatch_message()
         │       (menu nav, opener sending, etc.)
         ▼
   Cancel previous task if pending
         │
         ▼
   process_leomatch_task() — background asyncio.Task
         │
         ▼
   Wait out cooldown (70s between actions)
         │
         ▼
   Has description? ──NO──► dislike_profile() immediately
         │
        YES
         ▼
   classify_profile_quality(description)
   → Gemini: "Is this worth messaging? YES/NO"
         │
      YES│  NO
         │  └──► dislike_profile()
         ▼
   like_profile() → "💌 / 📹"
   Store PendingMatch in state
         │
         ▼
   (Later: "Write a message for this user" arrives)
         │
         ▼
   generate_first_message(anket_text)
   → Gemini generates personalised opener
         │
         ▼
   send_opener(intro_message)
         │
         ▼
   Append to state.sent_openers (FIFO buffer, max 5)
   Clear state.pending_match
```

### Interlocutor Pipeline (`dialog.py`)

**Trigger:** Any private message from a non-whitelisted user

**Flow:**

```
Private message arrives
         │
         ▼
   Extract chat_id, user_name immediately
   (avoids Pyrogram object lifetime issue)
         │
         ▼
   Append message text to state.message_buffers[chat_id]
         │
         ▼
   Cancel any previous pending task for this chat
   (debounce — user is still typing)
         │
         ▼
   process_dialogue_task(chat_id, user_name) — background asyncio.Task
         │
         ▼
   Sleep GRACE_PERIOD_SECONDS (7s)
   (collects burst messages)
         │
         ▼
   Pop all buffered messages → join with "\n"
   → sanitize_user_input() (length, control chars, NFC)
         │
         ▼
   detect_meeting_signal() ?
   → YES: add to meeting_signals_detected, notify operator
         │
         ▼
   Compute gap_seconds since last message
   → compute_reply_delay(gap_seconds)
   (smooth curve: 15s–10800s depending on gap)
         │
         ▼
   Sleep the computed delay
         │
         ▼
   Per-user rate limit check (MIN_REPLY_INTERVAL_SEC = 45s)
   → Too soon? Skip this cycle
         │
         ▼
   generate_conversation_response(chat_id, user_message)
   (see AI Integration section)
         │
         ▼
   validate_response(ai_response)
   → Invalid? Notify operator, skip send
         │
         ▼
   Simulate typing (len(response) / TYPING_SPEED_CPS seconds)
         │
         ▼
   send_reply() via TelegramAdapter
   → FloodWait? Retry with backoff (up to 3 times)
         │
         ▼
   Update state.last_reply_times[chat_id]
   Fire asyncio.create_task(_persist_histories(state))
```

---

## Module Map

```
src/
│
├── main.py              ENTRY POINT
│                        • Registers SIGTERM, SIGHUP, SIGUSR1 handlers
│                        • Checks file permissions at startup
│                        • Runs _run_with_graceful_shutdown(run())
│
├── app.py               LIFECYCLE COORDINATOR
│                        • Creates BotState, TelegramAdapter
│                        • Loads data from disk (histories, memories, whitelist)
│                        • Registers Pyrogram message handlers
│                        • Starts _heartbeat() background task
│                        • Calls replay_last_message() at startup
│                        • Contains shutdown_gracefully() — called on SIGTERM
│
├── leomatch.py          SCOUT PIPELINE
│                        • leomatch_handler() — Pyrogram callback
│                        • process_leomatch_task() — background task
│                        • process_leomatch_message() — direct action executor
│                        • replay_last_message() — startup recovery
│
├── dialog.py            INTERLOCUTOR PIPELINE
│                        • private_chat_handler() — Pyrogram callback
│                        • process_dialogue_task() — background task with full reply cycle
│                        • _persist_histories() — background async save
│
├── ai_client.py         AI INTEGRATION
│                        • initialize_ai() — creates genai.Client, validates model
│                        • with_api_retry() — async retry wrapper (timeout + error handling)
│                        • generate_first_message() — opener generation
│                        • classify_profile_quality() — profile quality YES/NO
│                        • _update_memory() — background memory extraction
│                        • generate_conversation_response() — main reply generation
│                        • _to_sdk_contents() — internal history → SDK format
│                        • _record_api_call() — logs token usage to stats.json
│
├── output_validator.py  RESPONSE VALIDATION
│                        • validate_response(text) → ValidationResult
│                        • Checks: empty, too long, too many |||parts, prompt leak,
│                          persona collapse (AI admits being AI)
│
├── input_sanitizer.py   INPUT VALIDATION
│                        • sanitize_user_input(text) → str
│                        • Strips control chars, NFC normalises, truncates at 1000 chars
│                        • Detects injection patterns (logs, does NOT block)
│
├── meeting_detector.py  MEETING SIGNAL DETECTION
│                        • detect_meeting_signal(text) → bool
│                        • 30 Russian + English meeting-suggestion phrases
│
├── storage.py           DATA PERSISTENCE
│                        • save_json_data() — atomic write (tmp→rename + fsync)
│                        • load_json_data() — load with corrupt-file backup
│                        • save/load_histories(), save/load_memories()
│                        • prune_stale_histories() — 90-day TTL
│                        • delete_user_data() — GDPR deletion
│                        • whitelist_user() — add to whitelist + persist
│
├── stats.py             EVENT RECORDING
│                        • record_event(event_type, metadata) — append to stats.json
│                        • get_api_stats_summary(hours) — aggregates api_call events
│
├── state.py             SHARED STATE
│                        • PendingMatch — typed profile card container
│                        • BotState — central dataclass with __post_init__ validation
│
├── telegram_adapter.py  TELEGRAM ABSTRACTION
│                        • TelegramAdapter — wraps all Pyrogram calls
│                        • like_profile(), dislike_profile(), navigate_to_profiles()
│                        • send_opener(), send_reply(), show_typing(), mark_read()
│                        • notify_operator(), get_last_bot_message()
│
├── operator_notify.py   OPERATOR ALERTS
│                        • operator_notify(client, message) — sends to Saved Messages
│
├── settings.py          CONSTANTS
│                        • All behavioural constants (safe to commit)
│                        • Loads prompt text files at import time
│                        • compute_reply_delay(gap_seconds) — smooth delay curve
│
├── credentials.py       API KEYS
│                        • Reads TELEGRAM_API_ID, TELEGRAM_API_HASH, GEMINI_API_KEY from .env
│                        • Gitignored
│
├── logging_setup.py     LOGGING
│                        • redact(text, max_chars) — PII-safe log helper
│                        • StructuredFormatter — JSON log lines
│                        • BotLogger — chat-scoped logger with chat_id field
│                        • setup_logging() — configures root logger
│
└── utils.py             UTILITIES
                         • get_message_text(message) → str | None
                         • safe_send_message(client, chat_id, text) — FloodWait retry
```

---

## Shared State (`BotState`)

`BotState` is a frozen dataclass (all fields are mutated in place) shared between both pipelines.
It is created once in `app.py:run()` and passed through every function call.

```python
@dataclass
class BotState:
    # Profile processing
    pending_match: Optional[PendingMatch]     # current liked profile awaiting opener

    # Timekeeping
    last_action_time: datetime                # last Scout like/dislike (for cooldown)
    start_time: datetime                      # bot start time (for heartbeat uptime)

    # Conversation data (persisted to disk)
    conversation_histories: Dict[str, list]   # {chat_id_str: [turn, ...]}
    conversation_memories: Dict[str, str]     # {chat_id_str: "Name: X. Likes Y."}

    # Scout→Interlocutor bridge
    sent_openers: List[dict]                  # FIFO queue of unsent opener texts

    # In-flight state (not persisted)
    message_buffers: Dict[int, List[str]]     # burst message accumulation
    active_dialogue_tasks: Dict[int, Task]    # running reply tasks
    last_reply_times: Dict[int, datetime]     # for per-user rate limiting
    meeting_signals_detected: Set[int]        # chat_ids where meeting was detected
    leomatch_task: Optional[Task]             # current Scout background task
    whitelist_ids: Set[int]                   # users the bot ignores

    # Client objects
    active_model_name: str                    # current Gemini model name
    ai_client: genai.Client                   # google-genai client
    app: pyrogram.Client                      # Telegram client
```

**Ownership rules:**
- `leomatch.py` owns `pending_match`, `sent_openers`, `leomatch_task`, `last_action_time`
- `dialog.py` owns `message_buffers`, `active_dialogue_tasks`, `last_reply_times`, `meeting_signals_detected`
- `ai_client.py` owns `conversation_histories`, `conversation_memories`
- `storage.py` owns `whitelist_ids` (load/save)
- `app.py` owns `ai_client`, `app`, `start_time`

---

## Data Persistence Layer

All runtime data lives in `data/` as JSON files.

### Conversation Histories (`data/conversation_histories.json`)

```json
{
  "123456789": [
    {"role": "model", "parts": ["hey, coffee fan spotted)"], "timestamp": "2026-06-01T10:00:00+00:00"},
    {"role": "user",  "parts": ["lol how did you know"],    "timestamp": "2026-06-01T10:05:00+00:00"},
    {"role": "model", "parts": ["profile didn't hide it)"], "timestamp": "2026-06-01T10:07:00+00:00"}
  ]
}
```

- Keyed by Telegram chat ID (as string)
- Each turn has `role` ("user" or "model"), `parts` (list of strings), `timestamp` (ISO UTC)
- Trimmed to last 20 turns by count AND by estimated token budget (whichever is stricter)
- Auto-pruned after 90 days of inactivity

### Conversation Memories (`data/conversation_memories.json`)

```json
{
  "123456789": "Name: Anna. Works as a nurse. Likes hiking and coffee."
}
```

- 1–2 sentence factual summary extracted by Gemini every 4 turns
- Prepended to the first user turn in every API call (not stored in history)
- Survives context window trimming

### Atomic Write Guarantee

Every write to a JSON file follows the pattern:
```
write to .tmp file → fsync → os.rename(tmp, target)
```

`os.rename()` is atomic on POSIX — a crash at any point leaves the original file intact.
If a `.tmp` file is left behind (partial write), it is cleaned up on next write.

---

## AI Integration Layer

### Gemini Client

The bot uses `google-genai` (not the deprecated `google-generativeai`). One `genai.Client`
instance is created at startup and shared across all API calls.

### All API Calls

```
generate_first_message()      → client.aio.models.generate_content(model, contents=prompt)
classify_profile_quality()    → client.aio.models.generate_content(model, contents=prompt)
_update_memory()              → client.aio.models.generate_content(model, contents=prompt)
generate_conversation_response() → client.aio.models.generate_content(
                                      model, contents=sdk_history, config=GenerateContentConfig(
                                          system_instruction=CONVERSATION_SYSTEM_PROMPT
                                      ))
```

All calls are **native async** (`client.aio.*`) — no `asyncio.to_thread` needed.

### History Format Conversion

Internal storage format (dict):
```python
{"role": "user", "parts": ["message text"], "timestamp": "..."}
```

SDK format (for API calls):
```python
types.Content(role="user", parts=[types.Part(text="message text")])
```

The conversion happens in `_to_sdk_contents()` in `ai_client.py` — only for the API call,
the internal dict format is never changed.

### Retry Policy (`with_api_retry`)

| Error | HTTP Code | Action |
|-------|-----------|--------|
| `ClientError` 429 | Too Many Requests | Retry after 60s, up to 3 times |
| `ServerError` | 5xx | Retry after 15s, up to 3 times |
| `asyncio.TimeoutError` | — | Retry after 10s, up to 3 times |
| `ClientError` 404 | Model not found | Return None immediately (no retry) |
| `ClientError` 403 | Bad API key | Return None immediately (no retry) |
| Any other `ClientError` | 4xx | Return None immediately (no retry) |

On `None` return, the caller's user turn is popped from history (rollback) to prevent orphaned turns.

---

## Security & Validation Layer

### Input Sanitization (`input_sanitizer.py`)

Applied to every user message before it enters history:
1. Strip control characters (except `\n`, `\t`, `\r`)
2. Unicode NFC normalization (closes homoglyph attack surface)
3. Truncate to 1000 characters
4. Detect and log injection patterns ("ignore all previous instructions", etc.)

Injection patterns are **logged, not blocked** — the ANTI-DEANON protocol handles deflection.

### Output Validation (`output_validator.py`)

Applied to every Gemini response before it reaches the user:
1. Not empty / whitespace-only
2. Under 600 characters
3. At most 4 ladder parts (`|||` separators)
4. No prompt leak markers ("dossier", "your task is to", "anti-deanon", etc.)
5. No persona collapse markers ("i am an ai", "i cannot fulfill", "i'm not able to", etc.)

Rejection triggers history rollback (user turn popped) and returns the fallback message.

### PII-Free Logging

No message content is written to logs. The `redact()` helper is used at every log site:
- Profile text → only length logged
- User messages → only length logged
- AI responses → only length logged
- Conversation memories → only length logged

---

## Startup Sequence

```
main.py
  │
  ├── _check_file_permissions()           warn if .env/.session are world-readable
  ├── signal.signal(SIGTERM, handler)
  ├── signal.signal(SIGHUP, handler)
  ├── signal.signal(SIGUSR1, handler)
  └── asyncio.run(_run_with_graceful_shutdown())
           │
           └── app.py:run()
                 │
                 ├── setup_logging()
                 ├── BotState()                     create state
                 ├── initialize_ai(state)           create genai.Client, validate model
                 ├── initialize_app(state)          create Pyrogram Client
                 │
                 ├── load_histories(state)          read conversation_histories.json
                 ├── prune_stale_histories(state)   remove > 90 day old entries
                 ├── load_memories(state)           read conversation_memories.json
                 ├── load_whitelist(state)          read whitelist.json
                 │
                 ├── async with state.app:          connect to Telegram
                 │     ├── TelegramAdapter(state.app, BOT_USERNAME)
                 │     ├── adapter.resolve_peer(BOT_USERNAME)  verify @leomatchbot reachable
                 │     ├── register leomatch_handler
                 │     ├── register private_chat_handler
                 │     ├── adapter.notify_operator("🚀 Bot started...")
                 │     ├── replay_last_message(...)  recover from last @leomatchbot message
                 │     ├── asyncio.create_task(_heartbeat(...))
                 │     └── asyncio.Event().wait()    run forever
```

---

## Shutdown Sequence

Triggered by SIGTERM (from systemd/Ctrl+C), which raises `KeyboardInterrupt`:

```
KeyboardInterrupt caught by _run_with_graceful_shutdown()
  │
  └── shutdown_gracefully(state)
        │
        ├── Cancel all state.active_dialogue_tasks
        ├── asyncio.wait(tasks, timeout=10s)  ← gives tasks time to finish
        │
        ├── Cancel state.leomatch_task
        ├── asyncio.wait_for(leomatch_task, timeout=5s)
        │
        ├── Drain _persist_histories tasks (timeout=5s)
        │
        ├── save_histories(state)   ← FINAL authoritative write
        └── save_memories(state)    ← FINAL authoritative write

Total maximum shutdown time: 20 seconds
(systemd TimeoutStopSec = 30s — safely above this)
```

---

## Key Algorithms

### Reply Delay Curve (`compute_reply_delay`)

Replaces the old binary 15-minute threshold with a continuous probability curve:

| Time since last message | Delay range |
|------------------------|-------------|
| < 2 minutes | 15–45 seconds |
| 2–15 minutes | 15–90 seconds |
| 15–60 minutes | 15–90s (fast, decreasing) OR 120–600s (medium, increasing probability) |
| 1–24 hours | 300–1200s OR 1800–7200s (5–25% chance of long delay) |
| > 24 hours | 300–1800s OR 3600–10800s (5% chance of very long) |

### Context Window Management

History is trimmed by estimated token count first (more accurate), then by turn count (hard ceiling):

```python
# 1. Token budget trim — keep at least 4 turns
while len(history) > 4 and _estimate_history_tokens(history) > MAX_CONTEXT_TOKENS:
    history.pop(0)  # drop oldest turn

# 2. Turn count hard cap
if len(history) > MAX_HISTORY_LENGTH:
    history = history[-MAX_HISTORY_LENGTH:]
```

Token estimation: `max(1, len(text) // 3)` — conservative for mixed Russian/English.

### Opener Injection

When a match sends their first private message, the bot checks `state.sent_openers` (FIFO):

```python
if not state.conversation_histories[chat_id_str]:
    if state.sent_openers:
        opener = state.sent_openers.pop(0)        # oldest unmatched opener
        state.conversation_histories[chat_id_str] = [{
            "role": "model",
            "parts": [opener["text"]],
            "timestamp": opener["sent_at"]
        }]
```

This gives the AI context for its own first message — it never starts a conversation amnesiac.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Single process, two pipelines** | Shared `BotState` makes opener→conversation handoff trivial without IPC |
| **asyncio, not threads** | Pyrogram is async; all I/O is naturally async; threads are only used for sync Gemini SDK calls via `asyncio.to_thread` |
| **No database — JSON files** | Zero infrastructure; data is human-readable; atomic writes make it safe |
| **One `genai.Client` instance** | Reused across all calls; Gemini model validated once at startup |
| **`system_instruction=` per call, not cached** | System prompt is ~800 tokens, below Gemini's 4K minimum for `CachedContent`; re-sending is correct |
| **FIFO opener buffer (max 5)** | Approximate match — if two mutual matches arrive before either replies, first reply gets first opener; better than no context at all |
| **`TelegramAdapter` abstraction** | All Pyrogram calls in one class — swap library by editing one file |
| **Prompt files, not Python strings** | Non-developers can edit the persona without opening `.py` files |
| **Inject memory into first history turn** | Memory is prepended to the oldest user turn in the API payload — not stored in history, so it doesn't consume context turns |
