# Product Gap Analysis — AI Dating Assistant

_Last updated: 2026-06-04_

> Extracted exclusively from existing documentation. No content is repeated or rewritten.
> Every gap is linked to its source document(s). Read the referenced document for full context.

---

## Phase 1 — System Grounding (Minimal)

- **What it is:** AI bot impersonating a human on Telegram dating platform `@leomatchbot`
- **What it does:** Browses profiles → likes/dislikes → sends openers → sustains conversations
- **Core user journey:** Profile card → like → mutual match → opener → conversation → meeting suggestion → operator handoff
- **Key behavior:** Two independent pipelines (Scout + Interlocutor) sharing one process and state

👉 See: [SYNTHESIS.md] — Sections 1 & 2 | [TECHNICAL-REFERENCE.md] — Section 4

---

## Phase 2–5 — Product Gap Register

---

### GAP-01 — No meeting detection or operator notification

- **Gap:** System cannot detect when a match suggests a meeting and does not alert the operator. The entire product goal goes unobserved.
- **Severity:** Critical
- **Type:** Intelligence / System Behavior
- **Impact:** User value — the operator cannot act on the system's output without manually monitoring every conversation
- **Source:** [SYNTHESIS.md] — §5 W1 / §8 Final Truth | [analysis/vision-vs-reality.md] — Gap 3 | [analysis/architectural-critique.md] — Proposal 8

---

### GAP-02 — Opener not stored in conversation history

- **Gap:** The AI's first message to a match is never written to `conversation_histories`. The Interlocutor starts every conversation amnesiac — with no record of what it said first.
- **Severity:** Critical
- **Type:** Flow / Intelligence
- **Impact:** User value — every conversation is contextually broken from turn 1
- **Source:** [analysis/vision-vs-reality.md] — Gap 4 / §9 "most important single gap" | [analysis/data-model.md] — §6.1 | [analysis/architectural-critique.md] — Proposal 6

---

### GAP-03 — No AI output validation before delivery

- **Gap:** `result.text` is cleaned for punctuation and forwarded directly to the user. No length guard, no prompt-leak detection, no ladder-part count limit.
- **Severity:** Critical
- **Type:** System Behavior / Intelligence
- **Impact:** System reliability + security — invalid, injected, or out-of-persona output reaches real users unfiltered
- **Source:** [analysis/architectural-critique.md] — PDC-2, Proposal 4 | [analysis/security-analysis.md] — §4, §5.2 | [analysis/failure-analysis.md] — §4.4 (empty response)

---

### GAP-04 — Non-atomic JSON write — history permanently losable on crash

- **Gap:** File is truncated before write completes. A crash mid-save destroys all conversation history. Recovery handler silently overwrites with `{}`.
- **Severity:** Critical
- **Type:** System Behavior
- **Impact:** System reliability — total data loss with no warning
- **Source:** [analysis/failure-analysis.md] — §3.1, §3.2 | [analysis/engineering-decisions.md] — D4 | [analysis/performance-scalability.md] — Proposal 7 | [TECHNICAL-REFERENCE.md] — §13

---

### GAP-05 — Burst message accumulation missing — only last message reaches AI

- **Gap:** During debounce, earlier messages in a burst are cancelled. Only the final message is sent to Gemini. The AI is blind to the full thought.
- **Severity:** High
- **Type:** Flow / Intelligence
- **Impact:** User value — multi-part messages are systematically truncated; AI responses are contextually incomplete
- **Source:** [analysis/vision-vs-reality.md] — Gap 6 | [analysis/runtime-behavior.md] — Flow E | [analysis/architectural-critique.md] — UE-2 (implicitly)

---

### GAP-06 — No per-user rate limiting — quota exhaustion possible

- **Gap:** A single user sending repeated messages can exhaust the Gemini API free-tier quota (15 RPM) with no throttle in the application.
- **Severity:** High
- **Type:** System Behavior
- **Impact:** Revenue (API billing) + reliability — all conversations degrade when quota is hit
- **Source:** [analysis/security-analysis.md] — §2, Threat Actor 2 | [analysis/performance-scalability.md] — §8, Proposal 6 | [analysis/failure-analysis.md] — §2.3 (rate limit)

