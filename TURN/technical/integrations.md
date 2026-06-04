# Integrations — External Services

## Telegram Bot API

**Library:** `python-telegram-bot` v20+ (async)
**Mode:** Webhook (not polling — polling is for local development only)

### Key patterns

**Webhook setup:**
```python
application.run_webhook(
    listen="0.0.0.0",
    port=int(os.environ.get("PORT", 8080)),
    webhook_url=f"{WEBHOOK_URL}/webhook"
)
```

**Handler registration order matters:**
```python
# Specific commands first
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("cancel", cancel_command))
app.add_handler(CommandHandler("delete_my_data", delete_data_command))

# Callback queries (button taps)
app.add_handler(CallbackQueryHandler(handle_callback))

# Media — photos
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

# Text fallback (must be last)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
```

**Inline keyboards:**
```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def make_goal_keyboard(conv_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Get a real meetup", callback_data=f"goal_meetup_{conv_id}")],
        [InlineKeyboardButton("🚪 Get closure", callback_data=f"goal_closure_{conv_id}")],
        [InlineKeyboardButton("💭 Just want advice", callback_data=f"goal_advice_{conv_id}")],
    ])
```

**Always answer callback queries:**
```python
await update.callback_query.answer()  # removes loading state from button
```

**Rate limiting:** Telegram allows 30 messages/second to different users, 1 message/second to the same user. APScheduler reminder jobs should stagger if many fire simultaneously. For MVP scale, this is not an issue.

**What Telegram bots CANNOT do (hard limits):**
- Cannot send messages to other users on behalf of the user
- Cannot read the user's messages to other people
- Cannot access the user's contact list
- Cannot initiate a conversation with a user who hasn't started the bot (`/start` must come first)

---

## OpenAI API

**Library:** `openai` Python SDK v1.x (async client)
**Models used:**
- `gpt-4-turbo` with vision for screenshot analysis
- `gpt-4` or `gpt-3.5-turbo` for script generation and regeneration

### Vision call pattern:
```python
response = await client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[{
        "role": "system",
        "content": VISION_SYSTEM_PROMPT
    }, {
        "role": "user",
        "content": [{
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
                "detail": "low"  # 'low' = cheaper, sufficient for text extraction
            }
        }]
    }],
    max_tokens=500,
    response_format={"type": "json_object"}
)
```

**`detail: "low"` is important** — reduces token cost significantly. Text extraction doesn't need high-res image analysis.

**`response_format: json_object`** forces GPT to return valid JSON. Always use this for structured outputs.

### Retry pattern:
```python
async def call_with_retry(func, *args, max_attempts=2, delay=3):
    for attempt in range(max_attempts):
        try:
            return await func(*args)
        except openai.APITimeoutError:
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
            else:
                raise
        except openai.APIError as e:
            raise  # don't retry on non-timeout errors
```

**Cost control:** Image compression to 512px before sending is mandatory. A 4K screenshot sent at full resolution costs ~10x more than a compressed version.

---

## Stripe

**Library:** `stripe` Python SDK
**Mode:** Checkout Sessions (hosted payment page)

### Create session:
```python
session = stripe.checkout.Session.create(
    payment_method_types=['card'],
    line_items=[{
        'price_data': {
            'currency': 'usd',
            'product_data': {'name': 'TURN Ultimatum Script'},
            'unit_amount': 500,  # $5.00 in cents
        },
        'quantity': 1,
    }],
    mode='payment',
    metadata={
        'user_id': str(user_id),
        'conversation_id': str(conv_id),
    },
    success_url='https://t.me/TurnBot',  # return to bot
    cancel_url='https://t.me/TurnBot',
)
return session.url
```

### Webhook handler (CRITICAL — signature verification):
```python
@app.route('/stripe-webhook', methods=['POST'])
async def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        conv_id = int(session['metadata']['conversation_id'])
        user_id = int(session['metadata']['user_id'])
        await handle_payment_success(user_id, conv_id, session['id'])
    
    return '', 200
```

**Idempotency:** `handle_payment_success` must check if `stripe_session_id` already exists in `payments` table before processing. Stripe may send the same webhook twice.

```python
async def handle_payment_success(user_id, conv_id, stripe_session_id):
    if db.payment_already_processed(stripe_session_id):
        return  # idempotent — already handled
    db.record_payment(user_id, conv_id, stripe_session_id, 500, 'completed')
    # ... deliver script
```

---

## APScheduler

**Library:** `apscheduler` v3.x
**Job store:** SQLAlchemyJobStore backed by SQLite (same DB file)
**Executor:** AsyncIOExecutor (must match python-telegram-bot's async model)

### Setup:
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

scheduler = AsyncIOScheduler(
    jobstores={
        'default': SQLAlchemyJobStore(url='sqlite:///turn.db')
    },
    job_defaults={
        'coalesce': True,      # run once even if missed multiple times
        'max_instances': 1,    # don't run job twice simultaneously
        'misfire_grace_time': 3600,  # run up to 1h late if bot was down
    }
)
scheduler.start()
```

### Adding a reminder job:
```python
from datetime import datetime, timedelta

def schedule_reminder(conv_id: int, hours: int = 48):
    run_time = datetime.now() + timedelta(hours=hours)
    scheduler.add_job(
        fire_reminder,
        'date',
        run_date=run_time,
        args=[conv_id],
        id=f'reminder_{conv_id}',     # unique ID prevents duplicates
        replace_existing=True,         # if rescheduled, replace old job
    )
```

### The `fire_reminder` function must be importable at module level:
APScheduler serializes jobs to the DB and re-imports the function on recovery. The function must be defined at module level (not inside a class or lambda).

```python
async def fire_reminder(conv_id: int):
    # This function is called by APScheduler — must be top-level
    conv = db.get_conversation(conv_id)
    if not conv or conv['status'] == 'closed':
        return
    chat_id = db.get_user_telegram_id(conv['user_id'])
    await bot.send_message(chat_id=chat_id, text=REMINDER_TEXT, reply_markup=make_outcome_keyboard(conv_id))
    db.set_status(conv_id, 'awaiting_outcome')
```

**The `bot` object must be accessible inside `fire_reminder`.** Pattern: store as module-level variable in `scheduler.py`, set during app initialization.
