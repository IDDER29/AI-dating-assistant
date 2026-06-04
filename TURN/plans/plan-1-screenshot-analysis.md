# Plan 1 — Screenshot Analysis

**Builds:** Photo handler → image compression → GPT Vision → ghost risk display  
**Depends on:** Plan 0 complete (bot runs, DB exists, LLMClient works)  
**Time:** ~1 day

---

## State Before
Bot responds to `/start`. Nothing else works. Sending a photo does nothing.

## State After
User sends a screenshot → bot compresses it → calls GPT-4o Vision → stores ghost risk + signals + extracted_text + vertical in DB → sends the user a ghost risk message with signals → conversation status = `'questioning'`.

---

## All Decisions Already Made — Don't Re-Think These

- Image compressed to max 512px before sending to OpenAI (`detail: "low"`) — saves ~80% on vision cost
- Raw image bytes are NEVER written to disk or DB — only the extracted text
- If vision returns `{"error": "unreadable"}` → ask for clearer screenshot
- Retry OpenAI once on timeout, fail gracefully on second failure
- `context.user_data` caches `conv_id` for the session but DB is always truth
- Text paste fallback: if user sends text >50 chars instead of photo, treat as raw conversation (skip vision)
- One active conversation per user — if one exists, block and offer `/cancel`

---

## Epic 1 — Image Utilities

### Task 1.1 — `core/utils.py`

```python
import base64
import io
from PIL import Image

def compress_image(image_bytes: bytes, max_size: int = 512) -> str:
    """Compress image to max_size px on longest side, return base64 string."""
    img = Image.open(io.BytesIO(image_bytes))
    
    # Convert to RGB if needed (handles PNG with alpha, etc.)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    
    # Resize keeping aspect ratio
    ratio = max_size / max(img.width, img.height)
    if ratio < 1:
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')
    # original image_bytes is not stored anywhere — GC handles it
```

**Verify:** `python -c "from core.utils import compress_image; print('utils OK')"` prints OK.

---

## Epic 2 — Vision Prompt

### Task 1.2 — Add to `core/prompts.py`

This is the exact prompt. Do not change it without updating the change log at the bottom of `TURN/technical/ai-design.md`.

```python
VISION_SYSTEM_PROMPT = """
You are TURN, a conversation analyst. Extract all visible text from this screenshot of a digital conversation. Then assess the ghosting risk.

Ghosting signals to look for:
- Response time patterns (long gaps = higher risk)
- Message length trends (getting shorter = higher risk)  
- Engagement quality (no questions asked = higher risk)
- Reciprocity (one person doing all the work = higher risk)
- Future faking ("we should definitely meet!" with no follow-through)
- Sudden drop-off after a previously active exchange

Return ONLY valid JSON, no other text:
{
  "extracted_text": "full conversation as a single string",
  "ghost_risk": integer 0-100,
  "signals": ["signal1", "signal2"],
  "vertical": "dating" | "friendship" | "networking" | "unknown"
}

Use only these signal labels (max 3):
"long delays", "short replies", "no questions asked", "future faking",
"sudden drop-off", "left on read", "one-sided effort", "decreasing enthusiasm",
"vague responses", "avoids concrete plans"

Ghost risk calibration:
0-30   = healthy, likely fine
31-60  = mild concern, could go either way
61-80  = high risk, losing momentum
81-100 = almost certainly ghosting or already ghosted

If you cannot read the screenshot:
{"error": "unreadable", "message": "Could not extract text from image"}
"""
```

---

## Epic 3 — Vision Analysis Function

### Task 1.3 — Add `analyze_screenshot` to `core/conversation.py`

Add this method to `ConversationOrchestrator`. Keep the class structure clean — one method per responsibility.

```python
import logging
import asyncio
from core import db, prompts
from core.llm_client import vision_client
from core.utils import compress_image

logger = logging.getLogger(__name__)

class ConversationOrchestrator:

    async def analyze_screenshot(self, user_id: int, image_bytes: bytes) -> dict:
        """
        Downloads nothing — receives raw bytes.
        Returns conv dict with ghost_risk, signals, vertical set.
        Raises ValueError if image unreadable.
        Raises RuntimeError on AI failure after retry.
        """
        # Compress — image_bytes goes out of scope after this, never stored
        image_b64 = compress_image(image_bytes)

        # Call vision with retry
        result = await self._vision_with_retry(image_b64)

        if result.get("error") == "unreadable":
            raise ValueError("unreadable")

        ghost_risk   = int(result.get("ghost_risk", 50))
        signals      = result.get("signals", [])
        extracted    = result.get("extracted_text", "")
        vertical     = result.get("vertical", "unknown")

        # Store in DB
        conv_id = db.create_conversation(user_id)
        db.update_conversation(
            conv_id,
            ghost_risk=ghost_risk,
            signals=str(signals),       # store as string repr, parse with eval() or json
            extracted_text=extracted,
            vertical=vertical,
            status='questioning'
        )

        logger.info(f"conv={conv_id} ghost_risk={ghost_risk} vertical={vertical}")
        return db.get_conversation(conv_id)

    async def analyze_text(self, user_id: int, text: str) -> dict:
        """
        Text paste fallback — skips vision, goes straight to questioning.
        Ghost risk estimated during script generation instead.
        """
        conv_id = db.create_conversation(user_id)
        db.update_conversation(
            conv_id,
            extracted_text=text,
            ghost_risk=50,              # neutral default — will refine in script gen
            signals="[]",
            vertical='unknown',
            status='questioning'
        )
        return db.get_conversation(conv_id)

    async def _vision_with_retry(self, image_b64: str) -> dict:
        for attempt in range(2):
            try:
                return await vision_client.vision(image_b64, prompts.VISION_SYSTEM_PROMPT)
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"Vision attempt 1 failed: {e} — retrying")
                    await asyncio.sleep(3)
                else:
                    logger.error(f"Vision failed after retry: {e}")
                    raise RuntimeError("AI vision unavailable") from e
```

