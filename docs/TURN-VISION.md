# TURN: The Conversation Conversion Engine
### *From digital text to real-life meetup – for dating, friendship, and networking.*

**Document Version:** 1.0
**Date:** June 2026
**Status:** Startup Blueprint — Confidential

---

## 1. Executive Summary

**TURN** is a platform-agnostic AI coach that converts stagnant digital conversations (dating apps, WhatsApp, LinkedIn, SMS) into real-life meetups — or provides dignified closure. Unlike ghosting detectors that only diagnose or AI wingmen that prolong texting, TURN forces a binary outcome: **meet or end**.

The core innovation is a three-layer architecture:

- **Layer 1 – Conversion Engine:** Screenshot analysis → ghost risk score → one-tap scripts (soft push, firm boundary, ultimatum) → auto-reminders → closure report.
- **Layer 2 – Social Skills Simulator:** Private, AI-powered roleplay to practice conversations and receive real-time feedback.
- **Layer 3 – Multi-Vertical:** Works for dating, friendship, and professional networking, auto-detecting context.

The MVP (Telegram bot) is built by forking and modifying the open-source `polikhronidi/AI-dating-assistant` — inheriting its realistic dialogue engine and state management, then replacing its "brain" with proprietary agentic questioning and script generation.

**Market opportunity:** 50-80% of daters experience ghosting; 1 in 10 adults have zero close friends; 99% of LinkedIn outreach dies. The social skills training market is $31B+. 62% of users would pay $10-20 to resolve uncertainty.

**Monetization:** Freemium — free ghost risk + soft scripts; premium at **$19.99/month** (or $5 one-time per conversation) for ultimatum scripts, auto-reminders, scheduling bridge, simulator, and closure reports.

**Ask:** $150,000 seed for full mobile app development, AI fine-tuning, and initial user acquisition.

---

## 2. The Problem

### 2.1 Pain Points

| Vertical | Problem | Data |
|----------|---------|------|
| **Dating** | Ghosting, future-faking, endless pen-pal loops | 50-80% ghosted; avg 4 ghostings/year; 79% of Gen Z report burnout |
| **Friendship** | "We should hang out" never materializes | 1 in 10 adults have zero close friends; Bumble BFF meets only 25% of the time |
| **Networking** | LinkedIn conversations die after first reply | 99% of outreach fails to convert to a coffee chat |

### 2.2 Why Existing Solutions Fail

| Category | Example | Flaw |
|----------|---------|------|
| Ghost detectors | Lucen, NoBlueTick | Diagnose but don't act → "you're being ghosted, good luck" |
| AI wingmen | RizzGPT, FireTexts | Optimize for more texting, not meeting — prolong the pen-pal cycle |
| Universal chat apps | Beeper, Sunbird | Died due to security nightmares and platform walled gardens |
| Social skills trainers | SpeakUp, Zocia | Practice in a vacuum, no real-world outcome tie |
| Anti-ghosting dating apps | Swept, After | Require users to leave existing apps (cold-start problem) |

**The gap:** No tool forces a decision (meet or close) across any messaging platform while teaching better conversation skills.

---

## 3. The Solution

### 3.1 Core Value Proposition

> *"Stop wondering. Get a date or get closure — in 3 texts or less."*

TURN is a **personal AI coach** that:

1. **Analyzes** any chat screenshot (from any app) and calculates a **Ghost Risk Score** (0-100%).
2. **Asks 2-3 adaptive questions** (goal, met before, investment level) to personalize the approach.
3. **Generates three scripts** — soft push, firm boundary, ultimatum — that the user can copy/paste.
4. **Schedules auto-reminders** to follow up (48h for free users, 24h for premium).
5. **Provides a closure report** (PDF) if no reply, plus a dignified goodbye message.
6. **Trains users** via a virtual simulator (premium) where they practice conversations with adjustable difficulty and receive real-time feedback.

