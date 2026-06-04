# Plan 9 — Gemini API Reliability & Cost Optimization

_Week: 5 (parallel with Plan 8) | Prerequisite: Plans 2, 7 complete | Must complete before: Plan 11_

> **Goal:** Make the Gemini integration production-grade. Pin the model version so
> deprecations don't silently break the bot. Build a token-aware context window so
> the bot never hits context limits. Track API cost so the operator knows what they
> are spending. Add a multi-model fallback so a single model outage doesn't kill
> all conversations.

---

## Context: What This Plan Operates On

After Plans 1–7:

```
src/
├── ai_client.py       # with_rate_limit_handling(), initialize_ai(),
│                      # generate_conversation_response(), classify_profile_quality()
├── settings.py        # GEMINI_PRIMARY_MODEL does NOT exist yet
├── credentials.py     # GEMINI_API_KEY
├── stats.py           # record_event() — used to track API usage
src/prompts/
├── conversation.txt   # CONVERSATION_SYSTEM_PROMPT (~800 tokens)
├── first_message.txt  # FIRST_MESSAGE_PROMPT (~500 tokens)
```

Key facts about the current integration:
- Model: `"gemini-1.5-flash-latest"` — auto-updating alias; no pinned version
- System prompt: passed via `system_instruction=` on `GenerativeModel` init (Plan 2 fix)
- Context window: trimmed to `MAX_HISTORY_LENGTH = 20` turns by turn count, not by tokens
- Error handling: covers 429, 503, 504, 500 with retry (Plan 2)
- Token usage: never tracked; cost is invisible to the operator

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-11 | Prompt cache not used — system prompt retransmitted on every call |
| GEM-01 | Model version unpinned — deprecation silently breaks all AI calls |
| GEM-02 | Context window uses turn count, not tokens — long messages can overflow |
| GEM-03 | Zero API cost visibility — operator cannot see token spend |
| GEM-04 | No model fallback — one model being down stops all conversations |

---

## Task 9.1 — Pin Model Version With Fallback Chain

**Status:** ⬜ Not started
**Files:** `src/settings.py`, `src/ai_client.py`
**Estimated effort:** 45 minutes
**Depends on:** Nothing (independent)

### Problem
`initialize_ai()` currently uses:
```python
state.model = genai.GenerativeModel(
    "gemini-1.5-flash-latest",
    system_instruction=CONVERSATION_SYSTEM_PROMPT,
)
```

`"gemini-1.5-flash-latest"` is an alias that Google updates automatically. When Google retires the underlying model version and the alias stops resolving, every API call will fail with a 404 or `NotFound` exception. This exception is currently NOT caught by `with_rate_limit_handling()` — it will propagate to the background task handler and silently abort conversations, with no operator notification.

Additionally, there is no fallback: if the primary model is unavailable (maintenance, regional outage, quota exhaustion on the specific model), there is no alternative.

### Root Cause
Model version was not pinned during development (latest worked fine). No fallback was designed.

### Implementation

**Step 1:** Add model configuration to `src/settings.py`:

```python
# settings.py — add after GEMINI-related constants:

# Gemini model configuration.
# PRIMARY: pinned to a specific version — stable, predictable behavior.
# FALLBACK: auto-updating alias — used only if primary fails.
# To upgrade: change GEMINI_PRIMARY_MODEL to the new version, test, then deploy.
# Check available versions: https://ai.google.dev/gemini-api/docs/models/gemini
GEMINI_PRIMARY_MODEL = "gemini-1.5-flash-002"
GEMINI_FALLBACK_MODEL = "gemini-1.5-flash-latest"

# Profile classification uses a lighter model to save cost and latency.
# It only needs to output YES/NO, not hold a conversation.
GEMINI_CLASSIFY_MODEL = "gemini-1.5-flash-002"
```

**Step 2:** Rewrite `initialize_ai()` in `src/ai_client.py` to try models in order and store which model is active:

