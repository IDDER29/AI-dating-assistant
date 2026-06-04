# Codebase Map — AI Dating Assistant

_Last updated: 2026-06-04_

---

## Repository Layout

```
AI-dating-assistant/
│
├── .env                          ← secrets (API keys, Telegram credentials)
├── requirements.txt              ← 4 dependencies: pyrogram, tgcrypto, google-generativeai, python-dotenv
├── ai_bot_logs.txt               ← rotating log output (written at runtime)
│
├── data/
│   ├── conversation_histories.json  ← persistent per-user chat histories (keyed by Telegram user ID)
│   └── whitelist.json               ← list of user IDs that bypass AI (operator handles manually)
│
├── src/                          ← all application code lives here
│   ├── main.py                   ← ENTRY POINT — starts asyncio loop, top-level error handling
│   ├── app.py                    ← application bootstrap: validates env, wires handlers, runs startup logic
│   ├── config.py                 ← all constants, env vars, tuning knobs, AI prompts
│   ├── state.py                  ← BotState dataclass — single shared mutable state object
│   ├── ai_client.py              ← Gemini API wrapper: init, cleanup, rate-limit retry, two generation fns
│   ├── leomatch.py               ← Scout brain: handles dating bot messages, likes/dislikes, first messages
│   ├── dialog.py                 ← Interlocutor brain: handles private chats, delay logic, ladder sending
│   ├── storage.py                ← JSON read/write helpers for histories and whitelist
│   ├── logging_setup.py          ← rotating file + console log handler setup
│   └── utils.py                  ← single helper: extract text from message.text or message.caption
│
└── docs/                         ← project documentation (this folder)
```

---

## Module Responsibilities

| Module | Role | Key exports |
|--------|------|-------------|
| `main.py` | Entry point. Runs `asyncio.run(run())`, handles top-level exceptions, saves history on crash/exit. | — |
| `app.py` | Bootstrap. Validates config, creates `Client`, registers handlers, replays last bot message on startup. | `run()`, `get_state()` |
| `config.py` | Single source of all configuration: paths, delays, limits, Telegram/AI credentials, full AI prompts, regex patterns. | All constants |
| `state.py` | `BotState` dataclass holding all shared runtime state: histories, active tasks, AI model, Pyrogram client. | `BotState` |
| `ai_client.py` | Wraps Gemini API. Handles rate-limit retries, response cleanup, and two generation paths. | `initialize_ai()`, `generate_first_message()`, `generate_conversation_response()` |
| `leomatch.py` | Scout brain. Parses dating bot messages, applies profile quality filter, sends like/dislike, triggers first-message generation. | `leomatch_handler()`, `process_leomatch_message()` |
| `dialog.py` | Interlocutor brain. Manages debounce timer, session detection, reply delay, typing simulation, and ladder-send splitting. | `private_chat_handler()`, `process_dialogue_task()` |
| `storage.py` | JSON persistence layer. Loads/saves histories and whitelist. | `load_histories()`, `save_histories()`, `load_whitelist()` |
| `logging_setup.py` | Configures rotating file handler + console handler for the root logger. | `setup_logging()` |
| `utils.py` | Trivial helper — extracts `.text` or `.caption` from Pyrogram message objects. | `get_message_text()` |

---

## Data Flow Summary

```
Telegram MTProto (via Pyrogram)
        │
        ├── Messages from @leomatchbot ──► leomatch_handler()
        │                                       │
        │                          profile card? ├── process_leomatch_task() [background, cooldown]
        │                                        │        └── process_leomatch_message()
        │                          other cmd?    └── process_leomatch_message() [direct]
        │                                                 │
        │                                  "Napishi"? ───► generate_first_message() ──► Gemini API
        │                                  like/dislike? ► send_message(BOT_USERNAME, "💌" / "👎")
        │
        └── Private messages from real users ──► private_chat_handler()
                                                      │
                                              whitelist? → skip
                                              else:
                                                mark read, cancel old task
                                                create process_dialogue_task() [background]
                                                      │
                                                debounce (7s grace period)
                                                compute delay (15s–3h depending on session state)
                                                sleep delay
                                                      │
                                                generate_conversation_response() ──► Gemini API
                                                      │
                                                split on "|||"? → ladder send with typing indicator
                                                else: single send with typing indicator
```

---

## State Object (`BotState`)

All modules share a single `BotState` instance passed by reference.

| Field | Type | Purpose |
|-------|------|---------|
| `last_seen_anket_text` | `str \| None` | Stores the last profile card text while waiting for the "Napishi" prompt |
| `last_action_time` | `datetime` | Tracks cooldown between consecutive like/dislike actions (70s) |
| `start_time` | `datetime` | Bot startup timestamp |
| `conversation_histories` | `Dict[str, list]` | Per-user Gemini chat history, keyed by user ID string |
| `active_dialogue_tasks` | `Dict[int, Task]` | Live asyncio tasks per private chat (enables debounce cancellation) |
| `leomatch_task` | `Task \| None` | Single background task for profile processing (replaced on new profile) |
| `whitelist_ids` | `Set[int]` | User IDs that bypass AI entirely |
| `model` | Gemini model | The initialized `GenerativeModel` instance |
| `app` | Pyrogram `Client` | The active Telegram client session |

---

## Configuration Knobs (all in `config.py`)

| Constant | Value | Effect |
|----------|-------|--------|
| `ACTION_COOLDOWN_SECONDS` | 70 | Min gap between like/dislike actions |
| `MAX_HISTORY_LENGTH` | 20 | Max messages kept per conversation (sliding window) |
| `GRACE_PERIOD_SECONDS` | 7 | Debounce wait before replying (in case user sends multiple messages) |
| `TYPING_SPEED_CPS` | 8 | Characters per second used to calculate simulated typing delay |
| `SESSION_TIMEOUT_MINUTES` | 15 | Inactivity gap that triggers "new session" delay logic |
| `REPLY_DELAY_CONFIG` | — | Probabilistic delay tiers: 60% fast (15–60s), 35% medium (5–15m), 5% long (1–3h) |

---

## External Dependencies

| Library | Purpose |
|---------|---------|
| `pyrogram` | Async Telegram MTProto client — reads/sends messages as a real user account |
| `tgcrypto` | Cryptographic backend required by Pyrogram |
| `google-generativeai` | Google Gemini API SDK |
| `python-dotenv` | Loads `.env` file into environment variables |

---

## Key Files Outside `src/`

| File | Notes |
|------|-------|
| `.env` | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `GEMINI_API_KEY` — never committed |
| `data/conversation_histories.json` | Auto-created; grows over time; survives restarts |
| `data/whitelist.json` | Manually maintained list of user IDs |
| `ai_bot_logs.txt` | Rotating log, max 5 MB × 2 backups |
| `ORCHESTRATOR_SEQUENCE.md` | Mermaid sequence diagram of startup and event flow |
