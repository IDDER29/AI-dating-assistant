# TURN — Plans Index

> Written for future-me (Claude). Every plan is self-contained.
> You should be able to open any plan cold and start writing code immediately.
> No re-reading other docs required — everything you need is inlined.

---

## How To Use These Plans

1. Open the plan for where you are right now
2. Read the "State Before" section to confirm you're at the right starting point
3. Execute tasks in order — each task ends with a concrete verification step
4. When all acceptance criteria pass, the plan is done — move to the next one

Never skip a plan. Each one leaves the codebase in a specific state that the next plan depends on.

---

## The Full Plan Sequence

| Plan | Name | What It Builds | Est. Time |
|------|------|----------------|-----------|
| [Plan 0](plan-0-foundation.md) | Foundation | Repo skeleton, config, DB schema, LLM abstraction, bot says /start | 1 day |
| [Plan 1](plan-1-screenshot-analysis.md) | Screenshot Analysis | Photo handler, image compression, GPT vision, ghost risk display | 1 day |
| [Plan 2](plan-2-agentic-questioning.md) | Agentic Questioning | State machine, 3 adaptive questions, inline keyboards, answer storage | 1 day |
| [Plan 3](plan-3-script-generation.md) | Script Generation | GPT script gen, 3-script display, free soft/firm delivery, reminder offer | 1 day |
| [Plan 4](plan-4-payments.md) | Stripe Payments | Ultimatum paywall, Stripe checkout, webhook, idempotency | 1 day |
| [Plan 5](plan-5-reminders-outcomes.md) | Reminders & Outcomes | APScheduler jobs, reminder message, outcome collection, ML labels | 1 day |
| [Plan 6](plan-6-rejection-regen.md) | Rejection & Regeneration | Not-for-me flow, rejection reason, one regen, fallback to reminder | 0.5 day |
| [Plan 7](plan-7-edge-cases-polish.md) | Edge Cases & Polish | All error paths, /cancel, /delete_my_data, logging, deployment | 1 day |
| [Plan 8](plan-8-web-api.md) | Web API | FastAPI channel, 6 REST endpoints, same core logic, CORS | 1 day |
| [Plan 9](plan-9-multi-llm.md) | Multi-LLM | Add Claude, Gemini, DeepSeek to LLMClient, per-task routing | 0.5 day |
| [Plan 10](plan-10-phase1-hardening.md) | Phase 1 Hardening | Subscription pricing, closure text, rate limiting, error monitoring | 2 days |

**Total MVP (Plans 0-7):** ~8 days of focused work
**Full Phase 1 (Plans 0-10):** ~11 days

---

## Decisions Already Made — Never Re-Debate These

These were decided with full context. Future-me: do not re-open them.

| Decision | Answer | ADR |
|----------|--------|-----|
| Fork existing repo or scratch? | Scratch | ADR-001 |
| SQLite or PostgreSQL? | SQLite (migrate at 500+ MAU) | ADR-002 |
| Telegram or web first? | Telegram bot | ADR-003 |
| Pricing model? | $5 per ultimatum (validation price) | ADR-004 |
| Closure PDF in MVP? | No — text response instead | ADR-005 |
| Core/channels separation? | Yes — from day one | ADR-006 |
| LLM abstraction? | Yes — LLMClient interface | ADR-007 |

---

## Codebase State After Each Plan

```
After Plan 0: skeleton runs, /start works, DB creates tables, LLMClient instantiates
After Plan 1: bot receives screenshot, returns ghost risk + signals
After Plan 2: bot asks 2-3 questions, stores all answers
After Plan 3: bot generates and displays 3 scripts with inline buttons
After Plan 4: ultimatum requires $5 Stripe payment, webhook updates DB
After Plan 5: reminder fires at 48h, outcome is collected and logged to ml_labels
After Plan 6: rejection flow works, one regen offered, fallback to reminder
After Plan 7: all edge cases handled, deployed to Railway, 10 beta users tested
After Plan 8: web API live at /api/*, same core logic, Telegram bot unchanged
After Plan 9: LLMClient routes vision→Gemini, scripts→Claude, regen→DeepSeek
After Plan 10: subscription pricing, rate limiting, monitoring, phase 1 complete
```