```python
# ai_client.py — replace initialize_ai():

from settings import (
    ANKET_PATTERN,
    CONVERSATION_SYSTEM_PROMPT,
    FIRST_MESSAGE_PROMPT,
    GEMINI_PRIMARY_MODEL,
    GEMINI_FALLBACK_MODEL,
    MAX_HISTORY_LENGTH,
)

def initialize_ai(state):
    """
    Initialize Gemini model with primary version, fall back to latest alias
    if the pinned version is unavailable.
    Stores the active model name in state.active_model_name for logging.
    """
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        logging.error(f"Failed to configure Gemini API key: {e}")
        state.model = None
        return

    model_candidates = [GEMINI_PRIMARY_MODEL, GEMINI_FALLBACK_MODEL]
    for model_name in model_candidates:
        try:
            state.model = genai.GenerativeModel(
                model_name,
                system_instruction=CONVERSATION_SYSTEM_PROMPT,
            )
            state.active_model_name = model_name
            logging.info(f"[AI] Gemini model initialized: {model_name}")
            if model_name == GEMINI_FALLBACK_MODEL:
                logging.warning(
                    f"[AI] Using fallback model '{model_name}' — "
                    "primary model unavailable. Update GEMINI_PRIMARY_MODEL "
                    "in settings.py when the new version is available."
                )
            return
        except Exception as e:
            logging.warning(
                f"[AI] Could not initialize model '{model_name}': {e}. "
                "Trying next candidate..."
            )

    logging.error(
        "[AI] All Gemini model candidates failed to initialize. "
        "Check GEMINI_API_KEY and model availability."
    )
    state.model = None
    state.active_model_name = None
```

**Step 3:** Add `active_model_name` field to `BotState` in `src/state.py`:

```python
# state.py — add to BotState:
active_model_name: Optional[str] = None
```

**Step 4:** Catch `NotFound` and `PermissionDenied` in `with_rate_limit_handling()` so model deprecation triggers a fallback instead of a silent crash.

In `ai_client.py`, update the exception handling in `with_rate_limit_handling()`:

```python
# ai_client.py — add to with_rate_limit_handling() exception handlers:

except google_exceptions.NotFound as e:
    logging.error(
        f"[AI] Model not found (attempt {attempt}/3): {e}. "
        "This may mean the model version was deprecated. "
        "Update GEMINI_PRIMARY_MODEL in settings.py."
    )
    # Do NOT retry a not-found error — it will keep failing
    return None

except google_exceptions.PermissionDenied as e:
    logging.error(
        f"[AI] Permission denied (attempt {attempt}/3): {e}. "
        "Check that GEMINI_API_KEY is valid and not revoked."
    )
    return None
```

**Step 5:** Include the active model name in the heartbeat notification (in `app.py`):

```python
# app.py — _heartbeat(), add to the notification message:
model_name = getattr(state, "active_model_name", "unknown")

await operator_notify(
    app_client,
    f"✅ Bot alive\n"
    f"Uptime: {uptime_hours}h {uptime_mins}m\n"
    f"Model: {model_name}\n"
    f"Active conversations: {active_count}\n"
    f"Total conversations: {history_count}\n"
    f"Meetings detected (session): {meeting_count}"
)
```

### Verification
```bash
# Test 1: Normal startup
# python src/main.py
# Log should show: "[AI] Gemini model initialized: gemini-1.5-flash-002"
# No fallback warning

# Test 2: Primary model unavailable (test by temporarily setting an invalid model name)
# settings.py: GEMINI_PRIMARY_MODEL = "gemini-9.9-does-not-exist"
# Log should show: "Could not initialize model 'gemini-9.9-does-not-exist'"
# Log should show: "[AI] Gemini model initialized: gemini-1.5-flash-latest"
# Log should show: "Using fallback model 'gemini-1.5-flash-latest'"
# Restore GEMINI_PRIMARY_MODEL

# Test 3: Both models fail
# (simulate by temporarily removing GEMINI_API_KEY)
# Log should show: "All Gemini model candidates failed"
# state.model should be None; bot should handle gracefully
```

---

## Task 9.2 — Token-Aware Context Window

**Status:** ⬜ Not started
**Files:** `src/ai_client.py`, `src/settings.py`
**Estimated effort:** 1.5 hours
**Depends on:** Nothing (independent)

### Problem
The current context window trimming uses turn count:
```python
if len(state.conversation_histories[chat_id_str]) > MAX_HISTORY_LENGTH:
    state.conversation_histories[chat_id_str] = \
        state.conversation_histories[chat_id_str][-MAX_HISTORY_LENGTH:]
```

