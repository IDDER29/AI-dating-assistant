# Plan 4 — Stripe Payments

**Builds:** Ultimatum paywall → Stripe Checkout → webhook → ultimatum delivered  
**Depends on:** Plan 3 complete (scripts displayed, ultimatum button exists)  
**Time:** ~1 day

---

## State Before
Ultimatum button shows placeholder text. No payment flow exists.

## State After
Tapping Ultimatum → Stripe payment link sent → user pays → webhook fires → ultimatum script delivered → reminder scheduled → status = `'reminder_set'`.

---

## All Decisions Already Made

- **$5 one-time per conversation** — not user-level premium. Gate = `payments` table WHERE `conversation_id=? AND status='completed'`. The `premium_until` column is reserved for future subscription.
- **Stripe Checkout** (hosted page) — not Stripe Elements. Simpler, no PCI scope.
- **Signature verification is MANDATORY** — `stripe.Webhook.construct_event()`. Without it, anyone can fake a webhook. This is the #1 security requirement.
- **Idempotency** — if webhook fires twice (Stripe does this), the second call is a no-op. Check `complete_payment()` returns None before proceeding.
- **success_url** → `https://t.me/{BOT_USERNAME}` — sends user back to the bot
- **cancel_url** → same as success_url — if they cancel, they return to bot
- **metadata** on Stripe session MUST include `conversation_id` and `user_telegram_id` — needed in webhook to know which conversation to unlock
- The HTTP server that receives Stripe webhooks runs in the same process as the bot (FastAPI, not Flask, because python-telegram-bot v20 is async)

---

## Epic 1 — Stripe Client

### Task 4.1 — `stripe_client.py`

```python
import stripe
import logging
import config

stripe.api_key = config.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)

def create_checkout_session(user_telegram_id: int, conv_id: int, bot_username: str) -> str:
    """Creates Stripe Checkout session. Returns the payment URL."""
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': 'TURN — Ultimatum Script'},
                'unit_amount': config.STRIPE_PRICE_CENTS,
            },
            'quantity': 1,
        }],
        mode='payment',
        metadata={
            'conversation_id': str(conv_id),
            'user_telegram_id': str(user_telegram_id),
        },
        success_url=f'https://t.me/{bot_username}',
        cancel_url=f'https://t.me/{bot_username}',
    )
    logger.info(f"Stripe session created: {session.id} for conv={conv_id}")
    return session.url

def verify_and_parse_webhook(payload: bytes, sig_header: str) -> dict | None:
    """
    Verifies Stripe webhook signature and returns the event dict.
    Returns None if signature is invalid — caller should return 400.
    NEVER skip this verification.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, config.STRIPE_WEBHOOK_SECRET
        )
        return event
    except ValueError:
        logger.warning("Stripe webhook: invalid payload")
        return None
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook: invalid signature")
        return None
```

---

## Epic 2 — Webhook HTTP Server

The bot runs as a FastAPI app in webhook mode. Add the Stripe webhook route to the same FastAPI instance.

### Task 4.2 — Update `main.py` to use FastAPI + python-telegram-bot together

python-telegram-bot v20 in webhook mode runs its own internal server. To add a Stripe webhook endpoint on the same port, use `Application.run_webhook()` with a custom FastAPI app.

```python
import logging
from fastapi import FastAPI, Request, Response
import uvicorn
import config
from core.db import init_db
from core.scheduler import init_scheduler
from channels.telegram_bot import build_application
import stripe_client as sc

logger = logging.getLogger(__name__)

fastapi_app = FastAPI()

# --- Stripe webhook endpoint ---
@fastapi_app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = sc.verify_and_parse_webhook(payload, sig)
    if event is None:
        return Response(status_code=400)
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        await handle_payment_success(
            conv_id=int(session['metadata']['conversation_id']),
            user_telegram_id=int(session['metadata']['user_telegram_id']),
            stripe_session_id=session['id']
        )
    
    return Response(status_code=200)

async def handle_payment_success(conv_id: int, user_telegram_id: int, stripe_session_id: str):
    from core.db import get_user_by_telegram_id, record_payment, complete_payment, get_conversation, update_conversation
    from core.scheduler import schedule_reminder

    user = get_user_by_telegram_id(user_telegram_id)
    if not user:
        logger.error(f"Payment webhook: user not found for telegram_id={user_telegram_id}")
        return

    record_payment(user['id'], conv_id, stripe_session_id, config.STRIPE_PRICE_CENTS)
    payment = complete_payment(stripe_session_id)
    if payment is None:
        logger.info(f"Payment {stripe_session_id} already processed — skipping (idempotent)")
        return

    conv = get_conversation(conv_id)
    if not conv:
        return

    update_conversation(conv_id, chosen_script_type='ultimatum', status='reminder_set')
    schedule_reminder(conv_id, hours=48)

    # Send ultimatum script to user
    from channels.telegram_bot import get_bot
    bot = get_bot()
    await bot.send_message(
        chat_id=user_telegram_id,
        text=f"Unlocked.\n\nCopy and send this:\n\n{conv['ultimatum_script']}"
    )
    await bot.send_message(
        chat_id=user_telegram_id,
        text="I'll check back in 48 hours. You've done your part."
    )
    logger.info(f"Ultimatum delivered for conv={conv_id}")

def main():
    init_db()
    init_scheduler()
    app = build_application()

    if config.WEBHOOK_URL:
        # In webhook mode: telegram bot + stripe webhook both on same server
        # python-telegram-bot v20 supports passing a custom app
        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            webhook_url=f"{config.WEBHOOK_URL}/webhook",
            allowed_updates=["message", "callback_query"],
            webserver_port=config.PORT
        )
        # Note: For Stripe webhook on a different path, use starlette integration
        # See: https://docs.python-telegram-bot.org/en/stable/examples.customwebhookbot.html
    else:
        app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
```

