# Execution Plans — AI Dating Assistant

_Last updated: 2026-06-04_

> Split from [IMPROVEMENT-BLUEPRINT.md](../IMPROVEMENT-BLUEPRINT.md).
> Each plan is one week of focused work. Execute in order — earlier plans are
> prerequisites for later ones.

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
```

Plans 1, 4, and 6 can be started simultaneously.
Plan 2 requires Plan 1 Task 1.3 to be complete.
Plan 3 requires Plans 1 and 2 complete.
Plan 5 requires Plans 2, 3, and 6 complete.
Plan 7 is last — refactors code that must be stable first.

---

## Issue → Plan Map

| Issues | Plan |
|--------|------|
| ISSUE-01 through ISSUE-05 | Plan 1 |
| ISSUE-06 through ISSUE-11 | Plan 2 |
| ISSUE-12 through ISSUE-17, ISSUE-31 | Plan 3 |
| ISSUE-18 through ISSUE-20 | Plan 4 |
| ISSUE-21 through ISSUE-24 | Plan 5 |
| ISSUE-22, ISSUE-23, ISSUE-32, ISSUE-33 | Plan 6 |
| ISSUE-25 through ISSUE-28, ISSUE-29 | Plan 7 |

---

## Quick Status Tracker

Update this table as tasks complete.

| Plan | Status | Completed tasks | Notes |
|------|--------|----------------|-------|
| Plan 1 | ⬜ Not started | 0 / 5 | |
| Plan 2 | ⬜ Not started | 0 / 5 | |
| Plan 3 | ⬜ Not started | 0 / 5 | |
| Plan 4 | ⬜ Not started | 0 / 3 | |
| Plan 5 | ⬜ Not started | 0 / 3 | |
| Plan 6 | ⬜ Not started | 0 / 3 | |
| Plan 7 | ⬜ Not started | 0 / 4 | |
