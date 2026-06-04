# Plan 7 — Edge Cases, Polish & Deployment

**Builds:** All error paths, /cancel, /delete_my_data, logging, Railway deployment, beta test  
**Depends on:** Plans 0-6 complete (full happy path works end-to-end)  
**Time:** ~1 day

---

## State Before
Happy path works. Edge cases crash or behave unexpectedly. No deployment. No real users.

## State After
All edge cases handled gracefully. Bot deployed to Railway. 10 real beta users have tested it. Logs are readable. GDPR commands work.

---

## All Decisions Already Made

- Logging: Python `logging` module. INFO level to stdout (Railway captures it). Log conversation milestones. Never log conversation text content.
- Deployment: Railway with persistent volume for `turn.db`. Webhook mode in production.
- `/cancel` closes active conversation regardless of its current status
- `/delete_my_data` requires confirmation button before deleting
- Unhandled exceptions in handlers: catch at top level, send user "Something went wrong" message, log the exception with full traceback
- Rate limiting for OpenAI: handled by retry logic already in place
- Image too large: Telegram's own API rejects >20MB photos before they reach the bot — but compress anyway
- User sends video/audio/sticker: ignore gracefully, send "Send a screenshot or paste text to get started"

---

## Epic 1 — Commands

### Task 7.1 — `/cancel` command

Add to `channels/telegram_bot.py`:

```python
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    active = get_active_conversation(user['id'])
    if not active:
        await update.message.reply_text("No active conversation to cancel.")
        return
    from core.db import update_conversation
    update_conversation(active['id'], status='closed')
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send a new screenshot whenever you're ready.")
```

### Task 7.2 — `/delete_my_data` command

```python
async def delete_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, delete everything", callback_data="confirm_delete"),
        InlineKeyboardButton("Cancel",                 callback_data="noop"),
    ]])
    await update.message.reply_text(
        "This will permanently delete all your conversations and data.\nAre you sure?",
        reply_markup=kb
    )
```

Add to `handle_callback`:

```python
elif data == "confirm_delete":
    from core.db import delete_user_data
    delete_user_data(update.effective_user.id)
    context.user_data.clear()
    await query.message.reply_text("Done. All your data has been deleted. Goodbye.")
    return
```

### Task 7.3 — Register new commands in `build_application`

```python
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("cancel", cancel_command))
app.add_handler(CommandHandler("delete_my_data", delete_data_command))
```

---

## Epic 2 — Unsupported Message Types

### Task 7.4 — Handle non-photo, non-text messages

Add handler at the bottom of `build_application` (must be last):

```python
app.add_handler(MessageHandler(
    filters.VIDEO | filters.AUDIO | filters.VOICE | filters.STICKER | filters.DOCUMENT,
    handle_unsupported
))
```

```python
async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send a screenshot or paste the conversation text to get started.")
```

---

## Epic 3 — Global Error Handler

### Task 7.5 — Add error handler to `build_application`

```python
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    import traceback
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    # Try to send error message to user
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong. Please try again or send /start to restart."
            )
        except Exception:
            pass  # don't crash the error handler

app.add_error_handler(error_handler)
```

---

## Epic 4 — Logging Setup

### Task 7.6 — Update logging in `main.py`

```python
import logging
import sys

def setup_logging():
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.DEBUG if config.DEBUG else logging.INFO
    )
    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
```

**Log these events (add to respective functions):**
```
INFO  conv={id} created user={telegram_id}
INFO  conv={id} ghost_risk={n} vertical={v}
INFO  conv={id} goal={g} met={m} investment={i}
INFO  conv={id} scripts generated
INFO  conv={id} script_chosen={type}
INFO  conv={id} payment_initiated
INFO  conv={id} payment_completed session={stripe_id}
INFO  conv={id} reminder_scheduled hours=48
INFO  conv={id} reminder_fired
INFO  conv={id} outcome={outcome}
ERROR conv={id} vision_failed attempt={n}: {error}
ERROR conv={id} script_gen_failed: {error}
```

Never log: extracted_text, script content, user messages.

---

## Epic 5 — Railway Deployment

### Task 7.7 — `Procfile` (Railway uses this)

```
web: python main.py
```

### Task 7.8 — Environment variables on Railway

Set these in Railway dashboard → Variables:

```
TELEGRAM_BOT_TOKEN=...
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
STRIPE_SECRET_KEY=sk_live_...     ← use live key in production
STRIPE_WEBHOOK_SECRET=whsec_...   ← from Stripe dashboard for this endpoint
WEBHOOK_URL=https://your-app.railway.app
DATABASE_PATH=/data/turn.db       ← persistent volume mount path
PORT=8080
DEBUG=false
```

### Task 7.9 — Railway persistent volume

In Railway dashboard: add a volume mounted at `/data`. Update `DATABASE_PATH=/data/turn.db`.

Without this, the SQLite DB is wiped on every deploy.

### Task 7.10 — Register Stripe webhook endpoint

In Stripe dashboard → Developers → Webhooks → Add endpoint:
- URL: `https://your-app.railway.app/stripe-webhook`
- Events: `checkout.session.completed`
- Copy the signing secret → set as `STRIPE_WEBHOOK_SECRET` in Railway

### Task 7.11 — Verify deployment

```bash
# Check bot is alive
curl https://your-app.railway.app/health  # add a /health route

# Check Telegram webhook is set
curl https://api.telegram.org/bot{TOKEN}/getWebhookInfo
```

Add `/health` route to `main.py`:

```python
@fastapi_app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## Epic 6 — Beta Test Checklist (10 Real Users)

### Task 7.12 — Before recruiting users

- [ ] Test full flow yourself with a real screenshot
- [ ] Test with a pasted conversation (text fallback)
- [ ] Test Stripe with real card (refund after)
- [ ] Test `/cancel` mid-conversation
- [ ] Test `/delete_my_data`
- [ ] Test bot restart mid-conversation (kill process, restart, send a message)
- [ ] Verify reminder fires (set `REMINDER_HOURS=0.017` in env = 1 minute, test, reset to 48)
- [ ] Verify DB entries look correct after a complete flow

### Task 7.13 — Recruit beta users

Channels to try:
- Reddit: r/dating_advice, r/socialskills — post "I built a tool for ghosting, want 10 beta testers"
- Twitter/X: post ghost risk screenshot result as hook
- Friends — specifically ones who have complained about ghosting recently

### Task 7.14 — What to watch for

- Where do users get confused? (high drop-off between steps)
- Do they actually tap the inline buttons or try to type?
- Do any scripts get rejected as "doesn't sound like me" frequently? (prompt tuning needed)
- Does the ghost risk feel calibrated? (users say "that's not accurate" → prompt tuning)
- Does anyone pay $5? (THE metric for plan 7 completion)

---

## Acceptance Criteria — Plan 7 Complete When:

- [ ] `/cancel` works at any point in the conversation
- [ ] `/delete_my_data` deletes all rows and confirms to user
- [ ] Sending a video/sticker gets a helpful message, not a crash
- [ ] Bot restart mid-conversation: next message resumes correctly
- [ ] Unhandled exception: user gets "Something went wrong" message, error logged with traceback
- [ ] Bot deployed to Railway, webhook confirmed via `getWebhookInfo`
- [ ] SQLite DB persists across deploys (persistent volume)
- [ ] Stripe webhook registered and verified in Stripe dashboard
- [ ] `/health` endpoint returns 200
- [ ] At least 3 real users have completed the full flow (screenshot → scripts → reminder → outcome)
- [ ] At least 1 real user has paid $5

**MVP is complete after Plan 7.**
