# System Architecture — AI Dating Assistant

_Last updated: 2026-06-04_

---

## 1. Architectural Style

The system is a **single-process, event-driven async application**. There is no web server, no message queue, no database, and no microservices. Everything runs inside one Python `asyncio` event loop that reacts to incoming Telegram events.

The architectural pattern is closest to an **Actor / Event Handler model**:
- The Pyrogram client is the event bus.
- Handlers are the actors — they receive events and spin up background tasks.
- The `BotState` dataclass is the shared in-memory store.
- JSON files on disk are the only persistence layer.

---

## 2. Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Python Process                              │
│                                                                     │
│  ┌────────────┐   bootstraps   ┌──────────────────────────────────┐ │
│  │  main.py   │──────────────► │           app.py                 │ │
│  │ (entry pt) │                │  - validates env                 │ │
│  └────────────┘                │  - builds BotState               │ │
│                                │  - wires handlers                │ │
│                                │  - runs startup replay           │ │
│                                └──────────────┬───────────────────┘ │
│                                               │                     │
│                          ┌────────────────────▼──────────────────┐  │
│                          │         Pyrogram Client               │  │
│                          │   (real Telegram user account)        │  │
│                          └──────┬──────────────────┬─────────────┘  │
│                                 │                  │                │
│              ┌──────────────────▼──┐    ┌──────────▼─────────────┐ │
│              │   leomatch.py       │    │      dialog.py          │ │
│              │   SCOUT BRAIN       │    │  INTERLOCUTOR BRAIN     │ │
│              │                     │    │                         │ │
│              │ - parse profile card│    │ - whitelist gate        │ │
│              │ - cooldown timer    │    │ - debounce timer        │ │
│              │ - like / dislike    │    │ - session detection     │ │
│              │ - first msg gen     │    │ - probabilistic delay   │ │
│              └──────┬──────────────┘    └──────────┬─────────────┘ │
│                     │                              │               │
│                     └──────────────┬───────────────┘               │
│                                    │                               │
│                          ┌─────────▼──────────┐                   │
│                          │    ai_client.py     │                   │
│                          │                     │                   │
│                          │ - rate-limit retry  │                   │
│                          │ - response cleanup  │                   │
│                          │ - history assembly  │                   │
│                          └─────────┬───────────┘                   │
│                                    │                               │
│  ┌────────────────┐      ┌─────────▼──────────┐                   │
│  │  storage.py    │◄─────│  Google Gemini API  │                   │
│  │  (JSON r/w)    │      │  (external)         │                   │
│  └────────────────┘      └─────────────────────┘                   │
│                                                                     │
│  ┌────────────────┐                                                 │
│  │   config.py    │  ◄── imported by every module                  │
│  │   state.py     │  ◄── passed by reference to every handler      │
│  └────────────────┘                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Startup Sequence

```
main.py
  └── asyncio.run(app.run())
        ├── setup_logging()
        ├── BotState()                        ← create single shared state object
        ├── initialize_ai(state)              ← connect to Gemini, store model in state
        ├── initialize_app(state)             ← validate env, create Pyrogram Client, store in state
        ├── load_histories(state)             ← read JSON → state.conversation_histories
        ├── load_whitelist(state)             ← read JSON → state.whitelist_ids
        │
        └── async with state.app:             ← open Telegram session
              ├── resolve_peer(@leomatchbot)   ← verify bot is reachable
              ├── add_handler(leomatch_handler)    ← wire Scout
              ├── add_handler(private_chat_handler) ← wire Interlocutor
              │
              ├── get_chat_history(@leomatchbot, limit=1)   ← startup replay
              │       ├── if last message found → process_leomatch_message(is_startup=True)
              │       └── if empty chat         → send_message("1")   ← wake bot
              │
              └── asyncio.Event().wait()       ← park forever, event loop drives everything
```

**Key insight:** The startup replay ensures the bot resumes exactly where it left off after a restart, re-processing whatever state the dating bot was in.

---

## 4. Two Parallel Event Pipelines

The application handles two completely independent event streams that never cross:

### Pipeline A — Scout (leomatch.py)

**Trigger:** Any message or edited message from `@leomatchbot`

```
Incoming message
      │
      ▼
leomatch_handler()
      │
      ├── empty text? → skip
      │
      ├── matches ANKET_PATTERN (Name, Age, City — Description)?
      │       └── YES → cancel existing leomatch_task (if any)
      │                 create new process_leomatch_task() [background]
      │                       └── wait for cooldown to expire
      │                           call process_leomatch_message()
      │
      └── NOT a profile → process_leomatch_message() [direct, no cooldown]


process_leomatch_message()
      │
      ├── KNOWN_SYSTEM_MESSAGES? → ignore (ads, confirmations)
      │
      ├── "1. View profiles" menu? → send "1" (navigate to profile view)
      │
      ├── Profile card?
      │       ├── save text → state.last_seen_anket_text
      │       ├── has description (>10 chars)? → like (💌 / 📹)
      │       └── no description?              → dislike (👎)
      │       └── update state.last_action_time (starts cooldown)
      │
      └── "Write a message for this user"?
              ├── retrieve state.last_seen_anket_text
              ├── generate_first_message(anket_text) → Gemini API
              ├── guard: >300 chars? → use fallback string
              └── send generated opener to @leomatchbot
                  clear state.last_seen_anket_text
```

