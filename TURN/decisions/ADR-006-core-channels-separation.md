# ADR-006: Core/Channels Separation (API-First Architecture)

**Status:** Decided  
**Date:** 2026-06-04

---

## Context

The original architecture had all logic in `main.py` — Telegram handlers, business logic, and DB calls all mixed together. This creates a rewrite problem: when a website is added, the business logic has to be extracted from Telegram-specific code under time pressure. That's the expensive path.

The question: should we design for multiple delivery channels from day one, even though only Telegram exists at MVP?

---

## Decision

Yes. Separate business logic (`core/`) from delivery channels (`channels/`) from day one.

The cost is low (a folder structure and one extra import level). The benefit is that adding a web API later is a weekend of work, not a rewrite.

---

## Why a Web API Matters

A Telegram bot has a distribution problem. To use it, a person needs:
1. A Telegram account
2. To find the bot link
3. To understand they're using a bot

A website removes all three barriers. More importantly, a website is shareable. Someone posts their ghost risk score on Reddit or TikTok. The link goes to a web page, not a Telegram bot. That's a fundamentally different growth mechanic.

The web channel is not built at MVP — the product isn't validated yet. But the architecture must not block it.

---

## The Structure

```
core/
  conversation.py    # ConversationOrchestrator — all business logic
  db.py
  llm_client.py
  prompts.py
  scheduler.py
  utils.py

channels/
  telegram_bot.py    # Telegram handlers → calls core/
  web_api.py         # FastAPI routes → calls same core/ (future)
```

**The rule:** Nothing in `channels/` contains business logic. Nothing in `core/` imports Telegram or HTTP libraries.

---

## What the Web API Looks Like (When Built)

See `../technical/architecture.md` → REST API Design section for the full contract.

Summary: 6 stateless endpoints (`/analyze`, `/questions`, `/answer`, `/scripts`, `/unlock`, `/outcome`) that drive the same conversation state machine the Telegram bot uses. The client (website, mobile app, anything) drives the flow; the server holds state in DB.

---

## The Key Insight

A website's frontend does not need to be built now. The API contract just needs to be defined and the core logic needs to be channel-agnostic. When a frontend developer (or no-code tool, or future-me) wants to build a website, the backend is already done.

---

## Consequences

- `core/conversation.py` must have no Telegram-specific imports
- `channels/telegram_bot.py` is thin — it formats messages and calls `core/`
- Adding Android app, iOS app, WhatsApp bot, or web app in the future = write a new channel, not rewrite the core
- Slightly more indirection at MVP (one extra import level) — acceptable cost

---

## Why Not Just `main.py` For Now

"We can refactor later" is always technically true and almost always wrong in practice. The refactor happens under pressure, with users on the platform, and with urgency to ship the next feature. The cost of separating now is 30 minutes. The cost of separating later under pressure is days.
