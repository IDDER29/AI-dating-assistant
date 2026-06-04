# ADR-005: Closure PDF Deferred to Post-MVP

**Status:** Decided  
**Date:** 2026-06-04

---

## Decision

The closure PDF report is excluded from the MVP. It will be built in Phase 1 hardening (weeks 5-8) once the core loop is validated.

---

## What the Closure PDF Is

A generated PDF sent to premium users who report "ghosted" or "gave up" after the reminder. Contains: ghost risk score, conversation timeline, signals, and a dignified goodbye script. Intended to provide closure and reframe the outcome as a win ("you ended the uncertainty").

---

## Why Deferred

**1. The trigger path is extremely rare at MVP.**
The closure PDF only fires when: (a) user is premium (paid $5) AND (b) outcome = 'ghosted' or 'gave_up'. In the first month, expect 20-50 paying users, of which maybe 40% get ghosted. That's 8-20 users. Building a full PDF generation system for 8-20 users in the first month is not a good use of week 4 build time.

**2. Week 4 should be error handling and real user testing.**
The most valuable thing in week 4 is putting the bot in front of 10-20 real users and fixing what breaks. PDF generation is complex (library setup, template design, Telegram file sending, edge cases) and time that would be better spent on product stability.

**3. The emotional value is unproven.**
The closure PDF solves the attribution problem — users who get ghosted might blame TURN. But it's a hypothesis that a PDF with "encouraging note" actually helps. Validate the core loop first. Then validate whether the PDF improves retention.

**4. A text-based closure response is sufficient for MVP.**
When outcome = 'ghosted', TURN can send a well-crafted text message instead of a PDF. Same emotional function, zero implementation cost.

---

## MVP Replacement

Instead of a PDF, send this text response when outcome = 'ghosted' or 'gave_up':

```
You already had your answer before you sent that message.
The ghost risk was {risk}%. You sent it anyway — that took clarity.

You saved yourself weeks of wondering.
That's the win.

When you're ready for the next one, send a new screenshot.
```

This is the same emotional beat as the PDF. No library, no file generation, no edge cases.

---

## When to Build It

Phase 1, after:
- Core loop has 50+ completed conversations with outcomes
- At least 5 users have asked "is there anything I can keep / download?"
- User feedback shows the text closure response is insufficient

If nobody asks for a downloadable report, it may never be needed.
