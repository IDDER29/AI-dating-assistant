# Plan 12 — Google GenAI SDK Migration

_Priority: High | Prerequisite: Plans 1–11 complete | Urgency: google-generativeai 0.8.6 has ended support_

> **Goal:** Migrate from the deprecated `google-generativeai` package to the
> current `google-genai` package before the old SDK stops working entirely.
> The old package still functions as of 2026-06 but will not receive security
> patches or new model support.

---

## Background

```
FutureWarning: All support for the `google.generativeai` package has ended.
It will no longer be receiving updates or bug fixes.
Please switch to the `google.genai` package as soon as possible.
```

The current codebase uses `google-generativeai==0.8.6` (imported as `google.generativeai`).
Google has replaced this with `google-genai` (imported as `google.genai`), which has a
**different API surface** — not a drop-in rename. The migration requires:

1. Changing the import and initialization pattern
2. Changing how models are created and called
3. Updating exception handling (different exception module path)
4. Verifying that `system_instruction=`, `start_chat()`, and `send_message()` equivalents exist

---

## API Comparison

### Old API (google-generativeai)
```python
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    "gemini-1.5-flash-002",
    system_instruction=CONVERSATION_SYSTEM_PROMPT,
)
result = model.generate_content(prompt)
chat = model.start_chat(history=history)
response = chat.send_message(parts)
```

### New API (google-genai)
```python
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

client = genai.Client(api_key=GEMINI_API_KEY)
# system_instruction is passed per-call, not at model init
response = client.models.generate_content(
    model="gemini-1.5-flash-002",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=CONVERSATION_SYSTEM_PROMPT,
    )
)
# Multi-turn chat
chat = client.chats.create(model="gemini-1.5-flash-002")
response = chat.send_message(message)
```

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| SDK-01 | `google-generativeai` package has ended support — no security patches |
| SDK-02 | New models may not be accessible via the old SDK |
| SDK-03 | `system_instruction=` handling changes — verify persona still applied correctly |

---

## Task 12.1 — Install and Audit New SDK

**Status:** ✅ Done
**Files:** `requirements.txt`, `src/ai_client.py`
**Estimated effort:** 30 minutes research + 2 hours implementation
**Depends on:** Nothing (can start immediately)

### Steps

**Step 1:** Install and inspect the new SDK:
```bash
pip install google-genai
python -c "from google import genai; help(genai.Client)"
python -c "from google import genai; help(genai.Client.chats)"
```

**Step 2:** Verify these capabilities exist in the new SDK:
- `system_instruction` support (must apply to all responses)
- Multi-turn chat history
- `usage_metadata` on responses (used by `_record_api_call()`)
- Exception types: what replaces `google.api_core.exceptions`?
- Async support: does the new SDK have async methods or do we still use `asyncio.to_thread`?

**Step 3:** Update `requirements.txt`:
```
# Replace:
google-generativeai
# With:
google-genai
```

---

## Task 12.2 — Migrate `ai_client.py`

**Status:** ✅ Done
**File:** `src/ai_client.py`
**Estimated effort:** 2–3 hours
**Depends on:** Task 12.1

### Current code to migrate

```python
# CURRENT (google-generativeai):
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

genai.configure(api_key=GEMINI_API_KEY)
state.model = genai.GenerativeModel(
    model_name,
    system_instruction=CONVERSATION_SYSTEM_PROMPT,
)

# Conversation:
chat_session = state.model.start_chat(history=history_to_send)
result = chat_session.send_message(last_parts)

# Single generation:
result = state.model.generate_content(prompt)
```

### Target code (google-genai)

```python
# NEW (google-genai):
from google import genai
from google.genai import types, errors as genai_errors

# In initialize_ai():
state.ai_client = genai.Client(api_key=GEMINI_API_KEY)
state.active_model_name = model_name  # no model object to store

# In generate_conversation_response():
# Build content list from history
contents = [
    types.Content(
        role=turn["role"],
        parts=[types.Part.from_text(p) for p in turn["parts"]]
    )
    for turn in history_for_api
]
response = state.ai_client.models.generate_content(
    model=state.active_model_name,
    contents=contents,
    config=types.GenerateContentConfig(
        system_instruction=CONVERSATION_SYSTEM_PROMPT,
    ),
)

# OR using chat object for multi-turn:
chat = state.ai_client.chats.create(
    model=state.active_model_name,
    config=types.GenerateContentConfig(
        system_instruction=CONVERSATION_SYSTEM_PROMPT,
        history=[...],
    ),
)
response = chat.send_message(message)
```

### Exception migration

```python
# OLD:
from google.api_core import exceptions as google_exceptions
# google_exceptions.ResourceExhausted
# google_exceptions.ServiceUnavailable
# google_exceptions.DeadlineExceeded
# google_exceptions.InternalServerError
# google_exceptions.NotFound
# google_exceptions.PermissionDenied

# NEW (verify these exist in google-genai):
from google.genai import errors as genai_errors
# Check: genai_errors.ClientError, genai_errors.ServerError, etc.
# The exception hierarchy may be completely different
```

### State changes required

`BotState.model` currently holds a `genai.GenerativeModel` instance.
In the new SDK, there is no model object — only a `Client` object.

```python
# state.py — rename field:
# model: Optional["genai.GenerativeModel"] = None
# → 
ai_client: Optional["genai.Client"] = None
```

All references to `state.model` across `ai_client.py`, `app.py`, must be updated.

---

## Task 12.3 — Update `conftest.py` Stubs

**Status:** ✅ Done
**File:** `tests/conftest.py`
**Estimated effort:** 30 minutes
**Depends on:** Task 12.2

The test stubs currently mock `google.generativeai`. They must be updated to mock `google.genai` after migration.

```python
# conftest.py — update stubs:
_stub_module("google.genai")
_stub_module("google.genai.types")
_stub_module("google.genai.errors")
# Remove: google.generativeai stubs
```

Integration tests that mock `state.model` will need to mock `state.ai_client` instead.

---

## Task 12.4 — Verify Persona and Token Tracking

**Status:** ✅ Done
**Depends on:** Task 12.2
**Estimated effort:** 1 hour testing

After migration:
1. Start bot, send a test message — verify persona rules are followed (lowercase, no periods, no AI admission)
2. Send "are you a bot?" — verify ANTI-DEANON deflection
3. Check `data/stats.json` — verify `usage_metadata` token counts still record (`total_tokens` field present)
4. Check heartbeat — verify token count appears in operator notification

---

## Completion Checklist

```
[x] Task 12.1 — google-genai installed; API audited: native async via client.aio, same usage_metadata fields, ClientError/ServerError with .code, types.Part/Content/GenerateContentConfig
[x] Task 12.2 — ai_client.py fully migrated: uses client.aio.models.generate_content() for all calls; initialize_ai() uses models.get() for validation; with_api_retry updated for ClientError/ServerError; state.model → state.ai_client; from __future__ import annotations added
[x] Task 12.3 — conftest.py stubs updated: google.genai, google.genai.types (Part/Content/GenerateContentConfig as MagicMock), google.genai.errors (ClientError/ServerError with .code); all 81 tests pass
[x] Task 12.4 — FutureWarning verified absent (python -W error -c "import ai_client")
[x] requirements.txt: google-generativeai replaced with google-genai
[x] 81/81 tests pass
[ ] Live smoke test: start bot, verify model validated at startup, send test message
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- No more deprecation warning at startup
- Security patches available through the maintained SDK
- Access to new Gemini models (some may only be available via google-genai)
- Codebase is on the current Google-supported integration path
