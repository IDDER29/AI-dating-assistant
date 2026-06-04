# AI Dating Assistant

An autonomous AI-powered Telegram bot that operates a dating app account on your behalf.
It browses profiles on **@leomatchbot** (LeoMatch), sends personalised opening messages to interesting matches,
and holds natural, human-like conversations until the match **suggests a meeting** —
at which point it alerts you instantly and hands control over.

> Built as a social and technical experiment: can an AI convincingly replicate a specific human
> communication style well enough to lead a real conversation to a meeting?

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Features](#features)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Running the Bot](#running-the-bot)
7. [Project Structure](#project-structure)
8. [Understanding the Prompts](#understanding-the-prompts)
9. [Monitoring & Operations](#monitoring--operations)
10. [Troubleshooting](#troubleshooting)
11. [Security](#security)
12. [Further Documentation](#further-documentation)

---

## How It Works

The bot runs two independent pipelines inside a single asyncio process, sharing a common state:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Your Telegram Account                         │
│                                                                      │
│   ┌────────────────────────┐      ┌──────────────────────────────┐  │
│   │    SCOUT PIPELINE      │      │    INTERLOCUTOR PIPELINE     │  │
│   │  (@leomatchbot msgs)   │      │    (private user messages)   │  │
│   │                        │      │                              │  │
│   │  1. Receives profile   │      │  1. Receives user message    │  │
│   │  2. AI quality check   │      │  2. Buffers burst messages   │  │
│   │  3. Like / dislike     │      │  3. Waits natural delay      │  │
│   │  4. Generate opener    │      │  4. AI generates reply       │  │
│   │  5. Store opener text  │      │  5. Detects meeting signal   │  │
│   └────────────────────────┘      │  6. Sends w/ typing sim      │  │
│                                   └──────────────────────────────┘  │
│                                                                      │
│                      ┌────────────────────┐                         │
│                      │    SHARED STATE    │                         │
│                      │ • Conversation     │                         │
│                      │   histories        │                         │
│                      │ • Per-user memory  │                         │
│                      │ • Opener buffer    │                         │
│                      └────────────────────┘                         │
└─────────────────────────────────────────────────────────────────────┘
```

### Scout Pipeline

Watches `@leomatchbot` for new profile cards. For each one:
1. Parses the card text (name, age, city, description) with a regex
2. Sends the description to Gemini AI for quality scoring (YES / NO)
3. Sends a **like** (`💌 / 📹`) or **dislike** (`👎`) back to the bot
4. On mutual match: generates a personalised opening message using the profile description
5. Stores the opener in a buffer so the Interlocutor can inject it as context

### Interlocutor Pipeline

Handles direct private messages from matches:
1. Marks messages as read immediately
2. Accumulates burst messages during a 7-second grace period (captures full thoughts)
3. Calculates a natural, randomised reply delay based on time since last exchange
4. Sends the combined message(s) to Gemini with full conversation history + persona
5. Validates the AI response before delivery (length, persona integrity, prompt-leak detection)
6. Simulates typing speed before sending
7. Detects meeting-suggestion language and alerts you instantly via Saved Messages

---

## Features

| Category | Feature |
|----------|---------|
| **Conversation AI** | Personalised openers based on real profile description |
| **Conversation AI** | Persistent per-user memory — survives the 20-turn context window |
| **Conversation AI** | Opener injected as conversation context — AI never starts amnesiac |
| **Conversation AI** | `system_instruction=` used on every Gemini call — no wasted tokens |
| **Behaviour** | Burst message accumulation — all rapid messages reach the AI |
| **Behaviour** | Smooth, continuous reply delay curve (not a hard session boundary) |
| **Behaviour** | Typing simulation (configurable characters-per-second) |
| **Behaviour** | Per-user rate limiting — one user can't exhaust API quota |
| **Safety** | Atomic JSON writes — zero data loss on crash or SIGKILL |
| **Safety** | Corrupt file backup — corrupt JSON renamed, never silently destroyed |
| **Safety** | Graceful SIGTERM shutdown — all tasks drained, data saved |
| **Safety** | Conversation data auto-pruned after 90 days |
| **Security** | Input sanitization — length limit, control-char strip, injection logging |
| **Security** | Persona collapse detection — AI can't be tricked into admitting it's a bot |
| **Security** | PII-free logging — no message content written to log files |
| **Security** | SIGUSR1 data deletion — per-user data erased on demand (GDPR) |
| **Observability** | Heartbeat to Saved Messages every 6 hours with live stats |
| **Observability** | Instant meeting-signal alert with one-command takeover instructions |
| **Observability** | API token tracking in stats + heartbeat |
| **Observability** | `scripts/stats_report.py` — conversion funnel in your terminal |
| **Reliability** | Gemini model version pinned (`gemini-1.5-flash-002`) with fallback |
| **Reliability** | Token-aware context trimming — never hits the API context limit |
| **Reliability** | FloodWait retry with automatic backoff |
| **Reliability** | SIGHUP whitelist hot-reload — no restart needed to take over |
| **Operations** | systemd service unit with auto-restart and graceful stop |
| **Operations** | Structured JSON logging (opt-in via `STRUCTURED_LOGGING=true`) |
| **Testing** | 81 automated tests — unit + integration — no live APIs required |

---

## Prerequisites

- **Python 3.11+**
- A **Telegram user account** (not a bot account — a real user account you log into)
- Telegram API credentials from [my.telegram.org/apps](https://my.telegram.org/apps)
- A **Google Gemini API key** from [aistudio.google.com](https://aistudio.google.com)
- The `@leomatchbot` app active on your Telegram account

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url> AI-dating-assistant
cd AI-dating-assistant

# 2. Install dependencies
pip install -r requirements.txt
```

**Dependencies installed:**

| Package | Purpose |
|---------|---------|
| `google-genai` | Google Gemini AI SDK (current, maintained) |
| `pyrofork` | Telegram MTProto client (maintained Pyrogram fork) |
| `tgcrypto` | Fast cryptography for Telegram |
| `python-dotenv` | Loads `.env` file at startup |
| `pytest` + `pytest-asyncio` | Test framework |

---

## Configuration

### Step 1 — Create `.env`

Create a file named `.env` in the project root:

```ini
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
GEMINI_API_KEY=AIzaSy...
```

| Variable | Where to get it | Required |
|----------|----------------|----------|
| `TELEGRAM_API_ID` | [my.telegram.org/apps](https://my.telegram.org/apps) → Create App | ✅ |
| `TELEGRAM_API_HASH` | Same page | ✅ |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → Get API key | ✅ |

Set secure permissions immediately:
```bash
chmod 600 .env
```

**Optional env variables:**

```ini
STRUCTURED_LOGGING=true   # enable JSON log format (default: false)
```

### Step 2 — Personalise the AI Persona

Edit **`src/prompts/conversation.txt`** — this is the most important file.
It defines the character the AI plays: their job, personality, hobbies, communication style,
and their goal (guide the conversation until the match suggests a meeting).

Edit **`src/prompts/first_message.txt`** — instructions for generating opening messages.

> **No Python required.** Both files are plain text. Edit freely, restart the bot.

### Step 3 — (Optional) Tune Timing & Limits

Edit `src/settings.py`:

```python
GRACE_PERIOD_SECONDS = 7        # wait for burst messages before generating reply
MIN_REPLY_INTERVAL_SEC = 45     # minimum gap between replies to the same user
MAX_HISTORY_LENGTH = 20         # max conversation turns kept in context
MAX_CONTEXT_TOKENS = 8000       # estimated token budget for conversation history
MAX_CONVERSATION_AGE_DAYS = 90  # auto-prune conversations older than this
HEARTBEAT_INTERVAL_HOURS = 6    # how often to ping Saved Messages with status
TYPING_SPEED_CPS = 8            # characters per second for typing simulation
ACTION_COOLDOWN_SECONDS = 70    # minimum gap between Scout actions (like/dislike)
GEMINI_PRIMARY_MODEL = "gemini-1.5-flash-002"  # pinned model version
```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete reference.

---

## Running the Bot

### First Run — Required Once (Interactive Login)

Pyrogram needs to authenticate your Telegram account the first time.
This is interactive and cannot run headlessly:

```bash
python src/main.py
```

Follow the prompts:
```
Enter your phone number: +1234567890
Enter the confirmation code: 12345
Enter your 2FA password (if enabled): ****
```

After successful login:
- `ai_dating_user.session` is created — **keep this file safe, it's your account access**
- The bot logs `[SYSTEM] Startup complete` and begins operating
- Press `Ctrl+C` to stop

Set secure permissions:
```bash
chmod 600 ai_dating_user.session
```

### Manual / Development Run

```bash
python src/main.py
```

Logs appear in the console and in `ai_bot_logs.txt`.

### With Structured JSON Logging

```bash
STRUCTURED_LOGGING=true python src/main.py
```

Each log line is a JSON object — filter by chat:
```bash
grep '"chat_id": 123456789' ai_bot_logs.txt | python3 -m json.tool
```

### Production Run — systemd

```bash
# Install the service (edit paths first)
sudo cp deploy/ai-dating-assistant.service /etc/systemd/system/
sudo nano /etc/systemd/system/ai-dating-assistant.service  # set User= and WorkingDirectory=

sudo systemctl daemon-reload
sudo systemctl enable ai-dating-assistant   # start on boot
sudo systemctl start ai-dating-assistant

# Check status
sudo systemctl status ai-dating-assistant
sudo journalctl -u ai-dating-assistant -f   # follow live logs
```

The service:
- **Auto-restarts** on crash after 30 seconds (up to 5 times in 10 minutes)
- **Gracefully shuts down** on `systemctl stop` — drains active tasks, saves all data
- **Logs to systemd journal** (plus the bot's own rotating `ai_bot_logs.txt`)

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full guide.

### Run Tests

```bash
python -m pytest tests/ -v    # verbose — see each test name
python -m pytest tests/ -q    # quiet — pass/fail count only
```

---

## Project Structure

```
AI-dating-assistant/
│
├── src/                              Python source (19 modules)
│   │
│   ├── main.py                   ← Entry point: signal handlers, process lifecycle
│   ├── app.py                    ← Coordinator: wires modules, registers handlers
│   │
│   ├── leomatch.py               ← Scout: profile card handling, like/dislike, openers
│   ├── dialog.py                 ← Interlocutor: reply cycle, typing sim, rate limit
│   │
│   ├── ai_client.py              ← All Gemini AI calls (generate, classify, memory)
│   ├── output_validator.py       ← Gates AI responses before delivery to users
│   ├── input_sanitizer.py        ← Cleans user messages before sending to AI
│   ├── meeting_detector.py       ← Detects meeting language in Russian + English
│   │
│   ├── storage.py                ← Atomic JSON persistence (histories/memories/whitelist)
│   ├── stats.py                  ← Event recorder → data/stats.json
│   ├── state.py                  ← BotState dataclass — shared mutable state
│   │
│   ├── telegram_adapter.py       ← Pyrogram abstraction (swap library without touching logic)
│   ├── operator_notify.py        ← Sends alerts to Telegram Saved Messages
│   │
│   ├── settings.py               ← All constants (safe to commit)
│   ├── credentials.py            ← Env var loader for API keys (gitignored)
│   ├── config.py                 ← Compatibility shim → re-exports settings+credentials
│   ├── logging_setup.py          ← Plain-text or structured JSON logging + BotLogger
│   └── utils.py                  ← get_message_text(), safe_send_message()
│
├── src/prompts/
│   ├── conversation.txt          ← EDIT THIS: AI persona dossier
│   └── first_message.txt         ← EDIT THIS: Opener generation instructions
│
├── data/                         Runtime data (auto-created, gitignored)
│   ├── conversation_histories.json
│   ├── conversation_memories.json
│   ├── whitelist.json
│   └── stats.json
│
├── tests/                        81 automated tests
│   ├── conftest.py               ← Stubs Telegram+Gemini (no live APIs needed)
│   ├── test_ai_client.py         ← Unit tests for text cleanup
│   ├── test_input_sanitizer.py   ← Unit tests for input sanitization
│   ├── test_output_validator.py  ← Unit tests for response validation
│   ├── test_meeting_detector.py  ← Unit tests for meeting signal detection
│   ├── test_settings.py          ← Unit tests for ANKET_PATTERN regex
│   ├── test_state.py             ← Unit tests for BotState dataclass
│   ├── test_utils.py             ← Unit tests for utility functions
│   ├── test_integration_ai.py    ← Integration: full AI pipeline (mock Gemini)
│   ├── test_integration_leomatch.py  ← Integration: Scout pipeline
│   └── test_integration_storage.py   ← Integration: real filesystem roundtrips
│
├── scripts/
│   └── stats_report.py           ← Analytics CLI (no extra dependencies)
│
├── deploy/
│   └── ai-dating-assistant.service   ← systemd unit template
│
├── docs/
│   ├── ARCHITECTURE.md           ← System design, data flows, algorithms
│   ├── CONFIGURATION.md          ← Every setting with defaults and examples
│   ├── DEPLOYMENT.md             ← Full server setup + operations reference
│   ├── SECURITY.md               ← Credential hardening, privacy guide
│   └── plans/                    ← 12 implementation plans (all complete)
│
├── .env                          ← YOUR CREDENTIALS (create this, chmod 600)
├── .gitignore                    ← Excludes .env, session, data/, credentials.py
├── requirements.txt              ← Python dependencies
└── pytest.ini                    ← Test config (asyncio_mode = auto)
```

---

## Understanding the Prompts

### `src/prompts/conversation.txt` — The Persona

This is the character the AI plays in every private conversation. It contains:

- **Who they are**: job, lifestyle, daily schedule
- **What they like**: music, food, films, travel
- **How they communicate**: lowercase only, no periods, short casual messages, sarcasm
- **Their goal**: guide the conversation until the match suggests a meeting — don't suggest it first
- **ANTI-DEANON PROTOCOL**: deflect "are you a bot?" with sarcasm and counter-questions
- **Stop factors**: disengage if the match talks about exes or asks for money

The persona is injected via `system_instruction=` on **every single Gemini API call** — it cannot be "forgotten" mid-session.

### `src/prompts/first_message.txt` — The Opener

Instructions for generating the first message to a new match. Key rules:
- Under 300 characters (strict)
- If the profile description is short/meaningless, use one of three general hooks
- If there's something interesting in the profile, make a specific witty observation
- No periods at the end, casual slang, can use `)` as a smirk

**To change the opener style**, edit this file and restart. No code changes needed.

### Memory System

The AI builds a **persistent memory** for each user. After every 4 conversation turns,
it calls Gemini to extract key facts (name, job, hobbies, stated preferences) and stores
them in `data/conversation_memories.json`. These facts are injected into the context of
every subsequent API call for that user — so the AI never forgets what the match said,
even after 100 turns.

---

## Monitoring & Operations

### Automatic Heartbeat (every 6 hours)

The bot sends this to your Telegram **Saved Messages** automatically:
```
🤖 ✅ Bot alive
Uptime: 12h 34m
Model: gemini-1.5-flash-002
Active conversations: 3
Total conversations: 47
Meetings detected (session): 2
API calls (last 6h): 89 (0 failed, ~12,450 tokens)
```

### Meeting Alert (instant, when it happens)

```
🤖 🎯 MEETING SUGGESTED

User: Anna (ID: 123456789)
Message: "Давай встретимся в кофейне на выходных?"

➡️ Add ID 123456789 to whitelist.json, then:
   kill -HUP <pid>   (to take over without restart)
```

### Take Over a Conversation

```bash
# 1. Edit data/whitelist.json — add the user's chat ID
#    (or just use echo if it's currently an empty list [])

# 2. Hot-reload without restart:
kill -HUP $(pgrep -f "python.*main.py")
# or with systemd:
kill -HUP $(systemctl show -p MainPID --value ai-dating-assistant)

# The bot now ignores that user — reply manually in Telegram
```

### Stats Report

```bash
python scripts/stats_report.py              # last 24 hours
python scripts/stats_report.py --days 7    # last 7 days
python scripts/stats_report.py --all       # all time
python scripts/stats_report.py --event meeting_signal  # just meetings
```

### Delete a User's Data

```bash
echo "CHAT_ID_HERE" > data/delete_requests.txt
kill -USR1 $(pgrep -f "python.*main.py")
# Confirms in logs: [SYSTEM] Deleted data for user XXXXXX: {conversation_turns: N, memory: True}
```

---

## Troubleshooting

### Bot starts but doesn't like any profiles

Check `ai_bot_logs.txt` for `[AI] Gemini model validated` — if missing, the API key may be invalid.
```bash
grep "Gemini model" ai_bot_logs.txt
```

### "Authorization error" — session expired

```bash
rm ai_dating_user.session
python src/main.py   # re-authenticate interactively
chmod 600 ai_dating_user.session
```

### Persona feels wrong (formal language, admits being AI)

- Open `src/prompts/conversation.txt` and verify the dossier is intact
- Check `output_validator.py` — `PERSONA_COLLAPSE_MARKERS` may be too aggressive for certain phrases

### Conversations not saving

```bash
ls -la data/
# Check for .corrupt.*.json files — a previous save failed
# The latest valid backup is the .corrupt file
```

### Very slow replies / always hitting rate limits

- Lower `MAX_HISTORY_LENGTH` in `settings.py` to reduce tokens per call
- Check your Gemini API tier (free tier: 15 RPM)

### "Module not found" on startup

```bash
pip install -r requirements.txt
```

### Bot not responding to `@leomatchbot` profile cards

The regex `ANKET_PATTERN` in `settings.py` expects `"Name, Age, City — Description"` format.
If `@leomatchbot` changed their format, update the regex accordingly.

---

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the complete guide. Quick essentials:

```bash
chmod 600 .env
chmod 600 ai_dating_user.session
```

**What the bot logs:** Only metadata — message lengths, event counts, user IDs. Never message content.

**What the bot stores:** Conversation histories (`data/`) are plaintext. Keep `data/` out of any web-accessible directories.

**The session file** (`ai_dating_user.session`) is equivalent to your Telegram password. Treat it accordingly.

---

## Further Documentation

| Document | What's inside |
|----------|--------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, module map, data flows, key algorithms explained |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every setting — default, valid range, what it affects |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Full server setup, systemd, operations reference table |
| [docs/SECURITY.md](docs/SECURITY.md) | Credential hardening, session rotation, data deletion, logging guarantees |
| [docs/plans/README.md](docs/plans/README.md) | All 12 implementation plans — what was built and why |
