# Competitive Landscape

## The Category Gap

The market has two categories. TURN belongs to neither.

**Category 1 — Diagnostic tools** (ghost detectors): Tell you something is wrong. Don't tell you what to do about it. Users leave more anxious than when they arrived.

**Category 2 — Content generators** (AI wingmen): Give you more things to say. Optimize for conversation engagement, not real-life outcomes. Deepen the pen-pal trap.

**TURN's category — Action accelerators**: Force a decision. Meet or end. Every product decision maps back to this.

---

## Direct Competitors

### Lucen
- **What it does:** Analyzes conversation screenshots for ghosting signals
- **Ghost risk:** Yes
- **Scripts:** No
- **Platform:** Web app
- **Fatal flaw:** Pure diagnostic. No action path. "You're 80% likely being ghosted. Good luck."
- **Lesson:** The diagnostic alone has value (people pay for it) but it leaves users stuck. TURN's script layer is what Lucen is missing.

### NoBlueTick
- **What it does:** Tracks read receipts and reply timing
- **Ghost risk:** Implicit (via data)
- **Scripts:** No
- **Fatal flaw:** Passive surveillance. Gives data about the problem, no resolution.

### RizzGPT
- **What it does:** Generates flirty/funny replies to dating app messages
- **Scripts:** Yes (but wrong goal)
- **Ghost risk:** No
- **Fatal flaw:** Optimizes for "engaging conversation" — which is more texting. The product succeeds when users text more, not when they meet. Misaligned incentives between product and user.
- **Lesson:** Script generation is a proven willingness-to-pay. The problem is the goal. TURN uses the same mechanism (script gen) but points it at a different outcome (meetup/closure).

### FireTexts
- Same category as RizzGPT. Same fatal flaw.

---

## Adjacent Competitors (Different Problem, Overlapping User)

### Bumble BFF
- **What it does:** Matches users for friendships
- **The overlap:** TURN's friendship vertical
- **Why not a threat:** Bumble BFF solves cold-start (finding new friends). TURN solves conversion (turning existing online connections into real relationships). Different problem, same user.
- **Data point:** Bumble BFF leads to real meetups only 25% of the time. The other 75% is the TURN opportunity.

### Shapr
- Same as Bumble BFF for the networking vertical. Creates new connections, doesn't convert them.

### SpeakUp / Zocia
- **What they do:** Social skills training
- **The overlap:** TURN's eventual Layer 2 (Simulator)
- **Why not a threat at MVP:** They practice skills in a vacuum. No tie to real conversations. No outcome measurement.
- **Long-term consideration:** If TURN builds the Simulator (Phase 3), these become partial competitors. Their weakness — no real-world outcome tie — is TURN's advantage.

---

## Dead Competitors (Cautionary Tales)

### Beeper / Sunbird
- Tried to aggregate all messaging platforms (iMessage, WhatsApp, etc.) into one app
- Killed by Apple actively blocking iMessage access and Google changing RCS policies
- **Lesson:** Platform dependency is existential risk. Screenshot-based approach exists specifically to avoid this. Never build anything that requires permission from another platform's API. This decision is locked in. See `../decisions/ADR-003-telegram-first.md`.

### Swept / After
- Anti-ghosting dating apps that required the other person to also use the product
- **Lesson:** Cold-start problem kills two-sided products in niche markets. TURN requires nothing from the other person. This is a core design constraint, not just a feature.

---

## Why Dating Apps Won't Build This

This is the most common investor objection: "Can't Tinder just add this?"

The answer is no, for a structural reason: dating app revenue depends on engagement (time in app, subscription renewals). A "force meetup" button reduces engagement by resolving conversations faster. Every successful TURN interaction is one fewer reason for the user to open the dating app tomorrow.

Hinge is the partial exception — their brand is "designed to be deleted." But even Hinge makes money from subscriptions, and subscribers who successfully meet people cancel. Hinge has no incentive to accelerate cancellations.

Dating apps are structurally incapable of building TURN. This is a durable protection, not just a temporary gap.

---

## Market Size (Why This Is Worth Pursuing)

- 400M+ online dating users globally
- 50-80% of users experience ghosting
- 62% of surveyed users (n=500) said they'd pay $10-20 to resolve uncertainty
- Social skills training market: $31B (growing to $60B+ by 2033)
- Focused TAM (English-speaking, willing to pay for ghosting solutions): ~50M users

These numbers don't need to be exact to be directionally correct. Even capturing 0.1% of 50M users at $15/month is $7.5M ARR. The market is large enough that precision doesn't matter at MVP stage.