---

## Epic 4 — Telegram Photo Handler

### Task 1.4 — Update `channels/telegram_bot.py`

Add these handlers. The file grows incrementally across plans — add to what exists.

```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import config
import logging
from core.db import get_or_create_user, get_active_conversation
from core.conversation import ConversationOrchestrator

logger = logging.getLogger(__name__)
orchestrator = ConversationOrchestrator()

# --- /start (already exists from Plan 0) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_or_create_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text(
        "👋 I'm TURN.\n\n"
        "Send me a screenshot of any conversation you're unsure about — "
        "dating, friendship, or work.\n\n"
        "I'll tell you the ghost risk and give you 3 scripts to move it forward.\n\n"
        "Send your screenshot to begin."
    )

# --- Photo handler (NEW in Plan 1) ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    user_id = user['id']

    # Block if active conversation exists
    active = get_active_conversation(user_id)
    if active:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Continue current", callback_data="noop"),
            InlineKeyboardButton("Cancel & start over", callback_data="cancel_conv")
        ]])
        await update.message.reply_text(
            "You have a conversation in progress. Finish it or start fresh.",
            reply_markup=kb
        )
        return

    await update.message.reply_text("Analyzing... ⏳")

    # Download image bytes — never touch disk
    photo = update.message.photo[-1]  # largest available
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()

    try:
        conv = await orchestrator.analyze_screenshot(user_id, bytes(image_bytes))
    except ValueError:  # unreadable
        await update.message.reply_text(
            "I couldn't read the conversation clearly.\n"
            "Try a screenshot with better contrast, or paste the text directly."
        )
        return
    except RuntimeError:  # AI down
        await update.message.reply_text(
            "AI is busy right now. Please try again in 30 seconds."
        )
        return

    context.user_data['conv_id'] = conv['id']

    # Send ghost risk message
    import ast
    signals = ast.literal_eval(conv['signals']) if conv['signals'] else []
    signals_text = "\n".join(f"• {s}" for s in signals) if signals else "• No strong signals detected"
    risk = conv['ghost_risk']
    emoji = "🔴" if risk >= 61 else "🟡" if risk >= 31 else "🟢"

    await update.message.reply_text(
        f"Ghost Risk: {risk}% {emoji}\n\nSignals:\n{signals_text}"
    )

    # Ask first question — implemented in Plan 2
    await ask_next_question(update, context, conv['id'])

# --- Text fallback (NEW in Plan 1) ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith('/'):
        return  # let command handlers handle it

    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    user_id = user['id']

    active = get_active_conversation(user_id)
    if active:
        # Route to question answer handler (Plan 2 handles this)
        await handle_active_conversation_text(update, context, active)
        return

    # No active conversation — if message looks like a pasted conversation, use it
    if len(text) > 50:
        await update.message.reply_text("Got it — analyzing your conversation... ⏳")
        conv = await orchestrator.analyze_text(user_id, text)
        context.user_data['conv_id'] = conv['id']
        await update.message.reply_text(
            "Conversation received. Ghost risk will be estimated based on content.\n"
            "Let me ask a few questions."
        )
        await ask_next_question(update, context, conv['id'])
    else:
        await update.message.reply_text("Send me a screenshot to get started.")

async def handle_active_conversation_text(update, context, active):
    # Placeholder — Plan 2 fills this in for investment_score numeric input
    pass

# Placeholder — Plan 2 implements this
async def ask_next_question(update, context, conv_id):
    pass

# --- Handler registration ---

def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
```

---

## Acceptance Criteria — Plan 1 Complete When:

- [ ] User sends a real screenshot → bot replies with ghost risk score + signals
- [ ] Ghost risk is an integer 0-100
- [ ] Signals are displayed as bullet points (2-3 signals)
- [ ] Conversation row exists in DB with `ghost_risk`, `signals`, `extracted_text`, `vertical` all set
- [ ] Conversation `status` = `'questioning'`
- [ ] `context.user_data['conv_id']` is set
- [ ] Sending a second screenshot while conversation is active → bot blocks and offers cancel
- [ ] Unreadable screenshot → clear error message asking for better image
- [ ] Raw image bytes are NOT written to any file or DB field (only extracted_text is stored)
- [ ] Pasting text >50 chars works as fallback
