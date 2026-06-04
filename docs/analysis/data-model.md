# Data Model — AI Dating Assistant

_Last updated: 2026-06-04_

---

## Table of Contents

1. [Overview of the Data Layer](#1-overview-of-the-data-layer)
2. [Persistent Entities](#2-persistent-entities)
   - 2.1 [ConversationHistory](#21-conversationhistory)
   - 2.2 [ConversationTurn](#22-conversationturn)
   - 2.3 [WhitelistedUser](#23-whitelisteduser)
3. [Ephemeral (In-Memory) Entities](#3-ephemeral-in-memory-entities)
   - 3.1 [BotState](#31-botstate)
   - 3.2 [ActiveDialogueTask](#32-activedialoguetask)
   - 3.3 [LeomatchTask](#33-leoматchtask)
   - 3.4 [PendingProfile](#34-pendingprofile)
4. [Transient (Single-Request) Objects](#4-transient-single-request-objects)
   - 4.1 [IncomingMessage (Pyrogram)](#41-incomingmessage-pyrogram)
   - 4.2 [GeminiChatHistory (API payload)](#42-geminichathistory-api-payload)
   - 4.3 [AIResponse](#43-airesponse)
5. [Entity Relationship Diagram](#5-entity-relationship-diagram)
6. [Data Lifecycle Analysis](#6-data-lifecycle-analysis)
   - 6.1 [ConversationTurn lifecycle](#61-conversationturn-lifecycle)
   - 6.2 [PendingProfile lifecycle](#62-pendingprofile-lifecycle)
   - 6.3 [WhitelistedUser lifecycle](#63-whitelisteduser-lifecycle)
7. [Data Ownership Rules](#7-data-ownership-rules)
8. [Schema Design Decisions](#8-schema-design-decisions)
9. [Consistency Rules & Validation](#9-consistency-rules--validation)
10. [Data Bottlenecks & Normalization Issues](#10-data-bottlenecks--normalization-issues)
11. [Business Object Evolution Over Time](#11-business-object-evolution-over-time)

---

## 1. Overview of the Data Layer

The system has no database engine. Its entire persistence layer consists of two JSON files and one session binary. All other data lives in memory and is destroyed on process exit.

### Data stores at a glance

| Store | Location | Format | Persistence | Mutable at runtime |
|-------|----------|--------|------------|-------------------|
| Conversation histories | `data/conversation_histories.json` | JSON object | Persistent | Yes — written after every AI reply |
| Whitelist | `data/whitelist.json` | JSON array | Persistent | No — read-only at runtime |
| Telegram session | `ai_dating_user.session` | SQLite (Pyrogram internal) | Persistent | By Pyrogram internally |
| Runtime state | Python heap (`BotState`) | In-memory object | Ephemeral | Yes — continuous |
| Log file | `ai_bot_logs.txt` | Plain text (rotating) | Persistent | Append-only |

### Key observation
There are **only two application-controlled data entities on disk**: the conversation history and the whitelist. Everything else — active tasks, cooldown timers, the pending profile buffer — exists only in RAM and is rebuilt (or discarded) on each restart.

---

## 2. Persistent Entities

### 2.1 ConversationHistory

The top-level container for all conversation data, keyed by Telegram user ID.

**Physical schema (`conversation_histories.json`):**
```json
{
  "<telegram_user_id_string>": [ ...ConversationTurn[] ],
  "<telegram_user_id_string>": [ ...ConversationTurn[] ]
}
```

**Logical schema:**

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `user_id` | string (JSON key) | Non-null, unique per entry | Telegram user ID as string. Must be string — JSON requires string keys. Original Telegram ID is an integer. |
| `turns` | array of ConversationTurn | Max 20 entries (sliding window) | Ordered chronologically oldest-to-newest |

**Identity key:** `user_id` (Telegram user ID, string-cast)

**Created by:** `ai_client.generate_conversation_response()` — first time a user sends a message and gets an AI reply

**Updated by:** `ai_client.generate_conversation_response()` — on every AI reply (two turns appended: user + model)

**Deleted by:** Never — no deletion logic exists in the codebase

**Read by:**
- `ai_client.generate_conversation_response()` — to build Gemini chat history
- `dialog.process_dialogue_task()` — to check last message timestamp for session classification

**Capacity:** Unbounded number of conversations (one entry per unique user). Each conversation is bounded at 20 turns.

---

### 2.2 ConversationTurn

A single message in a conversation — either from the user or from the AI.

**Physical schema (element of the turns array):**
```json
{
  "role": "user" | "model",
  "parts": ["message text as single string"],
  "timestamp": "2026-06-04T14:23:11.000000+00:00"
}
```

**Logical schema:**

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `role` | enum string | Must be `"user"` or `"model"` | Gemini API convention. `"user"` = real user message. `"model"` = AI-generated reply. |
| `parts` | string array | Always exactly 1 element | Gemini API uses arrays for multi-modal content; this system always has one text string |
| `timestamp` | ISO 8601 UTC string | Non-null, UTC timezone | Format: `datetime.datetime.now(datetime.timezone.utc).isoformat()`. Used for session classification only. Not sent to Gemini API. |

**Identity:** No explicit ID. Position within the parent array is the implicit ordering key.

**Invariant:** Turns must strictly alternate `user` → `model` → `user` → `model`. The code enforces this by always appending a user turn immediately before each AI call, and a model turn immediately after each AI response.

**Created by:** `ai_client.generate_conversation_response()`:
- User turn: appended when the function is called, before the API call
- Model turn: appended after successful AI response

**Updated by:** Never — turns are immutable once written

**Deleted by:** Never individually. The entire array is trimmed to the last 20 entries (the sliding window truncates from the front), which effectively deletes older turns by omission.

**Lifetime:** From creation until the conversation grows beyond 20 turns, at which point the oldest turn is dropped from the sliding window.

---

### 2.3 WhitelistedUser

A Telegram user ID that should bypass AI processing entirely. The operator handles these conversations manually.

**Physical schema (`whitelist.json`):**
```json
[123456789, 987654321]
```

**Logical schema:**

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `user_id` | integer | Non-null, unique | Telegram user ID as integer. Note the type inconsistency: stored as integer in whitelist.json but as string key in conversation_histories.json |

**Identity key:** The integer value itself (set semantics)

**Loaded into:** `state.whitelist_ids` as a Python `set[int]` for O(1) membership testing

**Created by:** Manual operator edit of `whitelist.json`

**Updated by:** Manual operator edit only

**Deleted by:** Manual operator edit only

**Read by:** `dialog.private_chat_handler()` — checked on every incoming private message

**Runtime representation:** After loading, whitelisted users exist only as `int` members of `state.whitelist_ids`. The original JSON array is not kept in memory.

---

## 3. Ephemeral (In-Memory) Entities

These exist only in the Python heap inside `BotState`. They are rebuilt from scratch on each startup or simply lost.

### 3.1 BotState

The root in-memory object. There is exactly one instance for the lifetime of the process.

**Schema:**

| Field | Python type | Default | Rebuilt on restart? |
|-------|------------|---------|---------------------|
| `conversation_histories` | `Dict[str, list]` | Loaded from JSON | Yes — from JSON file |
| `whitelist_ids` | `Set[int]` | Loaded from JSON | Yes — from JSON file |
| `model` | `GenerativeModel \| None` | Initialized by `initialize_ai` | Yes — from API key |
| `app` | `pyrogram.Client \| None` | Initialized by `initialize_app` | Yes — from credentials + session file |
| `last_seen_anket_text` | `str \| None` | `None` | No — lost on restart |
| `last_action_time` | `datetime` | `datetime.min` (UTC) | No — resets to epoch on restart |
| `start_time` | `datetime` | `now()` | No — resets to current time |
| `active_dialogue_tasks` | `Dict[int, asyncio.Task]` | `{}` | No — tasks are lost on restart |
| `leomatch_task` | `asyncio.Task \| None` | `None` | No — task is lost on restart |

**Restart behavior:**
- Persistent fields (`conversation_histories`, `whitelist_ids`, `model`, `app`) are fully restored.
- Ephemeral fields (`last_seen_anket_text`, `last_action_time`, `active_dialogue_tasks`, `leomatch_task`) are reset. Any in-progress Scout or Interlocutor actions are abandoned. The startup replay in `app.py` partially compensates for lost Scout state.

---

### 3.2 ActiveDialogueTask

An in-flight asyncio task for a specific private conversation. Represents a pending reply cycle.

**Implicit schema:**

| Attribute | Source | Value |
|-----------|--------|-------|
| `chat_id` | Dict key in `state.active_dialogue_tasks` | Integer Telegram chat ID |
| `task` | Dict value | `asyncio.Task` object |
| Stage | Implicit (task is running) | One of: grace sleep, delay sleep, API call, message delivery |

**Created by:** `dialog.private_chat_handler()` — on every incoming private message (after cancelling any existing task for the same chat_id)

**Cancelled by:** `dialog.private_chat_handler()` — when a new message arrives from the same user

**Removed by:** `dialog.process_dialogue_task()` `finally` block — on normal completion, cancellation, or exception

**Lifetime:** From message receipt to reply delivery (or task cancellation). Can be as short as 7 seconds (grace period only) or as long as 3+ hours (long-mode delay).

---

### 3.3 LeomatchTask

The single in-flight asyncio task for Scout profile processing. Only one exists at a time.

**Implicit schema:**

| Attribute | Source | Value |
|-----------|--------|-------|
| `task` | `state.leomatch_task` | `asyncio.Task \| None` |
| Stage | Implicit | One of: cooldown sleep, message processing, API call |

**Created by:** `leomatch.leomatch_handler()` — on each incoming profile card from @leomatchbot

**Cancelled by:** `leomatch.leomatch_handler()` — when a newer profile card arrives before the current task finishes

**Completed by:** Natural completion of `process_leomatch_task()` (after cooldown + processing)

**Not cleaned up after completion** (unlike `ActiveDialogueTask`): `state.leomatch_task` retains the reference to the completed task until it is overwritten by the next task. `task.done()` is checked before cancellation.

---

### 3.4 PendingProfile

The profile card text buffered between "profile shown" and "mutual match / write message" events. Not a class — lives as a string field on `BotState`.

**Implicit schema:**

| Attribute | Source | Notes |
|-----------|--------|-------|
| `text` | `state.last_seen_anket_text` | Full raw text of the last seen profile card |
| Format | `"Name, Age, City — Description"` | Matches `ANKET_PATTERN` |

**Created by:** `leomatch.process_leomatch_message()` — when a profile card is received and acted upon (`"💌"` sent)

**Consumed and destroyed by:** `leomatch.process_leomatch_message()` — when "Write a message for this user" is received. Set to `None` after use.

**Overwritten by:** Each new profile card — only the most recent profile is ever buffered. If two likes happen before a mutual match prompt, the first profile text is lost.

**Lost on restart:** If the bot crashes between liking a profile and receiving the "write message" prompt, the pending profile text is lost. On restart, the startup replay may re-receive the "write message" prompt but `state.last_seen_anket_text` will be `None`, causing the opener to be skipped (logged as a warning).

**Lifetime:** From like action → until "write message" prompt (typically seconds to minutes, depending on whether the other user has already liked back)

---

## 4. Transient (Single-Request) Objects

These exist only within a single function call. They are never stored or passed between modules.

### 4.1 IncomingMessage (Pyrogram)

A Pyrogram `Message` object passed to handler callbacks. Contains all Telegram message metadata.

**Fields used by this system:**

| Field | Type | Used by | Purpose |
|-------|------|---------|---------|
| `message.text` | `str \| None` | `utils.get_message_text()` | Text content for text messages |
| `message.caption` | `str \| None` | `utils.get_message_text()` | Text content for media messages |
| `message.chat.id` | `int` | `dialog.py` throughout | Identifies which conversation |
| `message.from_user.first_name` | `str` | `dialog.py` logging | Human-readable name for log lines |
| `message.edit_date` | `datetime \| None` | `leomatch_handler` | Distinguishes new vs edited messages |

**Lifetime:** Created by Pyrogram event dispatch, passed to handler, captured by reference in `asyncio.Task` closure, read at task execution time. Pyrogram holds the object in memory until GC — for long-delay tasks (up to 3 hours), the message object must survive in memory for the entire delay period.

---

### 4.2 GeminiChatHistory (API payload)

The history list constructed and sent to the Gemini API on each conversation request. Never stored — assembled fresh from `state.conversation_histories` on every call.

**Structure:**
```python
[
  # Injected system prompt (positions 0–1, always)
  {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
  {"role": "model", "parts": ["understood, I'm ready..."]},

  # Actual conversation history (from state.conversation_histories)
  {"role": "user",  "parts": ["hello"]},
  {"role": "model", "parts": ["hey)"]},
  ...
  # Last user message is NOT in history — sent via send_message()
]
```

**Relationship to ConversationTurn:** A `GeminiChatHistory` is derived from `ConversationTurn[]` by:
1. Stripping the `timestamp` field (Gemini API does not accept it)
2. Prepending the fake system prompt exchange
3. Removing the last entry (sent separately via `send_message`)

**Lifetime:** Created inside `generate_conversation_response()`, passed to `model.start_chat()`, immediately consumed. Not stored anywhere.

---

### 4.3 AIResponse

The raw response object returned by the Gemini SDK, and the cleaned text extracted from it.

**Fields:**
```python
result      # genai response object — has .text attribute
result.text # raw string from Gemini (may contain |||, dashes, periods)
ai_response # cleaned string after cleanup_ai_response()
parts       # list[str] after splitting on |||, or [ai_response] if no split
```

**Lifetime:** Created inside `generate_conversation_response()` or `generate_first_message()`, cleaned, stored to history (for conversation responses), and returned to the caller. The raw `result` object is discarded after `.text` is extracted.

---

## 5. Entity Relationship Diagram

### Conceptual ERD (text form)

```
╔══════════════════════════════════════════════════════════════════════╗
║                     PERSISTENT DATA LAYER                           ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │       ConversationHistory       │                                ║
║  │─────────────────────────────────│                                ║
║  │ PK  user_id : string            │  (Telegram user ID, stringified)
║  │     [max 20 ConversationTurns]  │                                ║
║  └────────────────┬────────────────┘                                ║
║                   │ contains (1:many, ordered, capped at 20)        ║
║                   │                                                 ║
║  ┌────────────────▼────────────────┐                                ║
║  │          ConversationTurn       │                                ║
║  │─────────────────────────────────│                                ║
║  │     role      : "user"|"model"  │                                ║
║  │     parts[0]  : string          │  (always exactly 1 element)    ║
║  │     timestamp : ISO 8601 UTC    │                                ║
║  └─────────────────────────────────┘                                ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │        WhitelistedUser          │                                ║
║  │─────────────────────────────────│                                ║
║  │ PK  user_id : integer           │  (Telegram user ID, integer)   ║
║  └─────────────────────────────────┘                                ║
╚══════════════════════════════════════════════════════════════════════╝

NOTE: ConversationHistory.user_id and WhitelistedUser.user_id
      refer to the same real-world entity (a Telegram user) but
      have DIFFERENT TYPES (string vs integer) and NO foreign key
      relationship. There is no enforcement that a whitelisted
      user cannot also have a conversation history.

╔══════════════════════════════════════════════════════════════════════╗
║                     EPHEMERAL DATA LAYER (BotState)                 ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │           BotState              │  (singleton, in-memory)        ║
║  │─────────────────────────────────│                                ║
║  │  conversation_histories         │──── mirrors ConversationHistory ║
║  │  whitelist_ids                  │──── mirrors WhitelistedUser     ║
║  │  model                          │──── Gemini model reference      ║
║  │  app                            │──── Pyrogram client reference   ║
║  │  start_time                     │                                 ║
║  │  last_action_time               │──► PendingProfile dependency   ║
║  │                                 │                                 ║
║  │  last_seen_anket_text ──────────┼──► PendingProfile (embedded)   ║
║  │  leomatch_task ─────────────────┼──► LeomatchTask (embedded)     ║
║  │  active_dialogue_tasks ─────────┼──► ActiveDialogueTask[] (map)  ║
║  └─────────────────────────────────┘                                ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │        PendingProfile           │  (0 or 1, embedded in BotState)║
║  │─────────────────────────────────│                                ║
║  │  text : string                  │  (raw profile card text)       ║
║  └─────────────────────────────────┘                                ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │       ActiveDialogueTask        │  (0..N, one per active chat)   ║
║  │─────────────────────────────────│                                ║
║  │ PK  chat_id : integer           │                                ║
║  │     task    : asyncio.Task      │                                ║
║  └─────────────────────────────────┘                                ║
║           │                                                         ║
║           │ corresponds to (no FK enforcement)                      ║
║           ▼                                                         ║
║  ConversationHistory.user_id (same value, different type context)   ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │         LeomatchTask            │  (0 or 1, embedded in BotState)║
║  │─────────────────────────────────│                                ║
║  │  task : asyncio.Task            │                                ║
║  └─────────────────────────────────┘                                ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║               EXTERNAL DATA (TELEGRAM PLATFORM)                     ║
║                                                                     ║
║  ┌─────────────────────────────────┐                                ║
║  │         TelegramUser            │  (external — not owned)        ║
║  │─────────────────────────────────│                                ║
║  │  user_id     : integer          │  PRIMARY KEY in Telegram        ║
║  │  first_name  : string           │  Used only in log messages      ║
║  │  username    : string           │  Not used by this system        ║
║  └─────────────────────────────────┘                                ║
║       │                   │                                         ║
║       │ 1 : many          │ 0/1 : 1                                 ║
║       ▼                   ▼                                         ║
║  ConversationHistory  WhitelistedUser                               ║
║  (system-owned)       (system-owned)                                ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Cardinality summary

| Relationship | Cardinality | Enforced? |
|-------------|-------------|-----------|
| TelegramUser → ConversationHistory | 0 or 1 (user may never get a reply) | No — implicit |
| TelegramUser → WhitelistedUser | 0 or 1 | No — manual list |
| ConversationHistory → ConversationTurn | 0..20 (sliding window) | Yes — in `ai_client.py` |
| BotState → PendingProfile | 0 or 1 (field is `None` or a string) | Yes — field initialization |
| BotState → LeomatchTask | 0 or 1 | Yes — single field |
| BotState → ActiveDialogueTask | 0..N (one per chat) | Yes — dict keyed by chat_id |
| ConversationHistory ↔ WhitelistedUser | No relationship (same real entity, different records) | No |

---

## 6. Data Lifecycle Analysis

### 6.1 ConversationTurn lifecycle

```
BIRTH
  User sends a private Telegram message
        │
        ▼
  private_chat_handler() fires
  [no data written yet — read receipt only]
        │
        ▼ (after grace period + delay)
  generate_conversation_response() called
        │
        ├── User turn CREATED:
        │       role: "user"
        │       parts: [message text]
        │       timestamp: UTC now
        │       → appended to state.conversation_histories[chat_id]
        │
        ├── [API call to Gemini]
        │
        ├── Model turn CREATED:
        │       role: "model"
        │       parts: [cleaned AI response]
        │       timestamp: UTC now
        │       → appended to state.conversation_histories[chat_id]
        │
        └── save_histories() called → both turns written to JSON


AGING
  With each new exchange, the history array grows.
  When len(history) > MAX_HISTORY_LENGTH (20):
        oldest_turn = history[0]
        history = history[-20:]   ← oldest turn implicitly deleted
        save_histories()


DEATH
  ConversationTurns are never explicitly deleted.
  They are displaced from the sliding window after 20 turns.
  The JSON file is never purged — deleted turns are simply absent
  from the saved array after the next save_histories() call.
  If the JSON file is manually deleted, all turns are permanently lost.
```

**Notable gap:** The user message is added to the history **before** the API call. If the API call fails after all 3 retries and returns `None`, the user turn is in the history but no model turn is appended. The next call will see an orphaned user turn followed immediately by the next user turn — two consecutive user turns — which violates the alternating-role invariant the Gemini API expects.

---

### 6.2 PendingProfile lifecycle

```
BIRTH
  @leomatchbot sends a profile card (Name, Age, City — Description)
  ANKET_PATTERN matches
        │
        ▼
  process_leomatch_message():
    description = match.group(4)
    if len(description.strip()) > 10:
        state.last_seen_anket_text = raw_text     ← CREATED
        send "💌"


WAITING
  State: state.last_seen_anket_text holds profile text
  Duration: until mutual match is established (seconds to indefinite)
  Risk: may be overwritten if another profile is liked before "write message" prompt


CONSUMPTION
  @leomatchbot sends "Write a message for this user"
        │
        ▼
  process_leomatch_message():
    anket_text = state.last_seen_anket_text
    intro = await generate_first_message(anket_text)
    send intro
    state.last_seen_anket_text = None              ← CONSUMED / DESTROYED


LOSS SCENARIOS
  1. Bot restarts between like and "write message" → text lost → opener skipped
  2. Another profile is liked before "write message" arrives → text overwritten
  3. No mutual match ever occurs → text stays in memory indefinitely
     until next profile card overwrites it, or process exits
```

---

### 6.3 WhitelistedUser lifecycle

```
BIRTH
  Operator manually adds integer ID to data/whitelist.json

LOAD
  At startup: load_whitelist(state)
    whitelist_list = load_json_data(WHITELIST_PATH, [])
    state.whitelist_ids = set(whitelist_list)

ACTIVE USE
  On every incoming private message:
    if chat_id in state.whitelist_ids: return   ← O(1) lookup

DEATH
  Operator manually removes ID from data/whitelist.json
  Takes effect on next restart (no runtime removal mechanism)

NOTE: A user who is added to whitelist.json while the bot is running
  will NOT be whitelisted until the bot restarts. Their messages
  will continue to be AI-processed until restart.
```

---

## 7. Data Ownership Rules

| Entity | Creator | Updater | Deleter | Notes |
|--------|---------|---------|---------|-------|
| ConversationHistory | `ai_client.py` | `ai_client.py` | Never (programmatically) | Created on first AI response to a user |
| ConversationTurn (user) | `ai_client.py` | Never | Implicitly via sliding window | Written before API call |
| ConversationTurn (model) | `ai_client.py` | Never | Implicitly via sliding window | Written after API response |
| WhitelistedUser | Operator (manual) | Operator (manual) | Operator (manual) | No programmatic access |
| PendingProfile | `leomatch.py` | `leomatch.py` (overwrite) | `leomatch.py` (set None) | Embedded in BotState |
| ActiveDialogueTask | `dialog.py` | N/A | `dialog.py` (finally block) | Tasks, not data |
| LeomatchTask | `leomatch.py` | N/A | `leomatch.py` (replace) | Tasks, not data |
| Telegram session | Pyrogram (first run) | Pyrogram (auto) | Manual (delete file) | Not application-controlled |

---

## 8. Schema Design Decisions

### Decision 1 — user_id stored as string key in histories, integer in whitelist

**Why:** JSON object keys must be strings. When Python serializes `{123: [...]}`, it becomes `{"123": [...]}` automatically. The whitelist is a JSON array — array elements can be integers — so the integer is preserved.

**Consequence:** There is a type inconsistency for the same real-world concept (Telegram user ID) across two files. Code in `ai_client.py` always does `chat_id_str = str(chat_id)` before accessing `conversation_histories`. Code in `dialog.py` checks `chat_id in state.whitelist_ids` where `chat_id` is an integer and `whitelist_ids` is a `set[int]`.

**Risk:** If a future developer stores the user_id as an integer in `conversation_histories`, lookups fail silently (key not found — empty history used). This has already bitten many Pyrogram-based projects.

---

### Decision 2 — `parts` is always a single-element list

**Why:** The Gemini API supports multi-modal content (text + images) by accepting a list of parts. This system only uses text, so `parts` always has exactly one string element: `["message text"]`.

**Consequence:** The schema is over-engineered for the actual use case. Every turn carries `"parts": ["text"]` when `"text": "text"` would be semantically cleaner for a text-only system. However, using the Gemini-native format means the data can be fed directly to the API without transformation.

---

### Decision 3 — timestamp stored on turn, not queried from filesystem

**Why:** File modification times are unreliable (they change on copy, backup, or filesystem operations). Embedding the timestamp in the data itself ensures accuracy and portability.

**Format used:** `datetime.datetime.now(datetime.timezone.utc).isoformat()` produces strings like `"2026-06-04T14:23:11.483291+00:00"`. Parsed back with `datetime.datetime.fromisoformat()`.

**Consequence:** The timestamp is only used for session classification in `dialog.py`. It is explicitly stripped before sending history to the Gemini API (the API does not accept the `timestamp` field).

---

### Decision 4 — No schema versioning

**Why:** Not implemented — the schema was never intended to evolve.

**Risk:** If the turn schema changes (e.g., adding a new field, changing `parts` structure), existing `conversation_histories.json` files from before the change will be loaded and used without any migration. Silent data corruption or missing fields are the likely failure mode.

---

### Decision 5 — Single flat JSON object, not an array of records

**Why:** Using the user_id as the key gives O(1) lookup by user_id. An array of `{user_id, turns[]}` records would require O(n) linear scan to find a specific user's history.

**Consequence:** The entire histories object is loaded into memory at startup and kept there. With a large number of conversations, this could become a significant memory footprint — but the 20-turn sliding window per conversation keeps each entry small.

---

## 9. Consistency Rules & Validation

### Rules that ARE enforced

| Rule | Where enforced | How |
|------|---------------|-----|
| Max 20 turns per conversation | `ai_client.generate_conversation_response()` | `history[-MAX_HISTORY_LENGTH:]` slice |
| Profile text min length for opener | `ai_client.generate_first_message()` | `if len(profile_text) < 15: substitute` |
| Opener max length (300 chars) | `leomatch.process_leomatch_message()` | `if len(intro_message) > 300: use fallback` |
| Empty message text is ignored | `leomatch_handler`, `process_dialogue_task` | `if not text: return` |
| Whitelisted users bypass AI | `dialog.private_chat_handler()` | Early return check |
| Self-messages ignored | Pyrogram filter `~filters.me` | Filter applied at handler registration |
| Known system messages ignored | `leomatch.process_leomatch_message()` | `any(phrase in text for phrase in KNOWN_SYSTEM_MESSAGES)` |

### Rules that are NOT enforced (gaps)

| Missing rule | Consequence | Risk |
|-------------|-------------|------|
| Role alternation in turns (user/model must alternate) | API call with consecutive user turns fails or produces degraded output | Medium — occurs if API call fails after user turn is appended |
| `parts` must be a list with exactly 1 string | Malformed turn causes API error | Low — only ever set by application code |
| `timestamp` must be valid ISO 8601 UTC | `fromisoformat()` throws `ValueError` on parse | Low — only ever set by `datetime.isoformat()` |
| `user_id` must be a valid Telegram ID | Any string key works — no validation | Low — only set via `str(chat_id)` from Pyrogram |
| JSON file integrity | Corrupted file is overwritten with `{}` | Medium — total history loss on corruption |
| No cross-validation between whitelist and histories | A whitelisted user can have a history; future messages bypass AI but old history persists | Low — benign |

---

## 10. Data Bottlenecks & Normalization Issues

### Bottleneck 1 — Full JSON rewrite on every save

Every AI response triggers `save_histories()` which rewrites the **entire** `conversation_histories.json`. At 100 conversations × 20 turns × ~150 bytes/turn, the file is ~300 KB. Each AI response (potentially every few seconds during active use) rewrites this entire file.

**Impact at scale:**
- 10 simultaneous active conversations → up to 10 writes/minute
- Writes are synchronous file I/O inside the asyncio event loop
- All writes serialize through Python's GIL

**Normalization issue:** The data is denormalized — all conversations are in one blob. An append-log design (one file per user, or SQLite) would make per-conversation writes O(1) regardless of total history size.

---

### Bottleneck 2 — Full history loaded into memory at startup

`state.conversation_histories` holds all conversations in a single Python dict in RAM. There is no lazy loading — even conversations from months ago that are never referenced again are loaded and held in memory for the process lifetime.

**Impact:** For a long-running bot with hundreds of users, this dict could grow significantly. Each turn is ~200–500 bytes in Python's heap representation, so 500 users × 20 turns × 300 bytes ≈ 3 MB — manageable but growing.

---

### Bottleneck 3 — Non-atomic write (data loss risk)

Covered in engineering decisions. The truncation-before-write pattern means a crash mid-save destroys the file. This is a correctness issue, not a performance bottleneck, but it affects data durability.

---

### Normalization issues

**Denormalization 1:** The Gemini system prompt is re-sent in every API call as a fake history entry. This means ~800 tokens of "data" that never changes is transmitted on every request. In a normalized design, `system_instruction=` would handle this once at model initialization.

**Denormalization 2:** Each `ConversationTurn` stores a `timestamp` that is only ever used for a single comparison (session classification). In a more normalized system, only the timestamp of the last turn needs to be stored/indexed — not every turn.

**Denormalization 3:** `WhitelistedUser` and `ConversationHistory` are separate entities that refer to the same concept (a Telegram user) but with no enforced relationship. A unified `User` entity with a `is_whitelisted` flag would eliminate this split.

---

## 11. Business Object Evolution Over Time

### A conversation from zero to end state

```
T=0   User matches with the bot's account via @leomatchbot.
      No data exists for this user anywhere.

T=1   @leomatchbot sends "Write a message for this user".
      state.last_seen_anket_text contains the profile card.
      generate_first_message() called.
      Bot sends opener message to @leomatchbot.
      NO entry in conversation_histories yet (opener is not tracked).
      state.last_seen_anket_text = None.

T=2   User receives opener in their Telegram DMs and replies.
      private_chat_handler() fires.
      read_chat_history() called → read receipt sent.
      process_dialogue_task() created.
      STILL no entry in conversation_histories.

T=3   After grace period + delay:
      generate_conversation_response() called.
      ENTRY CREATED in conversation_histories:
        {"user_id_str": [
          {role: "user", parts: ["user's first reply"], timestamp: T2},
          {role: "model", parts: ["ai response"], timestamp: T3}
        ]}
      save_histories() called → written to disk.

T=4..N  Conversation continues. Each exchange:
      - Appends 2 turns (user + model).
      - Once array length > 20, oldest turns dropped from front.
      - JSON rewritten on every model turn.

T=N+1  At some point, the match suggests meeting.
       The operator takes over manually.
       Operator adds user_id to whitelist.json.
       Bot restarts (or next morning).
       Future messages from this user: ignored by AI.
       ConversationHistory: still exists, never deleted.
       WhitelistedUser: created in whitelist.json.

T=∞   Both ConversationHistory and WhitelistedUser persist indefinitely.
      No archival, no deletion, no TTL mechanism exists.
```

### Key observation on data growth
The system accumulates data but never removes it. Every conversation ever had stays in `conversation_histories.json` (trimmed to 20 turns, but the user key persists). Every whitelisted user stays in `whitelist.json`. Over months of operation, both files grow monotonically. No housekeeping mechanism exists.
