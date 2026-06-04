# Plan 8 — Web API

**Builds:** FastAPI channel with 6 REST endpoints — same core logic as Telegram, no frontend  
**Depends on:** Plan 7 complete (MVP validated, at least 20 paying users)  
**Time:** ~1 day

---

## State Before
`channels/web_api.py` is a placeholder with comments. FastAPI is installed but only serves `/health` and `/webhook` (Telegram) and `/stripe-webhook`.

## State After
6 REST endpoints live at `/api/*`. Any website or mobile app can drive the full TURN conversation flow by calling these endpoints sequentially. Telegram bot is unchanged — both channels call the same `core/conversation.py`.

---

## All Decisions Already Made

- No frontend built here — API only. The API is the deliverable. A website's frontend developer (or future-me) builds the UI later.
- Stateless from client's perspective — no sessions, no cookies. Each call includes `conversation_id`. Server holds state in DB.
- Auth for MVP: a static API key in `Authorization: Bearer {key}` header. One key for the website, one for any other client. Set `WEB_API_KEY` in env. Add proper OAuth later if needed.
- CORS: allow all origins at MVP (`*`) — tighten after real domain is known
- Image upload via multipart form OR base64 JSON — support both
- `conversation_id` in all responses after `/analyze` — client must pass it in all subsequent calls
- Error responses: `{"error": "error_code", "message": "human readable"}` — consistent shape

---

## Epic 1 — Web API Channel

### Task 8.1 — `channels/web_api.py`

```python
import base64
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import config
from core.conversation import ConversationOrchestrator
from core import db, prompts

# This file adds routes to the shared fastapi_app from main.py
# Import the app from main.py and add routes here, OR use a router

from fastapi import APIRouter

router = APIRouter(prefix="/api")
orchestrator = ConversationOrchestrator()

# --- Auth ---

async def verify_api_key(authorization: str = Header(None)):
    if not config.WEB_API_KEY:
        return  # no key configured = no auth (dev mode)
    if authorization != f"Bearer {config.WEB_API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key")

# --- Models ---

class AnalyzeRequest(BaseModel):
    text: Optional[str] = None
    image_base64: Optional[str] = None

class AnswerRequest(BaseModel):
    conversation_id: int
    key: str    # 'goal' | 'met' | 'inv'
    value: str

class OutcomeRequest(BaseModel):
    conversation_id: int
    outcome: str  # 'met' | 'still_texting' | 'ghosted' | 'gave_up'

# --- Endpoints ---

@router.post("/analyze", dependencies=[Depends(verify_api_key)])
async def analyze(req: AnalyzeRequest, user_telegram_id: Optional[int] = None):
    """
    Step 1: Analyze a conversation screenshot or text.
    Pass either `text` (pasted conversation) or `image_base64` (base64-encoded image).
    Returns ghost risk, signals, vertical, and conversation_id for subsequent calls.
    
    user_telegram_id is optional — only needed if this web user has a linked Telegram account.
    For web-only users, create an anonymous user record.
    """
    # For web users: create/get an anonymous user by a stable identifier
    # Simplest MVP: require a user_id query param (e.g. device fingerprint or email hash)
    # For now: create a new user per analyze call (not ideal but works for MVP)
    
    # Use telegram_id=-1 for web users to distinguish from Telegram users
    # Better: add a `source` field to users table in future
    web_user_id = user_telegram_id or -1  # placeholder
    user = db.get_or_create_user(web_user_id, username="web_user")

    try:
        if req.image_base64:
            image_bytes = base64.b64decode(req.image_base64)
            conv = await orchestrator.analyze_screenshot(user['id'], image_bytes)
        elif req.text:
            conv = await orchestrator.analyze_text(user['id'], req.text)
        else:
            raise HTTPException(status_code=400, detail="Provide either text or image_base64")
    except ValueError:  # unreadable image
        raise HTTPException(status_code=422, detail="Could not read the image. Try a clearer screenshot.")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="AI service unavailable. Try again.")

    import ast
    signals = ast.literal_eval(conv['signals']) if conv['signals'] else []

    return {
        "conversation_id": conv['id'],
        "ghost_risk": conv['ghost_risk'],
        "signals": signals,
        "vertical": conv['vertical'],
    }

@router.post("/questions", dependencies=[Depends(verify_api_key)])
async def get_next_question(conversation_id: int):
    """
    Step 2: Get the next question to ask the user.
    Call repeatedly until `question` is null (all answered, scripts are ready).
    """
    conv = db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    question_key = orchestrator.get_current_question_key(conv)

    if question_key is None:
        return {"question": None, "scripts_ready": False, "generating": True}

    q = prompts.QUESTIONS[question_key]
    return {
        "question": q['text'],
        "options": [{"value": v, "label": l} for v, l in q['options']],
        "step": question_key,
        "scripts_ready": False
    }

@router.post("/answer", dependencies=[Depends(verify_api_key)])
async def submit_answer(req: AnswerRequest):
    """
    Step 3: Submit an answer to a question.
    After submitting, call /questions again to get the next question.
    When /questions returns scripts_ready=true, call /scripts/{id}.
    """
    conv = db.get_conversation(req.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    orchestrator.store_answer(req.conversation_id, req.key, req.value)

    # Check if all questions are now answered
    updated_conv = db.get_conversation(req.conversation_id)
    next_key = orchestrator.get_current_question_key(updated_conv)

    if next_key is None:
        # Trigger script generation async
        import asyncio
        asyncio.create_task(orchestrator.trigger_script_generation(req.conversation_id))
        return {"next_question": None, "scripts_generating": True}

    q = prompts.QUESTIONS[next_key]
    return {
        "next_question": {
            "question": q['text'],
            "options": [{"value": v, "label": l} for v, l in q['options']],
            "step": next_key
        },
        "scripts_generating": False
    }

@router.get("/scripts/{conversation_id}", dependencies=[Depends(verify_api_key)])
async def get_scripts(conversation_id: int):
    """
    Step 4: Get the generated scripts.
    Poll this endpoint until status='awaiting_choice' (scripts are ready).
    Ultimatum is gated — set ultimatum_locked=true if not paid.
    """
    conv = db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conv['status'] == 'generating_scripts':
        return {"status": "generating", "scripts": None}

    unlocked = db.is_ultimatum_unlocked(conversation_id)
    goal = conv['goal'] or 'meetup'

    return {
        "status": conv['status'],
        "goal": goal,
        "scripts": {
            "soft": conv['soft_script'],
            "firm": conv['firm_script'],
            "ultimatum": conv['ultimatum_script'] if unlocked else None,
        },
        "ultimatum_locked": not unlocked,
        "ultimatum_label": "Goodbye Script" if goal == 'closure' else "Ultimatum",
    }

@router.post("/unlock", dependencies=[Depends(verify_api_key)])
async def unlock_ultimatum(conversation_id: int, user_telegram_id: Optional[int] = None):
    """
    Step 4b: Create Stripe checkout to unlock ultimatum.
    Returns payment_url. After payment, webhook delivers the script.
    For web users, success_url should be the website's confirmation page.
    """
    conv = db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if db.is_ultimatum_unlocked(conversation_id):
        return {"already_unlocked": True, "payment_url": None}

    import stripe_client as sc
    # For web users: no bot_username needed — use the website URL
    success_url = config.WEB_SUCCESS_URL or "https://turn.app/success"
    cancel_url  = config.WEB_CANCEL_URL  or "https://turn.app/cancel"

    session = import_stripe().checkout.Session.create(
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
            'conversation_id': str(conversation_id),
            'user_telegram_id': str(user_telegram_id or 0),
            'channel': 'web',
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return {"payment_url": session.url}

@router.post("/outcome", dependencies=[Depends(verify_api_key)])
async def submit_outcome(req: OutcomeRequest):
    """
    Final step: Record the conversation outcome.
    Call after the user reports back whether they got a response.
    """
    valid_outcomes = ('met', 'still_texting', 'ghosted', 'gave_up')
    if req.outcome not in valid_outcomes:
        raise HTTPException(status_code=400, detail=f"outcome must be one of {valid_outcomes}")

    conv = db.get_conversation(req.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.close_conversation(req.conversation_id, outcome=req.outcome)
    db.log_ml_label(req.conversation_id)

    ghost_risk = conv['ghost_risk'] or 50
    messages = {
        'met':          "That's the one. You pushed, it worked.",
        'still_texting': "Still in motion — come back if it stalls again.",
        'ghosted':       f"Ghost risk was {ghost_risk}%. You got your answer. That's the win.",
        'gave_up':       "Moving on is also an answer. You made a decision.",
    }

    return {"outcome": req.outcome, "message": messages[req.outcome]}
```