### 3.2 The Three Layers

```
Layer 1 — Conversion Engine (MVP core)
  Screenshot upload → GPT-4 Vision extracts text + ghost risk
  Agentic questions (goal, context, tone preference)
  Script generation: soft / firm / ultimatum
  Reminder scheduler
  Outcome logging (meetup / ghosted / gave up)

Layer 2 — Simulator (premium, post-MVP)
  User chooses scenario + difficulty
  AI plays the other person
  Micro-feedback after each exchange
  "Charisma Score" tracks improvement over time

Layer 3 — Multi-Vertical (built into all layers)
  Auto-detects conversation type from screenshot content
  Adjusts script style (casual, professional, etc.)
  Same engine, all relationships
```

### 3.3 Unique Features — Competitive Moat

| Feature | Competitors | TURN |
|---------|-------------|------|
| Ghost detection | Passive risk score | Active resolution + ultimatum |
| Scripts | Generic pickup lines | Goal-adaptive, rejection-aware, tone-tuned |
| Follow-up | None or manual | Automatic reminder + closure message |
| Platform | Single app | Any app via screenshot |
| Training | Separate apps | Integrated simulator tied to real outcomes |
| Data moat | None | Labeled conversation outcomes for fine-tuning |

---

## 4. Market Opportunity

### 4.1 Total Addressable Market

| Segment | Market Size |
|---------|-------------|
| Online dating users (global) | 400M+ active users |
| Social skills training | $31B (growing to $60B+ by 2033) |
| AI companion / coaching | $120M (2025) |
| **Focused TAM** (English-speaking, willing to pay) | ~50M users |

### 4.2 Demand Signals

- Ghosting rates: 50-80% of users experience ghosting; 35% develop long-term self-doubt
- Friend recession: 10% of adults have no close friends (up 4x from 1990)
- LinkedIn failure: 99% of outreach messages never lead to a meeting
- Willingness to pay: survey (n=500) showed 62% would pay $10-20 to resolve uncertainty
- Burnout: 79% of Gen Z report dating app fatigue, primarily due to ghosting

### 4.3 Competitive Landscape

| Competitor | Type | Weakness |
|------------|------|----------|
| Lucen | Chat analyzer | No action scripts |
| RizzGPT | AI wingman | No ghost risk, no meetup forcing |
| Bumble BFF | Friendship app | No conversion tool for existing chats |
| Shapr | Networking app | No follow-up engine |
| SpeakUp | Social skills training | No real-world tie |

**Blue Ocean:** No one combines ghost risk + action scripts + simulator + multi-vertical + platform-agnostic.

---

## 5. Monetization

### 5.1 Freemium Model

| Feature | Free | Premium ($19.99/mo) |
|---------|------|---------------------|
| Ghost risk score | 3 chats/month | Unlimited |
| Soft / firm scripts | Yes | Yes |
| Ultimatum script | No | Yes |
| Auto-reminder | Basic (48h, manual) | Smart (24h, auto-follow-up) |
| Closure report (PDF) | No | Yes |
| Simulator | 5 min/month | Unlimited |
| Voice profile / tone memory | No | Yes |
| Multi-vertical | Limited | Full |

One-time option: **$5 per ultimatum chat** for low-frequency users.

### 5.2 B2B API (Future)

License the conversion engine to dating apps (Hinge, Bumble) to reduce user churn. Pricing: $0.10 per successful meetup or flat monthly fee.

### 5.3 Unit Economics (per premium user)

| Metric | Value |
|--------|-------|
| CAC (initial) | $5 (organic + referral) |
| Monthly subscription | $19.99 |
| Gross margin | ~85% |
| LTV (avg 6 months) | $120 |
| LTV/CAC | 24x |

---

## 6. Competitive Moat & Defensibility

### Short-Term (MVP Stage)
- First mover in "action-accelerator" category
- Screenshot-based (no API integration) → works on any chat app instantly
- Agentic questioning (adaptive, not static) → harder to copy than a simple prompt

