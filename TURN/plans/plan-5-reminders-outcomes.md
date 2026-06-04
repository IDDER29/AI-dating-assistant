# Plan 5 — Reminders & Outcomes

**Builds:** APScheduler reminder fires at 48h → outcome question → outcome stored → ML label logged  
**Depends on:** Plan 4 complete (reminder scheduled, status='reminder_set')  
**Time:** ~1 day

---

## State Before
`schedule_reminder()` adds a job to APScheduler. `fire_reminder` is referenced but not implemented. Reminder_yes button from Plan 3 sets status but doesn't schedule anything.

## State After
- Reminder_yes → APScheduler job scheduled → fires at 48h → sends outcome question
- User taps outcome → stored in DB → ML label logged → closing message sent → status = `'closed'`
- Reminder_no → conversation closed immediately

---

## All Decisions Already Made

- APScheduler SQLite job store — jobs survive bot restarts. Set up in Plan 0. Jobs fire up to 1h late if bot was down (`misfire_grace_time=3600`).
- `fire_reminder` MUST be a module-level function (not a class method) — APScheduler serializes the dotted path and re-imports it. A lambda or instance method won't survive restart.
- Before sending reminder: check `status != 'closed'` — conversation might have been cancelled while reminder was pending.
- 4 outcome options: `met` / `still_texting` / `ghosted` / `gave_up`
- ML label logged immediately on outcome: `ghost_risk_actual = 1` if outcome in ('ghosted','gave_up') else `0`
- Closing message varies by outcome (see exact copy below)
- After outcome: `context.user_data.clear()` is NOT reliable — just set status='closed' in DB. That's enough.

---

## Epic 1 — Fire Reminder Function

### Task 5.1 — Add `fire_reminder` to `channels/telegram_bot.py`

This MUST be at module level (top-level function, not inside a class).

```python
async def fire_reminder(conv_id: int):
    """
    Called by APScheduler after 48h delay.
    Module-level function — required for APScheduler serialization.
    """
    from core.db import get_conversation, get_user_by_id, update_conversation

    conv = get_conversation(conv_id)
    if not conv or conv['status'] == 'closed':
        return  # already resolved — skip silently

    # Get user's telegram_id to send the message
    # Need a helper that gets telegram_id from user DB id
    user = get_user_by_db_id(conv['user_id'])
    if not user:
        return

    update_conversation(conv_id, status='awaiting_outcome')

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎉 Yes, we're meeting!", callback_data=f"outcome_met_{conv_id}"),
            InlineKeyboardButton("💬 Still texting",       callback_data=f"outcome_still_texting_{conv_id}"),
        ],
        [
            InlineKeyboardButton("👻 They ghosted",        callback_data=f"outcome_ghosted_{conv_id}"),
            InlineKeyboardButton("🚶 I moved on",          callback_data=f"outcome_gave_up_{conv_id}"),
        ]
    ])

    bot = get_bot()
    await bot.send_message(
        chat_id=user['telegram_id'],
        text="⏰ Hey — did they reply to your script?",
        reply_markup=kb
    )
```

### Task 5.2 — Add `get_user_by_db_id` to `core/db.py`

```python
def get_user_by_db_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None
```

### Task 5.3 — Fix APScheduler job reference in `core/scheduler.py`

APScheduler needs the full dotted path to the function. Update `schedule_reminder`:

```python
def schedule_reminder(conv_id: int, hours: int = 48):
    from datetime import datetime, timedelta
    import random
    scheduler = get_scheduler()
    run_time = datetime.now() + timedelta(hours=hours) + timedelta(seconds=random.randint(0, 30))
    scheduler.add_job(
        func='channels.telegram_bot:fire_reminder',
        trigger='date',
        run_date=run_time,
        args=[conv_id],
        id=f'reminder_{conv_id}',
        replace_existing=True
    )
```

**Verify:** APScheduler can import `channels.telegram_bot:fire_reminder` by running `python -c "from channels.telegram_bot import fire_reminder; print('OK')"`.

---

## Epic 2 — Reminder_yes Handler (complete Plan 3 stub)

### Task 5.4 — Update `reminder_yes` in `handle_callback` (`channels/telegram_bot.py`)

Replace the Plan 3 stub:

```python
elif action_value == 'reminder_yes':
    from core.db import update_conversation
    from core.scheduler import schedule_reminder
    update_conversation(conv_id, status='reminder_set', reminder_set=1)
    schedule_reminder(conv_id, hours=48)
    await query.message.reply_text("Done. I'll check in with you in 48 hours. Good luck — you've done your part.")

elif action_value == 'reminder_no':
    from core.db import update_conversation
    update_conversation(conv_id, status='closed')
    await query.message.reply_text("Got it. Come back anytime with a new screenshot. /start")
```

---

## Epic 3 — Outcome Collection

### Task 5.5 — Add outcome handler to `handle_callback` (`channels/telegram_bot.py`)

Add this routing block:

```python
elif action_value.startswith('outcome_'):
    outcome_value = action_value[8:]  # strip 'outcome_'
    await handle_outcome(query.message, conv, outcome_value)
```

```python
async def handle_outcome(message, conv: dict, outcome: str):
    """
    Records outcome. Logs ML label. Sends closing message.
    outcome: 'met' | 'still_texting' | 'ghosted' | 'gave_up'
    """
    from core.db import update_conversation, log_ml_label, close_conversation

    conv_id   = conv['id']
    ghost_risk = conv['ghost_risk'] or 50

    close_conversation(conv_id, outcome=outcome)
    log_ml_label(conv_id)

    # Closing messages — exact copy
    messages = {
        'met': (
            "That's the one. 🎉\n\n"
            "You pushed, it worked.\n\n"
            "Come back next time you need a script. /start"
        ),
        'still_texting': (
            "Still in motion — that's something.\n\n"
            "If it stalls again, come back. /start"
        ),
        'ghosted': (
            f"You already had your answer before you sent that message.\n"
            f"The ghost risk was {ghost_risk}%. You sent it anyway — that took clarity.\n\n"
            "You saved yourself days of wondering. That's the win.\n\n"
            "When you're ready for the next one, send a new screenshot. /start"
        ),
        'gave_up': (
            "Moving on is also an answer.\n\n"
            "You made a decision — that's better than waiting indefinitely.\n\n"
            "Whenever you're ready for the next one. /start"
        ),
    }

    await message.reply_text(messages.get(outcome, "Conversation closed. /start"))
```

---

## Acceptance Criteria — Plan 5 Complete When:

- [ ] After free script selection + reminder_yes → job appears in APScheduler job store
- [ ] Job survives bot restart — verify by restarting and checking `select * from apscheduler_jobs`
- [ ] Manually trigger `fire_reminder(conv_id)` → outcome question appears in Telegram
- [ ] All 4 outcome buttons work — each records the correct value in DB
- [ ] After outcome tapped: `conversations.outcome` = the selected value
- [ ] After outcome tapped: `conversations.status` = `'closed'`
- [ ] `ml_labels` table has a new row for the conversation
- [ ] `ml_labels.ghost_risk_actual` = 1 for 'ghosted'/'gave_up', 0 for 'met'/'still_texting'
- [ ] Closing message for 'ghosted' includes the ghost risk number
- [ ] Closing message for 'met' includes the celebration line
- [ ] Fire reminder when conv is already closed → nothing happens (silent skip)
- [ ] For end-to-end: set APScheduler delay to 1 minute in `.env` (add `REMINDER_HOURS=0.017`) for testing, then reset to 48
