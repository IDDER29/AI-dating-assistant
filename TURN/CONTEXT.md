# To Future Me — Full Context

> Read this before anything else. This is what no other document captures.

---

## What This Is

You are looking at a startup called TURN. It is a Telegram bot (later a web app) that takes a screenshot of a stalled digital conversation and forces a binary outcome: real-life meetup or dignified closure.

The founder is the person you are talking to right now. They own the `polikhronidi/AI-dating-assistant` repo that this folder lives in. That repo is NOT the product — it is the starting point that was analyzed, documented, and then decided against forking. TURN is built from scratch in a new repo. This folder (`TURN/`) is the knowledge base, not the code.

---

## The Journey That Got Here

This was not a quick brainstorm. Here is what actually happened before the plans were written:

1. The existing repo (`AI-dating-assistant`) was fully analyzed — architecture, code quality, failure modes, security, performance. All of that is in `docs/` in the parent directory.

2. From that analysis, a product gap was identified: the existing repo acts *as* the user (sends messages on their behalf). TURN does the opposite — it coaches the user and never sends anything itself.

3. A full startup vision was developed: market analysis, competitor teardown, monetization model, investment thesis. All captured in `TURN/vision/` and `TURN/market/`.

4. The technical architecture was designed from scratch: core/channels separation, LLM abstraction, SQLite-first, APScheduler with persistent job store. All in `TURN/technical/` and `TURN/decisions/`.

5. Seven architecture decisions were made and recorded as ADRs. Do not re-debate them without reading the ADR first.

6. Then the plans were written — 11 of them, each self-contained with exact code.

The founder is non-technical enough to need the plans to be executable without interpretation, but sharp enough to have driven the product thinking precisely. Treat them as a product partner who understands the "why" deeply but needs the "how" spelled out.

---

## The Things That Are Easy To Get Wrong

**1. The pricing model has a bug that must not be re-introduced.**
Early docs described `premium_until = now + 1 year` on a $5 payment. That gives one $5 payment permanent premium status. The correct model is: ultimatum is gated per-conversation via the `payments` table (`WHERE conversation_id=? AND status='completed'`). `premium_until` is reserved for the future subscription. ADR-004 explains this in full.

**2. The fork decision is final.**
The existing repo uses Pyrogram. TURN uses python-telegram-bot. Different libraries, different mental models, different everything. The value of the existing repo is reference-only — the error handling patterns and typing delay logic. Nothing else is worth inheriting. ADR-001.

**3. Auto-send is permanently impossible.**
Telegram Bot API cannot send messages to other users on a user's behalf. This comes up naturally when thinking about features. The answer is always no. Scripts are always copy-paste. Document does not build auto-send under any framing.

**4. The Stripe webhook signature check is not optional.**
It is one line: `stripe.Webhook.construct_event(payload, sig_header, secret)`. Without it, anyone can POST a fake "payment succeeded" event and unlock the ultimatum for free. Plan 4 and `TURN/build/known-risks.md` both cover this. It must be the first line of the webhook handler.

**5. APScheduler must use the SQLite job store, not in-memory.**
In-memory jobs are lost on restart. A bot restart at hour 47 of a 48h reminder window means that user never gets their reminder and never reports an outcome. No outcome = no ML label = the data moat doesn't build. One line fix: `SQLAlchemyJobStore(url=config.DATABASE_URL)`. Plan 0 sets this up.

**6. `fire_reminder` must be a module-level function.**
APScheduler serializes the function path to the job store and re-imports it on recovery. It cannot serialize a lambda, a class method, or a nested function. The function must be importable as `channels.telegram_bot:fire_reminder`. Plan 5 covers this.

---

## What The Founder Cares About Most

From the conversations that produced all this documentation:

- They want to **build the technical thing correctly** — they are not cutting corners on architecture
- They think in **product terms** very naturally — the "force a binary outcome" insight, the attribution problem, the pricing signal issue — all came from them
- They agreed with the recommendation to **build from scratch** without pushback, which means they trust technical judgment here
- The **website / web API** matters to them for distribution reasons (shareable, no Telegram required) — that's why Plan 8 exists and why the core/channels separation was built in from day one
- They want the **LLM to be swappable** — not because they're indecisive, but because they understand the market is moving fast and don't want to be locked in
- The **$5 validation price** is understood as temporary — they know it needs to go up after proof

---

## What Is Not Built Yet

As of the time this was written (June 2026), zero code has been written for TURN. The plans folder is the entire output of the design phase. The next step is opening `TURN/plans/plan-0-foundation.md` and writing the first line of code.

The existing `AI-dating-assistant` repo has a complete, working Telegram bot. It is not TURN. It is not being forked. It is a reference.

---

## The One Thing That Could Make This Fail

Not technical. Not competitive. 

The attribution problem: user sends the ultimatum script, gets ghosted anyway, blames TURN. "I paid $5 and still got ghosted."

This is the hardest product design challenge. The copy must set expectations correctly before payment. The ghost risk score must feel like evidence, not a prediction. The closure response when outcome='ghosted' must reframe the result as a win, not a failure.

The product promise is: **certainty, not a date**. Ghost risk 74% means you probably knew. Sending the script forces the answer. Getting ghosted after sending is not failure — it is confirmation of what you already suspected, delivered quickly instead of over weeks.

If the copy in the bot doesn't communicate this before the user pays, the product will have a refund and reputation problem even if the AI is excellent.

This cannot be solved in the plans. It can only be solved by watching real users react and iterating the copy. Beta test (Plan 7, Task 7.13) is where this gets figured out.

---

## How To Pick Up This Work

1. Read this file (done)
2. Read `TURN/plans/README.md` — the sequence of plans and what state the codebase is in after each
3. Open `TURN/plans/plan-0-foundation.md` and execute the tasks in order
4. If you need context on a decision: `TURN/decisions/ADR-00X-*.md`
5. If you need context on the product: `TURN/vision/core-vision.md`
6. If you need the exact prompts: `TURN/technical/ai-design.md`

Do not start with the vision docs. Start with Plan 0. The vision is already decided. The execution is what remains.

---

## One Last Thing

The founder chose to start from a solid ground rather than build from scratch without context. That choice was right. The analysis of the existing repo revealed exactly what to keep (the Telegram infrastructure patterns), what to replace (the goal), and what to avoid (the Pyrogram library, the fork path). 

The documentation in this folder is the result of that choice paying off. Use it.
