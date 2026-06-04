# Plan 2 — AI Integration Correctness

_Week: 1b | Prerequisite: Plan 1 Task 1.3 | Must complete before: Plan 3, Plan 5_

> **Goal:** Fix every bug in the AI integration layer. Make Gemini usage semantically
> correct, fully error-handled, and safe to trust as the conversation engine.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-06 | `system_instruction=` unused — 800 tokens wasted per call |
| ISSUE-07 | AI output not validated before delivery to users |
| ISSUE-08 | No API timeout — network partition hangs thread forever |
| ISSUE-09 | Only HTTP 429 caught — all other API errors unhandled |
| ISSUE-10 | Orphaned user turn on API failure corrupts conversation history |
| ISSUE-11 | Empty `|||`-only response sends nothing silently |

---

## Task 2.1 — Use `system_instruction=` Parameter

**Status:** ⬜ Not started
**File:** `src/ai_client.py`
**Estimated effort:** 1 hour (including testing)
**Depends on:** Nothing

### Problem
The system prompt (`CONVERSATION_SYSTEM_PROMPT`, ~800 tokens) is injected as a fake `user`/`model` exchange at the start of every API call's history payload. This wastes ~800 tokens per request, is semantically incorrect (user turn ≠ system context), and can silently break if Gemini changes how early history turns are weighted.

The Gemini SDK has provided `system_instruction=` since `google-generativeai >= 0.3`. The current version is `0.8.6` — this parameter has been available the entire time.

### Implementation

**Step 1:** Update `initialize_ai()` in `ai_client.py`:

```python
def initialize_ai(state):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        state.model = genai.GenerativeModel(
            "gemini-1.5-flash-latest",
            system_instruction=CONVERSATION_SYSTEM_PROMPT   # ← add this
        )
        logging.info("Google Gemini model successfully initialized.")
    except Exception as e:
        logging.error(f"Failed to configure Google Gemini model: {e}")
        state.model = None
```

**Step 2:** Remove the fake exchange injection from `generate_conversation_response()`. Replace:

```python
# REMOVE:
full_prompt_history = [
    {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
    {"role": "model", "parts": ["understood, I'm ready. no periods and no extra stuff"]},
]
full_prompt_history.extend(history_for_api)

# REPLACE WITH:
full_prompt_history = history_for_api   # just the actual conversation turns
```

**Step 3:** Update the history slice logic. Previously `history_to_send = list(full_prompt_history)` then `history_to_send.pop()`. This logic removes the last entry before passing to `start_chat`. With the fake exchange gone, verify the slice still correctly excludes the last (current) user message.

The corrected section:
```python
history_for_api = [
    {"role": str(msg["role"]), "parts": list(msg["parts"])}
    for msg in state.conversation_histories[chat_id_str]
]

# Exclude the last turn (current user message) — it is sent via send_message()
history_to_send = history_for_api[:-1] if history_for_api else []

chat_session = state.model.start_chat(history=history_to_send)
last_msg = history_for_api[-1] if history_for_api else {"parts": [user_message]}
result = await with_rate_limit_handling(
    lambda: chat_session.send_message(last_msg.get("parts", []))
)
```

### Verification
```bash
# Start bot, open a fresh test conversation
# Send: "hey how are you"
# Verify: response is in persona (lowercase, no periods, informal)
# Send: "are you a bot?"
# Verify: ANTI-DEANON PROTOCOL response (deflection/sarcasm, not admission)
# Check API token usage: should be ~1000 tokens, not ~1800
```

---

## Task 2.2 — Add API Timeout and Extended Error Handling

**Status:** ⬜ Not started
**File:** `src/ai_client.py`
**Estimated effort:** 45 minutes
**Depends on:** Nothing (independent)

### Problem
`with_rate_limit_handling` wraps API calls in `asyncio.to_thread` with no timeout. A hung network call blocks a thread pool slot indefinitely.

The function only catches `ResourceExhausted` (HTTP 429). `ServiceUnavailable` (503), `DeadlineExceeded` (504), `InternalServerError` (500), and `TimeoutError` all propagate uncaught to the task handler, which abandons the conversation without sending a reply.

### Implementation

**Step 1:** Update the import at the top of `ai_client.py`:

```python
from google.api_core import exceptions as google_exceptions
```
(Already present — verify it includes all needed exception types.)

**Step 2:** Replace `with_rate_limit_handling()` entirely:

```python
async def with_rate_limit_handling(api_call, timeout_sec: float = 30.0):
    """
    Wrap a synchronous Gemini API call with:
    - asyncio.to_thread (non-blocking)
    - timeout (30s default)
    - retry on rate limit, server errors, and timeout (up to 3 attempts)
    """
    for attempt in range(1, 4):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(api_call),
                timeout=timeout_sec
            )

        except asyncio.TimeoutError:
            logging.warning(
                f"[AI] API call timed out after {timeout_sec}s "
                f"(attempt {attempt}/3). Retrying in 10s..."
            )
            await asyncio.sleep(10)

        except google_exceptions.ResourceExhausted as e:
            retry_delay = 60
            if hasattr(e, "error") and hasattr(e.error, "metadata"):
                for meta in e.error.metadata:
                    if meta[0] == "retry-delay":
                        retry_delay = int(meta[1].seconds) + 1
                        break
            logging.warning(
                f"[AI] Rate limit hit. Retrying in {retry_delay}s "
                f"(attempt {attempt}/3)..."
            )
            await asyncio.sleep(retry_delay)

        except (
            google_exceptions.ServiceUnavailable,
            google_exceptions.DeadlineExceeded,
            google_exceptions.InternalServerError,
        ) as e:
            logging.warning(
                f"[AI] Retryable server error: {type(e).__name__} "
                f"(attempt {attempt}/3). Retrying in 15s..."
            )
            await asyncio.sleep(15)

    logging.error("[AI] Failed to execute API request after 3 attempts.")
    return None
```

### Verification
```bash
# Test 1: Simulate timeout
#   Temporarily set timeout_sec=0.001 in a test call, verify TimeoutError is caught
#   and fallback string is returned (not a crash)

# Test 2: Normal operation
#   Send a conversation message, verify it still works correctly
```

---

## Task 2.3 — Fix Orphaned User Turn on API Failure

**Status:** ⬜ Not started
**File:** `src/ai_client.py`
**Estimated effort:** 30 minutes
**Depends on:** Task 2.2 (error handling in place)

### Problem
In `generate_conversation_response()`, the user turn is appended to history before the API call. If the call fails (all retries exhausted, timeout, any error), the user turn remains with no corresponding model turn. The next call sends two consecutive `"user"` turns to Gemini — violating the API's alternating-role contract. Conversation quality degrades silently and permanently.

### Implementation

**Step 1:** Restructure `generate_conversation_response()` to use rollback on failure:

```python
async def generate_conversation_response(chat_id: int, user_message: str, state) -> str:
    fallback_message = "hm, something went wrong, repeat that"
    if not state.model:
        return fallback_message

    chat_id_str = str(chat_id)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if chat_id_str not in state.conversation_histories:
        state.conversation_histories[chat_id_str] = []

    # Append user turn
    user_turn = {"role": "user", "parts": [user_message], "timestamp": now_iso}
    state.conversation_histories[chat_id_str].append(user_turn)

    # Trim to window
    if len(state.conversation_histories[chat_id_str]) > MAX_HISTORY_LENGTH:
        state.conversation_histories[chat_id_str] = \
            state.conversation_histories[chat_id_str][-MAX_HISTORY_LENGTH:]

    try:
        # Build history and call API
        history_for_api = [
            {"role": str(msg["role"]), "parts": list(msg["parts"])}
            for msg in state.conversation_histories[chat_id_str]
        ]
        history_to_send = history_for_api[:-1] if history_for_api else []
        chat_session = state.model.start_chat(history=history_to_send)
        last_parts = history_for_api[-1].get("parts", []) if history_for_api else [user_message]

        result = await with_rate_limit_handling(
            lambda: chat_session.send_message(last_parts)
        )

        if result and hasattr(result, "text"):
            ai_response = cleanup_ai_response(getattr(result, "text"))

            # Validate output (see Task 2.4)
            # validation happens here after 2.4 is added

            model_turn = {
                "role": "model",
                "parts": [ai_response],
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            state.conversation_histories[chat_id_str].append(model_turn)
            return ai_response

        # API returned None — roll back user turn
        state.conversation_histories[chat_id_str].pop()
        return fallback_message

    except Exception as e:
        # Any unexpected error — roll back user turn
        if state.conversation_histories[chat_id_str] and \
           state.conversation_histories[chat_id_str][-1] == user_turn:
            state.conversation_histories[chat_id_str].pop()
        logging.error(f"[AI] Unexpected error in generation: {e}", exc_info=True)
        return fallback_message
```

### Verification
```bash
# Test: Temporarily set GEMINI_API_KEY to an invalid value
# Send a message — verify:
#   - Fallback string is returned (not a crash)
#   - conversation_histories does NOT end with an orphaned user turn
#   - Next message with valid key produces a correct response
```

---

## Task 2.4 — Build Output Validator

**Status:** ⬜ Not started
**Files:** `src/output_validator.py` (new file), `src/ai_client.py`
**Estimated effort:** 1 hour
**Depends on:** Task 2.3 (rollback mechanism must exist before validator can trigger it)

