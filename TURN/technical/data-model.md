# Data Model

## Complete SQLite Schema

```sql
-- Run on first boot if tables don't exist

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    premium_until TIMESTAMP,        -- NULL = free; datetime = premium expiry
    conversations_this_month INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'analyzing',
                                    -- analyzing | questioning | generating_scripts
                                    -- awaiting_choice | awaiting_payment
                                    -- awaiting_rejection_reason | regenerating
                                    -- awaiting_reminder_confirm | reminder_set
                                    -- awaiting_outcome | closed
    ghost_risk INTEGER,             -- 0-100
    signals TEXT,                   -- JSON array: ["long delays", "short replies"]
    extracted_text TEXT,            -- raw OCR output; nulled after 30 days
    vertical TEXT,                  -- 'dating' | 'friendship' | 'networking' | null (auto-detected)
    goal TEXT,                      -- 'meetup' | 'closure' | 'advice'
    met_before BOOLEAN,
    investment_score INTEGER,       -- 1-10, only set if ghost_risk > 60
    soft_script TEXT,
    firm_script TEXT,
    ultimatum_script TEXT,
    chosen_script_type TEXT,        -- 'soft' | 'firm' | 'ultimatum' | null
    reminder_set BOOLEAN DEFAULT FALSE,
    reminder_time TIMESTAMP,
    outcome TEXT,                   -- 'met' | 'still_texting' | 'ghosted' | 'gave_up' | null
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    conversation_id INTEGER REFERENCES conversations(id),
    stripe_session_id TEXT UNIQUE NOT NULL,
    amount_cents INTEGER NOT NULL,  -- 500 for $5
    status TEXT NOT NULL DEFAULT 'pending',
                                    -- pending | completed | failed | refunded
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS script_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    rejected_script_type TEXT NOT NULL,     -- 'soft' | 'firm' | 'ultimatum'
    rejection_reason TEXT NOT NULL,         -- 'too_aggressive' | 'too_weak' | 
                                            -- 'doesnt_sound_like_me' | 'other'
    user_comment TEXT,                      -- optional free text
    regenerated_script TEXT,               -- what was sent as replacement
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ml_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    ghost_risk_predicted INTEGER,           -- what we predicted (0-100)
    ghost_risk_actual BOOLEAN,              -- derived: outcome IN ('ghosted', 'gave_up')
    vertical TEXT,
    script_chosen TEXT,
    outcome TEXT,
    labeled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_status ON conversations(user_id, status);
CREATE INDEX IF NOT EXISTS idx_conversations_reminder ON conversations(reminder_set, reminder_time);
CREATE INDEX IF NOT EXISTS idx_payments_stripe_session ON payments(stripe_session_id);
```

---

## Field-by-Field Rationale

### `users.premium_until`
Stores expiry datetime for premium access. NULL = free user. For $5 one-time payments, set to `NOW() + 1 year` per conversation — but this creates the "one payment = permanent premium" bug identified in analysis. 

**Correct model for $5 per-conversation pricing:** Do not use `premium_until` as the gate. Instead, check `payments` table for a completed payment linked to the specific `conversation_id`. The ultimatum is unlocked per-conversation, not per-user.

```python
# Correct check for ultimatum unlock:
def is_ultimatum_unlocked(conversation_id: int) -> bool:
    return db.query(
        "SELECT 1 FROM payments WHERE conversation_id=? AND status='completed'",
        (conversation_id,)
    ) is not None
```

`premium_until` is reserved for a future subscription model.

### `conversations.status`
This is the state machine. Every handler reads this first before doing anything. It is the authoritative record of where the conversation is. In-memory state (`context.user_data`) is a cache — DB is truth.

### `conversations.signals`
Stored as JSON string (SQLite has no native JSON type but supports JSON functions). Example: `'["long delays", "short replies", "no questions asked"]'`. Always parse with `json.loads()` before use.

### `conversations.extracted_text`
Privacy-sensitive. This is a verbatim copy of someone else's messages. Two rules:
1. The raw screenshot image is never stored — only the extracted text
2. `extracted_text` is nulled after 30 days: `UPDATE conversations SET extracted_text=NULL WHERE created_at < datetime('now', '-30 days')`

Run this as a daily scheduled job once the product has real users.

### `conversations.vertical`
Auto-detected from screenshot content by GPT-4 Vision. Values: `'dating'`, `'friendship'`, `'networking'`. Can be NULL if detection is uncertain. Scripts adapt their tone based on this field.

### `ml_labels.ghost_risk_actual`
Derived from outcome: `True` if outcome is `'ghosted'` or `'gave_up'`, `False` if outcome is `'met'` or `'still_texting'`. This is the ground truth label for future ghost risk model training.

---

## Active Conversation Constraint

A user can only have one conversation with `status != 'closed'` at a time. Enforced in `db.py`:

```python
def get_active_conversation(user_id: int) -> dict | None:
    return db.query(
        "SELECT * FROM conversations WHERE user_id=? AND status != 'closed' ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    )
```

In `main.py`, any screenshot received when `get_active_conversation()` returns non-None triggers the "you have an active conversation" message.

---

## Data Lifecycle

```
Screenshot received → extracted_text written
       ↓ (immediately)
Raw image deleted from memory (never written to disk or DB)
       ↓ (30 days)
extracted_text nulled (scheduled cleanup job)
       ↓ (never deleted)
ghost_risk, signals, scripts, outcome, ml_labels → permanent
```

The permanent data is the ML training set. The temporary data is privacy-sensitive content. This distinction drives the retention policy.
