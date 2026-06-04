# Plan 6 — Rejection & Regeneration

**Builds:** "Not for me" → reason collected → one regeneration → fallback to reminder  
**Depends on:** Plan 3 complete (scripts displayed, reject button exists)  
**Time:** ~0.5 day

---

## State Before
"Not for me" button sends placeholder message. Rejection flow doesn't exist.

## State After
User taps "Not for me" → asked why (4 options) → script regenerated once using GPT → new script shown. If user rejects again → offered reminder without script. All rejections logged in DB.

---

## All Decisions Already Made

- Only ONE regeneration. After second rejection, offer reminder without script. No infinite loop.
- 4 rejection reasons: `too_aggressive` / `too_weak` / `doesnt_sound_like_me` / `other`
- Regen uses `regen_client` (cheapest provider — DeepSeek or GPT-3.5) not `script_client`
- Regen returns plain text (not JSON) — just the new script string
- After regen: show the new script with same buttons (Soft/Firm/Ultimatum/Not for me) — but regeneration count is now 1, so tapping "Not for me" again goes to fallback
- Fallback: "You can still set a reminder without a script. Want me to check in with you in 48h?"
- Rejection count tracked by querying `script_rejections` table (not in-memory)
- Status during rejection flow: stays at `'awaiting_choice'` until resolved

---

## The Regen Prompt

```python
REGEN_SYSTEM_PROMPT = """
You are TURN, a conversation coach. The user rejected the script you generated.

Previous script: {previous_script}
Rejection reason: {rejection_reason}
Goal: {goal}
Conversation type: {vertical}

Rejection reasons mean:
- too_aggressive: Lower pressure. More open-ended. Less ultimatum energy.
- too_weak: More direct. Add a concrete ask or deadline. Less "let me know."
- doesnt_sound_like_me: Simpler, more casual language. Same intent, less formal.
- other: Completely different approach. Change the structure entirely.

Write ONLY the new script. No JSON. No explanation. No quotes. Just the script text.
Under 40 words. No emojis.
"""
```

---

## Epic 1 — Orchestrator: Regeneration

### Task 6.1 — Add to `core/conversation.py`

```python
async def regenerate_script(self, conv_id: int, rejected_type: str, reason: str) -> str:
    """
    Regenerates a single script based on rejection reason.
    Logs rejection to DB. Returns new script text.
    """
    from core.llm_client import regen_client

    conv = db.get_conversation(conv_id)
    previous = conv.get(f'{rejected_type}_script') or conv.get('soft_script') or ''
    goal     = conv['goal'] or 'advice'
    vertical = conv['vertical'] or 'unknown'

    system = prompts.REGEN_SYSTEM_PROMPT.format(
        previous_script=previous,
        rejection_reason=reason,
        goal=goal,
        vertical=vertical
    )

    new_script = await self._complete_with_retry(regen_client, system, "Write the improved script now.", json_mode=False)
    new_script = new_script.strip().strip('"')  # clean up any stray quotes

    db.log_rejection(conv_id, rejected_type, reason, regen=new_script)
    return new_script
```

Add `REGEN_SYSTEM_PROMPT` to `core/prompts.py` (exact text from above).

---

## Epic 2 — Telegram: Rejection Flow

### Task 6.2 — Update `script_reject` in `handle_callback` (`channels/telegram_bot.py`)

Replace the Plan 3 placeholder:

```python
elif action_value == 'script_reject':
    from core.db import get_rejection_count
    rejection_count = get_rejection_count(conv_id)

    if rejection_count >= 1:
        # Second rejection — offer reminder without script
        await handle_second_rejection(query.message, conv_id)
        return

    # First rejection — ask why
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Too aggressive",       callback_data=f"rr_too_aggressive_{conv_id}"),
            InlineKeyboardButton("Too weak",             callback_data=f"rr_too_weak_{conv_id}"),
        ],
        [
            InlineKeyboardButton("Doesn't sound like me", callback_data=f"rr_doesnt_sound_like_me_{conv_id}"),
            InlineKeyboardButton("Other",                 callback_data=f"rr_other_{conv_id}"),
        ]
    ])
    await query.message.reply_text("What didn't work?", reply_markup=kb)
    from core.db import update_conversation
    update_conversation(conv_id, status='awaiting_rejection_reason')
```

Add `rr_*` routing to `handle_callback`:

```python
elif action_value.startswith('rr_'):
    reason = action_value[3:]  # strip 'rr_'
    await handle_rejection_reason(query.message, context, conv, reason)
```

```python
async def handle_rejection_reason(message, context, conv: dict, reason: str):
    """User gave rejection reason. Regenerate script. Show new one."""
    conv_id      = conv['id']
    rejected_type = conv.get('chosen_script_type') or 'soft'  # which script they were looking at

    await message.reply_text("Rewriting... ✍️")

    try:
        new_script = await orchestrator.regenerate_script(conv_id, rejected_type, reason)
    except RuntimeError:
        await message.reply_text("AI is busy. Try again in 30 seconds.")
        return

    # Show the new script with same buttons
    goal = conv['goal'] or 'meetup'
    if goal == 'closure':
        label = "Goodbye Script (revised)"
    else:
        label = "Script (revised)"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Use this",              callback_data=f"use_regen_{conv_id}")],
        [InlineKeyboardButton("Skip — just set reminder", callback_data=f"regen_skip_{conv_id}")],
    ])

    # Store the regen script temporarily in context (or in DB)
    # Simplest: store in soft_script temporarily if it was a soft rejection
    # Better: add a regen_script column to conversations
    # MVP simplification: store in context.user_data which is fine for this session
    context.user_data[f'regen_{conv_id}'] = new_script

    await message.reply_text(
        f"Revised version:\n\n{new_script}",
        reply_markup=kb
    )
    from core.db import update_conversation
    update_conversation(conv_id, status='awaiting_choice')
```

Add `use_regen` and `regen_skip` to `handle_callback`:

```python
elif action_value == 'use_regen':
    new_script = context.user_data.get(f'regen_{conv_id}', '')
    if new_script:
        await query.message.reply_text(f"Copy and send this:\n\n{new_script}")
    # Offer reminder
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Set 48h reminder", callback_data=f"reminder_yes_{conv_id}"),
        InlineKeyboardButton("Skip",               callback_data=f"reminder_no_{conv_id}"),
    ]])
    await query.message.reply_text("I'll check back in 48 hours.", reply_markup=kb)
    from core.db import update_conversation
    update_conversation(conv_id, status='awaiting_reminder_confirm')

elif action_value == 'regen_skip':
    await handle_second_rejection(query.message, conv_id)
```

```python
async def handle_second_rejection(message, conv_id: int):
    """User rejected twice or skipped regen. Offer reminder without script."""
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Remind me in 48h", callback_data=f"reminder_yes_{conv_id}"),
        InlineKeyboardButton("No thanks",           callback_data=f"reminder_no_{conv_id}"),
    ]])
    await message.reply_text(
        "No problem — you can write your own message.\n\n"
        "Want me to check in with you in 48 hours to see how it went?",
        reply_markup=kb
    )
```

---

## Acceptance Criteria — Plan 6 Complete When:

- [ ] Tapping "Not for me" → 4 reason buttons appear
- [ ] Tapping a reason → "Rewriting..." then new script appears
- [ ] New script is different from original (different wording)
- [ ] New script is under 40 words
- [ ] `script_rejections` table has a row with the rejection reason and regenerated script
- [ ] Tapping "Not for me" a second time (or "Skip") → reminder offer appears
- [ ] Reminder offer after rejection works the same as normal reminder flow
- [ ] No third regeneration is ever offered
