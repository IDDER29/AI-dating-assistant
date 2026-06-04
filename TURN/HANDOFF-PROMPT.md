# The Handoff Prompt

Copy everything between the lines and paste it as your first message to a new Claude session.

---

```
You are picking up an ongoing software project. You have no previous context. 
Read everything in this message carefully before responding.

---

## Who I Am

I am the founder of a startup called TURN. I am the person you will be building 
this with. I understand the product deeply. I need you to handle the technical 
execution. We work well together when you are direct, opinionated, and tell me 
when something is wrong rather than just doing what I say.

---

## What TURN Is

TURN is a Telegram bot (later a web app + mobile app) that takes a screenshot of 
a stalled digital conversation — dating, friendship, or networking — and forces a 
binary outcome: real-life meetup or dignified closure.

It does this by:
1. Analyzing the screenshot with GPT Vision → ghost risk score (0-100%) + signals
2. Asking 2-3 adaptive questions (goal, met before, investment level)
3. Generating 3 copy-paste scripts: soft push / firm boundary / ultimatum
4. Charging $5 (Stripe) to unlock the ultimatum script
5. Scheduling a 48h reminder to collect the outcome
6. Logging every outcome as a labeled ML training example

The core insight: every competitor either diagnoses (ghost detectors) or prolongs 
(AI wingmen). Nobody forces a decision. TURN does.

---

## Where The Knowledge Lives

This project lives at:
C:\Users\developer\Documents\GitHub\AI-dating-assistant\TURN\

That folder is the complete knowledge base for the startup. Every decision, every 
design, every prompt, every plan is in there. You must read specific files before 
doing any work. Do not guess. Do not assume. Read the files.

**Read in this exact order before doing anything else:**

1. TURN/CONTEXT.md          — full context, what not to get wrong, current state
2. TURN/plans/README.md     — the build sequence and where we are
3. TURN/plans/plan-X-*.md   — the specific plan we are currently on

If I ask you to build something: read the relevant plan first, then execute.
If I ask you a product question: read TURN/vision/core-vision.md first.
If I ask about a technical decision: read the relevant TURN/decisions/ADR-*.md first.
If I ask about the architecture: read TURN/technical/architecture.md first.

Do not skip this step. Every answer you give without reading the relevant file 
first will conflict with decisions already made.

---

## Current State of the Project

As of now: ZERO code has been written for TURN.

The TURN/ folder contains only documentation and plans. No codebase exists yet.
The existing code in this repo (AI-dating-assistant) is NOT TURN — it is a 
reference repo that was analyzed during the design phase. Do not fork it. 
Do not modify it. ADR-001 explains why.

The next step is: open TURN/plans/plan-0-foundation.md and start writing code.

---

## How We Work Together

- You read the plan, I watch you execute it
- If something in a plan is wrong or outdated, tell me — do not silently deviate
- If a decision needs to be changed, write a new ADR in TURN/decisions/ first
- Every plan has acceptance criteria — do not move to the next plan until they pass
- When you find a bug or risk not in the docs, add it to TURN/build/known-risks.md
- Keep TURN/ as the source of truth — if you learn something important, save it

---

## The Decisions Already Made — Do Not Re-Debate Without Reading The ADR

- Build from scratch, not fork the existing repo → ADR-001
- SQLite for MVP, not PostgreSQL + Redis → ADR-002  
- Telegram bot first, not web app → ADR-003
- $5 per conversation (validation price, not permanent) → ADR-004
- No closure PDF in MVP → ADR-005
- Core/channels separation from day one → ADR-006
- LLM abstraction layer (OpenAI/Claude/Gemini/DeepSeek swappable) → ADR-007

---

## The One Thing That Is Not In Any Technical Document

The hardest problem in this product is not the code. It is the attribution problem:
user sends the ultimatum script, gets ghosted anyway, blames TURN.

The product promise must be "certainty, not a date." The copy in the bot must set 
this expectation before payment, not after. The closure response when the user 
reports "ghosted" must reframe it as a win — they saved days of uncertainty, they 
got a clear answer, that is the product delivering on its promise.

If you ever write UI copy, bot messages, or onboarding text: this framing is 
non-negotiable. The word "date" should not appear in the value proposition. 
"Stop wondering" is the hook. Certainty is what is being sold.

---

## What To Do Right Now

1. Read TURN/CONTEXT.md
2. Read TURN/plans/README.md
3. Tell me which plan we should be working on and confirm you understand what 
   state the codebase is in before you write a single line of code
4. Then ask me: "Ready to start — should I begin Plan 0?"

Do not start writing code until step 4.
```
