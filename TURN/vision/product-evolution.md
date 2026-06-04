# Product Evolution

## The Arc: Three Distinct Phases

TURN is not built all at once. Each phase has a single validation gate that must be passed before the next phase begins. Never start Phase N+1 if Phase N's gate is unproven.

---

## Phase 0 — Telegram Bot MVP (Weeks 1-4)

**What it is:** A Telegram bot. User sends screenshot, gets ghost risk + 3 scripts, pays $5 for ultimatum, gets a reminder. That's the entire product.

**Validation gate:** Do real users pay $5 to unlock the ultimatum script? Not "would you pay" (survey) but actual Stripe charges. Target: 20 paying users in the first 2 weeks after launch.

**Why Telegram first:**
- No app store, no review process, no distribution lag
- Bot infrastructure is mature and well-documented
- Users already live in Telegram
- Can be rebuilt or replaced without affecting users (they just get a new bot link)

**What's deliberately excluded:**
- Closure PDF (week 4 polish that almost nobody hits in first month)
- Subscription pricing (validate willingness to pay at all before optimizing price)
- Simulator (different product)
- Multi-user conversations (one active conv per user)

See `../product/mvp-scope.md` for the authoritative in/out list.

---

## Phase 1 — MVP Hardening (Weeks 5-8)

**Triggered by:** 20+ paying users, recurring usage patterns emerging from outcome data.

**What changes:**
- Move from SQLite to PostgreSQL (Neon or Supabase) when concurrent users exceed SQLite's safe range (~50 simultaneous)
- Add subscription pricing ($15-20/month) alongside the $5 one-time option — test both
- First look at outcome data: which ghost risk bands actually correlate with ghosting? Start calibrating prompts.
- Add `/delete_my_data` command (GDPR compliance, not optional once real users exist)
- Add rate limiting per user (prevent abuse, control OpenAI costs)

**Validation gate:** Is there a cohort of users who come back with a second conversation? Retention > 0 means the product has stickiness beyond first use.

---

## Phase 2 — Mobile App iOS (Month 3)

**Triggered by:** Telegram bot has 500+ MAU and retention evidence.

**Why this is the right next step:**
- Share sheet integration: user is in Hinge, taps share, TURN opens — no screenshot needed
- On-device ghost risk classifier (Core ML): eliminates image upload, solves privacy completely
- Push notifications: proactive reminders without user initiating
- Better UX: inline keyboards in Telegram are clunky for 10-option selections

**What the mobile app adds technically:**
- Share extension (iOS) to receive conversation from any app
- Local OCR + ghost risk model (privacy-first)
- Calendar integration for scheduling meetup suggestions
- Native push for reminders

**What it does not add yet:**
- Simulator
- Android (Phase 3)
- B2B API

**Validation gate:** App store conversion rate >3% from landing page. iOS before Android because iOS users have higher willingness to pay.

---

## Phase 3 — Simulator & Subscription (Month 5)

**Triggered by:** Mobile app live, $5k+ MRR.

**What the Simulator is:**
- User picks a scenario (first date ask, friend who keeps flaking, networking follow-up)
- Picks difficulty (easy / medium / hard — controls how responsive the AI persona is)
- AI plays the other person
- After each exchange: micro-feedback ("you asked a closed question — try open-ended")
- Tracks "Charisma Score" over sessions

**Important:** The simulator is a different product with different retention mechanics. It's not an extension of Layer 1 — it's a complementary product that shares infrastructure. Do not conflate them in product thinking.

**Why it justifies subscription:** The simulator only has value over time. Users return to practice, track improvement. That creates the recurring habit that makes $19.99/month defensible.

**Validation gate:** Simulator users have 2x retention of non-simulator users.

---

## Phase 4 — Android & Scale (Month 7)

Standard expansion. By this point the product is proven. Android opens the market that iOS excludes (most of the world).

Referral program makes sense here — users who successfully meet someone have a powerful story to share.

---

## Phase 5 — B2B API (Month 10+)

**The honest assessment:** This is the most uncertain phase and may never happen.

Dating apps have conflicting incentives — they want engagement (time in app), TURN wants conversion (meetup). Hinge is the exception ("designed to be deleted") but even Hinge's business model depends on subscription revenue from users who haven't met yet.

The realistic B2B path is not selling to Tinder or Hinge. It's selling to:
- HR tech companies (networking/LinkedIn use case)
- Social skills training platforms (they have the distribution, we have the AI)
- Corporate "professional relationship building" tools

Do not plan for B2B API until the B2C product has 10k+ MAU. The API has zero leverage without proof of consumer demand.

---

## What Never Gets Built (Design Decisions That Close Doors)

**Universal messaging aggregator:** Beeper and Sunbird both tried. Apple actively blocked them. Google changed its policies. The platform risk is existential. Screenshot-based approach exists specifically to avoid this path — never revisit it.

**Auto-send:** Telegram Bot API cannot send messages to other users on a user's behalf. Mobile apps could theoretically do this via accessibility APIs but it creates privacy and app store policy violations. TURN is a coach, not an actor. Copy-paste is the only delivery mechanism.

**Profile scraping / matching:** This would turn TURN into a dating app. TURN has no interest in the cold-start, matching, or discovery problems. It only serves existing conversations that have already started elsewhere.
