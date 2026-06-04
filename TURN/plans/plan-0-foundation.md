# Plan 0 — Foundation

**Builds:** Empty repo → working skeleton with /start, DB tables, LLM abstraction  
**Depends on:** Nothing — this is the starting point  
**Time:** ~1 day

---

## State Before
Empty repo. No files except maybe a `.gitignore`.

## State After
- Bot responds to `/start`
- All DB tables exist
- `LLMClient` instantiates with OpenAI, `vision()` and `complete()` callable
- `config.py` validates all env vars on startup and fails loudly if any are missing
- Deployment pipeline works (Railway/Render deploys successfully)

---

## Epic 1 — Project Structure

Create this exact folder structure. Do not deviate.

```
turn_mvp/
├── main.py
├── config.py
├── stripe_client.py
├── requirements.txt
├── .env                  ← never commit
├── .gitignore
├── core/
│   ├── __init__.py
│   ├── conversation.py
│   ├── db.py
│   ├── llm_client.py
│   ├── prompts.py
│   ├── scheduler.py
│   └── utils.py
└── channels/
    ├── __init__.py
    ├── telegram_bot.py
    └── web_api.py        ← placeholder only, not implemented yet
```

### Task 0.1 — `requirements.txt`

```
python-telegram-bot[webhooks]==20.7
openai==1.14.0
anthropic==0.18.0
google-generativeai==0.4.0
stripe==8.5.0
apscheduler==3.10.4
SQLAlchemy==2.0.28
Pillow==10.2.0
python-dotenv==1.0.1
fastapi==0.110.0
uvicorn[standard]==0.27.1
httpx==0.27.0
```

**Verify:** `pip install -r requirements.txt` completes with no errors.

---

### Task 0.2 — `.gitignore`

```
.env
turn.db
__pycache__/
*.pyc
.DS_Store
```

---

### Task 0.3 — `config.py`

All env vars loaded here. Everything else imports from config. If a required var is missing, the process exits immediately with a clear message — not a cryptic AttributeError later.

```python
import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val

# Telegram
TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # optional in dev (polling mode)

# LLM providers — at least one key must exist
LLM_PROVIDER        = os.getenv("LLM_PROVIDER", "openai")
LLM_VISION_PROVIDER = os.getenv("LLM_VISION_PROVIDER", LLM_PROVIDER)
LLM_SCRIPT_PROVIDER = os.getenv("LLM_SCRIPT_PROVIDER", LLM_PROVIDER)
LLM_REGEN_PROVIDER  = os.getenv("LLM_REGEN_PROVIDER",  LLM_PROVIDER)

OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY")
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY")

# Validate at least one LLM key exists
_all_llm_keys = [OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, DEEPSEEK_API_KEY]
if not any(_all_llm_keys):
    raise RuntimeError("At least one LLM API key required (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, or DEEPSEEK_API_KEY)")

# Stripe
STRIPE_SECRET_KEY      = _require("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET  = _require("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_CENTS     = int(os.getenv("STRIPE_PRICE_CENTS", "500"))  # $5.00

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "turn.db")
DATABASE_URL  = f"sqlite:///{DATABASE_PATH}"

# App
PORT = int(os.getenv("PORT", "8080"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
```

**Verify:** `python -c "import config"` with valid `.env` exits cleanly. With a missing var, it prints the var name and exits.

---

## Epic 2 — Database

### Task 0.4 — `core/db.py`

All SQL lives here. Nothing else touches the DB directly.

