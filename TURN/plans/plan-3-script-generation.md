# Plan 3 — Script Generation

**Builds:** GPT-4o generates 3 scripts → displayed with inline buttons → free soft/firm delivered  
**Depends on:** Plan 2 complete (all answers stored, status='generating_scripts')  
**Time:** ~1 day

---

## State Before
Status = `'generating_scripts'` after questions. "Generating scripts..." message was sent. Bot does nothing after that.

## State After
Bot calls GPT-4o with conversation + answers → stores 3 scripts in DB → sends them with buttons → user can tap soft or firm → receives the script text + reminder offer → status = `'awaiting_reminder_confirm'`.

---

## All Decisions Already Made

- Scripts are generated once and stored. Never regenerated on refresh (only on explicit rejection in Plan 6).
- Max 40 words per script — enforced in prompt. Users don't send long scripts.
- No emojis in generated scripts — users can add them. Coach models directness.
- When `goal = 'closure'`: button labels change in UI only. Data field `ultimatum_script` still stores the goodbye script. The DB schema doesn't change.
- Ultimatum button shows lock icon and "$5" — not unlocked until payment (Plan 4).
- After free script selected: always offer 48h reminder. User says yes/no. Both are valid.
- If `goal = 'closure'`: rename "Ultimatum" → "Goodbye Script" in button text only.
- `status` after scripts shown = `'awaiting_choice'`

---

## The Exact Prompt

```python
SCRIPT_SYSTEM_PROMPT = """
You are TURN, a direct conversation coach. Generate 3 scripts the user can copy and paste.

Context:
- Conversation: {conversation_text}
- Goal: {goal}
- Met in person: {met_before}
- Ghost risk: {ghost_risk}%
- Investment (1-10): {investment}
- Conversation type: {vertical}

Return ONLY valid JSON:
{{
  "soft_push": "...",
  "firm_boundary": "...",
  "ultimatum": "..."
}}

Rules:
1. Each script under 40 words
2. No emojis, no exclamation marks, no sycophantic openers
3. Every script must move toward a concrete decision (specific day, time, or yes/no)
4. Tone: dating=warm+direct, friendship=casual, networking=professional, unknown=neutral
5. If ghost_risk > 70: all three scripts use firmer language than normal

If goal is 'closure':
  soft_push    = gentle farewell  ("It's been a while — no hard feelings if things changed")
  firm_boundary = direct close    ("I don't think this is going anywhere. Take care.")
  ultimatum    = final goodbye    ("I'll take the silence as a no. Genuinely wish you well.")

If goal is 'meetup':
  soft_push    = casual ask with specific option  ("Free Wednesday? Want to grab coffee.")
  firm_boundary = ask with deadline               ("I need a yes or no by tomorrow, either is fine.")
  ultimatum    = decision demand                  ("I'll check back in 24h — no reply means I'm moving on, no hard feelings.")

If goal is 'advice':
  soft_push    = soft check-in    ("Hey, still thinking about us meeting up?")
  firm_boundary = direct ask      ("Are we still on for something, or has the moment passed?")
  ultimatum    = clarity demand   ("I need to know where this stands. A yes or no works for me.")
"""
```

---

## Epic 1 — Orchestrator: Script Generation

### Task 3.1 — Add to `core/conversation.py`

```python
import json
import logging
from core import db, prompts
from core.llm_client import script_client

async def generate_scripts(self, conv_id: int) -> dict:
    """
    Generates 3 scripts via LLM. Stores in DB. Returns conv dict.
    Called after all questions answered (status='generating_scripts').
    """
    conv = db.get_conversation(conv_id)
    if not conv:
        raise ValueError(f"Conversation {conv_id} not found")

    goal       = conv['goal'] or 'advice'
    met_before = 'yes' if conv['met_before'] else 'no'
    ghost_risk = conv['ghost_risk'] or 50
    investment = conv['investment_score'] or 5
    vertical   = conv['vertical'] or 'unknown'
    conv_text  = conv['extracted_text'] or '(no text available)'

    system = prompts.SCRIPT_SYSTEM_PROMPT.format(
        conversation_text=conv_text[:2000],  # cap at 2000 chars to control token cost
        goal=goal,
        met_before=met_before,
        ghost_risk=ghost_risk,
        investment=investment,
        vertical=vertical
    )

    raw = await self._complete_with_retry(script_client, system, "Generate the 3 scripts now.", json_mode=True)

    try:
        scripts = json.loads(raw)
    except json.JSONDecodeError:
        logging.error(f"Script gen bad JSON for conv {conv_id}: {raw}")
        raise RuntimeError("Script generation failed — bad JSON")

    soft      = scripts.get('soft_push', '')
    firm      = scripts.get('firm_boundary', '')
    ultimatum = scripts.get('ultimatum', '')

    db.update_conversation(conv_id,
        soft_script=soft,
        firm_script=firm,
        ultimatum_script=ultimatum,
        status='awaiting_choice'
    )

    logging.info(f"conv={conv_id} scripts generated ok")
    return db.get_conversation(conv_id)

async def _complete_with_retry(self, client, system: str, user: str, json_mode: bool = False) -> str:
    import asyncio
    for attempt in range(2):
        try:
            return await client.complete(system, user, json_mode=json_mode)
        except Exception as e:
            if attempt == 0:
                logging.warning(f"LLM attempt 1 failed: {e} — retrying")
                await asyncio.sleep(3)
            else:
                logging.error(f"LLM failed after retry: {e}")
                raise RuntimeError("AI unavailable") from e
```

Also update `trigger_script_generation` stub from Plan 2:

```python
async def trigger_script_generation(self, conv_id: int) -> None:
    db.update_conversation(conv_id, status='generating_scripts')
    # Now actually generate — this was a stub in Plan 2
    await self.generate_scripts(conv_id)
    # Note: The Telegram channel polls for status change or we call back directly.
    # Pattern: generate_scripts returns the conv, channel sends the scripts.
    # So trigger_script_generation should return the conv for the channel to use.
```

**Better pattern** — make `trigger_script_generation` return the conv so the channel can send scripts immediately:

```python
async def trigger_script_generation(self, conv_id: int) -> dict:
    db.update_conversation(conv_id, status='generating_scripts')
    return await self.generate_scripts(conv_id)
```

Update `ask_next_question` in `channels/telegram_bot.py` to use the return value:

```python
if question_key is None:
    await msg.reply_text("Generating your scripts... ✍️")
    conv = await orchestrator.trigger_script_generation(conv_id)
    await send_scripts(msg, conv)   # new function — see Task 3.2
    return
```

---

## Epic 2 — Telegram: Script Display

### Task 3.2 — Add `send_scripts` to `channels/telegram_bot.py`

```python
async def send_scripts(message, conv: dict):
    """Formats and sends the 3 scripts with inline keyboard."""
    conv_id = conv['id']
    goal    = conv['goal'] or 'meetup'

    soft      = conv['soft_script'] or '(not available)'
    firm      = conv['firm_script'] or '(not available)'

    # Label for ultimatum changes if goal is closure
    if goal == 'closure':
        soft_label      = '💬 Gentle Exit'
        firm_label      = '⚡ Direct Close'
        ultimatum_label = '🔒 Goodbye Script ($5)'
    else:
        soft_label      = '💬 Soft Push'
        firm_label      = '⚡ Firm Boundary'
        ultimatum_label = '🔒 Ultimatum ($5)'

    text = (
        f"Here are your 3 options. Copy the one that fits.\n\n"
        f"{soft_label[2:]}:\n{soft}\n\n"     # strip emoji for script body display
        f"{firm_label[2:]}:\n{firm}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(soft_label,      callback_data=f"script_soft_{conv_id}"),
            InlineKeyboardButton(firm_label,       callback_data=f"script_firm_{conv_id}"),
        ],
        [
            InlineKeyboardButton(ultimatum_label,  callback_data=f"script_ultimatum_{conv_id}"),
            InlineKeyboardButton("👎 Not for me",  callback_data=f"script_reject_{conv_id}"),
        ]
    ])

    await message.reply_text(text, reply_markup=keyboard)
```

### Task 3.3 — Handle free script selection in `handle_callback`

Add these cases to the routing block in `handle_callback`:

```python
elif action_value == 'script_soft' or action_value == 'script_firm':
    script_type = 'soft' if action_value == 'script_soft' else 'firm'
    await handle_free_script_selected(query.message, context, conv, script_type)

elif action_value == 'script_ultimatum':
    # Plan 4 handles payment — for now, show placeholder
    await query.message.reply_text("Payment coming in the next update. Stay tuned!")

elif action_value == 'script_reject':
    # Plan 6 handles rejection
    await query.message.reply_text("Rejection handling coming in Plan 6.")
```

```python
async def handle_free_script_selected(message, context, conv: dict, script_type: str):
    """User selected soft or firm (free). Send the script. Offer reminder."""
    conv_id = conv['id']
    script_text = conv['soft_script'] if script_type == 'soft' else conv['firm_script']

    from core.db import update_conversation
    update_conversation(conv_id, chosen_script_type=script_type)

    await message.reply_text(
        f"Copy and send this:\n\n{script_text}"
    )

    # Offer reminder
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Set 48h reminder", callback_data=f"reminder_yes_{conv_id}"),
        InlineKeyboardButton("Skip",                callback_data=f"reminder_no_{conv_id}"),
    ]])
    await message.reply_text(
        "I'll check back in 48 hours to see if they replied.",
        reply_markup=kb
    )
    update_conversation(conv_id, status='awaiting_reminder_confirm')
```

Add reminder_yes / reminder_no to `handle_callback` (stub — Plan 5 fills in scheduler logic):

```python
elif action_value == 'reminder_yes':
    # Plan 5 adds scheduler call here
    from core.db import update_conversation
    update_conversation(conv_id, status='reminder_set')
    await query.message.reply_text("Done. I'll check in with you in 48 hours. Good luck.")

elif action_value == 'reminder_no':
    from core.db import update_conversation
    update_conversation(conv_id, status='closed')
    await query.message.reply_text("Got it. Come back anytime with a new screenshot.")
```

---

## Acceptance Criteria — Plan 3 Complete When:

- [ ] After all questions answered → "Generating your scripts..." appears
- [ ] 1-3 seconds later → 3 scripts appear with 4 buttons (Soft, Firm, Ultimatum, Not for me)
- [ ] Scripts are under 40 words each
- [ ] Scripts contain no emojis
- [ ] When `goal = 'closure'`: buttons say "Gentle Exit", "Direct Close", "Goodbye Script"
- [ ] Tapping Soft or Firm → script text appears as a plain message
- [ ] Reminder offer appears with Yes/Skip buttons
- [ ] DB `soft_script`, `firm_script`, `ultimatum_script` all populated
- [ ] DB `chosen_script_type` set to 'soft' or 'firm' after selection
- [ ] Status = `'awaiting_reminder_confirm'` after script selected
- [ ] Ultimatum button tap → placeholder message (Payment in Plan 4)
