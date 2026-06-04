# Plan 2 — Agentic Questioning

**Builds:** 2-3 adaptive questions → inline keyboards → answer storage → triggers script gen  
**Depends on:** Plan 1 complete (ghost risk displayed, status='questioning')  
**Time:** ~1 day

---

## State Before
Bot shows ghost risk. `ask_next_question()` is a placeholder that does nothing.

## State After
Bot asks goal → met_before → investment_score (conditional on ghost_risk > 60). All answers stored in DB. After last answer, status = `'generating_scripts'` and script generation is triggered (Plan 3 implements the actual generation — Plan 2 just triggers it).

---

## All Decisions Already Made

- Exactly 3 question steps max: `ask_goal` → `ask_met` → `ask_investment`
- Third question (`ask_investment`) only asked if `ghost_risk > 60`
- Questions use inline keyboard buttons, not free text (except investment_score which uses number buttons 1-10)
- Callback data format: `"{action}_{value}_{conv_id}"` — always include conv_id to survive bot restarts
- After all answers collected: call `orchestrator.trigger_script_generation(conv_id)` — Plan 3 implements that method; Plan 2 just calls it
- When `goal = 'closure'`: script buttons will later say "Gentle Exit / Direct Close / Goodbye Script" instead of "Soft / Firm / Ultimatum" — Plan 2 stores the goal, Plan 3 uses it
- If user closes app mid-question and comes back: bot reads status from DB and resumes the right question

---

## The Question Flow (Exact Logic)

```
Status: 'questioning'
  Step determined by what's NULL in conversations row:
    goal IS NULL          → ask_goal
    met_before IS NULL    → ask_met  
    investment IS NULL AND ghost_risk > 60  → ask_investment
    else                  → all done → trigger_script_generation()
```

This logic means: on any incoming message/callback while status='questioning', check the DB to know which question to send. Never rely on in-memory step tracking.

---

## Epic 1 — Question Definitions

### Task 2.1 — Add to `core/prompts.py`

```python
# Question definitions — used by both Telegram and Web API channels
QUESTIONS = {
    'ask_goal': {
        'text': "What's your main goal here?",
        'options': [
            ('goal_meetup',   '📅 Get a real meetup'),
            ('goal_closure',  '🚪 Get closure / end it cleanly'),
            ('goal_advice',   '💭 Just want to know where I stand'),
        ]
    },
    'ask_met': {
        'text': "Have you met this person in real life?",
        'options': [
            ('met_yes', "Yes, we've met before"),
            ('met_no',  'No, still online only'),
        ]
    },
    'ask_investment': {
        'text': "Last one: how much would it sting if they never replied?\n(1 = barely care, 10 = genuinely hurt)",
        'options': [(f'inv_{i}', str(i)) for i in range(1, 11)]
    }
}
```

---

## Epic 2 — Orchestrator: Question Routing

### Task 2.2 — Add to `core/conversation.py`

```python
def get_current_question_key(self, conv: dict) -> str | None:
    """
    Returns the question key that should be asked next, or None if all answered.
    Always derived from DB state — never from in-memory tracking.
    """
    if conv['goal'] is None:
        return 'ask_goal'
    if conv['met_before'] is None:
        return 'ask_met'
    if conv['investment_score'] is None and (conv['ghost_risk'] or 0) > 60:
        return 'ask_investment'
    return None  # all done

def store_answer(self, conv_id: int, callback_action: str, callback_value: str) -> None:
    """
    Maps callback action → DB field and stores it.
    callback_action: 'goal' | 'met' | 'inv'
    callback_value: the value part of the callback data
    """
    if callback_action == 'goal':
        db.update_conversation(conv_id, goal=callback_value)
    elif callback_action == 'met':
        db.update_conversation(conv_id, met_before=1 if callback_value == 'yes' else 0)
    elif callback_action == 'inv':
        db.update_conversation(conv_id, investment_score=int(callback_value))

async def trigger_script_generation(self, conv_id: int) -> None:
    """
    Called when all questions are answered.
    Sets status to generating_scripts.
    Plan 3 replaces this stub with real generation logic.
    """
    db.update_conversation(conv_id, status='generating_scripts')
    # Plan 3 adds: await self.generate_scripts(conv_id)
```

---

## Epic 3 — Telegram: Question Display & Callback Routing

### Task 2.3 — Update `channels/telegram_bot.py`

Replace the `ask_next_question` placeholder and add callback handler.