### Task 8.2 — Add env vars to `config.py`

```python
WEB_API_KEY    = os.getenv("WEB_API_KEY")   # optional — no auth if not set
WEB_SUCCESS_URL = os.getenv("WEB_SUCCESS_URL", "https://turn.app/success")
WEB_CANCEL_URL  = os.getenv("WEB_CANCEL_URL",  "https://turn.app/cancel")
```

### Task 8.3 — Register router in `main.py`

```python
from channels.web_api import router as web_router
fastapi_app.include_router(web_router)

# Add CORS
from fastapi.middleware.cors import CORSMiddleware
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten after real domain is known
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## The API Flow (For Future Frontend Developer)

```
1. POST /api/analyze         → { conversation_id, ghost_risk, signals, vertical }
2. POST /api/questions       → { question, options, step }
3. POST /api/answer          → { next_question or scripts_generating: true }
   repeat 2-3 until next_question is null
4. GET  /api/scripts/{id}    → poll until status='awaiting_choice'
                               → { scripts: { soft, firm }, ultimatum_locked: true }
5. POST /api/unlock          → { payment_url }  (if ultimatum wanted)
   [user pays via Stripe, webhook fires, scripts/{id} will show ultimatum]
6. POST /api/outcome         → { outcome, message }
```

---

## Acceptance Criteria — Plan 8 Complete When:

- [ ] `curl -X POST /api/analyze -d '{"text":"hey how are you..."}'` returns ghost_risk and conversation_id
- [ ] Full API flow completable via curl/Postman without touching Telegram
- [ ] Telegram bot still works — no regression
- [ ] Invalid API key returns 401
- [ ] `/api/scripts/{id}` returns `ultimatum: null` and `ultimatum_locked: true` for unpaid conversations
- [ ] `/api/outcome` logs an ml_label row
- [ ] FastAPI auto-docs available at `/docs` (swagger UI)