```python
import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager
import config

@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                premium_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'analyzing',
                ghost_risk INTEGER,
                signals TEXT,
                extracted_text TEXT,
                vertical TEXT,
                goal TEXT,
                met_before INTEGER,
                investment_score INTEGER,
                soft_script TEXT,
                firm_script TEXT,
                ultimatum_script TEXT,
                chosen_script_type TEXT,
                reminder_set INTEGER DEFAULT 0,
                reminder_time TIMESTAMP,
                outcome TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                conversation_id INTEGER REFERENCES conversations(id),
                stripe_session_id TEXT UNIQUE NOT NULL,
                amount_cents INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS script_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                rejected_script_type TEXT NOT NULL,
                rejection_reason TEXT NOT NULL,
                user_comment TEXT,
                regenerated_script TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ml_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                ghost_risk_predicted INTEGER,
                ghost_risk_actual INTEGER,
                vertical TEXT,
                script_chosen TEXT,
                outcome TEXT,
                labeled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_user_status ON conversations(user_id, status);
        """)

# --- User functions ---

def get_or_create_user(telegram_id: int, username: str = None) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username)
        )
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return dict(row)

def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return dict(row) if row else None

# --- Conversation functions ---

def get_active_conversation(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE user_id=? AND status != 'closed' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None

def create_conversation(user_id: int) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (user_id, status) VALUES (?, 'analyzing')",
            (user_id,)
        )
        return cursor.lastrowid

def update_conversation(conv_id: int, **kwargs) -> None:
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [conv_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE conversations SET {fields} WHERE id=?", values)

def get_conversation(conv_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
        return dict(row) if row else None

def close_conversation(conv_id: int, outcome: str = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET status='closed', outcome=?, closed_at=CURRENT_TIMESTAMP WHERE id=?",
            (outcome, conv_id)
        )

# --- Payment functions ---

def record_payment(user_id: int, conv_id: int, stripe_session_id: str, amount_cents: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO payments (user_id, conversation_id, stripe_session_id, amount_cents, status) VALUES (?,?,?,?,'pending')",
            (user_id, conv_id, stripe_session_id, amount_cents)
        )

def complete_payment(stripe_session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE stripe_session_id=? AND status='completed'", (stripe_session_id,)).fetchone()
        if row:
            return None  # already processed — idempotency guard
        conn.execute(
            "UPDATE payments SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE stripe_session_id=?",
            (stripe_session_id,)
        )
        row = conn.execute("SELECT * FROM payments WHERE stripe_session_id=?", (stripe_session_id,)).fetchone()
        return dict(row) if row else None

def is_ultimatum_unlocked(conv_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM payments WHERE conversation_id=? AND status='completed'",
            (conv_id,)
        ).fetchone()
        return row is not None

# --- Rejection functions ---

def log_rejection(conv_id: int, script_type: str, reason: str, regen: str = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO script_rejections (conversation_id, rejected_script_type, rejection_reason, regenerated_script) VALUES (?,?,?,?)",
            (conv_id, script_type, reason, regen)
        )

def get_rejection_count(conv_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM script_rejections WHERE conversation_id=?", (conv_id,)).fetchone()
        return row['c']

# --- ML labels ---

def log_ml_label(conv_id: int) -> None:
    conv = get_conversation(conv_id)
    if not conv:
        return
    ghost_actual = 1 if conv['outcome'] in ('ghosted', 'gave_up') else 0
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO ml_labels (conversation_id, ghost_risk_predicted, ghost_risk_actual, vertical, script_chosen, outcome) VALUES (?,?,?,?,?,?)",
            (conv_id, conv['ghost_risk'], ghost_actual, conv['vertical'], conv['chosen_script_type'], conv['outcome'])
        )

# --- Delete user data (GDPR) ---

def delete_user_data(telegram_id: int) -> None:
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        return
    uid = user['id']
    with get_conn() as conn:
        conn.execute("DELETE FROM ml_labels WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", (uid,))
        conn.execute("DELETE FROM script_rejections WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", (uid,))
        conn.execute("DELETE FROM payments WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM conversations WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
```

**Verify:** `python -c "from core.db import init_db; init_db(); print('DB OK')"` prints `DB OK` and creates `turn.db`.

---

## Epic 3 — LLM Abstraction

### Task 0.5 — `core/llm_client.py`

The interface. OpenAI is the only implementation now. Claude, Gemini, DeepSeek added in Plan 9.

