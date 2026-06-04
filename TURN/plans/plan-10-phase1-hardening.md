# Plan 10 — Phase 1 Hardening

**Builds:** Subscription pricing, rate limiting, error monitoring, data cleanup, admin tools  
**Depends on:** Plan 7 complete + validation gate passed (20+ paying users, 50+ outcomes logged)  
**Time:** ~2 days

---

## State Before
MVP is live. $5 one-time payments working. 20+ paying users. Outcome data accumulating. No subscription. No rate limiting. No monitoring. `extracted_text` never gets cleaned up.

## State After
- Subscription option ($19.99/mo) alongside $5 one-time
- Rate limiting per user (prevent abuse, control LLM costs)
- Sentry error monitoring
- `extracted_text` privacy cleanup job (null after 30 days)
- Admin commands for founder use
- Multi-conversation support (remove the one-at-a-time limit)

---

## All Decisions Already Made

- $5 stays as one-time option — do NOT remove it. It's the entry point for low-frequency users.
- Subscription at $19.99/mo unlocks: unlimited ultimatums, voice profiles (future), multi-conversation
- Rate limit: 5 conversations per user per day (free), unlimited (premium)
- Sentry for error tracking — free tier is sufficient for MVP scale
- `extracted_text` nulled after 30 days via APScheduler daily job
- Multi-conversation support: remove the "one active conversation" block — instead show a list if multiple active
- Admin commands are only accessible to the founder's Telegram ID (hardcoded in config)

---

## Epic 1 — Subscription Pricing

### Task 10.1 — Add Stripe subscription product

In Stripe dashboard:
1. Create a product: "TURN Premium"
2. Create a price: $19.99/month recurring
3. Save the `price_id` (e.g. `price_xxx`)
4. Add to env: `STRIPE_SUBSCRIPTION_PRICE_ID=price_xxx`

### Task 10.2 — Add subscription checkout to `stripe_client.py`

```python
def create_subscription_session(user_telegram_id: int, bot_username: str) -> str:
    """Creates a Stripe Checkout session for monthly subscription."""
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{'price': config.STRIPE_SUBSCRIPTION_PRICE_ID, 'quantity': 1}],
        mode='subscription',
        metadata={'user_telegram_id': str(user_telegram_id), 'type': 'subscription'},
        success_url=f'https://t.me/{bot_username}',
        cancel_url=f'https://t.me/{bot_username}',
    )
    return session.url
```

### Task 10.3 — Handle subscription webhook events

In `handle_payment_success` (main.py), add subscription handling:

```python
# In stripe_webhook handler, add these events:
# 'customer.subscription.created'  → set premium_until = end of billing period
# 'customer.subscription.deleted'  → clear premium_until
# 'invoice.payment_succeeded'      → extend premium_until

if event['type'] == 'customer.subscription.created':
    sub = event['data']['object']
    user_telegram_id = int(sub['metadata'].get('user_telegram_id', 0))
    from datetime import datetime
    premium_until = datetime.fromtimestamp(sub['current_period_end'])
    user = db.get_user_by_telegram_id(user_telegram_id)
    if user:
        db.update_user_premium(user['id'], premium_until)
```

### Task 10.4 — Add `update_user_premium` to `core/db.py`

```python
def update_user_premium(user_id: int, premium_until) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET premium_until=? WHERE id=?", (premium_until, user_id))
```

### Task 10.5 — `/subscribe` command

```python
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = (await context.bot.get_me()).username
    url = stripe_client.create_subscription_session(update.effective_user.id, bot_username)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Subscribe $19.99/mo →", url=url)]])
    await update.message.reply_text(
        "TURN Premium — $19.99/month\n\n"
        "✅ Unlimited ultimatum scripts\n"
        "✅ Smart reminders\n"
        "✅ Multiple conversations\n\n"
        "Cancel anytime.",
        reply_markup=kb
    )
```

---

## Epic 2 — Rate Limiting

### Task 10.6 — Add rate limit check

Free users: 5 conversations per 24h. Premium users: unlimited.

Add to `core/db.py`:

```python
def get_conversation_count_today(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE user_id=? AND created_at > datetime('now', '-1 day')",
            (user_id,)
        ).fetchone()
        return row['c']

def is_premium(user_id: int) -> bool:
    from datetime import datetime
    with get_conn() as conn:
        row = conn.execute("SELECT premium_until FROM users WHERE id=?", (user_id,)).fetchone()
        if not row or not row['premium_until']:
            return False
        return datetime.fromisoformat(row['premium_until']) > datetime.now()
```

In `handle_photo` (telegram_bot.py), add before creating conversation:

