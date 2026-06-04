# MVP Scope — Authoritative Definition

> This document is the single source of truth for what is and is not in the MVP.
> If something is not listed here as IN, it is OUT. No exceptions without a new ADR.

---

## What MVP Is

A Telegram bot that takes a screenshot of a stalled conversation and produces:
1. A ghost risk score with 2-3 signals
2. Three copy-paste scripts (soft push, firm boundary, ultimatum)
3. A 48h follow-up reminder
4. An outcome log entry

The ultimatum script requires a $5 Stripe payment to unlock.

That is the entire product.

---

## IN Scope

| Feature | Description | Notes |
|---------|-------------|-------|
| `/start` command | Welcome + onboarding message | Upsert user in DB |
| Screenshot ingestion | User sends photo to bot | Compress before sending to OpenAI |
| Text fallback | User sends raw text instead of image | Skip vision, go straight to questioning |
| GPT-4 Vision OCR | Extract conversation text + ghost risk + signals | Returns JSON |
| Ghost risk display | Show score (0-100%) + 2-3 signals to user | Before questioning starts |
| Agentic questioning | 2-3 adaptive multiple-choice questions | Goal → Met before → Investment (conditional) |
| Script generation | GPT-4 generates soft/firm/ultimatum | All three generated upfront, gated on payment |
| Free script delivery | Soft + firm scripts, copy-paste | No payment required |
| Premium unlock | $5 Stripe payment unlocks ultimatum | One-time per conversation |
| Auto-reminder | APScheduler job fires after 48h | Asks "Did they reply?" |
| Outcome collection | 4 outcome buttons after reminder | met / still_texting / ghosted / gave_up |
| Outcome logging | Store outcome in SQLite | Critical for future ML |
| Script rejection | User can reject any script, get one regeneration | Log rejection reason |
| One active conversation limit | User cannot start new conv while one is active | `/cancel` to abandon |
| `/delete_my_data` | GDPR deletion command | Deletes all user rows |
| Error handling | Retry on OpenAI timeout, clear error messages | No silent failures |

---

## OUT of Scope (MVP)

| Feature | Why Excluded | When to Add |
|---------|-------------|-------------|
| Closure PDF | Only triggered on ghosted+premium path. <5 users hit this in first month. Too much work for too little return. | Phase 1 hardening |
| Subscription pricing | Validate willingness to pay at all before optimizing price structure | Phase 1 hardening |
| Multi-conversation support | Adds complex state management. One conv at a time is fine for validation. | Phase 1 |
| Voice profiles / tone memory | Premium feature that requires user history. No history yet. | Phase 2 mobile |
| Simulator | Different product entirely. Different retention mechanics. | Phase 3 |
| Calendar integration | Requires OAuth. Adds weeks of complexity. | Phase 2 mobile |
| Mobile app | Can't validate product-market fit via app store. Telegram removes distribution friction. | Phase 2 |
| Redis | SQLite + APScheduler SQLite job store is sufficient for MVP scale. No ops overhead. | Phase 1 if >50 concurrent users |
| PostgreSQL | Same — SQLite handles MVP scale cleanly | Phase 1 |
| B2B API | Zero leverage without consumer proof of demand | Phase 5 |
| Multi-language support | English first. | Post Series A |
| Analytics dashboard | Founders check DB directly at MVP scale | Phase 1 |

---

## Conversation State Machine

States a conversation can be in. The `status` column in `conversations` table always reflects this.

```
analyzing
    ↓ (vision OCR complete)
questioning
    ↓ (all answers collected)
generating_scripts
    ↓ (scripts ready)
awaiting_choice
    ↓ (user picks script)
    ├── [soft/firm] → awaiting_reminder_confirm
    │       ↓ (user says yes/no to reminder)
    │       → reminder_set OR closed_no_reminder
    └── [ultimatum] → awaiting_payment
            ↓ (Stripe webhook)
            → reminder_set
    └── [reject] → awaiting_rejection_reason
            ↓ (reason collected)
            → regenerating
                ↓
                awaiting_choice  (back to choice with new script)
                    ↓ (second rejection)
                    → offer_reminder_without_script

[all paths with reminder_set]
    ↓ (48h later, scheduler fires)
awaiting_outcome
    ↓ (user picks outcome)
closed
```

Every inbound message must first resolve current `status` from DB and route accordingly. State is never assumed from in-memory context alone (see `../decisions/ADR-002-sqlite-not-postgres.md` for why DB-as-state-source is the right pattern at MVP).

---

## Data Retention Policy

| Data | Retention | Reason |
|------|-----------|--------|
| Raw screenshot images | Deleted immediately after OCR | Privacy — images of other people's messages |
| `extracted_text` | 30 days then nulled | Needed for script quality; not needed permanently |
| `ghost_risk`, `signals` | Permanent | ML training data |
| `scripts` (all three) | Permanent | Effectiveness measurement |
| `outcome` | Permanent | Core ML label |
| `rejection_reason` | Permanent | Prompt improvement |
| User `telegram_id` | Until `/delete_my_data` | Identity |

---

## Success Metrics for MVP

The MVP is validated when:
1. **20 paying users** have completed the Stripe $5 payment (not free users, not signups — payments)
2. **Outcome data exists** for at least 50 conversations (proves the reminder loop works)
3. **At least 5 users** have returned for a second conversation (proves product has repeat value)

If metric 1 is not hit within 4 weeks of launch, the price or the core value proposition needs revisiting before building Phase 1. Do not proceed to Phase 1 on hope.