```python
import base64
import json
import asyncio
import config

class LLMClient:
    def __init__(self, provider: str = None):
        self.provider = provider or config.LLM_PROVIDER

    async def vision(self, image_base64: str, system_prompt: str) -> dict:
        if self.provider == "openai":
            return await self._openai_vision(image_base64, system_prompt)
        raise NotImplementedError(f"Vision not supported for provider: {self.provider}")

    async def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        if self.provider == "openai":
            return await self._openai_complete(system, user, json_mode)
        raise NotImplementedError(f"Complete not supported for provider: {self.provider}")

    # --- OpenAI ---

    async def _openai_vision(self, image_base64: str, system_prompt: str) -> dict:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                    "detail": "low"
                }}]}
            ],
            max_tokens=600
        )
        return json.loads(resp.choices[0].message.content)

    async def _openai_complete(self, system: str, user: str, json_mode: bool = False) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            max_tokens=500,
            **kwargs
        )
        return resp.choices[0].message.content


# Module-level singletons — use these everywhere
vision_client = LLMClient(provider=config.LLM_VISION_PROVIDER)
script_client  = LLMClient(provider=config.LLM_SCRIPT_PROVIDER)
regen_client   = LLMClient(provider=config.LLM_REGEN_PROVIDER)
```

**Verify:** With a valid OpenAI key: `python -c "import asyncio; from core.llm_client import script_client; print(asyncio.run(script_client.complete('Say hello', 'hi')))"` prints something.

---

## Epic 4 — Bot Skeleton

### Task 0.6 — `channels/telegram_bot.py`

```python
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import config
from core.db import init_db

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.db import get_or_create_user
    get_or_create_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text(
        "👋 I'm TURN.\n\n"
        "Send me a screenshot of any conversation you're unsure about — "
        "dating, friendship, or work.\n\n"
        "I'll tell you the ghost risk and give you 3 scripts to move it forward.\n\n"
        "Send your screenshot to begin."
    )

def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    return app
```

### Task 0.7 — `channels/web_api.py` (placeholder)

```python
# Web API channel — NOT implemented yet.
# Will be implemented in Plan 8.
#
# Contract:
#   POST /api/analyze      → ghost risk + signals
#   POST /api/questions    → next question
#   POST /api/answer       → store answer, check if scripts ready
#   GET  /api/scripts/{id} → get scripts
#   POST /api/unlock       → create Stripe checkout
#   POST /api/outcome      → record outcome
#
# All routes will call core/conversation.py — same logic as Telegram bot.
```

### Task 0.8 — `core/conversation.py` (skeleton only)

```python
# ConversationOrchestrator — implemented progressively across Plans 1-6.
# This file is the channel-agnostic brain of TURN.
# Telegram bot and web API both call methods here.

class ConversationOrchestrator:
    pass  # methods added in each subsequent plan
```

### Task 0.9 — `main.py`

```python
import logging
import config
from core.db import init_db
from core.scheduler import init_scheduler
from channels.telegram_bot import build_application

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG if config.DEBUG else logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    init_db()
    init_scheduler()
    app = build_application()

    if config.WEBHOOK_URL:
        logger.info(f"Starting in webhook mode: {config.WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            webhook_url=f"{config.WEBHOOK_URL}/webhook",
            allowed_updates=["message", "callback_query"]
        )
    else:
        logger.info("Starting in polling mode (dev)")
        app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
```

### Task 0.10 — `core/scheduler.py` (skeleton)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import config

_scheduler: AsyncIOScheduler = None

def init_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler(
        jobstores={'default': SQLAlchemyJobStore(url=config.DATABASE_URL)},
        job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 3600}
    )
    _scheduler.start()

def get_scheduler() -> AsyncIOScheduler:
    return _scheduler
```

### Task 0.11 — Empty `__init__.py` files

Create empty `core/__init__.py` and `channels/__init__.py`.

---

## Acceptance Criteria — Plan 0 Complete When:

- [ ] `python main.py` starts without errors in polling mode
- [ ] Sending `/start` to the bot receives the welcome message
- [ ] `turn.db` is created with all 5 tables
- [ ] `python -c "from core.llm_client import script_client; print(script_client.provider)"` prints `openai`
- [ ] `python -c "import config"` with a missing env var prints the var name and exits

---

## .env Template

Copy this, fill in real values:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
DATABASE_PATH=turn.db
DEBUG=true
# WEBHOOK_URL=  ← leave empty for local polling mode
```