---

### GAP-07 — No FloodWait handler — Telegram rate-limited messages silently lost

- **Gap:** `pyrogram.errors.FloodWait` is raised but never caught. The task exits on exception; the message is never sent; no retry occurs.
- **Severity:** High
- **Type:** System Behavior
- **Impact:** System reliability — message loss under normal Telegram operating conditions
- **Source:** [analysis/failure-analysis.md] — Missing 1 | [analysis/performance-scalability.md] — §9 item 3, Proposal 5 | [analysis/security-analysis.md] — §4

---

### GAP-08 — Profile quality filter is a character-count gate, not intelligent filtering

- **Gap:** Profiles are liked if description > 10 characters. No AI judgment, no compatibility signal, no quality inference.
- **Severity:** High
- **Type:** Intelligence
- **Impact:** User value — meaningful short profiles rejected; meaningless long profiles liked; opener quality degraded
- **Source:** [analysis/vision-vs-reality.md] — Gap 1 | [analysis/component-deep-dive.md] — §5 Trade-offs | [TECHNICAL-REFERENCE.md] — §5.5

---

### GAP-09 — Wrong profile text used for opener when multiple likes precede a match

- **Gap:** `state.last_seen_anket_text` is a single-slot buffer. A second like overwrites the first. When the first match's "write message" arrives, it uses the second profile's description.
- **Severity:** High
- **Type:** System Behavior / Flow
- **Impact:** User value — opener references the wrong person's profile; conversation starts with a factual error
- **Source:** [analysis/failure-analysis.md] — Assumption 1 | [analysis/data-model.md] — §3.4 | [analysis/architectural-critique.md] — PDC-3

---

### GAP-10 — Orphaned user turn on API failure corrupts future conversations

- **Gap:** User turn is appended before the Gemini call. On failure, no model turn is appended. Consecutive user turns break Gemini's alternating-role invariant on all subsequent calls.
- **Severity:** High
- **Type:** System Behavior
- **Impact:** System reliability — conversation quality degrades silently after every API failure
- **Source:** [analysis/failure-analysis.md] — §5.6, Missing 4 | [analysis/data-model.md] — §6.1 "notable gap" | [analysis/architectural-critique.md] — UE-1

---

### GAP-11 — No SIGTERM handler — history unsaved on managed shutdown

- **Gap:** Process managers (systemd, Docker) send SIGTERM before SIGKILL. No handler exists; history is not saved on managed shutdown.
- **Severity:** High
- **Type:** System Behavior
- **Impact:** System reliability — data loss on every planned deployment or service restart
- **Source:** [analysis/failure-analysis.md] — Missing 5 | [analysis/engineering-decisions.md] — D13 | [TECHNICAL-REFERENCE.md] — §13

---

### GAP-12 — `system_instruction=` unused — 800 tokens wasted per API call

- **Gap:** System prompt injected as a fake user/model exchange instead of using the SDK's `system_instruction=` parameter. ~800 tokens re-transmitted on every call.
- **Severity:** High
- **Type:** System Behavior / Intelligence
- **Impact:** Revenue (token cost) + reliability (fragile workaround may break on model update)
- **Source:** [analysis/engineering-decisions.md] — D6 | [analysis/architectural-critique.md] — PDC-5, Proposal 2 | [analysis/performance-scalability.md] — Proposal 2

---

### GAP-13 — No goal tracking — system cannot measure its own success

- **Gap:** No metric, log entry, or state field records whether conversations are progressing toward the stated goal (meeting suggestion). The system has no self-awareness of effectiveness.
- **Severity:** High
- **Type:** Intelligence / Feature
- **Impact:** User value — operator cannot evaluate whether the system is working
- **Source:** [analysis/vision-vs-reality.md] — §3 (goal-directed conversation row) | [SYNTHESIS.md] — §5 W1

---

### GAP-14 — Whitelist requires bot restart to take effect