### Problem
`result.text` is cleaned for punctuation and sent directly to users. No guard exists against: empty responses (Gemini safety filter triggered), excessively long responses, system prompt leakage, excessive `|||` parts that flood Telegram, or completely off-persona outputs.

### Implementation

**Step 1:** Create `src/output_validator.py`:

```python
"""
Validates AI-generated response text before delivery to users.
"""
from dataclasses import dataclass

MAX_RESPONSE_CHARS = 600
MAX_LADDER_PARTS = 4
PROMPT_LEAK_MARKERS = [
    "dossier",
    "your task is to",
    "anti-deanon",
    "communication rules",
    "system prompt",
    "you are the ai avatar",
    "you are an ai",
    "i am an ai",
    "as an ai language model",
]


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""


def validate_response(text: str) -> ValidationResult:
    """
    Returns ValidationResult(valid=True) if the response is safe to send.
    Returns ValidationResult(valid=False, reason=...) if it should be rejected.
    """
    # Empty or whitespace-only
    if not text or not text.strip():
        return ValidationResult(False, "empty response")

    # Too long (persona specifies 1-3 sentences)
    if len(text) > MAX_RESPONSE_CHARS:
        return ValidationResult(False, f"response too long ({len(text)} chars)")

    # Excessive ladder parts would cause Telegram flooding
    parts = [p for p in text.split("|||") if p.strip()]
    if len(parts) > MAX_LADDER_PARTS:
        return ValidationResult(False, f"too many ladder parts ({len(parts)})")

    # Possible system prompt leakage
    lower = text.lower()
    for marker in PROMPT_LEAK_MARKERS:
        if marker in lower:
            return ValidationResult(False, f"possible prompt leak: '{marker}'")

    return ValidationResult(True)
```

**Step 2:** Import and call in `ai_client.py` inside `generate_conversation_response()`, after `cleanup_ai_response`:

```python
from output_validator import validate_response

# After: ai_response = cleanup_ai_response(result.text)
validation = validate_response(ai_response)
if not validation.valid:
    logging.warning(
        f"[AI] Response failed validation ({validation.reason}). "
        "Rolling back user turn and using fallback."
    )
    # Roll back user turn (same path as API failure)
    if state.conversation_histories[chat_id_str] and \
       state.conversation_histories[chat_id_str][-1]["role"] == "user":
        state.conversation_histories[chat_id_str].pop()
    return fallback_message
```

### Verification
```bash
# Test each validation case:
# 1. Empty: manually return "" from API mock → fallback sent, history clean
# 2. Too long: set MAX_RESPONSE_CHARS=10 temporarily → fallback triggers
# 3. Prompt leak: ask AI to repeat its instructions → validator catches it
# 4. Too many parts: ask AI to split into 10 parts → validator catches it
```

---

## Task 2.5 — Empty Response Guard at Delivery Site

**Status:** ⬜ Not started
**File:** `src/dialog.py`
**Estimated effort:** 15 minutes
**Depends on:** Task 2.4

### Problem
After the AI response is received and validated (Tasks 2.3 + 2.4), there is still no guard at the delivery site for a residual empty string slipping through. An empty `send_message()` raises a Pyrogram exception and leaves the user with no reply and no visible error.

### Implementation

In `process_dialogue_task()`, before the ladder-split block:

```python
# After: ai_response = await generate_conversation_response(...)

if not ai_response or not ai_response.strip():
    logging.warning(
        f"[DIALOG] Received empty AI response for {user_name}. "
        "Skipping send."
    )
    return

if "|||" in ai_response:
    parts = [p.strip() for p in ai_response.split("|||") if p.strip()]
    if not parts:
        logging.warning(
            f"[DIALOG] Ladder split produced no parts for {user_name}. "
            "Skipping send."
        )
        return
    # ... rest of ladder send
```

### Verification
```bash
# Force ai_response = "" in a debug run
# Verify: log line appears, no send_message() called, no exception
```

---

## Completion Checklist

```
[ ] Task 2.1 — system_instruction= verified (persona works, token count reduced)
[ ] Task 2.2 — timeout + extended errors verified (simulate timeout, verify retry)
[ ] Task 2.3 — orphaned turn fix verified (bad API key test, history stays clean)
[ ] Task 2.4 — OutputValidator verified (all 4 rejection cases tested)
[ ] Task 2.5 — empty response guard verified (no crash on empty string)
[ ] Full conversation smoke test: persona correct, no crashes, saves working
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- ~44% reduction in Gemini API token usage per conversation reply
- Conversation history never ends in an invalid state after API failure
- Invalid AI output never reaches users
- All API errors are retried, not silently dropped
- Network partitions do not create hung threads
- **Plan 3 (conversation flow) and Plan 5 (intelligence) can now be started**