**Important:** python-telegram-bot v20 webhook + custom routes. The cleanest pattern:

```python
# main.py — production webhook mode with custom routes
import asyncio
from telegram.ext import Application
from fastapi import FastAPI
import uvicorn

# Build both apps
ptb_app = build_application()
fastapi_app = FastAPI()

# Register Stripe webhook on fastapi_app (done above)
# Register Telegram webhook on fastapi_app too:

@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    from telegram import Update
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=200)

async def startup():
    init_db()
    init_scheduler()
    await ptb_app.initialize()
    await ptb_app.bot.set_webhook(f"{config.WEBHOOK_URL}/webhook")
    await ptb_app.start()

async def shutdown():
    await ptb_app.stop()
    await ptb_app.shutdown()

fastapi_app.add_event_handler("startup", startup)
fastapi_app.add_event_handler("shutdown", shutdown)

if __name__ == "__main__":
    if config.WEBHOOK_URL:
        uvicorn.run(fastapi_app, host="0.0.0.0", port=config.PORT)
    else:
        # Polling for local dev
        init_db()
        init_scheduler()
        ptb_app.run_polling()
```

This pattern (FastAPI + ptb webhook + uvicorn) is the cleanest for adding multiple routes. Reference: `https://docs.python-telegram-bot.org/en/stable/examples.customwebhookbot.html`

### Task 4.3 — Add `get_bot()` helper to `channels/telegram_bot.py`

The webhook handler needs to send a message outside of a handler context (after Stripe payment). Store the bot instance at module level:

```python
_application: Application = None

def get_bot():
    return _application.bot

def build_application() -> Application:
    global _application
    _application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    # ... handlers ...
    return _application
```

---

## Epic 3 — Ultimatum Button Handler

### Task 4.4 — Update `handle_callback` in `channels/telegram_bot.py`

Replace the placeholder for `script_ultimatum`:

```python
elif action_value == 'script_ultimatum':
    from core.db import is_ultimatum_unlocked
    if is_ultimatum_unlocked(conv_id):
        # Already paid — deliver directly
        from core.db import update_conversation
        update_conversation(conv_id, chosen_script_type='ultimatum', status='reminder_set')
        from core.scheduler import schedule_reminder
        schedule_reminder(conv_id, hours=48)
        await query.message.reply_text(
            f"Copy and send this:\n\n{conv['ultimatum_script']}\n\n"
            "I'll check back in 48 hours."
        )
    else:
        # Need payment
        import stripe_client as sc
        bot_username = (await query.get_bot().get_me()).username
        url = sc.create_checkout_session(
            user_telegram_id=update.effective_user.id,
            conv_id=conv_id,
            bot_username=bot_username
        )
        update_conversation(conv_id, status='awaiting_payment')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Pay $5 →", url=url)]])
        await query.message.reply_text(
            "The ultimatum script forces the answer.\n"
            "Unlock it for $5 — one-time for this conversation.",
            reply_markup=kb
        )
```

---

## Epic 4 — Scheduler Integration (partial)

### Task 4.5 — Add `schedule_reminder` to `core/scheduler.py`

```python
from datetime import datetime, timedelta
import random

def schedule_reminder(conv_id: int, hours: int = 48):
    scheduler = get_scheduler()
    run_time = datetime.now() + timedelta(hours=hours) + timedelta(seconds=random.randint(0, 30))
    scheduler.add_job(
        'channels.telegram_bot:fire_reminder',  # dotted path — APScheduler imports it
        'date',
        run_date=run_time,
        args=[conv_id],
        id=f'reminder_{conv_id}',
        replace_existing=True
    )
```

`fire_reminder` is implemented in Plan 5.

---

## Acceptance Criteria — Plan 4 Complete When:

- [ ] Tapping Ultimatum → Stripe payment link appears as a button
- [ ] Clicking the link opens Stripe Checkout in browser
- [ ] Paying with test card `4242 4242 4242 4242` → Stripe dashboard shows completed payment
- [ ] Stripe webhook fires → `payments` table has a `completed` row for this `conversation_id`
- [ ] Ultimatum script appears in Telegram after payment
- [ ] Replaying the same webhook (duplicate) → second send does NOT happen (idempotency)
- [ ] Webhook with invalid signature → returns 400, nothing happens in DB
- [ ] `is_ultimatum_unlocked(conv_id)` returns True after payment
- [ ] Status = `'reminder_set'` after payment + delivery