```python
FREE_DAILY_LIMIT = 5

if not db.is_premium(user['id']):
    count = db.get_conversation_count_today(user['id'])
    if count >= FREE_DAILY_LIMIT:
        await update.message.reply_text(
            f"You've used {FREE_DAILY_LIMIT} free analyses today.\n\n"
            "Upgrade to Premium for unlimited: /subscribe"
        )
        return
```

---

## Epic 3 — Privacy Cleanup Job

### Task 10.7 — Add daily cleanup to `core/scheduler.py`

```python
def schedule_daily_cleanup():
    scheduler = get_scheduler()
    scheduler.add_job(
        func='core.db:null_old_extracted_text',
        trigger='cron',
        hour=3,     # 3 AM daily
        id='daily_cleanup',
        replace_existing=True
    )
```

Add `null_old_extracted_text` to `core/db.py`:

```python
def null_old_extracted_text() -> None:
    """Privacy: null extracted_text for conversations older than 30 days."""
    with get_conn() as conn:
        result = conn.execute(
            "UPDATE conversations SET extracted_text=NULL WHERE extracted_text IS NOT NULL AND created_at < datetime('now', '-30 days')"
        )
    import logging
    logging.getLogger(__name__).info(f"Privacy cleanup: nulled extracted_text for {result.rowcount} conversations")
```

Call `schedule_daily_cleanup()` from `init_scheduler()`.

---

## Epic 4 — Error Monitoring (Sentry)

### Task 10.8 — Add Sentry

Add to `requirements.txt`:
```
sentry-sdk[fastapi]==1.43.0
```

In `main.py`:

```python
import sentry_sdk
if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        traces_sample_rate=0.1,
        environment="production" if not config.DEBUG else "development"
    )
```

Add `SENTRY_DSN=https://xxx@sentry.io/xxx` to env. Get DSN from sentry.io (free tier).

---

## Epic 5 — Admin Commands

### Task 10.9 — Founder-only commands

Add to `config.py`:
```python
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))
```

```python
def admin_only(func):
    """Decorator — only runs if user is the admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config.ADMIN_TELEGRAM_ID:
            return
        return await func(update, context)
    return wrapper

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db.get_conn() as conn:
        users     = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
        convs     = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()['c']
        outcomes  = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE outcome IS NOT NULL").fetchone()['c']
        payments  = conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='completed'").fetchone()['c']
        revenue   = conn.execute("SELECT SUM(amount_cents) as s FROM payments WHERE status='completed'").fetchone()['s'] or 0

    await update.message.reply_text(
        f"📊 TURN Stats\n\n"
        f"Users: {users}\n"
        f"Conversations: {convs}\n"
        f"Outcomes logged: {outcomes}\n"
        f"Payments: {payments}\n"
        f"Revenue: ${revenue/100:.2f}"
    )

@admin_only
async def grant_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /grant_premium {telegram_id}"""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /grant_premium {telegram_id}")
        return
    target_id = int(args[0])
    from datetime import datetime, timedelta
    user = db.get_user_by_telegram_id(target_id)
    if not user:
        await update.message.reply_text(f"User {target_id} not found")
        return
    db.update_user_premium(user['id'], datetime.now() + timedelta(days=365))
    await update.message.reply_text(f"Premium granted to {target_id} for 1 year")
```

---

## Epic 6 — Multi-Conversation Support

### Task 10.10 — Remove one-active-conversation limit

Instead of blocking, show the user their active conversations and let them switch.

In `handle_photo`, replace the block with:

```python
active = get_active_conversation(user['id'])
if active:
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Continue current",         callback_data="noop"),
        InlineKeyboardButton("Start new (archive old)",  callback_data=f"archive_and_new"),
    ]])
    await update.message.reply_text(
        "You have a conversation in progress. Start a new one?",
        reply_markup=kb
    )
    # Store new photo in context for when user confirms
    context.user_data['pending_photo'] = bytes(image_bytes)
    return
```

Add `archive_and_new` to `handle_callback`:

```python
elif data == "archive_and_new":
    active = get_active_conversation(user['id'])
    if active:
        from core.db import update_conversation
        update_conversation(active['id'], status='closed')
    # Process the pending photo
    pending = context.user_data.pop('pending_photo', None)
    if pending:
        await handle_photo_bytes(update, context, user, pending)
```

---

## Acceptance Criteria — Plan 10 Complete When:

- [ ] `/subscribe` command shows subscription options
- [ ] Completing subscription in Stripe → `users.premium_until` is set in DB
- [ ] Free user hitting 5 conversations in a day → rate limit message + subscribe prompt
- [ ] Premium user → no rate limit
- [ ] Daily cleanup job: `extracted_text` nulled for conversations older than 30 days
- [ ] `/stats` command (admin only) shows correct counts
- [ ] `/grant_premium` command works for the admin
- [ ] Sentry captures errors and shows them in Sentry dashboard
- [ ] Multiple active conversations: user can archive old and start new
