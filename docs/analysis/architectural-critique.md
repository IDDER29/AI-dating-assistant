# Architectural Critique — AI Dating Assistant

_Last updated: 2026-06-04_

> Perspective: senior staff engineer reviewing a working personal-scale automation tool.
> Standard applied: "is this designed well enough to extend, debug, and maintain without
> rewriting it?" — not "would this pass Google's design review."

---

## Table of Contents

1. [Overall Verdict](#1-overall-verdict)
2. [Poor Design Decisions](#2-poor-design-decisions)
3. [Coupling and Abstraction Failures](#3-coupling-and-abstraction-failures)
4. [Under-Engineered Components](#4-under-engineered-components)
5. [Over-Engineered Components](#5-over-engineered-components)
6. [Structural Issues](#6-structural-issues)
7. [Concrete Improvement Proposals](#7-concrete-improvement-proposals)
8. [Alternative Architecture](#8-alternative-architecture)
9. [Long-Term Maintainability Assessment](#9-long-term-maintainability-assessment)

---

## 1. Overall Verdict

This is **competent code for its stated purpose and scale.** It works, it's readable, it's consistent, and it doesn't collapse under its own weight. For a solo experiment intended to run on one server for one operator, most of the architectural choices are defensible.

The problems become visible when you ask: "What would it take to fix a bug, add a feature, or onboard a second developer?" At that point, several structural issues surface that are not about scale — they're about design clarity, hidden coupling, and assumptions baked into the wrong layers.

The core architectural tension: **the codebase grew organically around a single use case and carries several load-bearing design decisions that were never made explicitly.** They work by accident of the current constraints, not by design.

---

## 2. Poor Design Decisions

### PDC-1 — `config.py` is three different things pretending to be one

`config.py` contains:
1. **Secrets loading** — `API_ID`, `API_HASH`, `GEMINI_API_KEY`
2. **Behavioral constants** — `ACTION_COOLDOWN_SECONDS`, `GRACE_PERIOD_SECONDS`, etc.
3. **Natural language prompts** — 150+ lines of conversational AI instructions
4. **Compiled regex** — `ANKET_PATTERN`
5. **Domain knowledge sets** — `KNOWN_SYSTEM_MESSAGES`

These have completely different change rates, audiences, and failure modes:
- Secrets change when credentials rotate
- Constants change when tuning behavior
- Prompts change when refining the persona
- Regex changes when `@leomatchbot` updates its format

Mixing them means a persona tweak requires touching the same file as a credential rotation. A regex update sits three screens away from an API key. A new developer cannot tell at a glance which parts are "settings" and which are "content."

**Concrete harm:** The file is 138 lines. The prompts alone are 85 lines — 62% of the file. Any developer trying to find `GRACE_PERIOD_SECONDS` has to scroll past two walls of Russian-language persona instructions. Any developer editing the prompt has to scroll past cryptographic credentials.

---

### PDC-2 — AI output is trusted and delivered without validation

```python
result = await with_rate_limit_handling(lambda: chat_session.send_message(last_parts))
if result and hasattr(result, "text"):
    ai_response = cleanup_ai_response(getattr(result, "text"))
    ...
    return ai_response
```

`cleanup_ai_response` strips dashes and trailing punctuation. That is the entire output processing pipeline. The response is then handed directly to `send_message`.

There is no validation that:
- The response is within the expected length range
- The response is in the correct language
- The response doesn't contain the system prompt verbatim
- The response doesn't contain a phone number, URL, or other content the persona should not produce
- The `|||` count is within a reasonable bound (prevents ladder-send flooding)

For an AI-driving system where the AI output IS the product, "trust and forward" is a design choice with significant behavioral and security implications. It is not a reasonable default.

**This decision is wrong regardless of scale.** Even in a single-operator system, unexpected AI output goes directly to a real person without any circuit breaker.

---

### PDC-3 — The pending profile is a naked field on BotState

The bridge between the Scout pipeline (profile shown) and the Interlocutor pipeline (opener sent) is:

```python
state.last_seen_anket_text: Optional[str] = None
```

This is a single untyped string with no:
- Timestamp (when was this profile shown?)
- User identifier (whose profile is this?)
- Lock or ownership (what if two profiles are processed simultaneously? The Scout has one task slot, so this can't happen today — but this invariant is not documented or enforced)

The semantics of "this field is set by one event and consumed by a different event arriving at an unknown later time" describe a simple message queue. Implementing it as a nullable string on a shared object loses all that semantic information and makes the code's intent opaque.

Anyone reading `state.last_seen_anket_text = None` at the consumption site has to trace the full flow to understand what this reset means. It should be a named operation: `state.clear_pending_profile()`, or a proper small dataclass.

---

### PDC-4 — `save_histories()` is called from inside `generate_conversation_response()`

```python
# ai_client.py
async def generate_conversation_response(...):
    ...
    save_histories(state)   # ← persistence side effect inside a generation function
    return ai_response
```

`generate_conversation_response` does three conceptually separate things:
1. Updates in-memory history (append turn)
2. Makes an AI API call
3. Persists the history to disk

The persistence call is a side effect of generation. The caller (`dialog.py`) does not know it happens. If a caller ever calls `generate_conversation_response` in a context where they don't want persistence (e.g., a test, a preview call, a dry-run), they cannot opt out.

This violates the principle of least surprise. A function named `generate_conversation_response` should generate a response. Persistence is the caller's responsibility or should be explicit.

---

### PDC-5 — The system prompt injection is a known-broken workaround left as-is

```python
full_prompt_history = [
    {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
    {"role": "model", "parts": ["understood, I'm ready. no periods and no extra stuff"]},
]
```

The correct API for this has been available for the duration of the project:
```python
genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=CONVERSATION_SYSTEM_PROMPT)
```

This is not a limitation — it's an omission. The wrong approach:
- Wastes ~800 tokens per API call
- Requires stripping the fake turns from the history before sending (done correctly, but needlessly)
- Is not semantically correct (user turn ≠ system instruction)
- Can be accidentally sent back to the user if the AI quotes early history
- Creates a hidden dependency between `generate_conversation_response` and `initialize_ai` — the model was initialized without persona, but the persona is injected at call time

This decision has no defense. It should have been implemented correctly from the start.

---

## 3. Coupling and Abstraction Failures

### CAF-1 — `leomatch.py` directly calls `client.send_message()`

Both `leomatch.py` and `dialog.py` call Pyrogram client methods directly:
```python
await client.send_message(BOT_USERNAME, "💌 / 📹")   # leomatch.py
await client.send_message(chat_id, part)              # dialog.py
await client.send_chat_action(...)                     # dialog.py
```

There is no abstraction over the Telegram client. If Pyrogram is replaced with `telethon` or `pyrofork`, every call site in both modules must be updated. There are ~12 direct client call sites across three files.

A `TelegramInterface` adapter with methods like `like_profile()`, `send_reply()`, `show_typing()`, `mark_read()` would isolate all Telegram coupling in one place. This is not over-engineering for a system this size — it's the minimum abstraction that makes swapping the client library a one-file change.

---

### CAF-2 — `BotState` is accessed by every module as a shared mutable blob

Every module writes directly to `BotState` fields:
```python
state.last_seen_anket_text = text          # leomatch.py
state.last_action_time = datetime.now()    # leomatch.py
state.conversation_histories[...].append() # ai_client.py
state.active_dialogue_tasks[chat_id] = task # dialog.py
state.whitelist_ids                         # dialog.py (read)
state.model                                 # ai_client.py (read)
```

`BotState` is the entire application's state in a single publicly-writable object. There are no access controls, no notifications on mutation, no clear ownership boundaries. Any module can corrupt any other module's state.

The practical consequence: a bug in `leomatch.py` that accidentally writes the wrong value to `conversation_histories` would be silently accepted. There would be no error, no log, no constraint violation — just wrong behavior in subsequent conversations.

---

### CAF-3 — The Scout and Interlocutor share state but have no formal protocol

The Scout pipeline sets `state.last_seen_anket_text`. The Interlocutor pipeline reads nothing from it. But they share `state.conversation_histories` and `state.whitelist_ids`. Two conceptually independent pipelines are coupled through a shared mutable bag.

The deeper issue: there is a **missing communication pathway** between Scout and Interlocutor. When the Scout sends an opener, the Interlocutor has no knowledge of this. When a match's first message arrives, the Interlocutor cannot find the opener that was sent. This is Gap #1 from the vision analysis — and it exists precisely because the two pipelines share only a generic state bag with no typed message passing.

A proper design would have the Scout emit an event ("opener sent for user X, text Y") that the Interlocutor subscribes to. With asyncio, this is a `asyncio.Queue` or a simple dict keyed by user_id — a deliberate communication channel instead of accidental shared state.

---

### CAF-4 — `app.py` knows too much

`app.py` imports from every other module:
```python
from ai_client import initialize_ai
from config import BOT_USERNAME, SESSION_NAME, API_HASH, API_ID, GEMINI_API_KEY
from dialog import private_chat_handler
from leomatch import leomatch_handler, process_leomatch_message
from logging_setup import setup_logging
from state import BotState
from storage import load_histories, load_whitelist
from utils import get_message_text
```

Eight imports from seven modules. `app.py` is a god-module that orchestrates everything. This is partly unavoidable for a bootstrap/orchestrator, but the `process_leomatch_message` import is a smell: the startup replay calls a function from a pipeline module directly. This means `app.py` understands the internals of the Scout pipeline well enough to call its processing function — it's not just wiring handlers, it's business logic.

The startup replay should be an internal concern of the Scout pipeline, exposed as a clean method: `leomatch.replay_last_message(client, state)`. `app.py` would call this without knowing about `process_leomatch_message`'s internals.

---

## 4. Under-Engineered Components

### UE-1 — Error recovery for broken conversation history

When `generate_conversation_response` fails after appending the user turn, the history is left in an invalid state (consecutive user turns). There is no cleanup:

```python
state.conversation_histories[chat_id_str].append(user_turn)
result = await with_rate_limit_handling(...)  # fails
# user_turn is now orphaned
return fallback_message
```

The fix is three lines: pop the user turn on failure. This is not a performance or scale concern — it's a correctness issue that affects every conversation where an API failure occurs. Given that conversations are the product, a broken conversation history is a product failure.

---

### UE-2 — `cleanup_ai_response` is too narrow

The cleanup function strips dashes and terminal punctuation. It does not:
- Detect or truncate responses over a reasonable length limit (long AI responses break the persona's "1–3 sentences" rule)
- Detect prompt leakage (AI response contains the system prompt)
- Detect the ladder delimiter count (prevent `|||`-flooding)
- Normalize encoding issues (smart quotes, zero-width spaces)

Five lines of guards here would prevent a class of misbehavior that currently goes through unchecked.

---

### UE-3 — No operator awareness of system state

The system produces rich internal state (`active_dialogue_tasks`, `conversation_histories`, cooldown times, whitelist contents) but exposes none of it. The operator's only window is a log file.

A minimal status command — send a message to the operator's Saved Messages with a summary — would require ~15 lines and would transform the system from a black box into a manageable tool. This is chronically under-engineered for a system designed to run unattended.

---

### UE-4 — The opener pipeline assumes success

```python
intro_message = await generate_first_message(state.last_seen_anket_text, state)
if len(intro_message) > 300:
    intro_message = "your profile caught my eye..."  # fallback
await asyncio.sleep(5)
await client.send_message(BOT_USERNAME, intro_message)
state.last_seen_anket_text = None
```

After `send_message`, the profile text is cleared unconditionally. If `send_message` throws (FloodWait, network error), the profile text is still cleared. The opener was never sent, the match has no opener, but the system has discarded the profile context.

The clear should happen only after confirmed delivery:
```python
await client.send_message(BOT_USERNAME, intro_message)
state.last_seen_anket_text = None  # only clears after successful send
```

Even in the current code this is one-line repositioning — not a refactor, just a correctness fix.

---

## 5. Over-Engineered Components

### OE-1 — `BotState` as a dataclass is mildly over-specified

`BotState` uses `@dataclass` with `field(default_factory=...)` for mutable defaults. This is correct Python, but for an object that is instantiated exactly once and mutated directly by all callers, the dataclass ceremony adds syntactic weight without behavioral benefit.

A plain class with `__init__` would be equally correct, more explicit about initialization order, and easier to add validation to. This is a mild observation, not a significant design flaw.

---

### OE-2 — `with_rate_limit_handling` is a partial solution presented as complete

The function handles `ResourceExhausted` (429) with up to 3 retries. It is written as a general retry wrapper (`with_rate_limit_handling`) but handles only one error type. The name implies generality; the implementation is specific.

This is a clarity problem: future developers may add new Gemini call sites believing they are protected by the general retry wrapper, when they are only protected against rate limiting. The function should either be named `with_rate_limit_retry` (honest about scope) or extended to handle all retryable errors (honest about claimed behavior).

---

## 6. Structural Issues

### SI-1 — No interface boundaries between layers

The system has a de facto three-layer structure:
```
Telegram interface (Pyrogram calls)
Business logic (leomatch.py, dialog.py)
AI interface (ai_client.py)
```

But these layers are not enforced. `dialog.py` calls `client.send_message()` directly (crossing from business to Telegram layer without an interface). `ai_client.py` calls `save_histories()` (crossing from AI layer to persistence). `leomatch.py` calls `generate_first_message()` which itself calls `cleanup_ai_response()` which modifies the string that will be sent directly to Telegram.

In a well-layered system, each layer depends only on the layer below it through a defined interface. Here, every layer reaches into every other layer freely. The result is a system where a change anywhere can have unexpected effects anywhere.

---

### SI-2 — Test infrastructure is completely absent

There are no tests of any kind — no unit tests, no integration tests, no smoke tests. For a codebase of this size, complete absence of tests is a maintenance liability, not a scale issue.

The most testable components (pure functions) are:
- `cleanup_ai_response(text)` — pure function, trivially unit-testable
- `get_message_text(message)` — pure function, trivially unit-testable
- `load_json_data(path, default)` — pure-ish, testable with tmp files
- Session classification logic in `process_dialogue_task` — extractable and testable

The AI generation functions are harder to test (external dependency) but the history assembly, token cleanup, and ladder split logic are all pure transformations that could be extracted and tested independently.

Without tests, every change to `cleanup_ai_response` requires manual testing. Every regex change to `ANKET_PATTERN` requires running the full bot. The test gap is not just a quality issue — it's a development velocity issue.

---

### SI-3 — The module boundary between `app.py` and `leomatch.py` is wrong

`app.py` calls `process_leomatch_message()` directly for the startup replay. `leomatch.py` also calls `process_leomatch_message()` internally (from `process_leomatch_task`). This means `process_leomatch_message` is simultaneously a private implementation detail of `leomatch.py` and a public API consumed by `app.py`.

The function has no visibility modifier (Python doesn't have them), no documentation of its callers, and no naming convention distinguishing public from internal. The export surface of `leomatch.py` is the entire module.

---

### SI-4 — Configuration and prompts cannot be changed at runtime

All tuning parameters and the AI persona live in Python constants loaded at import time. The running process cannot be told to use a different persona, adjust delays, or change the quality filter without a full restart.

For a 24/7 system, this means every configuration change requires downtime. An A/B test of two openers requires two separate running processes. An emergency delay adjustment (e.g., "dial up the response speed tonight") requires stopping and restarting the bot.

This is not a Python limitation — it's a design choice. Runtime-reloadable configuration (read from file on each use, or with a reload signal handler) would eliminate this constraint at minimal cost.

---

## 7. Concrete Improvement Proposals

### Proposal 1 — Split `config.py` into three files

**Current:** One file for everything.
**Proposed:**

```
src/
├── settings.py          # tunable constants (delays, thresholds, limits)
├── credentials.py       # env var loading (secrets only)
└── prompts/
    ├── first_message.txt
    └── conversation.txt
```

`settings.py` is safe to commit and share. `credentials.py` is git-ignored. Prompt files are plain text — editable by non-developers, diff-able in code review, A/B testable by filename.

**Migration cost:** ~30 minutes. Update import sites. No behavior change.

---

### Proposal 2 — Fix `system_instruction=` in one line

```python
# ai_client.py initialize_ai():
state.model = genai.GenerativeModel(
    "gemini-1.5-flash-latest",
    system_instruction=CONVERSATION_SYSTEM_PROMPT
)
```

Then remove the fake exchange injection from `generate_conversation_response`:
```python
# Remove these two lines from full_prompt_history:
{"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
{"role": "model", "parts": ["understood, I'm ready..."]},
```

**Migration cost:** 3 lines changed. Reduces token usage 44%. Eliminates the fragile workaround. Semantically correct.

---

### Proposal 3 — Extract a `TelegramAdapter`

```python
# src/telegram_adapter.py
class TelegramAdapter:
    def __init__(self, client):
        self._client = client

    async def like_profile(self):
        await self._client.send_message(BOT_USERNAME, "💌 / 📹")

    async def dislike_profile(self):
        await self._client.send_message(BOT_USERNAME, "👎")

    async def navigate_to_profiles(self):
        await self._client.send_message(BOT_USERNAME, "1")

    async def send_opener(self, text: str):
        await self._client.send_message(BOT_USERNAME, text)

    async def send_reply(self, chat_id: int, text: str):
        await self._client.send_message(chat_id, text)

    async def show_typing(self, chat_id: int):
        await self._client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    async def mark_read(self, chat_id: int):
        await self._client.read_chat_history(chat_id)
```

`leomatch.py` and `dialog.py` accept a `TelegramAdapter` instead of a raw `Client`. Switching to `telethon` or `pyrofork` means implementing a new adapter, not hunting through business logic.

**Migration cost:** ~1 hour. Add adapter, update handler signatures, pass adapter via partial.

---

### Proposal 4 — Add an `OutputValidator` before delivery

```python
# src/output_validator.py
import re

MAX_RESPONSE_LENGTH = 500
MAX_LADDER_PARTS = 5
PROMPT_LEAK_MARKERS = ["dossier", "your task is to", "anti-deanon", "communication rules"]

def validate_ai_response(text: str) -> tuple[bool, str]:
    """Returns (is_valid, reason). Caller uses fallback string if not valid."""
    if not text or not text.strip():
        return False, "empty response"
    if len(text) > MAX_RESPONSE_LENGTH:
        return False, f"response too long ({len(text)} chars)"
    parts = [p for p in text.split("|||") if p.strip()]
    if len(parts) > MAX_LADDER_PARTS:
        return False, f"too many ladder parts ({len(parts)})"
    lower = text.lower()
    for marker in PROMPT_LEAK_MARKERS:
        if marker in lower:
            return False, f"possible prompt leak (marker: '{marker}')"
    return True, ""
```

Called in `ai_client.py` after `cleanup_ai_response`. Five lines of guards on every response. This closes the open output pipeline described in PDC-2.

---

### Proposal 5 — Separate persistence from generation in `ai_client.py`

```python
# Current (persistence inside generation):
async def generate_conversation_response(chat_id, user_message, state):
    ...
    save_histories(state)   # ← side effect
    return ai_response

# Proposed (caller decides when to persist):
async def generate_conversation_response(chat_id, user_message, state):
    ...
    return ai_response   # pure: generate and return, no side effects

# dialog.py (caller persists explicitly):
ai_response = await generate_conversation_response(chat_id, user_message, state)
await asyncio.to_thread(save_histories, state)   # explicit, async, non-blocking
```

**Migration cost:** Move 1 line. Add 1 line in `dialog.py`. Increases testability. Removes hidden side effect. Makes save non-blocking.

---

### Proposal 6 — Define a Scout→Interlocutor handoff protocol

```python
# In BotState, replace:
last_seen_anket_text: Optional[str] = None

# With:
@dataclass
class PendingMatch:
    anket_text: str
    liked_at: datetime
    opener_text: Optional[str] = None  # filled after generation

pending_match: Optional[PendingMatch] = None
sent_openers: Dict[str, str] = field(default_factory=dict)  # anket_hash → opener_text
```

When the Scout sends an opener:
```python
state.pending_match.opener_text = intro_message
opener_hash = hashlib.md5(state.pending_match.anket_text.encode()).hexdigest()[:8]
state.sent_openers[opener_hash] = intro_message
state.pending_match = None
```

When the Interlocutor receives a first message from a new user:
```python
if chat_id_str not in state.conversation_histories:
    # New conversation — look for a recently sent opener
    if state.sent_openers:
        # Use most recent opener as first model turn
        recent_opener = list(state.sent_openers.values())[-1]
        state.conversation_histories[chat_id_str] = [{
            "role": "model",
            "parts": [recent_opener],
            "timestamp": datetime.now(UTC).isoformat()
        }]
        state.sent_openers.clear()
```

This is imprecise (the most recent opener is assumed to match the new conversation) but is far better than the current amnesia. A more precise solution requires `@leomatchbot` to provide the user ID when a mutual match occurs — which it may not expose.

---

### Proposal 7 — Make `save_histories` atomic and non-blocking

```python
# storage.py — atomic write:
def save_json_data(filepath, data):
    path = Path(filepath)
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        tmp_path.replace(path)  # atomic on POSIX
    except IOError as e:
        logging.error(f"Error saving {path}: {e}")
        tmp_path.unlink(missing_ok=True)  # clean up tmp file on failure
```

Combined with Proposal 5 (call via `asyncio.to_thread`), this makes persistence:
- Non-blocking (event loop never stalls on disk I/O)
- Atomic (crash-safe, no data loss)
- Clean on failure (tmp file removed if write fails)

**Total cost:** 5 lines changed across 2 files.

---

### Proposal 8 — Add a minimal operator notification channel

```python
# src/operator.py
async def notify(client, message: str):
    """Send a message to operator's Saved Messages."""
    try:
        await client.send_message("me", f"[BOT] {message}")
    except Exception as e:
        logging.error(f"Failed to notify operator: {e}")
```

Called at key events:
```python
# When a meeting is suggested (detected by keyword):
if any(w in user_message.lower() for w in ["meet", "coffee", "когда", "встретимся"]):
    await operator.notify(client, f"⚡ Meeting suggested by {user_name} ({chat_id})")

# When AI response validation fails:
await operator.notify(client, f"⚠️ Response validation failed for {user_name}: {reason}")

# Periodic heartbeat (once per hour):
await operator.notify(client, f"✓ Bot alive. Active: {len(state.active_dialogue_tasks)} conversations.")
```

**Cost:** ~20 lines. Transforms the system from black box to observable tool.

---

## 8. Alternative Architecture

For a production-quality version of the same product, the architecture would look like:

```
src/
├── main.py                    # entry point only
├── bootstrap.py               # initialization and wiring
│
├── config/
│   ├── settings.py            # tunable constants
│   ├── credentials.py         # env var loading
│   └── prompts/               # plain text prompt files
│
├── adapters/
│   ├── telegram.py            # TelegramAdapter (wraps Pyrogram)
│   └── gemini.py              # GeminiAdapter (wraps SDK)
│
├── pipelines/
│   ├── scout.py               # Scout pipeline (leomatch logic)
│   └── interlocutor.py        # Interlocutor pipeline (dialog logic)
│
├── services/
│   ├── ai_service.py          # generation logic (no persistence, no I/O)
│   ├── history_service.py     # conversation history management
│   └── delay_service.py       # delay calculation, session classification
│
├── state/
│   ├── bot_state.py           # BotState dataclass
│   └── pending_match.py       # PendingMatch dataclass
│
├── storage/
│   ├── history_store.py       # persistence (atomic writes, to_thread)
│   └── whitelist_store.py     # whitelist persistence
│
├── validation/
│   └── output_validator.py    # AI output guard layer
│
└── operator/
    └── notifications.py       # operator channel
```

**What changes structurally:**
1. Adapters isolate all external library coupling
2. Services contain pure logic with no I/O side effects
3. Pipelines orchestrate adapters and services
4. Storage layer is separate from services
5. Validation is a first-class layer, not an afterthought

**What stays the same:** The business logic, the timing constants, the AI prompts, the human-simulation approach, the asyncio concurrency model. The refactor is structural, not functional.

---

## 9. Long-Term Maintainability Assessment

### What makes this codebase maintainable today

- **Consistent patterns.** Every handler uses the same partial/state injection. Every background task uses the same cancel-and-replace debounce. Every AI call uses the same rate-limit wrapper. A developer learning one module can predict the others.
- **Short, focused functions.** No function is longer than ~60 lines. The longest single function (`process_dialogue_task`) is 85 lines including blank lines and docstring.
- **Clear module naming.** The file names describe what the module does. `leomatch.py` handles @leomatchbot. `dialog.py` handles dialogue. `ai_client.py` is the AI client. No mystery.
- **Single entry point.** `main.py` is unambiguously where the system starts. Bootstrapping is in `app.py`. There is no framework magic hiding the startup flow.

### What makes this codebase fragile over time

1. **`config.py` will become unmaintainable** as prompts are tuned and constants are adjusted in the same file. Within six months of active use, this file will be twice its current size.

2. **No tests means every change is a gamble.** The regex `ANKET_PATTERN` is the single most likely thing to need updating (if @leomatchbot changes format). There are no tests for it. Updating it requires running the full bot and observing behavior.

3. **The system prompt workaround will break eventually.** `gemini-1.5-flash-latest` auto-updates. A model update that changes how early history turns are weighted could silently disable the persona. There is no test for this and no detection mechanism.

4. **The data model has no schema.** `conversation_histories.json` has an implicit schema enforced entirely by the code that reads and writes it. Any schema change requires updating every access site simultaneously. There is no migration path.

5. **The `BotState` object is a shared-mutable-everything.** As features are added, `BotState` will accumulate more fields — each one a global accessible from anywhere. This is the pattern that produces "I changed X and Y broke for unknown reasons" bugs.

### The single highest-impact maintainability improvement

**Extract a `ConversationManager` service that owns all history operations.**

```python
class ConversationManager:
    def __init__(self, storage_path: Path):
        self._histories: Dict[str, list] = {}
        self._path = storage_path

    def load(self): ...
    def get_history(self, user_id: int) -> list: ...
    def append_user_turn(self, user_id: int, text: str): ...
    def append_model_turn(self, user_id: int, text: str): ...
    def rollback_last_user_turn(self, user_id: int): ...  # fixes orphan bug
    def get_last_timestamp(self, user_id: int) -> Optional[datetime]: ...
    async def save(self): ...  # atomic, non-blocking
```

This single class would:
- Fix the orphaned user turn bug (via `rollback_last_user_turn`)
- Move persistence out of `ai_client.py`
- Provide a typed interface to history instead of raw dict access
- Make the history schema explicit and enforceable
- Enable unit testing of history logic without touching the AI layer

It consolidates the most fragile and most frequently-changing part of the codebase into one class with a clear interface. Every other module interacts with history through this interface, not through raw dict operations on shared state.

**Estimated effort:** 2–3 hours. No behavior change. Eliminates 3 known bugs, 2 security concerns, and the primary scalability bottleneck in a single refactor.
