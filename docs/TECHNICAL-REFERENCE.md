# Technical Reference — AI Dating Assistant

_Version: 1.0 | Last updated: 2026-06-04_

> This is the single authoritative technical document for the project.
> It is updated incrementally as the system evolves. Do not create parallel versions.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Technology Stack](#3-technology-stack)
4. [System Architecture](#4-system-architecture)
   - 4.1 [Architectural Style](#41-architectural-style)
   - 4.2 [Component Map](#42-component-map)
   - 4.3 [Startup Sequence](#43-startup-sequence)
   - 4.4 [Two Event Pipelines](#44-two-event-pipelines)
5. [Module Reference](#5-module-reference)
   - 5.1 [main.py — Entry Point](#51-mainpy--entry-point)
   - 5.2 [app.py — Bootstrap & Orchestrator](#52-apppy--bootstrap--orchestrator)
   - 5.3 [state.py — Shared Runtime State](#53-statepy--shared-runtime-state)
   - 5.4 [config.py — Configuration & Prompts](#54-configpy--configuration--prompts)
   - 5.5 [leomatch.py — Scout Brain](#55-leomatchpy--scout-brain)
   - 5.6 [dialog.py — Interlocutor Brain](#56-dialogpy--interlocutor-brain)
   - 5.7 [ai_client.py — AI Facade](#57-ai_clientpy--ai-facade)
   - 5.8 [storage.py — Persistence Layer](#58-storagepy--persistence-layer)
   - 5.9 [logging_setup.py — Observability](#59-logging_setuppy--observability)
   - 5.10 [utils.py — Shared Helper](#510-utilspy--shared-helper)
6. [Data Layer](#6-data-layer)
   - 6.1 [conversation_histories.json](#61-conversation_historiesjson)
   - 6.2 [whitelist.json](#62-whitelistjson)
7. [AI Integration](#7-ai-integration)
   - 7.1 [Model Configuration](#71-model-configuration)
   - 7.2 [First Message Generation](#72-first-message-generation)
   - 7.3 [Conversation Response Generation](#73-conversation-response-generation)
   - 7.4 [Rate Limit Handling](#74-rate-limit-handling)
   - 7.5 [Response Cleanup Pipeline](#75-response-cleanup-pipeline)
8. [Human Simulation Layer](#8-human-simulation-layer)
9. [Concurrency Model](#9-concurrency-model)
10. [Configuration Reference](#10-configuration-reference)
11. [External Integrations](#11-external-integrations)
12. [Engineering Decisions & Trade-offs](#12-engineering-decisions--trade-offs)
13. [Known Issues & Improvement Backlog](#13-known-issues--improvement-backlog)
14. [Deployment Notes](#14-deployment-notes)

---

## 1. Project Overview

**AI Dating Assistant** is a single-operator automation tool that impersonates a real person on the Telegram dating platform `@leomatchbot`. It operates a real Telegram user account via the MTProto protocol, browsing dating profiles, making like/dislike decisions, generating personalized opening messages, and sustaining multi-turn conversations — all autonomously, 24/7.

### Problem it solves
Online dating requires sustained time investment in the early stages: browsing profiles, crafting openers, and maintaining small talk before a real connection forms. This system automates that entire top-of-funnel. The operator steps in only when a match has expressed interest in meeting.

### System goal
Produce warm "leads" — conversations in which the other person has organically come to suggest a real meeting — without any manual operator effort before that point.

### Design philosophy
The system is built to match its scale: one operator, one Telegram account, one AI model. It is intentionally a single-process, dependency-light application. Every architectural decision favors simplicity and correctness over extensibility.

---

## 2. Repository Structure

```
AI-dating-assistant/
│
├── .env                          # secrets — never committed
├── requirements.txt              # 4 dependencies only
├── ai_bot_logs.txt               # rotating runtime log (auto-created)
│
├── data/
│   ├── conversation_histories.json   # persistent per-user chat histories
│   └── whitelist.json                # user IDs that bypass AI
│
├── src/                          # all application code
│   ├── main.py                   # entry point + crash guard
│   ├── app.py                    # bootstrap + orchestrator
│   ├── config.py                 # all constants, env vars, AI prompts
│   ├── state.py                  # BotState dataclass (shared mutable state)
│   ├── ai_client.py              # Gemini API wrapper
│   ├── leomatch.py               # Scout brain (dating bot pipeline)
│   ├── dialog.py                 # Interlocutor brain (private chat pipeline)
│   ├── storage.py                # JSON read/write helpers
│   ├── logging_setup.py          # rotating file + console logging
│   └── utils.py                  # message text extraction helper
│
└── docs/                         # project documentation (this folder)
    ├── README.md                 # documentation index
    ├── TECHNICAL-REFERENCE.md    # ← this file
    ├── overview.md               # product concept and goals
    ├── analysis/
    │   ├── component-deep-dive.md
    │   └── engineering-decisions.md
    └── architecture/
        ├── codebase-map.md
        └── system-architecture.md
```

---

## 3. Technology Stack

| Layer | Technology | Version | Role |
|-------|-----------|---------|------|
| Language | Python | 3.10+ | Application runtime |
| Telegram interface | Pyrogram | 2.0.106 | Async MTProto client — operates a real user account |
| Cryptography | tgcrypto | 1.2.5 | Fast C-extension AES for MTProto (pyaes is fallback) |
| AI model | Google Gemini 1.5 Flash | `gemini-1.5-flash-latest` | Message generation |
| AI SDK | google-generativeai | 0.8.6 | Gemini API client (~15–20 transitive deps) |
| Config | python-dotenv | 1.2.2 | `.env` file loading |
| Persistence | JSON flat files | — | Conversation history + whitelist |
| Concurrency | asyncio | stdlib | Single event loop, cooperative multitasking |

> Full dependency analysis including transitive packages, risk matrix, removal impact, and system boundary definition: [analysis/dependencies-and-boundaries.md](analysis/dependencies-and-boundaries.md)

**Why MTProto and not the Telegram Bot API:**
The Bot API only works for registered bot accounts. `@leomatchbot` requires interaction from a real user account. MTProto is also the only way to send read receipts, show the "typing..." indicator in private chats, and appear as a real person in the match's contact list.

---

## 4. System Architecture

### 4.1 Architectural Style

The system is a **single-process, event-driven async application** with no web server, no message queue, no database, and no external services beyond Telegram and Gemini. The pattern is closest to an **Actor / Event Handler model**:

- Pyrogram client = event bus
- Handlers = actors (receive events, spawn background tasks)
- `BotState` = shared in-memory store
- JSON files = persistence layer

### 4.2 Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Python Process                              │
│                                                                     │
│  ┌────────────┐   bootstraps   ┌──────────────────────────────────┐ │
│  │  main.py   │──────────────► │           app.py                 │ │
│  │ (entry pt) │                │  validates env, builds BotState  │ │
│  └────────────┘                │  wires handlers, startup replay  │ │
│                                └──────────────┬───────────────────┘ │
│                                               │                     │
│                          ┌────────────────────▼──────────────────┐  │
│                          │         Pyrogram Client               │  │
│                          │   (real Telegram user account)        │  │
│                          └──────┬──────────────────┬─────────────┘  │
│                                 │                  │                │
│         ┌───────────────────────▼──┐    ┌──────────▼─────────────┐  │
│         │   leomatch.py            │    │      dialog.py          │  │
│         │   SCOUT BRAIN            │    │  INTERLOCUTOR BRAIN     │  │
│         │  @leomatchbot messages   │    │  private chat messages  │  │
│         └──────────┬───────────────┘    └──────────┬─────────────┘  │
│                    │                               │                │
│                    └─────────────┬─────────────────┘                │
│                                  │                                  │
│                        ┌─────────▼──────────┐                      │
│                        │    ai_client.py     │                      │
│                        │  Gemini API facade  │                      │
│                        └─────────┬───────────┘                      │
│                                  │                                  │
│  ┌────────────────┐    ┌──────────▼─────────┐                      │
│  │  storage.py    │◄───│  Google Gemini API  │                      │
│  │  JSON r/w      │    │  (external HTTPS)   │                      │
│  └────────────────┘    └─────────────────────┘                      │
│                                                                     │
│  ┌─────────────────────────────────────────┐                       │
│  │  config.py   ← imported by all modules  │                       │
│  │  state.py    ← passed to all handlers   │                       │
│  └─────────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.3 Startup Sequence

```
main.py
  └── asyncio.run(app.run())
        ├── setup_logging()
        ├── BotState()                         create single shared state
        ├── initialize_ai(state)               connect Gemini, store model
        ├── initialize_app(state)              validate env, create Pyrogram client
        ├── load_histories(state)              JSON → state.conversation_histories
        ├── load_whitelist(state)              JSON → state.whitelist_ids (set)
        │
        └── async with state.app:              open Telegram session
              ├── resolve_peer(@leomatchbot)   verify bot reachable
              ├── add_handler(leomatch_handler)
              ├── add_handler(private_chat_handler)
              │
              ├── get_chat_history(limit=1)    STARTUP REPLAY
              │     ├── message found → process_leomatch_message(is_startup=True)
              │     └── empty chat   → send_message("1")
              │
              └── asyncio.Event().wait()       park forever; event loop takes over
```

**Startup replay:** On every restart, the last message from `@leomatchbot` is re-processed. This ensures the bot resumes mid-flow after a crash — if it crashed while waiting to send an opener, the opener is generated and sent on restart. The `is_startup=True` flag suppresses false "unrecognized message" warnings.

### 4.4 Two Event Pipelines

The application processes two completely independent event streams that never share logic:

| Pipeline | Trigger | Module | Purpose |
|----------|---------|--------|---------|
| **Scout** | Any message/edit from `@leomatchbot` | `leomatch.py` | Browse profiles, like/dislike, send openers |
| **Interlocutor** | Any private message not from self or bot | `dialog.py` | Sustain conversations until meeting is suggested |

Both pipelines share `BotState` and `ai_client.py` but are otherwise isolated. Changes to one cannot break the other.

---

## 5. Module Reference

### 5.1 `main.py` — Entry Point

**Responsibility:** Start the application and handle all unrecoverable errors.

**Logic:**
```
asyncio.run(run())
├── UserDeactivated / AuthKeyUnregistered → log critical (session invalid)
├── KeyboardInterrupt                     → save histories, exit cleanly
└── Exception (catch-all)                → save histories, log traceback
```

**Design note:** `get_state()` from `app.py` provides crash-time access to the shared state without passing it through the call stack. This is the only module-level global accessor in the codebase and exists specifically because `asyncio.run()` blocks until the event loop terminates — by which point state would otherwise be unreachable.

**Connections:** Calls `app.run()`. On exit, calls `storage.save_histories(get_state())`.

---

### 5.2 `app.py` — Bootstrap & Orchestrator

**Responsibility:** Initialize all subsystems in dependency order, register event handlers, execute startup replay, and park the process.

**Key functions:**

`initialize_app(state)` — Validates that all three required env vars are present (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `GEMINI_API_KEY`). Creates the Pyrogram `Client` and stores it in `state.app`. Returns early with a `SystemExit(1)` if any var is missing.

`run()` — The main async coroutine. Executes the full startup sequence (see §4.3). Uses `functools.partial` to pre-bind `state` into handler callbacks:
```python
leomatch_cb = partial(leomatch_handler, state=state)
private_cb  = partial(private_chat_handler, state=state)
```
Pyrogram handlers have the signature `(client, message)`; `partial` adds `state` as a keyword argument, producing a callable Pyrogram can invoke without needing global state.

**Filter logic for handlers:**
```python
# Scout: only messages FROM the dating bot, not sent by self
filters.private & filters.chat(BOT_USERNAME) & ~filters.me

# Interlocutor: private messages NOT from the dating bot, not sent by self
filters.private & ~filters.chat(BOT_USERNAME) & ~filters.me
```
The `~filters.me` is critical — without it, the bot's own outgoing messages would trigger the handlers and create an infinite loop.

**Connections:** Imports from every other module. Exports `run()` and `get_state()`.

---

### 5.3 `state.py` — Shared Runtime State

**Responsibility:** Define the single shared mutable state object passed to every component.

```python
@dataclass
class BotState:
    last_seen_anket_text:    Optional[str]        = None
    last_action_time:        datetime             = datetime.min (UTC)
    start_time:              datetime             = now (UTC)
    conversation_histories:  Dict[str, list]      = {}
    active_dialogue_tasks:   Dict[int, Task]      = {}
    leomatch_task:           Optional[Task]       = None
    whitelist_ids:           Set[int]             = set()
    model:                   Optional[Any]        = None
    app:                     Optional[Any]        = None
```

**Field ownership:**

| Field | Written by | Read by | Purpose |
|-------|-----------|--------|---------|
| `last_seen_anket_text` | `leomatch.py` | `leomatch.py` | Bridge between profile card and "write message" events |
| `last_action_time` | `leomatch.py` | `leomatch.py` | Cooldown enforcement |
| `conversation_histories` | `ai_client.py` | `ai_client.py`, `dialog.py` | Per-user Gemini chat history |
| `active_dialogue_tasks` | `dialog.py` | `dialog.py` | Debounce: cancel-on-new-message |
| `leomatch_task` | `leomatch.py` | `leomatch.py` | Single profile-processing task slot |
| `whitelist_ids` | `storage.py` | `dialog.py` | Bypass AI for specified users |
| `model` | `app.py` via `ai_client` | `ai_client.py` | Gemini model instance |
| `app` | `app.py` | `leomatch.py`, `dialog.py` | Pyrogram client instance |

**Key initialization details:**
- `last_action_time = datetime.min` ensures the first profile never waits for a cooldown.
- All mutable defaults use `field(default_factory=...)` to prevent the shared-mutable-default Python bug.
- `model` and `app` are typed as `Optional[Any]` to avoid circular imports; callers check for `None` before use.

---

### 5.4 `config.py` — Configuration & Prompts

**Responsibility:** Single source of all constants, paths, credentials, timing parameters, AI prompts, and compiled patterns.

**Categories of content:**

**Paths:**
```python
BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR / "data"
HISTORY_PATH = DATA_DIR / "conversation_histories.json"
WHITELIST_PATH = DATA_DIR / "whitelist.json"
LOG_FILE_PATH  = BASE_DIR / "ai_bot_logs.txt"
```
All paths are derived from the config file's own location — the project is fully portable.

**Timing constants:**

| Constant | Value | Effect |
|----------|-------|--------|
| `ACTION_COOLDOWN_SECONDS` | 70 | Minimum gap between like/dislike actions in Scout |
| `GRACE_PERIOD_SECONDS` | 7 | Debounce wait before generating a reply |
| `SESSION_TIMEOUT_MINUTES` | 15 | Inactivity threshold for "new session" classification |
| `TYPING_SPEED_CPS` | 8 | Characters/second for typing delay simulation |
| `MAX_HISTORY_LENGTH` | 20 | Sliding window size for conversation history |

**Reply delay tiers:**
```python
REPLY_DELAY_CONFIG = {
    "active_session": {"min_sec": 15,   "max_sec": 60},
    "new_session": {
        "fast":   {"chance": 0.60, "min_sec": 15,   "max_sec": 60},
        "medium": {"chance": 0.35, "min_sec": 300,  "max_sec": 900},
        "long":   {"chance": 0.05, "min_sec": 3600, "max_sec": 10800},
    },
}
```
The nested dict structure allows `dialog.py` to select a tier by name and read `min_sec`/`max_sec` uniformly — no branching at the call site.

**Profile regex:**
```python
ANKET_PATTERN = re.compile(
    r"^(.+?),\s*(\d+),\s*(.+?)(?:[-–—]\s*(.*))?$", re.DOTALL
)
```
Matches `@leomatchbot` profile card format: `Name, Age, City — Description`. Groups: 1=name, 2=age, 3=city, 4=description. `re.DOTALL` allows descriptions with newlines. Compiled once at import time.

**Known system messages (ignored by Scout):**
```python
KNOWN_SYSTEM_MESSAGES = {"✨🔍", "Like sent, waiting for a response.", ...}
```
A `set` for O(1) membership testing.

**AI prompts:** `FIRST_MESSAGE_PROMPT` and `CONVERSATION_SYSTEM_PROMPT` — full multi-paragraph natural language strings. `FIRST_MESSAGE_PROMPT` contains `{profile_text}` filled via `str.format()`.

---

### 5.5 `leomatch.py` — Scout Brain

**Responsibility:** Process all messages from `@leomatchbot`, apply the like/dislike decision, and generate personalized opening messages for mutual matches.

**Internal flow:**

```
leomatch_handler(client, message, state)
│
├── extract text (message.text or message.caption)
├── empty? → return
│
├── matches ANKET_PATTERN?
│     YES → cancel existing leomatch_task
│            create process_leomatch_task() [background]
│
└── NO  → process_leomatch_message() [direct, no cooldown]


process_leomatch_task(client, message, state)
│
├── compute remaining cooldown = ACTION_COOLDOWN - time_since_last_action
├── remaining > 0? → sleep(remaining)
└── call process_leomatch_message()


process_leomatch_message(client, text, state, is_startup=False)
│
├── KNOWN_SYSTEM_MESSAGES match?  → return (ignore ads/confirmations)
├── "1. View profiles" in text?   → send "1" (navigate bot menu)
│
├── ANKET_PATTERN match?
│     → save text to state.last_seen_anket_text
│     → description > 10 chars? → send "💌 / 📹" (like)
│     → else                   → send "👎" (dislike)
│     → update state.last_action_time
│
├── "Write a message for this user" in text?
│     → retrieve state.last_seen_anket_text
│     → generate_first_message(anket_text, state)
│     → len > 300? → use hardcoded fallback
│     → send opener to @leomatchbot
│     → clear state.last_seen_anket_text
│
└── unrecognized (not startup) → log warning
```

**The `last_seen_anket_text` bridge:**
There is a temporal gap between two events from `@leomatchbot`: (A) "here is a profile" and (B) "write a message for this user" (sent only after a mutual like). `state.last_seen_anket_text` stores the profile text at event A and makes it available at event B. It is cleared immediately after use.

**Cooldown mechanics:**
The 70-second cooldown is computed dynamically from `last_action_time`, not as a fixed sleep from task creation. If 50 seconds have already elapsed, only 20 more are waited. The cooldown is reset every time a like or dislike is sent.

**Task replacement:**
Only one `leomatch_task` exists at a time. When a new profile card arrives before the previous task finishes, the previous task is cancelled. This ensures only the most recent profile is acted upon — matching real human behavior of never going back to process an earlier profile.

---

### 5.6 `dialog.py` — Interlocutor Brain

**Responsibility:** Handle all private conversations, implementing the full human-simulation stack: read receipts, debounce, session classification, probabilistic delay, reply generation, typing simulation, and ladder sending.

**Internal flow:**

```
private_chat_handler(client, message, state)
│
├── chat_id in whitelist_ids? → return (operator handles manually)
├── read_chat_history(chat_id) → instant read receipt (double checkmark)
├── existing task for chat_id? → cancel it (debounce reset)
└── create process_dialogue_task() → store in active_dialogue_tasks[chat_id]


process_dialogue_task(client, message, state)
│
├── sleep(7s grace period)
│       [CancelledError here = user sent another message → silent exit]
│
├── CLASSIFY SESSION:
│     last message timestamp in history < 15 min ago? → "active_session"
│     else "new_session" with probabilistic tier:
│           rand < 0.05          → "long"   delay (1–3h)
│           rand < 0.40          → "medium" delay (5–15min)
│           else                 → "fast"   delay (15–60s)
│
├── sleep(random delay from selected tier)
│
├── generate_conversation_response(chat_id, user_message, state)
│
├── "|||" in response?
│     YES (ladder mode):
│           for each part:
│             send_chat_action(TYPING)
│             sleep(len(part) / 8 CPS + 0.5–2.0s jitter)
│             send_message(part)
│
│     NO (single mode):
│           send_chat_action(TYPING)
│           sleep(len(response) / 8 CPS + 0.5–2.0s jitter)
│           send_message(response)
│
└── finally: active_dialogue_tasks.pop(chat_id)   ← always clean up
```

**The three timing layers and their distinct purposes:**

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| Grace period (7s) | `asyncio.sleep` before generation | Consolidate burst messages from one user |
| Session delay (15s–3h) | Probabilistic tier selection | Simulate realistic reply latency patterns |
| Typing simulation (per-char) | `send_chat_action` + proportional sleep | Make message arrival feel natural |

These layers are independent — each is removable without affecting the others.

**Debounce in detail:**
`active_dialogue_tasks[chat_id]` holds the live task for each conversation. When the same user sends a new message, the existing task is cancelled at whatever stage it's in (grace period, delay, or generation) and a fresh task starts. The `finally` block ensures the dict entry is always removed, preventing memory leaks.

---

### 5.7 `ai_client.py` — AI Facade

**Responsibility:** Abstract all Gemini API interaction — initialization, history management, rate-limit handling, response cleanup, and two generation paths.

**`initialize_ai(state)`:**
Calls `genai.configure(api_key=...)` (configures the SDK globally) and creates a `GenerativeModel` instance. Failure sets `state.model = None`; both generation functions detect this and return fallback strings.

**`cleanup_ai_response(text)`:**
Post-processing pipeline run on every AI output:
1. Replace em-dash (`—`) and en-dash (`–`) with space
2. Strip leading/trailing whitespace
3. Strip trailing `.`, `?`, `!` (persona rules forbid sentence-ending punctuation)
4. Collapse multiple spaces to one
5. Fix `" ,"` → `","` artifacts

**`with_rate_limit_handling(api_call)`:**
Wraps all Gemini calls. Uses `asyncio.to_thread` to run the synchronous SDK in a thread pool (keeps the event loop unblocked). Catches `ResourceExhausted` (HTTP 429), parses the retry-after delay from error metadata, and retries up to 3 times. Returns `None` after 3 failures.

**`generate_first_message(anket_text, state)`:**
Stateless one-shot generation for opening messages.
- Extracts the profile description from the parsed profile card
- Substitutes a generic prompt if description < 15 characters
- Injects description into `FIRST_MESSAGE_PROMPT` template
- Calls `model.generate_content(prompt)` — no chat history

**`generate_conversation_response(chat_id, user_message, state)`:**
Stateful chat-session generation for ongoing conversations.

```
1. Append user message + UTC timestamp to state.conversation_histories[chat_id]
2. Trim history to MAX_HISTORY_LENGTH (sliding window)
3. Build API payload:
     [system prompt as fake user turn]
     [system acknowledgment as fake model turn]
     [all actual history messages]
4. Start chat session with all-but-last messages as history
5. Send last user message via chat_session.send_message()
6. Clean up response text
7. Append AI response + timestamp to history
8. Save histories to disk
9. Return cleaned response
```

**System prompt injection pattern:**
Gemini's chat API has no system-role. The workaround is injecting `CONVERSATION_SYSTEM_PROMPT` as a fake first user message, with a fake model acknowledgment following it. This ensures the model processes the persona rules at the start of every API call.

> ⚠️ **Known issue:** `GenerativeModel` accepts a `system_instruction=` parameter that would replace this workaround entirely, reduce token usage by ~800 tokens per call, and eliminate the silent-breakage risk. See §13.

---

### 5.8 `storage.py` — Persistence Layer

**Responsibility:** Read and write all data persisted to the filesystem.

**Generic helpers:**

`load_json_data(filepath, default_data)`:
- File exists and valid → return parsed JSON
- File exists, empty (size=0) → create with default, return default
- File exists, invalid JSON → log error, overwrite with default, return default
- File missing → create parent dirs, create with default, return default

`save_json_data(filepath, data)`:
- Open in write mode (truncates), dump full data as indented UTF-8 JSON
- Logs error on `IOError`, does not raise

**Domain wrappers:**

| Function | Effect |
|----------|--------|
| `load_histories(state)` | `HISTORY_PATH` → `state.conversation_histories` |
| `save_histories(state)` | `state.conversation_histories` → `HISTORY_PATH` |
| `load_whitelist(state)` | `WHITELIST_PATH` (JSON array) → `state.whitelist_ids` (Python set) |

`ensure_ascii=False` is used in all JSON writes to preserve Cyrillic text without escaping.

> ⚠️ **Known issue:** No atomic write. The file is truncated before writing completes. A crash between truncation and completion destroys all history. See §13.

---

### 5.9 `logging_setup.py` — Observability

**Responsibility:** Configure the root logger with two output handlers for the lifetime of the application.

**Configuration:**
```python
Level:   logging.INFO
Format:  "%(asctime)s - [%(levelname)s] - %(message)s"

Handlers:
  StreamHandler  → stdout/stderr (console)
  RotatingFileHandler → ai_bot_logs.txt
      maxBytes   = 5 MB
      backupCount = 2        (max 15 MB total storage)
      encoding   = utf-8
```

The `if not logger.handlers` guard prevents duplicate handlers on repeated `setup_logging()` calls (e.g., in tests).

All other modules log via `logging.info/warning/error/critical` — they never import `logging_setup` directly. The root logger routes to the configured handlers automatically.

**Log prefix convention:** Each module prefixes its log messages with a bracketed module label, e.g.:
- `[LEOMATCH-DISPATCHER]`, `[LEOMATCH-TASK]`, `[LEOMATCH-EXECUTOR]`
- `[DISPATCHER]`, `[DIALOG]`
- `[SYSTEM]` for `app.py` infrastructure messages

---

### 5.10 `utils.py` — Shared Helper

**Responsibility:** Extract text content from Pyrogram message objects.

```python
def get_message_text(message) -> str | None:
    return message.text or message.caption
```

In Pyrogram, text messages populate `.text`; media messages (photos, videos) with a caption populate `.caption`. The dating bot `@leomatchbot` sends profile cards as media messages — without the `.caption` fallback, all profile cards would be silently ignored.

Used by: `app.py`, `leomatch.py`, `dialog.py`.

---

## 6. Data Layer

### 6.1 `conversation_histories.json`

**Schema:**
```json
{
  "telegram_user_id_as_string": [
    {
      "role": "user",
      "parts": ["message text"],
      "timestamp": "2026-06-04T14:23:11.000000+00:00"
    },
    {
      "role": "model",
      "parts": ["ai response text"],
      "timestamp": "2026-06-04T14:24:05.000000+00:00"
    }
  ]
}
```

**Key characteristics:**
- Keys are Telegram user IDs converted to strings (JSON requires string keys)
- History per user is capped at `MAX_HISTORY_LENGTH=20` entries (sliding window)
- Timestamps are ISO 8601 UTC strings; used by `dialog.py` to classify sessions
- Written on every AI response; read at startup and during session classification
- The `parts` field is a list (Gemini API requirement) but always contains a single string

### 6.2 `whitelist.json`

**Schema:**
```json
[123456789, 987654321]
```

A JSON array of integer Telegram user IDs. Loaded into `state.whitelist_ids` as a Python `set` at startup. Never written by the application — modifications require manual editing and restart.

---

## 7. AI Integration

### 7.1 Model Configuration

```python
genai.configure(api_key=GEMINI_API_KEY)
state.model = genai.GenerativeModel("gemini-1.5-flash-latest")
```

`gemini-1.5-flash-latest` is chosen for speed and cost over quality — appropriate for short conversational messages. The `-latest` suffix means the model may be silently upgraded by Google, which could change response style.

### 7.2 First Message Generation

**Trigger:** `@leomatchbot` sends "Write a message for this user" after a mutual match.

**Input:** The full profile card text stored in `state.last_seen_anket_text`.

**Process:**
1. Parse profile card with `ANKET_PATTERN` → extract description (group 4)
2. Description < 15 chars → substitute `"Profile description is short or meaningless"`
3. Inject into `FIRST_MESSAGE_PROMPT` via `str.format(profile_text=...)`
4. Call `model.generate_content(prompt)` — stateless, no history
5. Validate length ≤ 300 chars; use hardcoded fallback if exceeded
6. Apply `cleanup_ai_response()`

**Output:** Single opening message string, max 300 characters.

### 7.3 Conversation Response Generation

**Trigger:** A private message from a real user (after debounce and delay).

**Input:** `chat_id` (int), `user_message` (str), `state`.

**History assembly for API:**
```
[SYSTEM PROMPT AS FAKE USER TURN]
[FAKE MODEL ACKNOWLEDGMENT]
[turn 1 user] [turn 1 model]
[turn 2 user] [turn 2 model]
...
[current user message]  ← sent via send_message(), not in history
```

**Process:**
1. Append user message to `state.conversation_histories[chat_id]`
2. Trim to last 20 entries
3. Build full history with system prompt injected at position 0
4. `model.start_chat(history=all_except_last)`
5. `chat_session.send_message(last_user_message)`
6. Clean response, append to history, save histories, return

**Output:** Response string, possibly containing `|||` separators for ladder send.

### 7.4 Rate Limit Handling

```python
async def with_rate_limit_handling(api_call):
    for attempt in range(3):
        try:
            return await asyncio.to_thread(api_call)
        except google_exceptions.ResourceExhausted as e:
            retry_delay = parse_retry_after(e) or 60
            await asyncio.sleep(retry_delay)
    return None   # caller uses fallback string
```

`asyncio.to_thread` is essential — the Gemini SDK is synchronous. Without it, every AI call would block the event loop, preventing all other conversations and incoming messages from being processed during API wait times.

### 7.5 Response Cleanup Pipeline

Applied to every AI response before delivery:

| Step | Transformation | Reason |
|------|---------------|--------|
| 1 | `—` / `–` → space | Persona rules forbid dashes |
| 2 | `strip()` | Remove leading/trailing whitespace |
| 3 | `rstrip(".?!")` | Persona rules forbid trailing punctuation |
| 4 | `re.sub(r"\s+", " ")` | Collapse multi-space artifacts |
| 5 | `" ,"` → `","` | Fix space-before-comma from dash replacement |

---

## 8. Human Simulation Layer

Seven independent techniques layer together to produce human-like behavior. Each is removable without breaking the others.

| Layer | Technique | Where | Effect |
|-------|-----------|-------|--------|
| 1 | Persona prompt | `config.py` + `ai_client.py` | Consistent fictional personality, slang, first-person stories |
| 2 | Response cleanup | `ai_client.py` | Strips punctuation and patterns that read as machine-generated |
| 3 | Ladder send (`|||`) | `dialog.py` + `ai_client.py` | Splits thoughts into multiple messages like a real person typing fast |
| 4 | Probabilistic delay | `dialog.py` | 60/35/5% fast/medium/long tiers for new sessions |
| 5 | Grace period debounce | `dialog.py` | Waits 7 seconds to consolidate burst messages before replying |
| 6 | Read receipt + typing | `dialog.py` | Instant double-checkmark; "typing..." indicator proportional to message length |
| 7 | Action cooldown | `leomatch.py` | 70-second minimum between Scout actions prevents bot-detection patterns |

---

## 9. Concurrency Model

**Model:** Single-threaded cooperative multitasking via `asyncio`. One event loop, multiple coroutines, no true parallelism for application logic.

**Thread pool usage:** `asyncio.to_thread` is used for Gemini SDK calls only (the SDK is synchronous). This creates real OS threads but only for blocking network I/O — all state mutations happen in the single event loop thread.

**Active concurrent elements:**

| Element | Quantity | Lifecycle |
|---------|----------|-----------|
| `process_leomatch_task` | 0 or 1 | Created per profile; cancelled on new profile |
| `process_dialogue_task` | 0–N (one per active chat) | Created per message; cancelled on next message from same user |
| Gemini thread pool tasks | 0–N | One per active AI call; managed by `asyncio.to_thread` |

**Why there are no race conditions:**
Asyncio is cooperative — only one coroutine runs at a time. A coroutine runs uninterrupted until it hits an `await`. All reads and writes to `BotState` happen in coroutines, never in threads. `asyncio.to_thread` callbacks only pass return values back — they never touch `BotState` from the thread.

**Debounce implementation:**
Both pipelines use cancel-and-replace on a named task slot (`leomatch_task` for Scout; `active_dialogue_tasks[chat_id]` for Interlocutor). Cancellation of a sleeping coroutine is instantaneous and handled via `asyncio.CancelledError`.

---

## 10. Configuration Reference

All values are in `src/config.py` unless noted.

**Credentials (from `.env`):**

| Variable | Purpose |
|----------|---------|
| `TELEGRAM_API_ID` | Telegram MTProto application ID |
| `TELEGRAM_API_HASH` | Telegram MTProto application hash |
| `GEMINI_API_KEY` | Google AI Studio API key |

**Application constants:**

| Constant | Value | Tuning effect |
|----------|-------|--------------|
| `BOT_USERNAME` | `"leomatchbot"` | Target dating bot handle |
| `SESSION_NAME` | `"ai_dating_user"` | Pyrogram `.session` filename |
| `ACTION_COOLDOWN_SECONDS` | `70` | Higher = more human-like, slower profile throughput |
| `MAX_HISTORY_LENGTH` | `20` | Higher = more context, higher token cost per request |
| `GRACE_PERIOD_SECONDS` | `7` | Higher = better burst consolidation, more latency |
| `TYPING_SPEED_CPS` | `8` | Lower = slower typing simulation |
| `SESSION_TIMEOUT_MINUTES` | `15` | Higher = more conversations treated as "active" |

**Reply delay tiers:**

| Mode | Probability | Range |
|------|------------|-------|
| Active session | 100% (if session active) | 15–60 seconds |
| New session / fast | 60% | 15–60 seconds |
| New session / medium | 35% | 5–15 minutes |
| New session / long | 5% | 1–3 hours |

---

## 11. External Integrations

### Telegram (via Pyrogram / MTProto)

| Aspect | Detail |
|--------|--------|
| Protocol | MTProto — user account, not Bot API |
| Auth | API_ID + API_HASH + `.session` file (phone+OTP on first run) |
| Client | `pyrogram.Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)` |
| Session file | `ai_dating_user.session` in working directory — equivalent to full account access |
| Actions used | `send_message`, `send_chat_action`, `read_chat_history`, `get_chat_history`, `resolve_peer` |

**MTProto vs Bot API — why it matters:**
The Bot API cannot send read receipts, cannot control the "typing..." indicator in private chats, and cannot interact with `@leomatchbot` as a real user. MTProto is the only way to make the account appear human.

### Google Gemini (via google-generativeai)

| Aspect | Detail |
|--------|--------|
| Model | `gemini-1.5-flash-latest` |
| SDK | `google.generativeai` |
| Auth | `GEMINI_API_KEY` via `genai.configure()` |
| Invocation | `generate_content()` (one-shot) and `start_chat() + send_message()` (session) |
| Error handling | `ResourceExhausted` (429) with retry-after parsing, 3 attempts |
| Thread safety | Called via `asyncio.to_thread` to avoid blocking event loop |

---

## 12. Engineering Decisions & Trade-offs

### D1 — Single-process asyncio

**Choice:** One process, one event loop, no threads for application logic.

**Why:** The workload is I/O-bound. Asyncio handles concurrent conversations, API calls, and delay timers without parallelism. Adding threads or processes would introduce synchronization overhead with no benefit.

**Risk:** A blocking call outside `asyncio.to_thread` freezes all active conversations. Currently safe; easy to break by a future developer.

---

### D2 — MTProto over Bot API

**Choice:** Pyrogram operating a real user account.

**Why:** Mandatory for the system to work. Bot accounts cannot use read receipts, typing indicators, or interact with bots that require real users.

**Risk:** Violates Telegram ToS — the account can be banned without warning. No mitigation strategy exists in the code.

---

### D3 — Single shared BotState

**Choice:** One dataclass passed by reference to all components.

**Why:** Simplest architecture for single-operator, single-session use. No global variables, no DI framework.

**Trade-off:** No encapsulation — any module can write any field. Safe at current scale.

---

### D4 — JSON flat-file persistence

**Choice:** JSON files on disk, full rewrite on every save.

**Why:** Appropriate for the data volume. Human-readable, easily backed up, no infrastructure.

**Risk:** Non-atomic writes. Crash during save destroys all conversation history. Fix: write-to-tmp + `os.rename()`.

---

### D5 — System prompt as fake chat turn

**Choice:** `CONVERSATION_SYSTEM_PROMPT` injected as a synthetic `user`/`model` exchange at history position 0.

**Why:** Gemini's chat history API has no system role. Workaround that functions correctly.

**Risk:** Wastes ~800 tokens per API call. Could break silently if Gemini changes first-message handling. Correct fix: use `system_instruction=` parameter on `GenerativeModel`.

---

### D6 — Debounce via cancel-and-replace tasks

**Choice:** Cancel existing task on new event, create replacement.

**Why:** Idiomatic asyncio. Cancelling a sleeping coroutine is instant and clean.

**Trade-off:** Only the last message before the grace period expires is sent to AI. Earlier messages in a burst are lost to the AI (though read receipts are sent for all).

---

### D7 — Probabilistic delay tiers

**Choice:** 60/35/5% fast/medium/long distribution for new sessions.

**Why:** Uniform delays are detectable and inhuman. Tiered distribution creates realistic variability.

**Trade-off:** Long-mode delays (1–3h) can compound if the user keeps sending messages — each new message can reset to a long delay.

---

### D8 — Binary profile quality filter

**Choice:** Like if description > 10 chars; dislike otherwise.

**Why:** Simple, fast, no API cost. Good enough heuristic for the stated purpose.

**Trade-off:** Misses short-but-meaningful profiles; likes long-but-empty ones.

---

### D9 — Ladder send via `|||` delimiter in AI output

**Choice:** AI inserts `|||` in ~30% of responses; app splits and sends parts separately.

**Why:** Offloads the structural decision to the AI, which has full conversational context.

**Trade-off:** AI doesn't reliably follow the 30% frequency instruction. Output structure is non-deterministic.

---

### D10 — History trimmed by message count

**Choice:** Sliding window of 20 most recent messages.

**Why:** Simple. 20 messages is more context than most dating conversations need.

**Trade-off:** Count ≠ tokens. Long messages could hit Gemini's context window. No token counting in the current code.

---

## 13. Known Issues & Improvement Backlog

### High Priority (correctness / reliability)

**1. Non-atomic JSON write**
- **File:** `storage.py`, `save_json_data()`
- **Risk:** Data loss on crash mid-write
- **Fix:**
  ```python
  tmp = path.with_suffix(".tmp")
  with tmp.open("w", encoding="utf-8") as f:
      json.dump(data, f, ensure_ascii=False, indent=4)
  tmp.replace(path)   # atomic on POSIX
  ```

**2. System prompt should use `system_instruction=`**
- **File:** `ai_client.py`, `initialize_ai()`
- **Risk:** ~800 wasted tokens per API call; silent breakage risk on model update
- **Fix:**
  ```python
  state.model = genai.GenerativeModel(
      "gemini-1.5-flash-latest",
      system_instruction=CONVERSATION_SYSTEM_PROMPT
  )
  ```
  Then remove the fake first exchange from `generate_conversation_response()`.

### Medium Priority (deployment / operations)

**3. No SIGTERM handling**
- **File:** `main.py`
- **Risk:** History not saved when stopped by systemd/Docker/supervisord
- **Fix:**
  ```python
  import signal
  signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt()))
  ```

**4. `Optional[Any]` types on state fields**
- **File:** `state.py`
- **Risk:** No IDE autocomplete or type checking for `state.model` and `state.app`
- **Fix:** Use string-quoted forward references:
  ```python
  model: Optional["genai.GenerativeModel"] = None
  app:   Optional["pyrogram.Client"] = None
  ```

### Low Priority (quality / maintainability)

**5. History trimmed by count, not tokens**
- **File:** `ai_client.py`
- **Risk:** Very long messages could approach Gemini's context window
- **Fix:** Use `tiktoken` or Gemini's count_tokens to enforce a token budget

**6. AI prompts mixed into config alongside secrets and constants**
- **File:** `config.py`
- **Improvement:** Move prompts to `src/prompts/first_message.txt` and `src/prompts/conversation.txt`; load with `Path(__file__).parent.joinpath(...).read_text()`

**7. No burst message accumulation**
- **File:** `dialog.py`
- **Improvement:** Collect all messages received during the grace period and concatenate them before sending to the AI, so the full thought is visible

**8. No structured logging**
- **File:** `logging_setup.py`
- **Improvement:** JSON-format logs with fields for `chat_id`, `user_name`, `module` would make debugging and monitoring significantly easier

**9. No health check / watchdog**
- **Improvement:** A periodic log line (e.g., every 30 minutes: "bot alive, N active conversations") would enable external monitoring and detect silent hangs

---

## 14. Deployment Notes

### First-time setup

```bash
git clone <repo>
cd AI-dating-assistant
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, GEMINI_API_KEY
python3 src/main.py         # first run: enter phone + OTP to create .session file
```

After the `.session` file is created, `Ctrl+C` to stop. The session persists indefinitely.

### Ongoing operation (tmux)

```bash
tmux new -s dating_bot
python3 src/main.py
# Ctrl+B, D to detach — bot runs in background
# tmux attach -t dating_bot to return
```

### Critical files — never delete or commit

| File | Contents |
|------|---------|
| `.env` | All API credentials |
| `ai_dating_user.session` | Telegram session (equivalent to account password) |
| `data/conversation_histories.json` | All conversation context |

### Whitelist management

To exclude a user from AI processing (switch to manual):
1. Find their Telegram user ID (forward a message to `@userinfobot`)
2. Add the integer ID to `data/whitelist.json`
3. Restart the bot

### Updating the AI persona

Edit `FIRST_MESSAGE_PROMPT` and/or `CONVERSATION_SYSTEM_PROMPT` in `src/config.py`. Restart the bot. Changes take effect immediately on the next AI call — conversation histories are not affected.
