# ADR-001: Build From Scratch, Not Fork

**Status:** Decided  
**Date:** 2026-06-04

---

## Context

The `polikhronidi/AI-dating-assistant` repo exists in this project. The original plan was to fork it and replace the "brain" (dialogue generation) with TURN's conversion logic. Later analysis challenged this assumption.

---

## Decision

Build TURN from scratch. Do not fork the existing repo.

---

## Reasons

**1. Incompatible library stack.**
The existing repo uses **Pyrogram** for Telegram. TURN's technical spec is built on **python-telegram-bot v20+**. These are fundamentally different libraries with different handler patterns, different async models, and different APIs. You cannot copy-paste between them. Every piece of code from the old repo requires mental translation before it can be used — that's slower than writing it fresh.

**2. Different product model.**
The existing repo is built to *act as the user* — it sends messages on their behalf, manages profiles, runs autonomously. TURN is the opposite — it *coaches* the user and never sends anything. The mental model, the conversation state machine, and the handler logic are all inverted. "Forking" would mean keeping the scaffolding and replacing almost everything inside it. That's not a fork — it's a rewrite with extra cognitive load.

**3. The inherited value is minimal.**
The genuinely useful parts of the existing repo are:
- Telegram error handling patterns (rate limits, user deactivated) — 30 lines
- Realistic message sending (typing delays, chunked messages) — 20 lines
- General project structure — can be replicated in 10 minutes

None of this justifies inheriting the entire codebase.

**4. Scratch = clean state machine.**
The MVP requires a clean, readable state machine (`analyzing → questioning → generating_scripts → awaiting_choice → ...`). Starting from a codebase with a different state model (profile scraping, two-brain architecture) means either fighting the existing structure or building on top of it awkwardly.

---

## What We Do Keep (As Reference, Not Code)

- Keep the existing repo open as a browser tab during implementation
- Reference its error handling patterns when implementing `gpt_client.py`
- Reference its typing delay implementation when building polished message sending
- That's it — read, don't copy

---

## Consequences

- Week 1 starts with an empty repo
- No inherited technical debt
- State machine is designed from first principles (see `../technical/process-flow.md`)
- If we want typing delays, we write 5 lines ourselves

---

## Why Not Fork Anyway

The counter-argument: "forking is faster because the boilerplate is done."

The boilerplate (bot initialization, handler registration, env var loading) takes 30-45 minutes to write from scratch with a good template. The cognitive overhead of mapping Pyrogram patterns to python-telegram-bot patterns, and understanding what to keep vs. delete, takes longer than that. The fork is a false shortcut.