**Cooldown mechanism:** A 70-second cooldown between actions (tracked via `last_action_time`) prevents the dating bot from detecting bot-like rapid behavior. When a new profile card arrives during cooldown, the existing task is cancelled and replaced — only the most recent profile is ever processed.

---

### Pipeline B — Interlocutor (dialog.py)

**Trigger:** Any private message NOT from `@leomatchbot` and NOT sent by self

```
Incoming private message
      │
      ▼
private_chat_handler()
      │
      ├── chat_id in whitelist_ids? → skip entirely (operator handles manually)
      │
      ├── read_chat_history(chat_id) → mark all messages as read (double checkmark)
      │
      ├── existing task for this chat_id?
      │       └── YES → cancel it (implements debounce)
      │
      └── create process_dialogue_task() [background]
            store in state.active_dialogue_tasks[chat_id]


process_dialogue_task()
      │
      ├── sleep(GRACE_PERIOD_SECONDS=7)       ← debounce: wait for user to finish typing
      │         [if user sends another message, this task gets cancelled and restarted]
      │
      ├── DETERMINE SESSION TYPE:
      │       look up last message timestamp in conversation_histories
      │       ├── gap < 15 min? → "active_session"  (reply in 15–60s)
      │       └── gap > 15 min? → "new_session" (probabilistic):
      │               60% → fast   (15–60s)
      │               35% → medium (5–15 min)
      │                5% → long   (1–3 hours)
      │
      ├── sleep(random delay from chosen tier)
      │
      ├── generate_conversation_response(chat_id, user_message, state)
      │         └── builds Gemini chat session with full history + system prompt
      │             sends message, gets response, appends to history, saves JSON
      │
      ├── "|||" in response?
      │       └── YES → ladder send:
      │               for each part:
      │                   send_chat_action(TYPING)
      │                   sleep(len(part) / 8 CPS + 0.5–2s jitter)
      │                   send_message(part)
      │
      └── NO → single send:
              send_chat_action(TYPING)
              sleep(len(response) / 8 CPS + 0.5–2s jitter)
              send_message(response)
```

---

## 5. AI Integration Architecture

Both pipelines use `ai_client.py` but via different generation paths:

### Path 1 — First Message (stateless, one-shot)

```
generate_first_message(anket_text)
      │
      ├── parse profile with ANKET_PATTERN → extract description
      ├── description < 15 chars? → substitute "Profile description is short or meaningless"
      ├── inject into FIRST_MESSAGE_PROMPT template (f-string)
      └── model.generate_content(prompt) → single prompt, no history
```

This is a **stateless prompt** — no chat history, no back-and-forth. The model gets one shot to produce a witty opener.

### Path 2 — Conversation Reply (stateful, chat session)

```
generate_conversation_response(chat_id, user_message, state)
      │
      ├── append user_message to state.conversation_histories[chat_id_str]
      ├── trim to MAX_HISTORY_LENGTH=20 messages (sliding window)
      │
      ├── BUILD HISTORY for API:
      │       [system turn injected as fake first exchange]
      │       user:  CONVERSATION_SYSTEM_PROMPT
      │       model: "understood, I'm ready..."
      │       [then all actual conversation history]
      │
      ├── model.start_chat(history=all_except_last)
      ├── chat_session.send_message(last_user_message)
      │
      ├── cleanup_ai_response() → strip dashes, trailing punctuation, collapse whitespace
      │
      ├── append AI response to history with UTC timestamp
      ├── save_histories(state)
      └── return cleaned response text
```

**System prompt injection pattern:** Because Gemini's chat API doesn't have a dedicated system-message role, the system prompt is injected as a synthetic user/model exchange at the start of every history payload. This is a workaround for the API's structure.

### Rate Limit Handling

```
with_rate_limit_handling(api_call)
      │
      ├── attempt 1 → run in thread (asyncio.to_thread, keeps event loop free)
      ├── ResourceExhausted (429)?
      │       ├── parse retry-delay from error metadata (if present)
      │       └── fallback: 60 seconds
      │       sleep → attempt 2 → sleep → attempt 3
      └── 3 failures → return None → caller uses fallback string
```

All Gemini calls run in a thread pool via `asyncio.to_thread` to prevent the synchronous SDK from blocking the event loop.

---

## 6. Concurrency Model

The application uses **cooperative multitasking** via `asyncio`. Key concurrent elements:

| Task | Lifecycle | Cancellation |
|------|-----------|-------------|
| `process_leomatch_task` | Created per profile card | Cancelled when a newer profile arrives |
| `process_dialogue_task` | Created per private message | Cancelled when same user sends another message (debounce) |
| Pyrogram event loop | Permanent | Never cancelled |
| `asyncio.Event().wait()` | Permanent park | Killed only by `KeyboardInterrupt` or fatal error |

**Debounce pattern:** Both pipelines use the same pattern — cancel the existing task for a given "slot" (leomatch has one slot; dialog has one slot per `chat_id`) and create a new one. This naturally handles rapid successive events.

**No locking needed:** Because Python's asyncio is single-threaded (one coroutine runs at a time), there are no race conditions on `BotState` mutations. The `asyncio.to_thread` calls for Gemini API are the only true multi-threading, and they only read parameters / return values — they never mutate `BotState` directly.

---

## 7. Persistence Architecture

```
data/
├── conversation_histories.json
│       {
│         "123456789": [
│           {"role": "user",  "parts": ["hey"], "timestamp": "2026-06-04T..."},
│           {"role": "model", "parts": ["hey)"], "timestamp": "2026-06-04T..."},
│           ...  (max 20 entries, sliding window)
│         ],
│         ...
│       }
│
└── whitelist.json
        [123456789, 987654321]
```

**Write strategy:** Histories are saved to disk on every AI response (`save_histories()` called inside `generate_conversation_response`). There is no batching or dirty-flag mechanism — every reply triggers a full JSON rewrite.

**Failure resilience:** `main.py` catches `KeyboardInterrupt` and unexpected exceptions and calls `save_histories()` before exiting, reducing the risk of losing the last few turns on crash.

---

## 8. Human Simulation Architecture

The system layers multiple independent techniques to produce human-like behavior:

```
Layer 1 — Content:    AI persona prompt (dossier, rules, forbidden patterns)
Layer 2 — Format:     cleanup_ai_response() strips academic punctuation
Layer 3 — Structure:  "|||" ladder split (30% of AI responses)
Layer 4 — Timing:     probabilistic reply delay tiers (seconds to hours)
Layer 5 — Debounce:   7-second grace period consolidates burst messages
Layer 6 — Feedback:   instant read receipts + per-character typing simulation
Layer 7 — Gating:     cooldown between Scout actions (70 seconds)
```

Each layer is independent — they compose rather than interact. Removing any one layer degrades realism but doesn't break the others.

---

## 9. Design Patterns Used

| Pattern | Where | How |
|---------|-------|-----|
| **Event Handler** | `app.py` → `leomatch_handler`, `private_chat_handler` | Pyrogram dispatches events to registered callbacks |
| **Task-per-request** | Both handlers | Each event spawns an asyncio task for deferred processing |
| **Debounce** | `dialog.py`, `leomatch.py` | Cancel-and-replace on the same task slot |
| **State object** | `state.py` | Single `BotState` passed by reference — avoids globals while keeping shared state accessible |
| **Template method** | `config.py` PROMPTS | `FIRST_MESSAGE_PROMPT` uses `{profile_text}` placeholder filled at call time |
| **Retry with backoff** | `ai_client.with_rate_limit_handling` | Up to 3 attempts with delay extracted from API error metadata |
| **Facade** | `ai_client.py` | Hides Gemini SDK complexity (threading, history assembly, cleanup) behind two clean async functions |
| **Startup replay** | `app.py` | Re-processes last bot message on boot to handle restarts mid-flow |
| **Whitelist gate** | `dialog.py` | Early return before any processing — clean opt-out for manual control |

---

## 10. External Integrations

| Integration | Protocol | Library | Auth |
|-------------|----------|---------|------|
| Telegram | MTProto (not Bot API) | Pyrogram | `API_ID` + `API_HASH` + `.session` file |
| Google Gemini | HTTPS REST | `google-generativeai` SDK | `GEMINI_API_KEY` |

**MTProto vs Bot API:** Using MTProto (user account) rather than the Bot API is architecturally significant — it allows the system to operate as a real human account, use read receipts, typing indicators, and interact with bots that require a real user (like `@leomatchbot`). A bot token could not do this.

---

## 11. Identified Architectural Weaknesses

| Weakness | Risk | Notes |
|----------|------|-------|
| Full JSON rewrite on every save | Performance degrades as history grows | Acceptable at current scale; would need append-log or SQLite at scale |
| No message deduplication | Edited messages re-processed | `leomatch_handler` handles `EditedMessageHandler` but `process_leomatch_message` has no idempotency key |
| System prompt injected as fake chat turn | Fragile API workaround | Gemini may eventually enforce role structure — should migrate to proper system instruction field |
| Single `BotState` with no snapshot/rollback | A mid-save crash corrupts JSON | Atomic write (write-to-tmp, rename) would eliminate this |
| No health check or watchdog | Silent failures go undetected until operator checks | A periodic ping or heartbeat log line would help |
| History trimmed by count, not time | Old conversations eventually drop context | A time-based eviction would be more semantically correct |