`MAX_HISTORY_LENGTH = 20` assumes each turn is roughly the same size. In reality, turns vary dramatically:
- User sends a 5-word message: ~20 tokens
- AI responds with a 300-character response: ~75 tokens
- A burst message combining 5 messages: ~250 tokens

If a user sends many long messages, 20 turns can exceed 10,000 tokens. Gemini 1.5 Flash's context window is 1,000,000 tokens, so overflow is extremely unlikely. However, the PRACTICAL issue is that very long histories increase API latency and cost significantly, and there is no visibility into this.

The second problem: `generate_first_message()` uses a fresh model call with `generate_content(prompt)` — it does not use the same model object initialized with `system_instruction=`. This is intentional (first message uses a different prompt), but the call creates a new context that does not share the system instruction. This is a minor inefficiency.

### Root Cause
Turn-count trimming was a simple approximation that works at current message lengths. Token counting was not implemented. No cost visibility exists.

### Implementation

**Step 1:** Add a lightweight token estimator to `src/ai_client.py`. We do not add `tiktoken` as a dependency (unnecessary overhead for an approximation that is already imprecise). Use character-count approximation: 1 token ≈ 4 characters for English, ≈ 2–3 characters for Russian Cyrillic. We use a conservative 3 chars/token.

```python
# ai_client.py — add helper function:

CHARS_PER_TOKEN_ESTIMATE = 3  # conservative estimate; Cyrillic is ~2-3 chars/token
MAX_CONTEXT_TOKENS = 8000     # practical limit — keep history well under model max

def _estimate_tokens(text: str) -> int:
    """Rough token count estimate: 3 chars per token (conservative for mixed Ru/En)."""
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)

def _estimate_history_tokens(history: list) -> int:
    """Estimate total tokens for a conversation history list."""
    total = 0
    for turn in history:
        for part in turn.get("parts", []):
            total += _estimate_tokens(str(part))
    return total
```

**Step 2:** Add `MAX_CONTEXT_TOKENS` to `src/settings.py`:

```python
# settings.py — add:
MAX_CONTEXT_TOKENS = 8000   # estimated token budget for conversation history
```

**Step 3:** Replace the turn-count trim in `generate_conversation_response()` with a token-budget trim:

Find this code in `ai_client.py`:
```python
if len(state.conversation_histories[chat_id_str]) > MAX_HISTORY_LENGTH:
    state.conversation_histories[chat_id_str] = \
        state.conversation_histories[chat_id_str][-MAX_HISTORY_LENGTH:]
```

Replace with:
```python
# Trim history by estimated token budget, not turn count.
# Always keep at least the last 4 turns for conversational coherence.
history = state.conversation_histories[chat_id_str]
while len(history) > 4:
    estimated = _estimate_history_tokens(history)
    if estimated <= MAX_CONTEXT_TOKENS:
        break
    # Drop the oldest turn (index 0)
    history.pop(0)

# Hard fallback: if still over MAX_HISTORY_LENGTH by count, trim by count too
if len(history) > MAX_HISTORY_LENGTH:
    history = history[-MAX_HISTORY_LENGTH:]
    state.conversation_histories[chat_id_str] = history
```

**Step 4:** Add token estimation to the stats record so the operator can see usage trends.

In `generate_conversation_response()`, after the model turn is appended, record an estimated token count:

```python
# After appending model_turn to history:
estimated_context_tokens = _estimate_history_tokens(
    state.conversation_histories[chat_id_str]
)
if estimated_context_tokens > MAX_CONTEXT_TOKENS * 0.8:
    logging.warning(
        f"[AI] Context token estimate for {chat_id} is high: "
        f"~{estimated_context_tokens} tokens (budget: {MAX_CONTEXT_TOKENS})"
    )
```

**Step 5:** Update `settings.py` import in `ai_client.py` to include `MAX_CONTEXT_TOKENS`:

```python
from settings import (
    ANKET_PATTERN,
    CONVERSATION_SYSTEM_PROMPT,
    FIRST_MESSAGE_PROMPT,
    GEMINI_PRIMARY_MODEL,
    GEMINI_FALLBACK_MODEL,
    MAX_CONTEXT_TOKENS,
    MAX_HISTORY_LENGTH,
)
```

