# Process Flow — Runtime Sequence

> This is what happens in the code, step by step, for every path through the MVP.
> Use this when implementing `main.py` to know what each handler must do.

---

## Startup

```
main.py runs
  → config.py validates all env vars (fail loudly if any missing)
  → db.py creates tables if not exist (idempotent)
  → scheduler.py starts BackgroundScheduler with SQLite job store
  → scheduler.py recovers any jobs that were due while bot was down
  → python-telegram-bot registers all handlers
  → bot sets webhook URL with Telegram API
  → HTTP server starts listening on /webhook and /stripe-webhook
```

---

## Handler: /start

```
Trigger: user sends /start

1. db.get_or_create_user(telegram_id, username)
2. Send welcome message (see user-journeys.md for exact copy)
3. No state change — user is ready to send a screenshot
```

---

## Handler: Photo received

```
Trigger: update.message.photo is not None

1. db.get_active_conversation(user_id)
   → if exists and status != 'closed':
     → send "You have an active conversation. [Continue] [/cancel]"
     → return

2. utils.download_and_compress_image(update.message.photo[-1])
   → get_file() → download_as_bytearray()
   → PIL resize to max 512px on longest side
   → convert to base64

3. Send "Analyzing... ⏳"

4. gpt_client.analyze_screenshot(image_base64)
   → returns VisionResult(ghost_risk, signals, extracted_text, vertical)
   → if error='unreadable': send error message, return
   → if OpenAI timeout: retry once; if second failure: send retry message, return

5. image data deleted from memory (Python GC handles this; do not write to disk)

6. db.create_conversation(user_id, ghost_risk, signals, extracted_text, vertical)
   → returns conv_id
   → sets status='questioning'

7. context.user_data['conv_id'] = conv_id  (cache for this session)

8. Send ghost risk message with signals

9. Send first question (ask_goal) with inline keyboard
```

---

## Handler: Text message (non-command)

```
Trigger: update.message.text and not starts_with('/')

1. db.get_active_conversation(user_id)
   → if None: send "Send a screenshot or paste a conversation to get started"
   → if status='questioning' and step='ask_investment':
     → try parse as integer 1-10
     → if valid: treat as answer (same as callback handler)
     → if invalid: send "Please pick a number 1-10"

2. Special case: if no active conversation and message looks like pasted conversation text:
   → treat as raw conversation (skip vision step)
   → db.create_conversation(user_id, ghost_risk=None, extracted_text=text)
   → send "Got the conversation. Let me ask a few questions."
   → send first question (ask_goal)
   
Note: Raw text path skips ghost risk calculation at this step.
      Ghost risk is estimated from text during script generation instead.
```

---

## Handler: Callback query (inline button taps)

```
Trigger: update.callback_query

1. Parse callback_data format: "{action}_{value}_{conv_id}"
   e.g. "goal_meetup_42", "script_soft_42", "outcome_met_42"

2. Always verify conv_id matches active conversation for this user
   → if mismatch: answer callback with "This conversation is outdated" and return

3. Route by action prefix:

   "goal_*" → store goal, send next question (ask_met)
   "met_*"  → store met_before, check ghost_risk to decide next question
              → if ghost_risk > 60: send ask_investment
              → else: trigger script generation
   "inv_*"  → store investment_score, trigger script generation
   "script_soft" or "script_firm" → handle_free_script_selection()
   "script_ultimatum" → handle_ultimatum_selection()
   "script_reject" → handle_script_rejection()
   "reminder_yes" → schedule_reminder(), confirm to user
   "reminder_no"  → db.set_status(conv_id, 'closed'), send closing message
   "rejection_reason_*" → store reason, trigger regeneration
   "outcome_*" → handle_outcome()
   "cancel_conv" → db.set_status(conv_id, 'closed'), send cancellation message

4. Always answer the callback query (answerCallbackQuery) to remove loading state
```

---

## Sub-flow: Script Generation

