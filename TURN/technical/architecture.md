# System Architecture

## Overview

TURN MVP is a single Python process. No microservices, no message queues, no external workers. One Telegram bot handler, one SQLite database, one in-process scheduler. This is deliberate — see `../decisions/ADR-002-sqlite-not-postgres.md`.

**Two architectural decisions are baked in from day one even though their full value is only realized later:**

1. **Core/channels separation** — business logic lives in `core/`, delivery channels (Telegram, future web API) live in `channels/`. The Telegram bot and a future website call the same core functions. See `../decisions/ADR-006-core-channels-separation.md`.

2. **LLM abstraction** — all AI calls go through a single `LLMClient` interface. Swapping OpenAI for Claude or Gemini is a one-line config change. See `../decisions/ADR-007-llm-abstraction.md`.

```
turn_mvp/
├── main.py                    # Entry point — starts bot + API server
├── config.py                  # Env vars, constants, LLM provider selection
│
├── core/                      # Business logic — channel-agnostic
│   ├── conversation.py        # ConversationOrchestrator — the entire TURN flow
│   ├── db.py                  # SQLite CRUD
│   ├── llm_client.py          # LLM abstraction interface + provider implementations
│   ├── prompts.py             # All system prompts (canonical)
│   ├── scheduler.py           # APScheduler setup + reminder logic
│   └── utils.py               # Image compression, text sanitization
│
├── channels/
│   ├── telegram_bot.py        # Telegram handlers — calls core/conversation.py
│   └── web_api.py             # FastAPI routes — calls same core/conversation.py (future)
│
├── stripe_client.py           # Stripe — shared by both channels
├── requirements.txt
├── .env                       # Never committed
└── turn.db                    # SQLite file, auto-created on first run
```

---

## Component Responsibilities

### `core/conversation.py` — The Heart
- `ConversationOrchestrator` class with all business logic
- Methods: `analyze(image_or_text)`, `process_answer(conv_id, key, value)`, `generate_scripts(conv_id)`, `handle_rejection(conv_id, reason)`, `record_outcome(conv_id, outcome)`
- No Telegram imports, no HTTP imports — pure logic
- Both `channels/telegram_bot.py` and `channels/web_api.py` call these methods

### `core/llm_client.py` — LLM Abstraction
- Single `LLMClient` class, provider selected from `config.LLM_PROVIDER`
- Two methods: `vision(image_base64, prompt)` → dict and `complete(system, user)` → str
- Implementations: OpenAI, Anthropic (Claude), Google (Gemini), DeepSeek, MiniMax
- Different providers can be used for different tasks (e.g. Gemini for vision, Claude for scripts)
- See `../decisions/ADR-007-llm-abstraction.md` for provider comparison

### `channels/telegram_bot.py`
- Registers all Telegram handlers
- Routes incoming messages/callbacks to correct handler based on conversation `status` from DB
- Never contains business logic — only routing and Telegram-specific formatting
- Key pattern: always read `status` from DB at the start of every handler, never assume state from in-memory context

### `channels/web_api.py` — Future Web Channel
- FastAPI routes exposing the same `ConversationOrchestrator`
- Not built at MVP — file is a placeholder that documents the intended API contract
- See REST API Design section below

### `db.py`
- Single interface to SQLite
- All SQL lives here, nowhere else
- Exposes typed functions: `get_user(telegram_id)`, `create_conversation(user_id, ghost_risk, signals)`, `update_outcome(conv_id, outcome)`, etc.
- Never returns raw rows — always returns dataclasses or dicts

### `gpt_client.py`
- Two main functions: `analyze_screenshot(image_base64)` → `VisionResult` and `generate_scripts(conv_text, answers, ghost_risk)` → `Scripts`
- Third function: `regenerate_script(previous_script, rejection_reason)` → `str`
- All retry logic lives here (retry once on timeout, raise after second failure)
- All JSON parsing lives here (validate GPT output before returning)

### `prompts.py`
- **The canonical source of truth for all AI behavior**
- Every system prompt stored as a named constant
- Prompt changes are tracked in git history — this file is the record of how TURN's AI evolved
- See `../technical/ai-design.md` for the prompts themselves and their rationale

### `scheduler.py`
- APScheduler with SQLAlchemy job store backed by the same SQLite DB
- Jobs survive bot restarts (critical — see `../decisions/ADR-002-sqlite-not-postgres.md`)
- One job type: `fire_reminder(conv_id)` — sends the outcome question
- Background thread, polls every 60 seconds

### `stripe_client.py`
- `create_checkout_session(user_id, conv_id)` → URL
- `handle_webhook(payload, signature)` → updates user premium status
- Webhook signature verification is mandatory (see `../build/known-risks.md`)

---

## Data Flow (One Complete Conversation)

