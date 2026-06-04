# Component Deep Dive — AI Dating Assistant

_Last updated: 2026-06-04_

---

## Table of Contents

1. [main.py — Entry Point & Crash Guard](#1-mainpy--entry-point--crash-guard)
2. [app.py — Bootstrap & Orchestrator](#2-apppy--bootstrap--orchestrator)
3. [state.py — Shared Runtime State](#3-statepy--shared-runtime-state)
4. [config.py — Configuration & AI Prompts](#4-configpy--configuration--ai-prompts)
5. [leomatch.py — Scout Brain](#5-leomatchpy--scout-brain)
6. [dialog.py — Interlocutor Brain](#6-dialogpy--interlocutor-brain)
7. [ai_client.py — AI Facade](#7-ai_clientpy--ai-facade)
8. [storage.py — Persistence Layer](#8-storagepy--persistence-layer)
9. [logging_setup.py — Observability](#9-logging_setuppy--observability)
10. [utils.py — Shared Helper](#10-utilspy--shared-helper)

---

## 1. `main.py` — Entry Point & Crash Guard

### What it does
`main.py` is the outermost shell of the application. Its sole job is to call `app.run()` inside `asyncio.run()` and catch every exception that escapes the rest of the system. It is not responsible for any business logic.

### How it works internally
```python
asyncio.run(run())                     # starts event loop, blocks until done
```
Three exception handlers wrap this call:

| Exception | Meaning | Response |
|-----------|---------|---------|
| `UserDeactivated / AuthKeyUnregistered` | Telegram session is invalid | Log critical, no save (histories may be corrupt anyway) |
| `KeyboardInterrupt` | Operator stopped the bot | Save histories, then exit cleanly |
| `Exception` (catch-all) | Unhandled crash anywhere in the system | Save histories, log with traceback |

The history save on both `KeyboardInterrupt` and general `Exception` ensures conversation state is never fully lost — at worst the last AI response is missing from the file.

### Why designed this way
Separating the entry point from the bootstrap (`app.py`) is a standard separation of concerns. `main.py` answers "how do we start and what do we do if we die"; `app.py` answers "how do we set up the system". This also makes `app.run()` independently testable without triggering `if __name__ == "__main__"`.

### Connections to other parts
- Calls `app.run()` — the only import from the application layer.
- Calls `storage.save_histories(state)` on exit — requires `get_state()` to retrieve the shared state object from `app.py`.
- `get_state()` is a module-level getter in `app.py` that exposes the `_STATE` global — a deliberate escape hatch for crash recovery without passing state all the way through the call stack.

### Trade-offs and constraints
- **`get_state()` global access** is an architectural compromise. Ideally `run()` would return the state on exit, but `asyncio.run()` blocks until the coroutine finishes, so by the time it returns the state is inaccessible in most crash scenarios. The global accessor pattern solves this cleanly.
- The catch-all `except Exception` is intentionally broad — the goal is maximum crash resilience for a 24/7 deployment, not strict error typing.

---

## 2. `app.py` — Bootstrap & Orchestrator

### What it does
`app.py` is the application's nervous system. It initializes all subsystems in the correct order, connects all components to the shared state, registers event handlers, and executes a startup replay before handing control to the event loop.

### How it works internally

**Initialization chain (sequential, order-dependent):**
```
setup_logging()          ← must come first — other subsystems log during init
BotState()               ← create the single shared state object
initialize_ai(state)     ← connect to Gemini, store model in state.model
initialize_app(state)    ← validate env, create Pyrogram client, store in state.app
load_histories(state)    ← populate state.conversation_histories from disk
load_whitelist(state)    ← populate state.whitelist_ids from disk
```
If `state.model` or `state.app` is `None` after init (indicating a failed initialization), the function returns early rather than starting with a broken system.

**Handler registration:**
```python
# Scout: listens to @leomatchbot (both new and edited messages)
add_handler(MessageHandler(leomatch_cb, filters.private & filters.chat(BOT_USERNAME) & ~filters.me))
add_handler(EditedMessageHandler(leomatch_cb, ...))

# Interlocutor: listens to all OTHER private messages
add_handler(MessageHandler(private_cb, filters.private & ~filters.chat(BOT_USERNAME) & ~filters.me))
```
The `~filters.me` filter on both handlers is critical — it prevents the bot from reacting to its own sent messages, which would create an infinite loop.

**`partial()` pattern:**
```python
leomatch_cb = partial(leomatch_handler, state=state)
```
Pyrogram's handler signature is `(client, message)`. Since the handlers also need `state`, `functools.partial` pre-binds the `state` keyword argument, producing a two-argument callable that Pyrogram can call normally. This avoids a global state variable inside the handler modules.

**Startup replay:**
```python
history = [msg async for msg in state.app.get_chat_history(bot_peer.user_id, limit=1)]
last_message = history[0] if history else None
if last_message and (text := get_message_text(last_message)):
    await process_leomatch_message(state.app, text, state, is_startup=True)
else:
    await state.app.send_message(BOT_USERNAME, "1")
```
After a restart, the bot re-processes the last message from `@leomatchbot` with `is_startup=True`. This flag suppresses the "unrecognized text" warning in `leomatch.py` for messages that arrived before the bot was running. If the chat is empty (first ever run), sending `"1"` navigates the dating bot to the profile-browsing view.

### Why designed this way
Centralizing all initialization in one place guarantees that all components see a fully initialized state before any events are processed. The explicit ordered initialization also makes dependencies visible — if Gemini fails, there's no point creating a Telegram client.

### Connections to other parts
- Imports from every other module except `main.py`.
- Exports `run()` (called by `main.py`) and `get_state()` (used by `main.py` for crash-time save).
- Holds the `_STATE` global — the only module-level mutable global in the entire codebase.

### Trade-offs and constraints
- **`async with state.app`** context manager from Pyrogram handles connection, authentication, and disconnection. All handler registration and event processing must happen inside this block.
- The `asyncio.Event().wait()` at the end is an intentional infinite park. The application has no planned exit condition — it runs until killed. There is no graceful shutdown signal handling (e.g. `SIGTERM`), which means a process manager termination goes straight to the `Exception` catch-all in `main.py`.

---

## 3. `state.py` — Shared Runtime State

### What it does
`state.py` defines `BotState`, a single dataclass that holds all mutable runtime state of the application. Every module that needs to read or write shared data does so through this object.

### How it works internally

```python
@dataclass
class BotState:
    last_seen_anket_text: Optional[str] = None
    last_action_time: datetime = field(default_factory=...)
    start_time: datetime = field(default_factory=...)
    conversation_histories: Dict[str, list] = field(default_factory=dict)
    active_dialogue_tasks: Dict[int, Any] = field(default_factory=dict)
    leomatch_task: Optional[Any] = None
    whitelist_ids: Set[int] = field(default_factory=set)
    model: Optional[Any] = None
    app: Optional[Any] = None
```

Each field serves a specific purpose:

| Field | Owner module | Purpose |
|-------|-------------|---------|
| `last_seen_anket_text` | `leomatch.py` | Bridges the gap between "profile received" and "write message" events |
| `last_action_time` | `leomatch.py` | Cooldown enforcement between like/dislike actions |
| `start_time` | `app.py` | Bot uptime tracking |
| `conversation_histories` | `ai_client.py` + `storage.py` | Per-user Gemini chat history |
| `active_dialogue_tasks` | `dialog.py` | Live asyncio tasks enabling debounce cancellation |
| `leomatch_task` | `leomatch.py` | Single background task slot for profile processing |
| `whitelist_ids` | `dialog.py` + `storage.py` | Fast O(1) set lookup for bypassing AI |
| `model` | `ai_client.py` + `app.py` | The live Gemini model instance |
| `app` | `app.py` + `leomatch.py` + `dialog.py` | The live Pyrogram client |

`default_factory` is used for all mutable defaults (dicts, sets, lists) to prevent the classic Python shared-mutable-default-argument bug.

`last_action_time` is initialized to `datetime.min` with UTC timezone, ensuring the first cooldown check always evaluates as "cooldown expired" — no special-casing needed on first run.

### Why designed this way
A single shared state object passed by reference is the simplest architecture that avoids both global variables (which make testing difficult and dependencies implicit) and complex dependency injection frameworks. Since `asyncio` is single-threaded, there are no race conditions on this object despite multiple coroutines reading and writing it.

### Connections to other parts
Instantiated once in `app.py`, then passed into every handler via `partial()`, and further into every background task and AI function via direct argument passing. It is the single thread connecting all components.

### Trade-offs and constraints
- **No validation or encapsulation.** Any module can write any field. This is a conscious trade-off for simplicity — the codebase is small enough that loose coupling is not a problem.
- **`model: Optional[Any]` and `app: Optional[Any]`** use `Any` typing rather than proper types (`genai.GenerativeModel`, `pyrogram.Client`). This avoids circular imports and heavy import overhead in `state.py`, but loses type safety.
- **No snapshot or rollback.** If `conversation_histories` is corrupted in-memory, there's no recovery path except from the last saved JSON file.

---

## 4. `config.py` — Configuration & AI Prompts

### What it does
`config.py` is the central configuration file. It holds every tunable constant, all file paths, all environment variable reads, both AI prompts in full, and the compiled regex pattern for profile parsing. Nothing is hard-coded in any other module.

### How it works internally

**Environment loading:**
```python
load_dotenv()
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
```
`load_dotenv()` is called at module import time, meaning the first `import config` in any module triggers environment loading. This is safe because Python's module system guarantees `config` is only imported once.

**Path resolution:**
```python
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
```
All paths are derived from the config file's own location, making the project portable — it can be placed anywhere on the filesystem without path hardcoding.

**Timing constants:**
```python
ACTION_COOLDOWN_SECONDS = 70
GRACE_PERIOD_SECONDS = 7
SESSION_TIMEOUT_MINUTES = 15
TYPING_SPEED_CPS = 8

REPLY_DELAY_CONFIG = {
    "active_session": {"min_sec": 15, "max_sec": 60},
    "new_session": {
        "fast":   {"chance": 0.60, "min_sec": 15,   "max_sec": 60},
        "medium": {"chance": 0.35, "min_sec": 300,  "max_sec": 900},
        "long":   {"chance": 0.05, "min_sec": 3600, "max_sec": 10800},
    },
}
```
`REPLY_DELAY_CONFIG` is a nested dict rather than flat constants, which allows `dialog.py` to select a tier by name and uniformly apply `min_sec`/`max_sec` from whichever tier is chosen — no conditional logic needed at the call site for the random range.

**Profile regex:**
```python
ANKET_PATTERN = re.compile(
    r"^(.+?),\s*(\d+),\s*(.+?)(?:[-–—]\s*(.*))?$", re.DOTALL
)
```
This pattern matches the `@leomatchbot` profile card format: `Name, Age, City — Description`. Groups: 1=name, 2=age, 3=city, 4=description (optional). The `re.DOTALL` flag allows descriptions containing newlines. The pattern is compiled once at import time.

**AI Prompts:**
Both `FIRST_MESSAGE_PROMPT` and `CONVERSATION_SYSTEM_PROMPT` are multi-paragraph strings stored in full in `config.py`. `FIRST_MESSAGE_PROMPT` uses a single `{profile_text}` placeholder for `str.format()` injection. `CONVERSATION_SYSTEM_PROMPT` has no placeholders — it's injected wholesale as a synthetic chat turn.

**Known system messages filter:**
```python
KNOWN_SYSTEM_MESSAGES = {
    "✨🔍", "Like sent, waiting for a response.",
    "I suggest a deal", "Everyone will see this temporary text",
    "Done", "Maybe later", "Skip",
}
```
A set (not a list) for O(1) membership testing. These are interface strings from `@leomatchbot` that should be silently ignored.

### Why designed this way
Centralizing all constants, paths, and prompts in one file means:
1. The operator can configure everything by editing one file.
2. No magic numbers are scattered across business logic modules.
3. The AI prompts are easy to find and iterate on without touching any code logic.

### Connections to other parts
Imported by every module. The only module that does not import `config` is `utils.py` (too simple to need it) and `state.py` (to avoid import order issues).

### Trade-offs and constraints
- **Prompts in code rather than external files** means changing the persona requires a code change, not a config change. For a single-operator bot this is acceptable; for a multi-user product it would be a significant limitation.
- **No type validation of env vars.** `API_ID` is loaded as a string; Pyrogram expects an integer. This conversion happens implicitly inside Pyrogram's `Client()` constructor. A failed conversion produces a confusing error.
- **All constants are public globals.** There's no namespacing or access control — any module can mutate `config.GRACE_PERIOD_SECONDS` at runtime, though none do.

---

## 5. `leomatch.py` — Scout Brain

### What it does
`leomatch.py` implements the Scout pipeline: it processes all messages from `@leomatchbot`, interprets the dating bot's protocol, makes like/dislike decisions, and triggers first-message generation when a mutual match is established.

### How it works internally

**Three-function architecture:**

```
leomatch_handler()          ← event receiver / dispatcher
      │
      ├── profile? → process_leomatch_task()    ← background task with cooldown
      │                     └── process_leomatch_message()
      │
      └── other?  → process_leomatch_message()  ← direct call
```

**`leomatch_handler` — dispatcher:**
The handler's only job is to classify the incoming message and route it correctly. Profile cards get deferred to a background task (because they need cooldown logic); all other messages are processed immediately.

Profile detection uses `ANKET_PATTERN.match(text)` — the same regex used later in processing. No separate classification pass is needed.

**Task replacement on new profile:**
```python
if state.leomatch_task and not state.leomatch_task.done():
    state.leomatch_task.cancel()
state.leomatch_task = asyncio.create_task(process_leomatch_task(...))
```
The single `leomatch_task` slot means at most one profile task is ever running. When the dating bot sends a new profile (which happens rapidly during browsing), the old task is cancelled and replaced. Only the most recent profile is ever acted upon — which mirrors real human behavior (you don't go back and act on a profile you already scrolled past).

**`process_leomatch_task` — cooldown enforcer:**
```python
time_since_last_action = (now - state.last_action_time).total_seconds()
if time_since_last_action < ACTION_COOLDOWN_SECONDS:
    wait_time = ACTION_COOLDOWN_SECONDS - time_since_last_action
    await asyncio.sleep(wait_time)
```
The cooldown is computed dynamically from `last_action_time` rather than being a fixed sleep. If 50 seconds have already passed since the last action, only 20 more seconds are waited — not a full 70. This is important because the task may be created some time after the action it's waiting on.

**`process_leomatch_message` — state machine:**
This function implements the dating bot's interaction protocol as a linear set of `if` branches:

```
State: system/ad message     → return (ignore)
State: main menu             → send "1" (navigate to profiles)
State: profile card          → like or dislike based on description quality
                               store anket text → state.last_seen_anket_text
State: "Write a message"     → retrieve stored anket text
                               generate opener via Gemini
                               send opener to bot
                               clear state.last_seen_anket_text
State: unrecognized (runtime) → log warning
State: unrecognized (startup) → suppress warning (is_startup=True)
```

The **profile card decision logic** is deliberately simple:
```python
if description and len(description.strip()) > 10:
    # like
else:
    # dislike
```
A description longer than 10 characters is the only quality signal. No sentiment analysis, no keyword matching, no AI involvement at this stage — speed and simplicity over nuance.

**The `last_seen_anket_text` bridge:**
There is a temporal gap between the dating bot showing a profile (event A) and asking "Write a message for this user" (event B, which arrives only after a mutual like). `state.last_seen_anket_text` bridges these two events. The profile text is stored at event A and consumed at event B. It is cleared after use to prevent stale profile text from being used for future openers.

### Why designed this way
The three-function split cleanly separates concerns: dispatching (what kind of event is this?), timing (is it safe to act now?), and execution (what action to take?). The cooldown-as-background-task pattern means the event loop is never blocked — the bot keeps receiving events while waiting for the cooldown.

### Connections to other parts
- Receives `state` via `partial()` from `app.py`.
- Reads/writes `state.last_seen_anket_text`, `state.last_action_time`, `state.leomatch_task`.
- Calls `generate_first_message()` from `ai_client.py`.
- Calls `client.send_message()` directly on the Pyrogram client.
- Uses `ANKET_PATTERN`, `KNOWN_SYSTEM_MESSAGES`, `BOT_USERNAME`, `ACTION_COOLDOWN_SECONDS` from `config.py`.

### Trade-offs and constraints
- **No idempotency.** If the same message arrives twice (e.g., an edited message that didn't actually change), it will be processed twice. The `EditedMessageHandler` in `app.py` is registered for robustness but could cause double-liking if `@leomatchbot` edits a profile card.
- **Binary quality filter.** The 10-character description threshold is a blunt instrument. Short but meaningful profiles (e.g., "artist") get disliked. This is a conscious simplification — the alternative would be AI-based profile evaluation, adding latency and API cost for every profile.
- **`state.last_seen_anket_text` is not thread-safe in spirit.** If two profile cards arrived nearly simultaneously (theoretically impossible given the single leomatch_task slot, but worth noting), the second would overwrite the first.

---

## 6. `dialog.py` — Interlocutor Brain

### What it does
`dialog.py` is the most behaviorally complex module. It handles all private conversations, implementing the full human-simulation stack: debounce, session classification, probabilistic delay, read receipts, typing simulation, and ladder-send splitting.

### How it works internally

**Two-function architecture:**
```
private_chat_handler()       ← event receiver / debounce controller
      │
      └── process_dialogue_task()   ← full reply cycle (background)
```

**`private_chat_handler` — debounce:**
```python
await client.read_chat_history(chat_id)    # instant read receipt

if chat_id in state.active_dialogue_tasks:
    state.active_dialogue_tasks[chat_id].cancel()  # debounce: reset timer

task = asyncio.create_task(process_dialogue_task(...))
state.active_dialogue_tasks[chat_id] = task
```
The read receipt fires immediately and unconditionally — creating the "seen" double-checkmark effect that signals presence. The task cancellation and replacement is the debounce: if the user sends three messages in 5 seconds, three tasks are created and two are immediately cancelled. Only the third survives to actually run.

**`process_dialogue_task` — full reply cycle:**

**Step 1 — Grace period:**
```python
await asyncio.sleep(GRACE_PERIOD_SECONDS)  # 7 seconds
```
Even after the debounce, a 7-second wait gives the user time to finish a multi-message thought. If another message arrives during this sleep, `CancelledError` is raised and caught, and the task exits silently.

**Step 2 — Session classification:**
```python
last_msg_time = datetime.fromisoformat(last_timestamp)
time_since_last_msg = (now - last_msg_time).total_seconds()
is_new_session = time_since_last_msg >= SESSION_TIMEOUT_MINUTES * 60
```
"New session" means the last conversation turn was more than 15 minutes ago (or this is the first message ever). Session type determines the delay tier.

**Step 3 — Probabilistic delay:**
```python
rand = random.random()
if rand < 0.05:    mode = "long"   # 1–3 hours
elif rand < 0.40:  mode = "medium" # 5–15 minutes
else:              mode = "fast"   # 15–60 seconds
delay = random.randint(min_sec, max_sec)
await asyncio.sleep(delay)
```
The probabilities are asymmetric and deliberate: most new-session replies are fast, but occasional long delays simulate being busy. Active-session replies are always fast (no tier selection needed).

**Step 4 — Generate reply:**
```python
ai_response = await generate_conversation_response(chat_id, user_message, state)
```
The user's message text is extracted from the `message` object stored at task creation time. Note: this is the text at the time the message was received — if the user edits the message during the delay period, the original text is used. The AI response may contain `|||` separators.

**Step 5 — Deliver with typing simulation:**
```python
# Ladder mode
parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
for part in parts:
    typing_delay = (len(part) / TYPING_SPEED_CPS) + random.uniform(0.5, 2.0)
    await client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    await asyncio.sleep(typing_delay)
    await client.send_message(chat_id, part)
```
Typing speed is 8 characters per second plus 0.5–2.0 seconds of random jitter. A 40-character message produces ~5–7 seconds of typing indicator. `send_chat_action(TYPING)` must be called before each message — it cancels itself after 5 seconds or when a message is sent, whichever comes first.

**Task cleanup:**
```python
finally:
    state.active_dialogue_tasks.pop(chat_id, None)
```
The `finally` block runs whether the task completes normally, is cancelled, or throws an exception. It removes the task from the tracking dict so a future message from the same user doesn't try to cancel a finished task.

### Why designed this way
The two-function split isolates the synchronous "should we reply?" decision (whitelist gate, read receipt, debounce) from the asynchronous "how and when to reply?" execution. This keeps `private_chat_handler` fast and non-blocking — it does very little work and returns control to the event loop immediately.

The delay logic is deliberately spread across three independent mechanisms (grace period, session tier delay, typing simulation) because each serves a different purpose:
- Grace period: consolidates burst messages
- Session delay: simulates the human pattern of not instantly replying to a new conversation
- Typing simulation: makes the arrival of the message feel natural and proportional

### Connections to other parts
- Receives `state` via `partial()` from `app.py`.
- Reads `state.whitelist_ids`, `state.active_dialogue_tasks`, `state.conversation_histories`.
- Writes `state.active_dialogue_tasks`.
- Calls `generate_conversation_response()` from `ai_client.py`.
- Calls `client.read_chat_history()`, `client.send_chat_action()`, `client.send_message()` on the Pyrogram client.

### Trade-offs and constraints
- **The delayed reply creates a subtle bug window:** the task captures the `message` object at creation time. If Pyrogram garbage-collects or invalidates the message object during a long delay (e.g., 2-hour "long" mode), accessing `message.chat.id` or `message.from_user.first_name` inside the task could fail. In practice Pyrogram holds message objects in memory until GC, but this is unverified for very long delays.
- **No acknowledgment of delay.** If the user sends a message and waits 3 hours for a reply, they get no "read receipt" beyond the initial double-checkmark. A real person might send "busy rn, talk later" — the bot never does.
- **Ladder split is entirely AI-controlled.** The `|||` separator is placed by Gemini in about 30% of responses per the prompt instruction. There is no validation that ladder parts are semantically meaningful — if Gemini puts `|||` in the middle of a sentence, it will be split mid-thought.
- **`active_dialogue_tasks` grows unbounded** in theory (one entry per unique chat_id). In practice `finally` cleanup prevents accumulation, but if a task is somehow orphaned (edge case in Pyrogram event handling), the entry remains.

---

## 7. `ai_client.py` — AI Facade

### What it does
`ai_client.py` is the bridge between the application and the Google Gemini API. It abstracts away the SDK's specifics, handles all error cases, cleans up AI output, and provides two clean async functions to the rest of the system.

### How it works internally

**`initialize_ai(state)`:**
```python
genai.configure(api_key=GEMINI_API_KEY)
state.model = genai.GenerativeModel("gemini-1.5-flash-latest")
```
Configures the SDK globally (the `genai.configure` call is module-level state in the SDK) and creates a model instance. On failure, `state.model` is set to `None`, which causes both generation functions to return fallback strings rather than crash.

**`cleanup_ai_response(text)`:**
```python
cleaned = text.replace("–", " ").replace("—", " ")
cleaned = cleaned.strip().rstrip(".?!")
cleaned = re.sub(r"\s+", " ", cleaned)
cleaned = cleaned.replace(" ,", ",")
```
Post-processing pipeline run on every AI response:
1. Replace em-dashes and en-dashes with spaces (the persona rules forbid dashes)
2. Strip leading/trailing whitespace
3. Strip trailing sentence-ending punctuation (the persona rules forbid periods)
4. Collapse multiple spaces into one
5. Fix space-before-comma artifacts

This is a pure text transformation that runs synchronously — no async needed.

**`with_rate_limit_handling(api_call)`:**
```python
for attempt in range(3):
    try:
        return await asyncio.to_thread(api_call)
    except google_exceptions.ResourceExhausted as e:
        retry_delay = 60
        # parse metadata for retry-after header
        await asyncio.sleep(retry_delay)
```
All Gemini API calls are wrapped in this function. Two key design choices:
1. `asyncio.to_thread` runs the synchronous SDK call in a thread pool, keeping the event loop free to process other events during the API wait.
2. The retry-delay is parsed from the error's metadata if available, falling back to 60 seconds. This respects the API's own backoff recommendation rather than using an arbitrary fixed delay.

**`generate_first_message(anket_text, state)`:**
```python
match = ANKET_PATTERN.match(anket_text)
profile_text = match.group(4).strip() if match and match.group(4) else ""
if len(profile_text) < 15:
    profile_text = "Profile description is short or meaningless"
prompt = FIRST_MESSAGE_PROMPT.format(profile_text=profile_text)
result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
```
Stateless one-shot generation. The profile description is extracted from the parsed profile card, with a minimum-length gate that forces a generic fallback prompt for empty profiles. The `generate_content` call sends a single prompt with no chat history.

**`generate_conversation_response(chat_id, user_message, state)`:**
This is the most complex function in the codebase:

```python
# 1. Append user message to history with timestamp
state.conversation_histories[chat_id_str].append(
    {"role": "user", "parts": [user_message], "timestamp": now_iso}
)

# 2. Trim to sliding window
if len(history) > MAX_HISTORY_LENGTH:
    history = history[-MAX_HISTORY_LENGTH:]

# 3. Build API payload: inject system prompt as fake first exchange
full_prompt_history = [
    {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
    {"role": "model", "parts": ["understood, I'm ready. no periods and no extra stuff"]},
    *actual_history
]

# 4. Remove last message from history (will be sent separately)
history_to_send = full_prompt_history[:-1]

# 5. Start chat session with history, send last message
chat_session = state.model.start_chat(history=history_to_send)
result = await with_rate_limit_handling(
    lambda: chat_session.send_message(last_parts)
)

# 6. Append AI response to history, save to disk
```

The system prompt injection pattern is worth examining closely: Gemini's `start_chat` API takes a `history` list but expects alternating `user`/`model` roles. There is no `system` role. The workaround is to prepend a fake user message containing the system prompt, followed by a fake model acknowledgment. This is architecturally fragile — if Gemini changes how it handles the first message in history, the persona could break silently.

The last message is always sent via `send_message` rather than included in `history`, because the SDK's `start_chat` + `send_message` pattern is: "here's the history so far, now send the next message and get a response". Including the last user message in the history would cause it to be treated as a past message with no response, not the current message to respond to.

### Why designed this way
Wrapping all AI interaction in a facade module keeps the rest of the codebase decoupled from the Gemini SDK. If the SDK changes, or if the AI provider is replaced, only `ai_client.py` needs to change. The two generation functions have clean signatures that make sense in business terms (`generate_first_message`, `generate_conversation_response`) rather than SDK terms (`generate_content`, `start_chat`).

### Connections to other parts
- Called by `leomatch.py` (first message) and `dialog.py` (conversation reply).
- Reads `state.model` and `state.conversation_histories`.
- Calls `save_histories(state)` from `storage.py` after every successful conversation reply.
- Imports `ANKET_PATTERN`, `CONVERSATION_SYSTEM_PROMPT`, `FIRST_MESSAGE_PROMPT`, `MAX_HISTORY_LENGTH` from `config.py`.

### Trade-offs and constraints
- **The system prompt injection is a known fragile point.** There's no guarantee that Gemini honors the fake first exchange the same way across model versions.
- **`asyncio.to_thread` creates real OS threads.** Under high load (many simultaneous conversations), this could create many threads. For the single-operator use case this is not a concern.
- **History trimming is by message count, not token count.** If messages are long, the history sent to the API could exceed the model's context window. In practice, the conversational messages are short enough that 20 messages is well within limits.
- **`save_histories()` is called inside `generate_conversation_response`.** This creates a tight coupling between AI generation and persistence — generating a response always writes to disk. This is safe and ensures durability, but means the AI function has a side effect beyond generating text.

---

## 8. `storage.py` — Persistence Layer

### What it does
`storage.py` provides the read/write interface for all data persisted to disk. It manages two JSON files: conversation histories and the whitelist.

### How it works internally

**Generic JSON loader/saver:**
```python
def load_json_data(filepath, default_data):
    path = Path(filepath)
    if path.exists() and path.stat().st_size > 0:
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logging.error(...)
    # Fall through: create file with defaults
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(default_data, f, ensure_ascii=False, indent=4)
    return default_data
```

The loader handles four scenarios:
1. File exists and is valid JSON → return parsed data
2. File exists but is empty (size=0) → fall through to creation
3. File exists but is corrupted JSON → log error, fall through to overwrite
4. File does not exist → create parent dirs, create file with defaults

`ensure_ascii=False` is important — conversation histories contain Cyrillic text, which would otherwise be escaped to `\uXXXX` sequences.

**Domain-specific wrappers:**
```python
def load_histories(state):
    state.conversation_histories = load_json_data(HISTORY_PATH, {})

def save_histories(state):
    save_json_data(HISTORY_PATH, state.conversation_histories)

def load_whitelist(state):
    whitelist_list = load_json_data(WHITELIST_PATH, [])
    state.whitelist_ids = set(whitelist_list)  # list → set for O(1) lookup
```
The whitelist is stored as a JSON array (human-readable, easy to edit manually) but loaded as a `set` for efficient membership testing. The conversion happens once at load time.

### Why designed this way
The generic `load_json_data`/`save_json_data` pair avoids duplicating error handling for each file type. The domain-specific wrappers (`load_histories`, `save_histories`) keep the calling code clean — callers pass `state` and don't need to know about file paths.

### Connections to other parts
- Called from `app.py` at startup (load), from `ai_client.py` after each AI response (save histories), and from `main.py` on crash/exit (save histories).
- Reads paths from `config.py`.
- Writes directly into `state.conversation_histories` and `state.whitelist_ids`.

### Trade-offs and constraints
- **Full rewrite on every save.** `save_json_data` opens the file in write mode (`"w"`) and rewrites the entire contents. For the current scale (tens of conversations) this is negligible. At thousands of conversations the file size and write latency would become a concern.
- **No atomic write.** If the process is killed mid-write (e.g., power loss), the JSON file will be truncated and corrupted. A safe write pattern would be: write to a `.tmp` file, then `os.rename()` (atomic on POSIX). This is not implemented.
- **Whitelist is load-only.** There's no `save_whitelist` function. The whitelist can only be modified by editing the JSON file manually and restarting the bot, or editing it while the bot runs (changes take effect on next restart).
- **JSON decode error recovery destroys data.** If `conversation_histories.json` is corrupted, the loader overwrites it with `{}`, losing all history. A more robust approach would rename the corrupt file to a backup before overwriting.

---

## 9. `logging_setup.py` — Observability

### What it does
`logging_setup.py` configures Python's standard logging framework with two outputs: a rotating file and the console (stdout).

### How it works internally

```python
def setup_logging():
    logger = logging.getLogger()        # root logger
    logger.setLevel(logging.INFO)

    if not logger.handlers:             # idempotency guard
        formatter = logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s")

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        file_handler = RotatingFileHandler(
            str(LOG_FILE_PATH),
            maxBytes=5 * 1024 * 1024,   # 5 MB per file
            backupCount=2,              # keep 2 rotated files = max 15 MB total
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)
```

The `if not logger.handlers` guard prevents duplicate handlers if `setup_logging()` is called more than once (which can happen in test environments or if `app.py` is imported multiple times).

`RotatingFileHandler` with `maxBytes=5MB` and `backupCount=2` gives a maximum of 15 MB of log storage before old logs are deleted. The format `%(asctime)s - [%(levelname)s] - %(message)s` is human-readable and sortable.

All other modules use `logging.info()`, `logging.warning()`, `logging.error()`, `logging.critical()` directly — they don't import or reference `logging_setup`. Python's logging framework handles routing to the configured handlers automatically through the root logger.

### Why designed this way
A single setup function called once at startup is the standard Python logging pattern. Rotating file handlers are essential for 24/7 operation — without rotation, the log file would grow indefinitely.

### Connections to other parts
- Called once from `app.py` at the start of `run()`.
- All other modules use standard `logging.*` calls that route through the root logger configured here.

### Trade-offs and constraints
- **No log levels per module.** All modules log at INFO or above. There's no way to turn up verbosity for just `dialog.py` without changing the root logger level, which makes all modules verbose.
- **Log format lacks context fields** like chat_id or username at the formatter level — these are embedded manually in log message strings (e.g., `f"[DIALOG] Reply for {user_name}..."`). Structured logging (JSON format with fields) would make log parsing and filtering much easier.
- **Console output duplicates file output.** During operator-monitored runs this is useful; for unattended server deployments it's noise (stdout goes nowhere useful in tmux background sessions).

---

## 10. `utils.py` — Shared Helper

### What it does
`utils.py` contains a single utility function that extracts text content from a Pyrogram message object.

### How it works internally

```python
def get_message_text(message) -> str | None:
    return message.text or message.caption
```

In Pyrogram, a message object has `text` for regular text messages and `caption` for messages that contain media with text (photos, videos with captions). When the dating bot sends a profile card with an image, the text is in `.caption`, not `.text`. Without this unification, profile cards would be silently dropped.

The `or` short-circuit returns `None` if both are falsy (empty/None), which callers check before processing.

### Why designed this way
This two-field check appears in multiple modules (`leomatch.py`, `dialog.py`). Centralizing it in `utils.py` eliminates duplication and ensures all modules handle the caption case consistently. Despite its trivial size, this function encodes a non-obvious fact about Pyrogram's message model.

### Connections to other parts
Imported by `app.py`, `leomatch.py`, and `dialog.py`. The function has no dependencies — it takes only a Pyrogram message object and returns a string or None.

### Trade-offs and constraints
- **No type annotation on the `message` parameter.** Using `Any` or a Pyrogram type hint would improve IDE support but would require importing Pyrogram's type, adding a dependency to what is otherwise a zero-dependency utility.
- **The module is a single function.** If it grows, it should remain a home for message-manipulation utilities rather than becoming a miscellaneous "helpers" dumping ground.
