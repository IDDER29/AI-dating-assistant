# TURN — Master Knowledge Base

> This folder is the single source of truth for the TURN startup.
> Written for future-me (Claude), not for humans.
> Every document here was earned through analysis, not generated speculatively.

---

## What Is TURN

TURN is a Telegram bot (later mobile app) that takes a screenshot of any digital conversation and forces a binary outcome: **real-life meetup or dignified closure**. It does this by scoring ghost risk, asking 2-3 adaptive questions, generating three scripts (soft / firm / ultimatum), scheduling a follow-up reminder, and logging the outcome.

The core insight: every competitor either diagnoses (ghost detectors) or prolongs (AI wingmen). Nobody forces a decision. TURN does.

Works for dating, friendship, and professional networking from the same engine.

---

## How To Use This Folder

**Starting a new session cold?** Read in this order:
1. `CONTEXT.md` — **read this first, always**. Full context, what went wrong before, what the founder cares about, what not to get wrong.
2. `README.md` (this file) — folder map and index
3. `plans/README.md` — where you are in the build sequence
4. The current plan — execute without re-reading everything else

**Resuming implementation?** Go straight to `build/implementation-plan.md`.

**Changing direction?** Write a new ADR in `decisions/` first. Never change direction without recording why.

---

## Folder Map

```
TURN/
├── README.md                        ← you are here; orientation + index
│
├── vision/
│   ├── core-vision.md               ← the product insight, the gap, the bet
│   ├── product-evolution.md         ← MVP → mobile → B2B arc
│   └── positioning.md               ← competitive moat, blue ocean analysis
│
├── product/
│   ├── mvp-scope.md                 ← exact what's in / out of MVP (authoritative)
│   ├── features.md                  ← all features across all layers
│   ├── user-personas.md             ← who uses this and why
│   └── user-journeys.md             ← step-by-step flows from user POV
│
├── market/
│   ├── opportunity.md               ← TAM, demand signals, willingness to pay
│   └── competitive-landscape.md     ← all competitors, their gaps, why they fail
│
├── technical/
│   ├── architecture.md              ← system design, components, stack decisions
│   ├── data-model.md                ← complete SQLite schema with rationale
│   ├── process-flow.md              ← full runtime sequence step by step
│   ├── ai-design.md                 ← all prompts, vision extraction, script gen, regen
│   └── integrations.md              ← Telegram, OpenAI, Stripe, APScheduler specifics
│
├── decisions/
│   ├── ADR-001-scratch-not-fork.md  ← why we build fresh, not fork the existing repo
│   ├── ADR-002-sqlite-not-postgres.md
│   ├── ADR-003-telegram-first.md
│   ├── ADR-004-pricing-model.md     ← the $5 vs subscription debate and resolution
│   └── ADR-005-pdf-deferred.md      ← why closure PDF is post-MVP
│
└── build/
    ├── implementation-plan.md       ← week-by-week task checklist
    └── known-risks.md               ← technical risks with concrete mitigations
```

---

## Current State (June 2026)

| Layer | Status |
|-------|--------|
| Vision & strategy | Complete — captured in `vision/` |
| MVP scope | Defined — captured in `product/mvp-scope.md` |
| Technical design | Complete — captured in `technical/` |
| Architecture decisions | Recorded — captured in `decisions/` |
| Code | **Not started** — next step is `build/implementation-plan.md` |

---

## Non-Negotiable Constraints

These are facts about the platform that cannot be changed by product decisions. Violating them means the feature is impossible, not just hard.

1. **Telegram bots cannot send messages to other users on a user's behalf.** No auto-send. Ever. Scripts are always copy-paste only.
2. **Screenshot images must be deleted immediately after OCR.** Never persist raw images. Privacy is the product.
3. **One active conversation per user at MVP.** Enforced in code. Simplifies state management massively.
4. **Stripe webhook must verify signature** via `stripe.Webhook.construct_event()`. Non-negotiable security requirement.

---

## Naming Conventions