### Verification
```bash
# Test 1: Normal conversation — no trimming needed
# Have a 5-turn conversation with short messages
# Verify: no trimming warnings, history grows normally

# Test 2: Long-message conversation
# Send 25 messages each ~300 chars (~100 tokens each = ~2500 tokens for last 25)
# Verify: token budget trim kicks in before turn-count trim
# Verify: AI response still contextually appropriate (recent turns preserved)

# Test 3: Very long single message (near MAX_USER_MESSAGE_CHARS = 1000)
# After Plan 8 Task 8.1, this is capped at 1000 chars (~333 tokens)
# History trim should handle this gracefully

# Debug: Add temporary logging to see estimated tokens per call
# Look for: "[AI] Context token estimate for X is high: ~NNNN tokens"
```

---

## Task 9.3 — API Usage Tracking

**Status:** ⬜ Not started
**Files:** `src/ai_client.py`, `src/stats.py`
**Estimated effort:** 45 minutes
**Depends on:** Plan 5 complete (stats.py must exist)

### Problem
The operator has zero visibility into:
- How many Gemini API calls are made per day
- How many tokens are consumed (and at what cost)
- Which calls are for conversation vs. profile classification vs. memory updates
- Whether the free tier (15 RPM, 1M tokens/day) is approaching its limit