### Long-Term (12-18 months)
- **Proprietary labeled dataset:** Every conversation outcome feeds the ML pipeline. After 10,000 labeled examples, the ghost risk model and script generator outperform generic GPT-4.
- **Fine-tuned on-device models:** Mobile app runs ghost risk classifier locally → privacy advantage + no API latency
- **User voice profiles:** Premium users save their tone (switching costs)
- **Partnerships:** License conversion engine to dating apps (B2B API)

### Why Incumbents Won't Copy Quickly
- Dating apps (Tinder, Hinge) have conflicting incentives — they want users to stay in the app, not meet offline
- General AI companies don't focus on niche behavioral applications
- Social media giants have privacy and trust barriers to analyzing private messages

---

## 7. Roadmap & Milestones

| Phase | Timeline | Deliverables | Cost |
|-------|----------|--------------|------|
| **0. Pre-MVP** | 2 weeks | Fork `AI-dating-assistant`, replace prompts, add agentic questions, integrate Stripe $5. Telegram bot with 100 beta users. | $500 |
| **1. MVP Launch** | Week 4 | Public Telegram bot, 1,000 users, 20% conversion to $5. Outcome tracking enabled. | $2,000 |
| **2. Mobile App (iOS)** | Month 3 | Native app with share sheet, on-device ghost risk (Core ML), calendar sync, push notifications. | $20,000 |
| **3. Simulator & Premium** | Month 5 | Virtual practice + feedback engine, $19.99 subscription. | $15,000 |
| **4. Android & Scale** | Month 7 | Android app, referral program, influencer marketing. | $25,000 |
| **5. B2B API** | Month 10 | License to dating apps; hire sales team. | $40,000 |

**Total to profitability:** ~$100,000.

---

## 8. Risks & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Users don't want to pay | Medium | High | MVP validates with $5 one-time before subscription |
| Telegram bot banned | Low | Medium | Use official Bot API; eventual mobile app reduces reliance |
| GPT costs too high | Low | Medium | Cache frequent requests; fine-tune smaller model for ghost risk |
| Competitor copies | Medium | Medium | Build moat via labeled data + voice profiles + on-device models |
| Privacy backlash | Low | High | Delete images immediately; on-device processing; transparent GDPR policy |
| User doesn't get meetup | High | Low | Product promise is "clarity or meetup" — closure is also a win |

---

## 9. Investment Ask

### Use of Funds ($150,000 Seed Round)

| Category | % | Amount | Description |
|----------|---|--------|-------------|
| Engineering (mobile app) | 50% | $75,000 | Full-stack + iOS development (3 months) |
| AI fine-tuning & API credits | 20% | $30,000 | Label 5,000 conversations, fine-tune ghost risk model |
| Marketing & user acquisition | 20% | $30,000 | TikTok/Reddit ads, influencer partnerships, referral program |
| Legal & operations | 5% | $7,500 | Terms of service, privacy policy, Stripe setup |
| Contingency | 5% | $7,500 | Unforeseen costs |

### Milestones for Series A ($1.5M)
- 50,000 MAU
- 10% conversion to premium ($19.99)
- $100k MRR
- iOS + Android apps live
- B2B pilot with one dating app

### Terms (Indicative)
- Pre-money valuation: $2M – $3M (angel / pre-seed)
- Raise: $150k for 5-7% equity (convertible note or SAFE with 20% discount)

---

## 10. Conclusion

TURN is not another dating app or ghost detector. It is the first **action-acceleration platform** that bridges the gap between digital conversation and real-life connection — for dating, friendship, and networking. The problem is massive, the current solutions are broken, and the technical path is clear (leveraging open-source foundations).

**Next step:** Build and validate the Telegram bot MVP in 2 weeks, charging $5 per ultimatum chat. Real payment conversion is the only validation metric that matters at this stage.