```python
from core.prompts import QUESTIONS
from core.db import get_conversation, update_conversation

async def ask_next_question(update_or_message, context, conv_id: int):
    """
    Sends the next unanswered question to the user.
    Called after screenshot analysis and after each answer.
    update_or_message: either an Update or a Message object.
    """
    conv = get_conversation(conv_id)
    if not conv:
        return

    question_key = orchestrator.get_current_question_key(conv)

    if question_key is None:
        # All questions answered — trigger script generation
        await orchestrator.trigger_script_generation(conv_id)
        # Show "generating" message — Plan 3 will send the scripts
        msg = update_or_message if hasattr(update_or_message, 'reply_text') else update_or_message.message
        await msg.reply_text("Generating your scripts... ✍️")
        # Plan 3 will intercept status='generating_scripts' and continue
        return

    q = QUESTIONS[question_key]
    keyboard = _make_keyboard(q['options'], conv_id)

    msg = update_or_message if hasattr(update_or_message, 'reply_text') else update_or_message.message
    await msg.reply_text(q['text'], reply_markup=keyboard)


def _make_keyboard(options: list, conv_id: int) -> InlineKeyboardMarkup:
    """
    options: list of (callback_value, label) tuples
    callback_data format: "{callback_value}_{conv_id}"
    e.g. "goal_meetup_42", "met_yes_42", "inv_7_42"
    """
    # Split into rows of max 3 buttons
    rows = []
    row = []
    for i, (value, label) in enumerate(options):
        row.append(InlineKeyboardButton(label, callback_data=f"{value}_{conv_id}"))
        if len(row) == 3 or i == len(options) - 1:
            rows.append(row)
            row = []
    return InlineKeyboardMarkup(rows)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Central callback router. Parses all button taps.
    Callback data format: "{action}_{value}_{conv_id}" OR "{action}_{conv_id}" for simple actions.
    """
    query = update.callback_query
    await query.answer()  # removes loading state — ALWAYS do this first

    data = query.data
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)

    # --- Parse callback data ---
    # Format examples:
    #   "goal_meetup_42"    → action=goal, value=meetup, conv_id=42
    #   "met_yes_42"        → action=met, value=yes, conv_id=42
    #   "inv_7_42"          → action=inv, value=7, conv_id=42
    #   "cancel_conv"       → action=cancel_conv (no conv_id needed)
    #   "noop"              → do nothing

    if data == "noop":
        return

    if data == "cancel_conv":
        active = get_active_conversation(user['id'])
        if active:
            from core.db import update_conversation
            update_conversation(active['id'], status='closed')
        await query.message.reply_text("Cancelled. Send a new screenshot whenever you're ready.")
        return

    # All other callbacks have conv_id as last segment
    parts = data.rsplit('_', 1)
    if len(parts) != 2:
        return
    action_value, conv_id_str = parts[0], parts[1]
    try:
        conv_id = int(conv_id_str)
    except ValueError:
        return

    # Verify this conversation belongs to this user
    conv = get_conversation(conv_id)
    if not conv or conv['user_id'] != user['id']:
        await query.message.reply_text("This conversation has expired.")
        return

    # Route by action prefix
    if action_value.startswith('goal_'):
        _value = action_value[5:]  # strip 'goal_'
        orchestrator.store_answer(conv_id, 'goal', _value)
        await ask_next_question(query.message, context, conv_id)

    elif action_value.startswith('met_'):
        _value = action_value[4:]  # strip 'met_'
        orchestrator.store_answer(conv_id, 'met', _value)
        await ask_next_question(query.message, context, conv_id)

    elif action_value.startswith('inv_'):
        _value = action_value[4:]  # strip 'inv_'
        orchestrator.store_answer(conv_id, 'inv', _value)
        await ask_next_question(query.message, context, conv_id)

    # Plan 3 adds: script_soft, script_firm, script_ultimatum, script_reject
    # Plan 4 adds: reminder_yes, reminder_no
    # Plan 5 adds: outcome_*

# Update build_application to register callback handler
def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
```

### Task 2.4 — Handle numeric text input for investment question

In `handle_active_conversation_text` (the placeholder in Plan 1), fill in:

```python
async def handle_active_conversation_text(update, context, active):
    """Handles text while conversation is active — only used for investment_score numeric input."""
    text = update.message.text.strip()
    conv = active

    # Only accept numeric input during ask_investment step
    question_key = orchestrator.get_current_question_key(conv)
    if question_key == 'ask_investment':
        try:
            val = int(text)
            if 1 <= val <= 10:
                orchestrator.store_answer(conv['id'], 'inv', str(val))
                await ask_next_question(update.message, context, conv['id'])
                return
        except ValueError:
            pass
        await update.message.reply_text("Please pick a number between 1 and 10.")
    else:
        # Unexpected text during questioning — ignore or re-ask
        await ask_next_question(update.message, context, conv['id'])
```

---

## Acceptance Criteria — Plan 2 Complete When:

- [ ] After ghost risk display, bot immediately asks "What's your main goal?" with 3 buttons
- [ ] Tapping goal button → bot asks "Have you met in real life?"
- [ ] If `ghost_risk > 60`: tapping met button → bot asks investment question (1-10)
- [ ] If `ghost_risk <= 60`: tapping met button → skips to "Generating scripts..." (Plan 3 continues from there)
- [ ] Tapping investment button → "Generating scripts..."
- [ ] DB `conversations` row has `goal`, `met_before`, `investment_score` (if asked) all set correctly
- [ ] Conversation `status` = `'generating_scripts'` after all answers
- [ ] Bot restart mid-question: user sends any message → bot re-sends the correct current question
- [ ] Sending `/cancel` during questioning → conversation closed, user can start fresh
