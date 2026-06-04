# User Personas

> These are not marketing personas. They are behavioral archetypes that drive design decisions.
> Every product decision should be answerable with "which persona does this serve and how?"

---

## Persona 1 — The Anxious Dater

**Who:** 22-35, urban, active on 2-3 dating apps simultaneously. Sends thoughtful messages, rarely gets matching energy back. Has been ghosted 3-5 times in the last year. Overthinks every reply.

**The moment they need TURN:** They sent a message 3 days ago. The other person has been active (status shows online) but hasn't replied. They've drafted 4 follow-up messages and deleted all of them. They don't know if they're being "too much" or if they should just accept it's over.

**What they want:** Permission. They want someone to tell them it's okay to send a direct message asking for clarity — and to tell them exactly what to say.

**What they'll pay for:** The ultimatum script. The soft push feels too passive. The firm boundary feels too aggressive. The ultimatum says "I'll check back in 24h, otherwise I'm moving on" — it's decisive without being harsh. That's worth $5 to them.

**How they measure success:** Not necessarily a date. Success is sending the message and knowing they did what they could. Closure is acceptable. Uncertainty is not.

**Design implication:** The ghost risk score is emotionally important to this persona. They need external validation that their anxiety is warranted (or not). The score should feel clinical and objective, not judgmental. Never say "they're definitely ghosting you" — say "Ghost Risk: 78%. Signals: no questions asked, 3-day delay, short replies."

---

## Persona 2 — The Practical Networker

**Who:** 28-45, professional, uses LinkedIn and email for business development. Knows that follow-up matters but doesn't know how to follow up without seeming desperate. Has a pipeline of "warm" connections who never respond to their second message.

**The moment they need TURN:** They had a great initial exchange with a potential partner or client on LinkedIn. The other person said "let's connect further!" and then went silent. It's been 10 days.

**What they want:** A professional, non-desperate follow-up message that moves toward a concrete next step (call, meeting, coffee).

**What they'll pay for:** Less likely to pay $5 than Persona 1 (lower emotional stakes), but more likely to pay for a subscription if the tool integrates into their workflow. B2B pricing should be higher than consumer.

**How they measure success:** A meeting scheduled within 2 weeks.

**Design implication:** Vertical auto-detection from screenshot must correctly identify LinkedIn conversations and switch to professional tone. The scripts for this persona should always suggest a concrete next step ("15-minute call this Thursday?") not vague reengagement ("would love to catch up!"). This persona values specificity.

---

## Persona 3 — The Reluctant Closer

**Who:** Any age. Has been "texting" someone (romantic or platonic) for weeks or months with no real progress. They know it's going nowhere but can't bring themselves to end it cleanly. Every few days there's a message that restarts hope.

**The moment they need TURN:** They've been exchanging messages with someone for 6 weeks. They've tried to make plans twice and both times the other person said "sounds good!" and then nothing happened. They need to either commit or close — but they feel rude ending it.

**What they want:** The closure option. They don't want a date anymore. They want a graceful exit script that's kind but final.

**What they'll pay for:** The closure path, which in TURN's design is triggered when the user selects "goal: closure" in the agentic questioning. The ultimatum script in this mode becomes a goodbye message, not an ask.

**How they measure success:** Sending the message and feeling at peace with the outcome. No response is also a valid outcome for this persona.

**Design implication:** When `goal = closure`, the script generation prompt should produce a dignified goodbye, not an aggressive ultimatum. The word "ultimatum" should not appear in the UI for this path — rename it "Goodbye Script" or "Closure Message." This is a UI copy decision, not a technical one.

---

## Persona 4 — The Chronic Overthinker (Churns Without Paying)

**Who:** Uses TURN to get the ghost risk score, reads the scripts, feels validated, but never actually sends any of them. Returns next week with a new screenshot of the same conversation.

**Why they matter:** They inflate MAU without contributing to revenue or outcome data. They are the "read receipts" problem — the diagnostic is satisfying enough that the action becomes optional.

**Design implication:** The free tier should show ghost risk and signals but not the full scripts. This creates the right forcing function: to get the actionable output (scripts), you have to commit to the flow. If the full scripts are free forever, Persona 4 extracts value without contributing outcome data.

**Note:** Do not optimize for Persona 4 at MVP. If they're using the product, that's fine. But don't design features specifically for them.

---

## Who TURN Is Not For

- People who want to be charmed into a conversation (they want an AI wingman, not a coach)
- People who want their messages sent for them (technically impossible on Telegram; also wrong product)
- People who want relationship advice (TURN is tactical, not therapeutic)
- People in ongoing healthy conversations (no ghost risk → no TURN value → don't try to serve them)