```
Triggered after all questions answered

1. db.get_conversation(conv_id) → full row
2. db.set_status(conv_id, 'generating_scripts')
3. Send "Generating your scripts... ✍️"
4. gpt_client.generate_scripts(extracted_text, goal, met_before, investment_score, ghost_risk, vertical)
   → returns Scripts(soft_push, firm_boundary, ultimatum)
5. db.store_scripts(conv_id, soft_push, firm_boundary, ultimatum)
6. db.set_status(conv_id, 'awaiting_choice')
7. Send scripts message with inline keyboard:
   [💬 Use Soft] [⚡ Use Firm] [🔒 Ultimatum ($5)] [👎 Not for me]
   
   Note: If goal='closure', rename buttons:
   [💬 Gentle Exit] [⚡ Direct Close] [🔒 Goodbye Script ($5)] [👎 Not for me]
```

---

## Sub-flow: Stripe Payment

```
Triggered when user taps "🔒 Ultimatum ($5)"

1. db.check_ultimatum_unlocked(conv_id) → if already paid: skip to script delivery
2. stripe_client.create_checkout_session(user_id, conv_id, amount_cents=500)
   → metadata: {user_id, conv_id}
   → success_url: points back to bot (or static "return to bot" page)
   → returns session.url
3. db.set_status(conv_id, 'awaiting_payment')
4. Send payment link message

--- (user pays in browser) ---

Stripe webhook fires to /stripe-webhook:
1. stripe_client.verify_webhook_signature(payload, signature_header)
   → if invalid: return 400, log warning
2. If event.type == 'checkout.session.completed':
   → extract conv_id from metadata
   → db.record_payment(user_id, conv_id, stripe_session_id, amount=500, status='completed')
   → db.set_status(conv_id, 'reminder_set')
   → scheduler.add_job(fire_reminder, conv_id, hours=48)
   → send_ultimatum_script_to_user(conv_id)
3. Return 200

send_ultimatum_script_to_user(conv_id):
   → db.get_conversation(conv_id) → ultimatum_script
   → Send script text to user
   → Send "I'll check back in 48 hours."
```

---

## Sub-flow: Reminder

```
Job fires: scheduler calls fire_reminder(conv_id)

1. db.get_conversation(conv_id)
   → if status='closed': skip (conversation already resolved, skip silently)
2. db.get_user_telegram_id(conv_id) → chat_id
3. Send reminder message with outcome keyboard
4. db.set_status(conv_id, 'awaiting_outcome')
```

---

## Sub-flow: Outcome Collection

```
Trigger: outcome_* callback

1. Parse outcome from callback: 'met' | 'still_texting' | 'ghosted' | 'gave_up'
2. db.update_outcome(conv_id, outcome)
3. db.set_status(conv_id, 'closed')
4. db.log_ml_label(conv_id)  → inserts into ml_labels table
5. Send closing message (varies by outcome — see user-journeys.md)
6. context.user_data.clear()  → clean up in-memory cache
```

---

## /cancel command

```
1. db.get_active_conversation(user_id)
   → if None: "No active conversation to cancel."
2. db.set_status(conv_id, 'closed')
3. Send "Cancelled. Send a new screenshot whenever you're ready."
```

---

## /delete_my_data command

```
1. Send confirmation prompt with [Yes, delete everything] [Cancel]
2. On confirm:
   → DELETE FROM ml_labels WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)
   → DELETE FROM script_rejections WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)
   → DELETE FROM payments WHERE user_id=?
   → DELETE FROM conversations WHERE user_id=?
   → DELETE FROM users WHERE id=?
3. Send "Done. All your data has been deleted."
Note: ml_labels are deleted too — user's right to be forgotten supersedes ML training value.
```

---

## Error Handling Matrix

| Error | Location | Handler Behavior |
|-------|----------|-----------------|
| OpenAI timeout (first) | gpt_client | Retry once after 3s |
| OpenAI timeout (second) | gpt_client | Raise; main.py catches, sends user message |
| OpenAI invalid JSON | gpt_client | Raise ValueError with raw response logged |
| Image too large (>20MB) | handle_photo | Send "Please send a smaller screenshot" |
| Image unreadable | gpt_client | Return error flag; main.py asks for clearer image |
| Stripe webhook invalid sig | stripe_client | Return 400, log warning, do nothing |
| Stripe webhook duplicate | stripe_client | Check idempotency on stripe_session_id; skip if already processed |
| User sends message mid-payment | main.py | Check status='awaiting_payment'; send "Complete payment first or /cancel" |
| Callback for closed conversation | main.py | Answer callback "This conversation is already closed" |
| Bot restart mid-conversation | main.py | status read from DB on next message; conversation resumes correctly |
