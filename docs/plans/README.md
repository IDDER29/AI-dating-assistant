# Execution Plans — AI Dating Assistant

_Last updated: 2026-06-04_

> Split from [IMPROVEMENT-BLUEPRINT.md](../IMPROVEMENT-BLUEPRINT.md).
> Plans 1–7 cover all ISSUE-XX items from the original blueprint.
> Plans 8–11 cover additional issues found in the analysis documents
> (security, Gemini reliability, production deployment, code quality).

---

## Plan Index

| Plan | File | Week | Focus | Prerequisite |
|------|------|------|-------|-------------|
| **Plan 1** | [plan-1-data-safety.md](plan-1-data-safety.md) | Week 1a | Data integrity & storage safety | None — start here |
| **Plan 2** | [plan-2-ai-integration.md](plan-2-ai-integration.md) | Week 1b | AI API correctness & reliability | Plan 1 Task 1.3 |
| **Plan 3** | [plan-3-conversation-flow.md](plan-3-conversation-flow.md) | Week 2 | Conversation completeness & flow | Plans 1 + 2 |
| **Plan 4** | [plan-4-error-resilience.md](plan-4-error-resilience.md) | Week 2 | Error handling & system resilience | Plan 1 |
| **Plan 5** | [plan-5-product-intelligence.md](plan-5-product-intelligence.md) | Week 3 | Meeting detection, stats, memory | Plans 2 + 3 + 6 |
| **Plan 6** | [plan-6-operator-observability.md](plan-6-operator-observability.md) | Week 2 | Operator notifications & control | Plan 1 |
| **Plan 7** | [plan-7-architecture-refactor.md](plan-7-architecture-refactor.md) | Week 4 | Code structure & long-term quality | All prior plans |
| **Plan 8** | [plan-8-security-hardening.md](plan-8-security-hardening.md) | Week 5 | Input sanitization, PII, credentials | Plans 1, 2, 7 |
| **Plan 9** | [plan-9-gemini-reliability.md](plan-9-gemini-reliability.md) | Week 5 | Model pinning, token budget, cost tracking | Plans 2, 7 |
| **Plan 10** | [plan-10-production-hardening.md](plan-10-production-hardening.md) | Week 6 | Graceful shutdown, pyrofork, systemd | Plans 1, 4, 7, 8 |
| **Plan 11** | [plan-11-code-quality.md](plan-11-code-quality.md) | Week 7 | Structured logging, types, integration tests, stats CLI | All prior plans |

---

## Execution Order

```
[Plan 1] ──► [Plan 2] ──► [Plan 3] ──► [Plan 5]
     │                                     ▲
     └──────► [Plan 4] ──────────────────►─┘
     │
     └──────► [Plan 6] ──────────────────► [Plan 5]
                                              │
[All above complete] ───────────────────► [Plan 7]
                                              │
                          ┌───────────────────┤
                          ▼                   ▼
                      [Plan 8]           [Plan 9]
                      (Security)         (Gemini)
                          │                   │
                          └────────┬──────────┘
                                   ▼
                               [Plan 10]
                            (Production)
                                   │
                                   ▼
                               [Plan 11]
                          (Code Quality — Final)
```

Plans 8 and 9 can run in parallel (Week 5).
Plan 10 requires Plans 8 (security foundation) to be done.
Plan 11 is last — refactors and tests code that must be stable first.

---

## Issue → Plan Map

| Issues | Plan |
|--------|------|
| ISSUE-01 through ISSUE-05 | Plan 1 |
| ISSUE-06 through ISSUE-11 | Plan 2 + Plan 9 (ISSUE-11 deferred) |
| ISSUE-12 through ISSUE-17, ISSUE-31 | Plan 3 |
| ISSUE-18 through ISSUE-20 | Plan 4 |
| ISSUE-21 through ISSUE-24 | Plan 5 |
| ISSUE-22, ISSUE-23, ISSUE-32, ISSUE-33 | Plan 6 |
| ISSUE-25 through ISSUE-28, ISSUE-29 | Plan 7 + Plan 8 (ISSUE-29 hardened) |
| ISSUE-30 (GDPR/ethics) | Not code-implementable — product decision |
| SEC-01 (input sanitization) | Plan 8 |
| SEC-02 (prompt injection defense) | Plan 8 |
| SEC-03 (persona collapse detection) | Plan 8 |
| SEC-04 (PII in logs) | Plan 8 |
| SEC-05 (user data deletion) | Plan 8 |
| GEM-01 (model version pinning) | Plan 9 |
| GEM-02 (token-aware context) | Plan 9 |
| GEM-03 (API cost visibility) | Plan 9 |
| GEM-04 (model fallback) | Plan 9 |
| PROD-01 (graceful shutdown) | Plan 10 |
| PROD-02 (persist task on shutdown) | Plan 10 |
| PROD-03 (message object lifetime) | Plan 10 |
| PROD-04 (Pyrogram unmaintained) | Plan 10 |
| PROD-05 (no systemd unit) | Plan 10 |
| QA-01 (structured logging) | Plan 11 |
| QA-02 (BotState Optional[Any]) | Plan 11 |
| QA-03 (app.py god module) | Plan 11 |
| QA-04 (with_rate_limit_handling name) | Plan 11 |
| QA-05 (no integration tests) | Plan 11 |
| QA-06 (no stats query tool) | Plan 11 |

---

## Quick Status Tracker

| Plan | Status | Tasks | Notes |
|------|--------|-------|-------|
| Plan 1 | ✅ Done | 5 / 5 | Atomic write, corrupt backup, async persist, SIGTERM, pruning |
| Plan 2 | ✅ Done | 5 / 5 | system_instruction=, timeout, orphan rollback, validator, empty guard |
| Plan 3 | ✅ Done | 5 / 5 | Opener injection, burst buffer, AI filter, memory, smooth delay |
| Plan 4 | ✅ Done | 3 / 3 | FloodWait, per-user rate limit, SIGHUP whitelist |
| Plan 5 | ✅ Done | 3 / 3 | Meeting detector, goal tracking, stats |
| Plan 6 | ✅ Done | 3 / 3 | operator_notify, heartbeat, critical event notifications |
| Plan 7 | ✅ Done | 4 / 4 | Config split, TelegramAdapter, PendingMatch, 36 tests |
| Plan 8 | ✅ Done | 5 / 5 | Input sanitizer, persona collapse, privacy logs, data deletion, file permissions |
| Plan 9 | ✅ Done | 4 / 4 | Model pinning+fallback, token-aware trim, API usage tracking, error stats |
| Plan 10 | ⬜ Not started | 0 / 4 | |
| Plan 11 | ⬜ Not started | 0 / 6 | |