- **Gap:** Whitelist is loaded once at startup; runtime changes to `whitelist.json` are ignored until restart. The most time-sensitive operator action (take over a conversation now) requires downtime.
- **Severity:** Medium
- **Type:** Feature / UX
- **Impact:** User value — operator cannot respond quickly to an urgent conversation
- **Source:** [analysis/vision-vs-reality.md] — Divergence 4 | [analysis/component-deep-dive.md] — §15 | [analysis/data-model.md] — §6.3

---

### GAP-15 — No operator visibility into live system state

- **Gap:** No dashboard, no status command, no heartbeat. The operator's only interface is tailing a log file. Active conversations, meeting suggestions, errors — all invisible unless actively searched.
- **Severity:** Medium
- **Type:** Feature / UX
- **Impact:** User value — the product's output cannot be consumed without manual monitoring
- **Source:** [analysis/vision-vs-reality.md] — Divergence 1 | [analysis/architectural-critique.md] — UE-3, Proposal 8 | [SYNTHESIS.md] — §3 Philosophy 5

---

### GAP-16 — No Gemini API timeout — hanging calls block thread indefinitely

- **Gap:** `asyncio.to_thread` has no timeout. A network partition causes the thread pool slot to be consumed indefinitely until the user sends another message (which cancels the task via debounce).
- **Severity:** Medium
- **Type:** System Behavior
- **Impact:** System reliability — thread leak + silent no-reply under network partition
- **Source:** [analysis/failure-analysis.md] — §2.3, Missing 2 | [analysis/performance-scalability.md] — §9 item 1

---

### GAP-17 — Non-ResourceExhausted Gemini errors are unhandled

- **Gap:** `with_rate_limit_handling` catches only HTTP 429. 503, 504, and connection errors propagate uncaught, abandon the task, and leave an orphaned user turn in history.
- **Severity:** Medium
- **Type:** System Behavior
- **Impact:** System reliability — API outages cause cascading conversation corruption
- **Source:** [analysis/failure-analysis.md] — §2.2, Missing 3 | [analysis/architectural-critique.md] — OE-2

---

### GAP-18 — Context window cuts off early conversation facts

- **Gap:** 20-turn sliding window permanently discards the earliest conversation turns. Names, stated preferences, disclosed details from early messages are forgotten and cannot be referenced.
- **Severity:** Medium
- **Type:** Intelligence / Feature
- **Impact:** User value — relationship context degrades over time; AI may contradict itself or ask repeated questions
- **Source:** [analysis/vision-vs-reality.md] — Gap 2 | [analysis/data-model.md] — §11 | [analysis/engineering-decisions.md] — D11

---

### GAP-19 — No persistent distilled memory across conversation window

- **Gap:** No mechanism extracts and stores key facts from conversations (name, job, preferences) that survive the 20-turn window.
- **Severity:** Medium
- **Type:** Intelligence / Feature
- **Impact:** User value — long conversations lose coherence; persona cannot demonstrate memory
- **Source:** [analysis/vision-vs-reality.md] — Gap 2 (proposed fix) | [analysis/data-model.md] — §10 Normalization issue 2

---

### GAP-20 — Opener quality cannot be tuned without code changes

- **Gap:** `FIRST_MESSAGE_PROMPT` is a Python constant in `config.py`. Experimenting with opener styles requires editing source code and restarting.
- **Severity:** Medium
- **Type:** Feature / UX
- **Impact:** User value — operator cannot iterate on the product's most impactful conversion element
- **Source:** [analysis/vision-vs-reality.md] — Divergence 2 | [analysis/architectural-critique.md] — PDC-1, Proposal 1

---

### GAP-21 — Credentials stored unencrypted at rest

- **Gap:** `.env` and `.session` file sit in the working directory with default filesystem permissions. Server read access = full Telegram account takeover + Gemini API key theft.
- **Severity:** Medium
- **Type:** System Behavior (Security)
- **Impact:** System reliability — single point of full compromise
- **Source:** [analysis/security-analysis.md] — §1, §3, Threat Actor 3

---

### GAP-22 — `save_histories()` blocks the asyncio event loop

