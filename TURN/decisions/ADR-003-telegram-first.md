# ADR-003: Telegram Bot as First Distribution Channel

**Status:** Decided  
**Date:** 2026-06-04

---

## Decision

Build the MVP as a Telegram bot, not a web app, iOS app, or Android app.

---

## Reasons

**1. No app store review process.**
iOS review takes 1-7 days and can reject for arbitrary reasons. Android is faster but still adds friction. Telegram bots are live the moment the code deploys. Speed to first user matters.

**2. No distribution problem.**
Users already have Telegram. There's no "download the app" step. Share the bot link and the user is in the product. The conversion funnel from "heard about TURN" to "first screenshot analyzed" can be under 60 seconds.

**3. Screenshot workflow is natural on Telegram.**
Users take a screenshot on their phone, open Telegram, send it to the bot. This is already a natural behavior — people share screenshots with friends all the time. TURN is just a different kind of friend.

**4. Faster iteration.**
No App Store update cycle. Deploy a fix and it's live for all users in seconds. At MVP stage, you'll iterate on prompts, copy, and flow multiple times per day.

**5. Proven infrastructure.**
python-telegram-bot is mature, async-native, well-documented, and has a large community. Bot infrastructure for Stripe webhooks, APScheduler, and SQLite is well-understood.

---

## Limitations of Telegram (Acknowledged)

**No share sheet.** Users must manually take a screenshot and send it to the bot. The mobile app's share sheet (Phase 2) will remove this friction. Telegram is acceptable for validation but not for scale.

**No push notifications.** The bot can only message users who have interacted with it recently. APScheduler reminders work because the user started the conversation — the bot is allowed to message them.

**No auto-send.** The Telegram Bot API cannot send messages to other users on a user's behalf. Scripts are always copy-paste. This is a fundamental platform constraint, not a product decision. Do not promise or build auto-send.

**Bot can be blocked.** If Telegram decides TURN violates their ToS, the bot can be banned. Mitigation: use official Bot API only, never spam, never scrape, never auto-message users who haven't opted in. This risk is low but real — the mobile app (Phase 2) removes the dependency.

---

## Why Not Web App First

A web app requires a user to be at a computer while their stalled conversation is on their phone. The workflow breaks. Dating app conversations happen on mobile — the tool must be on mobile too. Telegram is on mobile. A web app is not the right channel for this use case.

---

## Why Not Mobile App First

Validated product-market fit before spending $20k-$75k on mobile development. The Telegram bot answers the core question: will people pay to resolve conversation uncertainty? If the answer is no on Telegram, it's no on mobile too. Build mobile after proof, not before.