- Files: `kebab-case.md`
- ADRs: `ADR-NNN-short-title.md` where NNN is zero-padded sequence
- Decisions inside ADRs: always include Status / Context / Decision / Consequences / Why Not X
- Cross-references: use relative paths `../decisions/ADR-001-scratch-not-fork.md`
- Dates: ISO 8601 always (`2026-06-04`)

---

## Versioning Strategy

Documents are not versioned by filename. History is preserved inside each document with dated `## Update — YYYY-MM-DD` sections at the bottom. The top of the document always reflects current truth.

---

## Complete File Index

| File | Purpose |
|------|---------|
| `vision/core-vision.md` | The product insight, the gap, the bet, the attribution problem |
| `vision/product-evolution.md` | Phase 0 → 5 arc with validation gates |
| `vision/positioning.md` | Competitive moat, blue ocean, why incumbents won't copy |
| `product/mvp-scope.md` | Authoritative IN/OUT list for MVP |
| `product/features.md` | All features: MVP / future / rejected with reasoning |
| `product/user-personas.md` | 4 behavioral archetypes that drive design decisions |
| `product/user-journeys.md` | Exact step-by-step flows with real UI copy |
| `market/opportunity.md` | Demand signals, TAM, why the survey number is weak |
| `market/competitive-landscape.md` | All competitors, why they fail, why incumbents won't copy |
| `technical/architecture.md` | System design, component map, stack decisions, scale limits |
| `technical/data-model.md` | Complete SQLite schema with field-by-field rationale |
| `technical/process-flow.md` | Every handler, every sub-flow, error handling matrix |
| `technical/ai-design.md` | All prompts with rationale, cost estimates, question logic |
| `technical/integrations.md` | Telegram, OpenAI, Stripe, APScheduler — key patterns |
| `decisions/ADR-001-scratch-not-fork.md` | Why we build fresh |
| `decisions/ADR-002-sqlite-not-postgres.md` | Why SQLite for MVP |
| `decisions/ADR-003-telegram-first.md` | Why Telegram bot first |
| `decisions/ADR-004-pricing-model.md` | $5 validation price + pricing bug fix |
| `decisions/ADR-005-pdf-deferred.md` | Why closure PDF is post-MVP |
| `decisions/ADR-006-core-channels-separation.md` | API-first architecture — core logic separate from Telegram/web channels |
| `decisions/ADR-007-llm-abstraction.md` | LLM provider abstraction — swap OpenAI/Claude/Gemini/DeepSeek via config |
| `build/implementation-plan.md` | Week-by-week task checklist |
| `build/known-risks.md` | 10 identified risks with concrete mitigations |
| `plans/README.md` | Plans index — start here before writing any code |
| `plans/plan-0-foundation.md` | Repo skeleton, config, DB, LLMClient, /start |
| `plans/plan-1-screenshot-analysis.md` | Photo handler, compression, Vision OCR, ghost risk |
| `plans/plan-2-agentic-questioning.md` | State machine, 3 adaptive questions, answer storage |
| `plans/plan-3-script-generation.md` | GPT script gen, display, free soft/firm delivery |
| `plans/plan-4-payments.md` | Stripe checkout, webhook, ultimatum unlock |
| `plans/plan-5-reminders-outcomes.md` | APScheduler, 48h reminder, outcome collection, ML labels |
| `plans/plan-6-rejection-regen.md` | Not-for-me flow, one regen, fallback |
| `plans/plan-7-edge-cases-polish.md` | Error handling, /cancel, GDPR, Railway deploy, beta |
| `plans/plan-8-web-api.md` | FastAPI REST API — 6 endpoints, same core logic |
| `plans/plan-9-multi-llm.md` | Claude, Gemini, DeepSeek providers in LLMClient |
| `plans/plan-10-phase1-hardening.md` | Subscription, rate limiting, monitoring, multi-conv |

---

## What Lives Here vs. In Code

| Belongs in TURN/ | Belongs in code comments / commits |
|------------------|-------------------------------------|
| Why a decision was made | What a function does |
| What was considered and rejected | Implementation details |
| Business logic rules | Algorithmic details |
| Product constraints | Edge case handling |
| Prompt templates (canonical) | Prompt variations in A/B tests |