- **Gap:** Full JSON rewrite runs synchronously in the event loop thread. At ~200+ conversations, each save blocks all other event processing for tens of milliseconds.
- **Severity:** Low (at current scale)
- **Type:** System Behavior
- **Impact:** System reliability at scale — event loop starvation compounds under load
- **Source:** [analysis/performance-scalability.md] — Bottleneck 2, Proposal 1 | [analysis/architectural-critique.md] — Proposal 5

---

### GAP-23 — `@leomatchbot` protocol change causes silent total Scout failure

- **Gap:** All Scout logic is hardcoded to specific strings and a single regex. Any `@leomatchbot` interface change silently breaks the entire discovery pipeline with no alerting.
- **Severity:** Low (probability-based)
- **Type:** System Behavior
- **Impact:** System reliability — unpredictable external dependency with no mitigation
- **Source:** [analysis/failure-analysis.md] — Assumption 4 | [analysis/dependencies-and-boundaries.md] — §2.3 | [analysis/engineering-decisions.md] — D4 (implicit)

---

### GAP-24 — No test infrastructure of any kind

- **Gap:** Zero unit, integration, or smoke tests. Every code change requires full manual bot operation to verify. The most change-prone elements (regex, prompt format, cleanup logic) have no automated coverage.
- **Severity:** Low
- **Type:** System Behavior
- **Impact:** Maintainability — every change is a gamble; development velocity degrades over time
- **Source:** [analysis/architectural-critique.md] — SI-2 | [SYNTHESIS.md] — §9 "what makes this codebase fragile"

---

## Prioritized Gap Table

| Priority | Gap ID | Gap | Severity | Type | Effort to Fix |
|----------|--------|-----|----------|------|--------------|
| 1 | GAP-04 | Non-atomic write → data loss on crash | Critical | System Behavior | 3 lines |
| 2 | GAP-12 | `system_instruction=` unused → 800 token waste + fragility | High | System Behavior | 1 line |
| 3 | GAP-02 | Opener not stored → conversation amnesia | Critical | Flow | ~20 lines |
| 4 | GAP-10 | Orphaned user turn on API failure | High | System Behavior | 5 lines |
| 5 | GAP-01 | No meeting detection or operator notification | Critical | Intelligence | ~20 lines |
| 6 | GAP-07 | No FloodWait handler → message loss | High | System Behavior | 10 lines |
| 7 | GAP-11 | No SIGTERM handler → history unsaved on shutdown | High | System Behavior | 3 lines |
| 8 | GAP-03 | No AI output validation before delivery | Critical | System Behavior | 20 lines |
| 9 | GAP-16 | No Gemini API timeout → thread leak | Medium | System Behavior | 3 lines |
| 10 | GAP-17 | Only 429 caught — other API errors unhandled | Medium | System Behavior | 5 lines |
| 11 | GAP-05 | Burst messages — only last sent to AI | High | Flow | 15 lines |
| 12 | GAP-09 | Wrong profile text for opener (single-slot buffer) | High | System Behavior | ~20 lines |
| 13 | GAP-06 | No per-user rate limiting | High | System Behavior | 15 lines |
| 14 | GAP-13 | No goal tracking / success measurement | High | Intelligence | 20 lines |
| 15 | GAP-15 | No operator visibility into live state | Medium | Feature / UX | 20 lines |
| 16 | GAP-14 | Whitelist requires restart to take effect | Medium | Feature / UX | 15 lines |
| 17 | GAP-08 | Profile quality filter is character count only | High | Intelligence | 5 lines + AI call |
| 18 | GAP-18 | Context window cuts off early conversation facts | Medium | Intelligence | 30 lines |
| 19 | GAP-19 | No persistent distilled memory | Medium | Intelligence | ~50 lines |
| 20 | GAP-22 | `save_histories()` blocks event loop | Low | System Behavior | 2 lines |
| 21 | GAP-20 | Opener tuning requires code changes | Medium | Feature / UX | 30 min refactor |
| 22 | GAP-21 | Credentials unencrypted at rest | Medium | Security | Ops config |
| 23 | GAP-23 | `@leomatchbot` protocol change = silent Scout failure | Low | System Behavior | Monitoring |
| 24 | GAP-24 | No test infrastructure | Low | Maintainability | Hours |