```
1. User sends screenshot
   main.py:handle_photo()
     → utils.compress_image()
     → gpt_client.analyze_screenshot() [OpenAI Vision API]
     → db.create_conversation(ghost_risk, signals, extracted_text)
     → db.set_status(conv_id, 'questioning')
     → main.py sends ghost risk message + first question

2. User answers questions (2-3 rounds)
   main.py:handle_callback()
     → db.store_answer(conv_id, question_key, answer)
     → determine next question or proceed
     → if all answered: db.set_status(conv_id, 'generating_scripts')
     → gpt_client.generate_scripts(extracted_text, answers, ghost_risk)
     → db.store_scripts(conv_id, soft, firm, ultimatum)
     → db.set_status(conv_id, 'awaiting_choice')
     → main.py sends script buttons

3a. User selects free script (soft/firm)
    main.py:handle_callback('script_soft' or 'script_firm')
      → db.update_chosen_script(conv_id, script_type)
      → main.py sends script text + reminder offer
      → if reminder: scheduler.add_job(fire_reminder, conv_id, hours=48)
      → db.set_reminder(conv_id, True, reminder_time)
      → db.set_status(conv_id, 'reminder_set')

3b. User selects ultimatum (premium)
    main.py:handle_callback('script_ultimatum')
      → db.get_user_premium(user_id) → if not premium:
      → stripe_client.create_checkout_session(user_id, conv_id)
      → main.py sends payment link
      [payment completes in browser]
      → stripe_client.handle_webhook() → db.set_premium(user_id)
      → db.update_chosen_script(conv_id, 'ultimatum')
      → scheduler.add_job(fire_reminder, conv_id, hours=48)
      → main.py sends ultimatum script

3c. User rejects script
    main.py:handle_callback('script_reject')
      → main.py asks rejection reason
      → db.log_rejection(conv_id, reason)
      → gpt_client.regenerate_script(previous, reason)
      → main.py sends new script
      → if second rejection: offer reminder without script

4. Reminder fires (48h later)
   scheduler → main.py:send_reminder(conv_id)
     → main.py sends outcome question

5. Outcome collected
   main.py:handle_callback('outcome_*')
     → db.update_outcome(conv_id, outcome)
     → db.set_status(conv_id, 'closed')
     → db.log_ml_label(conv_id, ghost_risk, outcome)
     → main.py sends closing message
```

---

## REST API Design (Future Web Channel)

The API is not built at MVP. The contract is defined here so the core logic is designed to support it from day one. When a website is ready, `channels/web_api.py` implements these routes using FastAPI — no changes to `core/` needed.

```
POST /api/analyze
  Body:    { "text": "...", "image": "base64..." }  # one of text or image
  Returns: { "conversation_id": "uuid", "ghost_risk": 74, "signals": [...], "vertical": "dating" }

POST /api/questions
  Body:    { "conversation_id": "uuid" }
  Returns: { "question": "What's your goal?", "options": [...], "step": "ask_goal" }

POST /api/answer
  Body:    { "conversation_id": "uuid", "key": "goal", "value": "meetup" }
  Returns: { "next_question": {...} | null, "scripts_ready": true | false }

GET  /api/scripts/{conversation_id}
  Returns: { "soft": "...", "firm": "...", "ultimatum_locked": true }

POST /api/unlock
  Body:    { "conversation_id": "uuid" }
  Returns: { "payment_url": "https://checkout.stripe.com/..." }

POST /api/outcome
  Body:    { "conversation_id": "uuid", "outcome": "met" | "ghosted" | "still_texting" | "gave_up" }
  Returns: { "message": "closing text" }
```

**Why this shape:** Stateless from the client's perspective. Each call is independent. The server holds state in the DB (conversation `status`). A website, mobile app, or any other client can drive the flow by following the API sequence.

**Authentication (future):** API key per client (website gets one key, Telegram bot gets another). Not needed at MVP — both channels are internal.

---

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Only reasonable choice for this stack |
| Bot framework | python-telegram-bot v20+ | Async-native, large community, well-documented |
| Web framework | FastAPI (future) | Async-native, auto-generates OpenAPI docs, pairs well with python-telegram-bot |
| Database | SQLite + SQLAlchemy | Zero ops, sufficient for MVP scale, APScheduler integrates natively |
| Scheduler | APScheduler with SQLite job store | Jobs survive restarts; in-process = no extra service |
| LLM (vision) | Configurable via `LLM_PROVIDER` — default GPT-4o, alt: Gemini 1.5 Pro | See ADR-007 |
| LLM (scripts) | Configurable — default Claude Sonnet, alt: GPT-4o, DeepSeek | See ADR-007 |
| LLM (regen) | Configurable — default DeepSeek or GPT-3.5 (low-stakes, cost-sensitive) | See ADR-007 |
| Payments | Stripe Checkout | One-click flow, webhook-based, battle-tested |
| Deployment | Railway or Render | Zero ops, webhook mode, auto-restart on crash |
| PDF (deferred) | fpdf2 | Lightweight; not in MVP |

---

## Deployment Architecture

Single process, webhook mode (not polling):

```
Railway/Render
  └── Python process
        ├── channels/telegram_bot.py  (webhook on /webhook)
        ├── channels/web_api.py       (FastAPI on /api/* — future)
        ├── stripe_client.py          (webhook on /stripe-webhook)
        ├── APScheduler background thread
        └── SQLite file (persistent volume)
```

Environment variables (all required at start, bot fails loudly if missing):
- `TELEGRAM_BOT_TOKEN`
- `LLM_PROVIDER` (default: `openai` — options: `openai`, `anthropic`, `gemini`, `deepseek`, `minimax`)
- `LLM_VISION_PROVIDER` (can differ from LLM_PROVIDER — e.g. `gemini` for vision, `anthropic` for scripts)
- `OPENAI_API_KEY` (if using OpenAI)
- `ANTHROPIC_API_KEY` (if using Claude)
- `GOOGLE_API_KEY` (if using Gemini)
- `DEEPSEEK_API_KEY` (if using DeepSeek)
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `WEBHOOK_URL`
- `DATABASE_PATH` (default: `turn.db`)

---

## Scale Limits of This Architecture

SQLite handles ~50-100 concurrent writes before contention becomes noticeable. APScheduler in-process has no hard limit but becomes unreliable above ~1000 simultaneous scheduled jobs. Neither limit is relevant until TURN has 500+ MAU. At that point, migrate to PostgreSQL + Redis as described in `../vision/product-evolution.md` Phase 1.

Do not pre-optimize for scale that doesn't exist yet.
