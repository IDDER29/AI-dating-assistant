# Configuration Reference

Every tunable value in the AI Dating Assistant — where it lives, what it does,
its default, valid range, and what happens when you change it.

---

## Table of Contents

1. [Environment Variables (`.env`)](#environment-variables-env)
2. [Behavioural Constants (`src/settings.py`)](#behavioural-constants-srcsettingspy)
3. [Gemini Model Configuration](#gemini-model-configuration)
4. [AI Prompt Files (`src/prompts/`)](#ai-prompt-files-srcprompts)
5. [Output Validator Thresholds (`src/output_validator.py`)](#output-validator-thresholds-srcoutput_validatorpy)
6. [Input Sanitizer Limits (`src/input_sanitizer.py`)](#input-sanitizer-limits-srcinput_sanitizerpy)
7. [Data Files (`data/`)](#data-files-data)

---

## Environment Variables (`.env`)

These are secrets and must **never** be committed to version control.
The `.gitignore` excludes `.env` automatically.

Create at the project root:
```ini
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
GEMINI_API_KEY=AIzaSy...
STRUCTURED_LOGGING=false
```

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `TELEGRAM_API_ID` | integer | ✅ | Telegram application ID from [my.telegram.org/apps](https://my.telegram.org/apps) |
| `TELEGRAM_API_HASH` | string | ✅ | Telegram application hash from the same page |
| `GEMINI_API_KEY` | string | ✅ | Google Gemini API key from [aistudio.google.com](https://aistudio.google.com) |
| `STRUCTURED_LOGGING` | `"true"` / `"false"` | No | Enable JSON log format for log shipping tools. Default: `"false"` (plain text) |

### Getting Telegram API credentials

1. Go to [my.telegram.org/apps](https://my.telegram.org/apps)
2. Log in with your phone number
3. Create a new application (any name and platform)
4. Copy `api_id` (integer) and `api_hash` (hex string)

> **Important:** These credentials authenticate your application, not your account.
> You still need to enter your phone number + confirmation code on first run.

---

## Behavioural Constants (`src/settings.py`)

Edit this file to tune timing, limits, and model selection.
All values here are safe to commit — no secrets.

### Timing

| Constant | Default | Unit | Description |
|----------|---------|------|-------------|
| `GRACE_PERIOD_SECONDS` | `7` | seconds | After a message arrives, wait this long before generating a reply. Allows burst messages to accumulate. |
| `MIN_REPLY_INTERVAL_SEC` | `45` | seconds | Minimum time between replies to the same user. Prevents one user from flooding the API. |
| `ACTION_COOLDOWN_SECONDS` | `70` | seconds | Minimum time between Scout actions (like/dislike/navigate). Prevents Telegram rate-limiting. |
| `TYPING_SPEED_CPS` | `8` | chars/sec | Simulated typing speed. At 8 CPS, a 160-character reply takes ~20 seconds to "type". |

**Tuning tips:**
- Increase `GRACE_PERIOD_SECONDS` if users frequently send 2–3 rapid messages
- Decrease `TYPING_SPEED_CPS` to simulate faster typing (more responsive feel)
- Increase `MIN_REPLY_INTERVAL_SEC` on the free Gemini tier to reduce quota pressure

### Reply Delay Curve

The `compute_reply_delay(gap_seconds)` function in `settings.py` returns the delay before
sending a reply, based on how long ago the match last messaged. It produces a smooth curve,
not a hard threshold.

| Gap since last message | Typical delay |
|----------------------|---------------|
| < 2 minutes (active chat) | 15–45 seconds |
| 2–15 minutes | 15–90 seconds |
| 15–60 minutes | 15–600 seconds (mixed fast/medium) |
| 1–24 hours | 5–20 minutes (mostly medium) |
| > 24 hours (cold) | 5–30 minutes, rarely 1–3 hours |

Modify the function directly in `settings.py` if you want different behaviour.

### Context Window

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_HISTORY_LENGTH` | `20` | Maximum number of conversation turns kept. Hard cap applied after token budget trim. |
| `MAX_CONTEXT_TOKENS` | `8000` | Estimated token budget for conversation history. Oldest turns are dropped when exceeded. |
| `CHARS_PER_TOKEN_ESTIMATE` | `3` | Characters per token for estimation. Conservative for mixed Russian/English. |

Token estimation is approximate (3 chars/token). Actual token count may differ.
The budget exists to avoid latency and cost spikes from very long conversations.

### Memory & Retention

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_CONVERSATION_AGE_DAYS` | `90` | Conversations with no activity for this many days are deleted at startup. |

### Heartbeat

| Constant | Default | Description |
|----------|---------|-------------|
| `HEARTBEAT_INTERVAL_HOURS` | `6` | How often to send a status message to Telegram Saved Messages. |

### Other

| Constant | Default | Description |
|----------|---------|-------------|
| `SESSION_NAME` | `"ai_dating_user"` | Base name for the Pyrogram session file. File created: `ai_dating_user.session`. |
| `BOT_USERNAME` | `"leomatchbot"` | Telegram username of the dating bot being operated. Change only if the target app changes. |

---

## Gemini Model Configuration

```python
# src/settings.py
GEMINI_PRIMARY_MODEL = "gemini-1.5-flash-002"   # pinned version
GEMINI_FALLBACK_MODEL = "gemini-1.5-flash-latest"  # used if primary unavailable
```

At startup, `initialize_ai()` tries `GEMINI_PRIMARY_MODEL` first by calling `client.models.get()`.
If that fails (model deprecated, unavailable), it tries `GEMINI_FALLBACK_MODEL`.

**To upgrade the model:**
1. Choose a version from [ai.google.dev/gemini-api/docs/models/gemini](https://ai.google.dev/gemini-api/docs/models/gemini)
2. Change `GEMINI_PRIMARY_MODEL` in `settings.py`
3. Test: `python -c "from ai_client import initialize_ai; from state import BotState; s=BotState(); initialize_ai(s); print(s.active_model_name)"`
4. Deploy

---

## AI Prompt Files (`src/prompts/`)

These are **plain text** files. Edit them freely — no Python knowledge required.
The bot must be restarted after edits.

### `src/prompts/conversation.txt` — The Persona

This file is the most important configuration in the entire system.

**What it controls:**
- Who the AI is (profession, lifestyle, hobbies)
- How they write (lowercase, commas not periods, casual tone, sarcasm)
- Their goal (guide conversation to the match suggesting a meeting)
- How to handle identity checks ("are you a bot?")
- What topics cause disengagement (exes, scam attempts)
- Example facts from their life to reference in conversation

**Sections to customise:**
```
### BASICS
- Profession: ...change this to your persona's job...
- Lifestyle: ...describe their daily routine...

### HOBBIES AND STORIES
- Main hobby: ...
- Your story: ...a memorable anecdote to use for intrigue...

### TASTES
- Music: ...
- Cinema: ...
- Food: ...

### CHARACTER
- Humor style: ...
- What they value: ...
- What annoys them: ...
```

**Rules section — be careful:**
The `COMMUNICATION RULES` section defines formatting constraints the AI must follow.
Do not remove the `|||` ladder separator rule or the `NO PERIODS` rule — the output
validator and ladder-send logic depend on them.

**The goal statement** should always direct the AI toward making the match suggest a meeting,
not the other way around. Changing this fundamentally changes the product behaviour.

### `src/prompts/first_message.txt` — Opener Instructions

Controls how the AI generates the first message to a new match.

**Key rules to keep:**
- **Character limit**: under 300 characters (hard enforced in code)
- **Fallback hooks**: what to say when the profile has no description
- **Style rules**: lowercase, no periods, casual

**To change opener style:** Edit the examples section and the writing style section.
The `{profile_text}` placeholder is replaced by the actual profile description at runtime.

---

## Output Validator Thresholds (`src/output_validator.py`)

These control what AI responses are accepted vs. rejected before delivery.

```python
MAX_RESPONSE_CHARS = 600    # Max response length in characters
MAX_LADDER_PARTS = 4        # Max number of ||| separated message parts
```

| Threshold | Default | Effect if raised | Effect if lowered |
|-----------|---------|-----------------|------------------|
| `MAX_RESPONSE_CHARS` | `600` | Allow longer responses | More responses rejected as too long |
| `MAX_LADDER_PARTS` | `4` | Allow more split messages | Fewer ladder sends allowed |

**Marker lists** — these cause rejection if found in the AI output:

`PROMPT_LEAK_MARKERS` — phrases that indicate the system prompt is leaking into the response:
```python
["dossier", "your task is to", "anti-deanon", "communication rules", ...]
```

`PERSONA_COLLAPSE_MARKERS` — phrases that indicate the AI has broken character:
```python
["i am an ai", "i'm an ai", "i cannot fulfill", "i'm not able to", ...]
```

**Adding markers:** If you find a phrase that indicates persona break in your conversations,
add it to `PERSONA_COLLAPSE_MARKERS`. Both lists are lowercase substring matches.

---

## Input Sanitizer Limits (`src/input_sanitizer.py`)

```python
MAX_USER_MESSAGE_CHARS = 1000   # Max user message length after sanitization
```

User messages over 1000 characters are truncated. A warning is logged.
This prevents a single user from consuming the entire token budget in one message.

**Injection pattern detection** — these patterns trigger a log warning (not a block):
```python
"ignore all previous instructions"
"[SYSTEM]"
"forget everything"
# ... and others
```

To add a new injection pattern, add a regex string to `_INJECTION_PATTERNS` in `input_sanitizer.py`.

---

## Data Files (`data/`)

The `data/` directory is created automatically. All files are JSON.

### `data/conversation_histories.json`

**Format:**
```json
{
  "<telegram_chat_id>": [
    {"role": "model", "parts": ["opener text"], "timestamp": "2026-06-01T10:00:00+00:00"},
    {"role": "user",  "parts": ["user message"], "timestamp": "2026-06-01T10:05:00+00:00"},
    {"role": "model", "parts": ["reply text"],   "timestamp": "2026-06-01T10:07:00+00:00"}
  ]
}
```

**Manual editing:** Safe to do while the bot is stopped. To delete a conversation, remove its key.
To restart a conversation, delete its history (bot will start fresh).

### `data/conversation_memories.json`

**Format:**
```json
{
  "<telegram_chat_id>": "Name: Anna. Works as a nurse. Likes hiking and strong coffee."
}
```

Extracted and updated by Gemini every 4 conversation turns.
**Manual editing:** Safe to edit or delete entries. On next turn with this user,
Gemini will update the memory from scratch.

### `data/whitelist.json`

**Format:**
```json
[123456789, 987654321]
```

User IDs in this list are completely **ignored** by the bot — it will not reply to them.
Use this when you've taken over a conversation manually.

**Hot-reload without restart:**
```bash
# Edit data/whitelist.json, then:
kill -HUP $(pgrep -f "python.*main.py")
```

### `data/stats.json`

**Format:** Array of event objects, newest last, capped at 2000 entries.

```json
[
  {"event": "profile_liked", "timestamp": "...", "has_description": true},
  {"event": "opener_sent",   "timestamp": "...", "length": 187},
  {"event": "api_call",      "timestamp": "...", "type": "conversation",
   "status": "ok", "chat_id": "123456789",
   "prompt_tokens": 450, "response_tokens": 85, "total_tokens": 535},
  {"event": "meeting_signal","timestamp": "...", "chat_id": 123456789, "user_name": "Anna"}
]
```

**Event types:**

| Event | Meaning | Fields |
|-------|---------|--------|
| `profile_liked` | Profile approved by AI | `has_description` |
| `profile_disliked` | Profile rejected | `reason` (no_description / ai_rejected) |
| `opener_sent` | Opening message sent | `length` |
| `conversation_started` | First reply to a new user | `chat_id` |
| `reply_sent` | Reply delivered | `chat_id`, `ladder` (bool) |
| `meeting_signal` | Match suggested meeting | `chat_id`, `user_name` |
| `api_call` | Gemini API call | `type`, `status`, `prompt_tokens`, `response_tokens`, `total_tokens` |
| `api_error` | Gemini API error | `reason` |

**Query with the CLI tool:**
```bash
python scripts/stats_report.py --days 7
python scripts/stats_report.py --event meeting_signal
```

---

## Quick Reference — All Defaults

```python
# Timing
GRACE_PERIOD_SECONDS       = 7
MIN_REPLY_INTERVAL_SEC     = 45
ACTION_COOLDOWN_SECONDS    = 70
TYPING_SPEED_CPS           = 8
HEARTBEAT_INTERVAL_HOURS   = 6

# Context
MAX_HISTORY_LENGTH         = 20
MAX_CONTEXT_TOKENS         = 8000
CHARS_PER_TOKEN_ESTIMATE   = 3
MAX_CONVERSATION_AGE_DAYS  = 90

# Gemini
GEMINI_PRIMARY_MODEL       = "gemini-1.5-flash-002"
GEMINI_FALLBACK_MODEL      = "gemini-1.5-flash-latest"

# Output validation
MAX_RESPONSE_CHARS         = 600
MAX_LADDER_PARTS           = 4

# Input sanitization
MAX_USER_MESSAGE_CHARS     = 1000

# Bot identity
SESSION_NAME               = "ai_dating_user"
BOT_USERNAME               = "leomatchbot"
```