Without this data, the operator cannot know if they need to upgrade to a paid plan or if the system is being abused (ISSUE-19 — per-user rate limiting reduces but doesn't eliminate quota risk).

### Root Cause
Token usage was never tracked. The Gemini API response objects contain usage metadata but it was never read.

### Implementation

**Step 1:** Add a `_record_api_call()` helper in `src/ai_client.py` that reads usage metadata from the Gemini API response and records it to stats:

```python
# ai_client.py — add helper:

from stats import record_event

def _record_api_call(result, call_type: str, chat_id_str: str = ""):
    """
    Extract token usage from a Gemini API response and record to stats.
    Gemini API response objects have a .usage_metadata attribute with:
      - prompt_token_count: tokens in the input (history + current message)
      - candidates_token_count: tokens in the generated response
      - total_token_count: sum of both
    """
    if result is None:
        record_event("api_call", {
            "type": call_type,
            "status": "failed",
            "chat_id": chat_id_str,
        })
        return

    metadata = getattr(result, "usage_metadata", None)
    if metadata:
        record_event("api_call", {
            "type": call_type,
            "status": "ok",
            "chat_id": chat_id_str,
            "prompt_tokens": getattr(metadata, "prompt_token_count", 0),
            "response_tokens": getattr(metadata, "candidates_token_count", 0),
            "total_tokens": getattr(metadata, "total_token_count", 0),
        })
    else:
        record_event("api_call", {
            "type": call_type,
            "status": "ok",
            "chat_id": chat_id_str,
        })
```

**Step 2:** Call `_record_api_call()` at every Gemini API call site in `ai_client.py`.

In `generate_conversation_response()`, after `result = await with_rate_limit_handling(...)`:
```python
result = await with_rate_limit_handling(
    lambda: chat_session.send_message(last_parts)
)
_record_api_call(result, "conversation", chat_id_str)
```

In `generate_first_message()`:
```python
result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
_record_api_call(result, "first_message")
```

In `classify_profile_quality()`:
```python
result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
_record_api_call(result, "profile_classify")
```

In `_update_memory()`:
```python
result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
_record_api_call(result, "memory_update", chat_id_str)
```

**Step 3:** Add a simple stats summary to the heartbeat notification in `app.py`.

Read the last N stats entries and compute a summary. Create a helper in `src/stats.py`:

```python
# stats.py — add function:

def get_api_stats_summary(hours: int = 6) -> dict:
    """
    Summarize API usage from the last N hours.
    Returns: {"calls": int, "total_tokens": int, "failures": int}
    """
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    summary = {"calls": 0, "total_tokens": 0, "failures": 0}
    try:
        if not STATS_PATH.exists():
            return summary
        with STATS_PATH.open("r", encoding="utf-8") as f:
            events = json.load(f)
        for event in events:
            if event.get("event") != "api_call":
                continue
            ts = event.get("timestamp", "")
            try:
                event_time = datetime.fromisoformat(ts)
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
                if event_time < cutoff:
                    continue
            except ValueError:
                continue
            summary["calls"] += 1
            if event.get("status") == "failed":
                summary["failures"] += 1
            summary["total_tokens"] += event.get("total_tokens", 0)
    except Exception as e:
        logging.error(f"[STATS] Failed to compute API summary: {e}")
    return summary
```

**Step 4:** Include the API summary in the heartbeat:

```python
# app.py — _heartbeat():
from stats import get_api_stats_summary

api_stats = get_api_stats_summary(hours=HEARTBEAT_INTERVAL_HOURS)

await operator_notify(
    app_client,
    f"✅ Bot alive\n"
    f"Uptime: {uptime_hours}h {uptime_mins}m\n"
    f"Model: {model_name}\n"
    f"Active conversations: {active_count}\n"
    f"Total conversations: {history_count}\n"
    f"Meetings detected (session): {meeting_count}\n"
    f"API calls (last {HEARTBEAT_INTERVAL_HOURS}h): {api_stats['calls']} "
    f"({api_stats['failures']} failed, ~{api_stats['total_tokens']:,} tokens)"
)
```

### Verification
```bash
# Run bot for a few minutes, have a few conversations, classify a few profiles
# cat data/stats.json | python3 -m json.tool | grep '"event": "api_call"'
# Should see entries like:
# {
#   "event": "api_call",
#   "timestamp": "2026-06-04T...",
#   "type": "conversation",
#   "status": "ok",
#   "chat_id": "12345",
#   "prompt_tokens": 450,
#   "response_tokens": 85,
#   "total_tokens": 535
# }

# Wait for heartbeat (or reduce HEARTBEAT_INTERVAL_HOURS to 0.017 for 60s test)
# Verify: heartbeat message contains "API calls (last Xh): N (0 failed, ~NNNN tokens)"
```

---

## Task 9.4 — Add `NotFound` and `PermissionDenied` to Stats

**Status:** ⬜ Not started
**File:** `src/ai_client.py`
**Estimated effort:** 15 minutes
**Depends on:** Task 9.1 (NotFound handling added there), Task 9.3 (stats recording)

### Problem
When `with_rate_limit_handling()` returns `None` after a `NotFound` or `PermissionDenied` exception (added in Task 9.1), the failure is logged but not recorded in stats. The heartbeat summary will show the failure count but not the reason.

### Implementation

Update `with_rate_limit_handling()` to pass the failure reason to stats when returning `None`:

```python
# ai_client.py — in with_rate_limit_handling(), update the NotFound handler:

except google_exceptions.NotFound as e:
    logging.error(
        f"[AI] Model not found (attempt {attempt}/3): {e}. "
        "Update GEMINI_PRIMARY_MODEL in settings.py."
    )
    record_event("api_error", {"reason": "model_not_found", "error": str(e)[:100]})
    return None

except google_exceptions.PermissionDenied as e:
    logging.error(
        f"[AI] Permission denied (attempt {attempt}/3): {e}. "
        "Check GEMINI_API_KEY."
    )
    record_event("api_error", {"reason": "permission_denied", "error": str(e)[:100]})
    return None

# Also update the "all retries exhausted" path:
logging.error("[AI] Failed to execute API request after 3 attempts.")
record_event("api_error", {"reason": "all_retries_exhausted"})
return None
```

### Verification
```bash
# Temporarily set an invalid GEMINI_API_KEY in .env
# Send a conversation message
# Check stats.json:
# Should contain: {"event": "api_error", "reason": "permission_denied", ...}
# Restore valid API key
```

---

## Completion Checklist

```
[ ] Task 9.1 — Model version pinned; fallback to latest alias works; NotFound caught
[ ] Task 9.2 — Token-aware trim active; no context overflow possible; high-usage warning tested
[ ] Task 9.3 — API calls recorded in stats.json with token counts; heartbeat shows summary
[ ] Task 9.4 — NotFound and PermissionDenied recorded in stats; operator alerted
[ ] Full smoke test: 10+ conversation turns, verify history trimming correct
[ ] Heartbeat test: verify new heartbeat format with model name and API stats
[ ] pytest — all existing tests still pass
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- A pinned model version prevents silent breakage when Google deprecates `gemini-1.5-flash-latest`
- If the primary model is unavailable, the fallback takes over automatically with an operator warning
- Context window trimming is token-aware — very long messages are handled gracefully
- Every API call is recorded in stats.json with token counts — operator can track cost
- Heartbeat now reports model name and API usage since last heartbeat
- **Plan 10 can now start (production hardening assumes a stable, observable AI layer)**
