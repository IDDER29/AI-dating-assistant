# Feature Registry

> Every feature TURN has, will have, or considered and rejected.
> Status: MVP | Phase1 | Phase2 | Phase3 | Rejected
> This file is append-only. Never delete rejected features — the reasoning matters.

---

## Layer 1 — Conversion Engine

| Feature | Status | Description |
|---------|--------|-------------|
| Screenshot ingestion | MVP | User sends photo to bot; bot downloads + compresses |
| Text paste fallback | MVP | User pastes raw conversation text; skips vision step |
| GPT-4 Vision OCR | MVP | Extracts text + ghost risk + signals + vertical detection |
| Ghost risk score (0-100%) | MVP | Displayed to user before questioning |
| Signal display (2-3 signals) | MVP | Named signals from fixed vocabulary for ML consistency |
| Vertical auto-detection | MVP | dating / friendship / networking detected from screenshot |
| Agentic questioning (2-3 questions) | MVP | Goal → Met before → Investment (conditional on ghost_risk) |
| Script generation (3 scripts) | MVP | Soft push / firm boundary / ultimatum via GPT-4 |
| Closure script mode | MVP | When goal=closure, scripts reframe as goodbye messages |
| Free script delivery | MVP | Soft + firm scripts, copy-paste, no payment |
| Premium unlock ($5) | MVP | Ultimatum / goodbye script requires Stripe payment |
| 48h reminder | MVP | APScheduler job fires, asks "Did they reply?" |
| Outcome collection | MVP | 4 options: met / still_texting / ghosted / gave_up |
| Script rejection + regen | MVP | One regeneration per conversation with reason |
| Outcome logging → ML labels | MVP | ml_labels table populated on conversation close |
| /cancel command | MVP | Abandons active conversation |
| /delete_my_data command | MVP | GDPR deletion |
| One active conversation limit | MVP | Enforced in code |

---

## Phase 1 Additions (Weeks 5-8)

| Feature | Status | Description |
|---------|--------|-------------|
| Closure PDF report | Phase1 | PDF with ghost risk, timeline, goodbye script |
| extracted_text nulling (30-day) | Phase1 | Scheduled cleanup for privacy |
| Subscription pricing ($19.99/mo) | Phase1 | Monthly plan alongside $5 one-time |
| Rate limiting per user | Phase1 | Prevent abuse, control OpenAI costs |
| Admin commands | Phase1 | /stats, /manual_premium for founder use |
| Error monitoring (Sentry) | Phase1 | Crash reporting and error tracking |

---

## Phase 2 Additions (Mobile App)

| Feature | Status | Description |
|---------|--------|-------------|
| iOS share sheet | Phase2 | Receive conversation directly from any app |
| On-device ghost risk (Core ML) | Phase2 | Privacy: no image upload needed |
| Push notifications | Phase2 | Native reminders (not bot messages) |
| Calendar integration | Phase2 | Suggest specific meetup times from user calendar |
| Voice profiles | Phase2 | Save personal communication style for tone-adaptive scripts |

---

## Phase 3 Additions (Simulator)

| Feature | Status | Description |
|---------|--------|-------------|
| Scenario selection | Phase3 | User picks: first date ask / friend flake / networking |
| AI persona (other person) | Phase3 | GPT plays the other side of the conversation |
| Difficulty setting | Phase3 | Controls AI responsiveness (easy/medium/hard) |
| Micro-feedback | Phase3 | After each exchange: "try an open question", "good warmth" |
| Charisma Score | Phase3 | Tracks improvement across sessions |

---

## Rejected Features

| Feature | Why Rejected |
|---------|-------------|
| Auto-send scripts | Telegram Bot API cannot send messages to other users. Technically impossible. Rejected permanently. |
| Universal messaging aggregator | Beeper/Sunbird path. Platform blocks (Apple, Google) are existential. Rejected permanently. |
| Profile scraping / matching | Turns TURN into a dating app. Different product, different cold-start problem. Rejected. |
| Real-time conversation monitoring | Would require continuous access to the user's messages. Privacy and platform policy violation. Rejected. |
| Relationship advice / therapy | TURN is tactical, not therapeutic. Out of scope. |
| Read receipt tracking | Passive surveillance that doesn't lead to action. Diagnosis without resolution. Rejected. |
| Multi-conversation support (MVP) | Adds state machine complexity at MVP stage. Deferred to Phase 1. Not rejected permanently. |
| B2B API (early) | Zero leverage without consumer proof. Dating apps have conflicting incentives. Deferred to Phase 5. |
