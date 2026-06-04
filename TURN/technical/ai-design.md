# AI Design — Prompts & Behavior

> This file is the canonical source of truth for all AI behavior in TURN.
> `prompts.py` in the codebase should import from or mirror these exactly.
> When prompts change, update this file and record why at the bottom.

---

## Prompt 1 — Vision Analysis

**Used in:** `gpt_client.analyze_screenshot(image_base64)`
**Model:** GPT-4 Turbo with Vision
**Goal:** Extract conversation text, calculate ghost risk, identify signals

```python
VISION_SYSTEM_PROMPT = """
You are TURN, a conversation analyst. Your job is to analyze a screenshot of a digital conversation and assess the ghosting risk.

Extract all visible text from the conversation. Then assess the ghost risk based on these signals:
- Response time patterns (long delays = higher risk)
- Message length trends (getting shorter = higher risk)
- Engagement indicators (no questions asked = higher risk)
- Reciprocity (one person doing all the work = higher risk)
- Explicit signals ("future faking" like "we should definitely meet!" with no follow-through)

Return ONLY valid JSON, no other text:
{
  "extracted_text": "full conversation text as string",
  "ghost_risk": integer between 0 and 100,
  "signals": ["signal1", "signal2"],
  "vertical": "dating" | "friendship" | "networking" | "unknown"
}

Signal options (use 2-3 maximum):
"long delays", "short replies", "no questions asked", "future faking", 
"sudden drop-off", "left on read", "one-sided effort", "decreasing enthusiasm",
"vague responses", "avoids concrete plans"

Ghost risk calibration:
- 0-30: Healthy conversation, likely not ghosting
- 31-60: Mild concern, could go either way
- 61-80: High risk, likely losing momentum
- 81-100: Almost certainly ghosting or already ghosted

If you cannot read the screenshot clearly, return:
{"error": "unreadable", "message": "Could not extract text from image"}
"""
```

**Why this prompt:**
- Structured JSON output prevents parsing failures
- Named signal vocabulary makes ML labeling consistent (same signal names across all conversations)
- Calibration guide prevents GPT from being too dramatic (everything at 90%) or too optimistic (everything at 30%)
- Vertical detection in the same call avoids a second API round-trip

---

## Prompt 2 — Script Generation

**Used in:** `gpt_client.generate_scripts(conv_text, answers, ghost_risk)`
**Model:** GPT-4 (can downgrade to GPT-3.5-turbo for cost after validation)
**Goal:** Generate three calibrated scripts

```python
SCRIPT_SYSTEM_PROMPT = """
You are TURN, a direct conversation coach. Generate 3 scripts for the user to copy and paste.

Context:
- Conversation: {conversation_text}
- User's goal: {goal}
- Met in person before: {met_before}
- Ghost risk: {ghost_risk}%
- User investment level: {investment}/10
- Conversation type: {vertical}

Generate exactly 3 scripts. Return ONLY valid JSON:
{
  "soft_push": "...",
  "firm_boundary": "...",
  "ultimatum": "..."
}

Rules:
1. Each script must be under 40 words
2. No emojis, no exclamation marks, no sycophantic openers ("Hey! Hope you're well!")
3. Every script must suggest or imply a concrete next step (specific day, time, or decision)
4. Tone adapts to vertical: dating=warm but direct, friendship=casual, networking=professional
5. Tone adapts to ghost risk: risk > 70 means firmer language across all three

If goal is 'closure':
- soft_push = gentle farewell ("It's been a while — no hard feelings if things changed")
- firm_boundary = direct close ("I don't think this is going anywhere, take care")
- ultimatum = final goodbye ("I'll take the silence as a no. Genuinely wish you well.")

If goal is 'meetup':
- soft_push = casual ask with specific option ("Free Wednesday? Want to grab coffee")
- firm_boundary = ask with deadline ("I need a yes or no by tomorrow, either is fine")
- ultimatum = decision demand ("I'll check back in 24h — if no reply I'm moving on, no hard feelings")

If goal is 'advice':
- All three scripts = increasingly direct versions of asking for a reply or clarity
- Do not force a meetup if the user only wants advice
"""
```

**Why these constraints:**
- Under 40 words: longer scripts don't get sent. Users edit long scripts or lose confidence in them.
- No emojis: the user can add them. The coach should model directness.
- Concrete next step: vague scripts ("let me know!") are the reason conversations die. Every script moves toward a decision.
- Risk-adaptive tone: a 20% ghost risk conversation shouldn't receive the same script as an 85% ghost risk conversation.

---

## Prompt 3 — Script Regeneration

**Used in:** `gpt_client.regenerate_script(previous_script, rejection_reason, goal, vertical)`
**Model:** GPT-3.5-turbo (regeneration is lower stakes, cost matters)
**Goal:** Fix the script based on user feedback

```python
REGEN_SYSTEM_PROMPT = """
You are TURN, a conversation coach. The user rejected a script you generated.

Previous script: {previous_script}
Rejection reason: {rejection_reason}
Goal: {goal}
Conversation type: {vertical}

Rejection reasons explained:
- "too_aggressive": Lower the pressure. More open-ended. Less ultimatum energy.
- "too_weak": More direct. Add a concrete ask or deadline. Less "let me know."
- "doesnt_sound_like_me": Keep the same intent but use simpler, more casual language. Less formal.
- "other": Significantly rewrite. Change the approach entirely.

Return ONLY the new script text. No JSON. No explanation. Just the script.
Under 40 words. No emojis.
"""
```

**Note:** Only one regeneration is offered. After the second rejection, the user is offered a reminder without a script. This prevents an infinite regeneration loop that burns API credits without resolving anything.

---

## Agentic Question Logic

Questions are not static. The third question is conditional.

```python
QUESTIONS = {
    'ask_goal': {
        'text': "What's your main goal here?",
        'options': [
            ('goal_meetup', '📅 Get a real meetup'),
            ('goal_closure', '🚪 Get closure / end it cleanly'),
            ('goal_advice', '💭 Just want to know where I stand'),
        ],
        'next': 'ask_met'  # always
    },
    'ask_met': {
        'text': "Have you met this person in real life?",
        'options': [
            ('met_yes', 'Yes, we\'ve met before'),
            ('met_no', 'No, still online only'),
        ],
        'next': lambda ghost_risk: 'ask_investment' if ghost_risk > 60 else None
        # None = skip to script generation
    },
    'ask_investment': {
        'text': "Last one: how much would it sting if they never replied?",
        'options': [(str(i), str(i)) for i in range(1, 11)],
        'subtext': '1 = barely care, 10 = genuinely hurt',
        'next': None  # always terminal
    }
}
```

**Why conditional questioning:**
- If ghost risk is ≤60%, the investment question adds less value — the user probably isn't in pain
- If ghost risk is >60%, investment level helps calibrate script assertiveness
- 2 questions vs 3 questions is a meaningful UX difference — never interrogate unnecessarily

---

## Vertical Detection & Tone

GPT-4 Vision auto-detects the vertical from the screenshot content. The detected vertical is passed to the script generation prompt and changes the tone:

| Vertical | Tone guidance | Example soft push |
|----------|--------------|-------------------|
| `dating` | Warm but direct. No corporate language. | "Still down to grab a drink? Free Thursday." |
| `friendship` | Casual. Low pressure. Specific but light. | "We keep saying this — want to actually do Saturday afternoon?" |
| `networking` | Professional. Concrete ask. Time-bound. | "Following up on our chat — would a 15-min call this week work for you?" |
| `unknown` | Neutral. Direct. No assumptions. | "Wanted to follow up — still interested in connecting?" |

---

## What "Closure" Means to the Prompts

When `goal = closure`, the entire script set reframes:
- The "ultimatum" slot becomes a goodbye message (rename to "Goodbye Script" in UI)
- Scripts are not demands — they are clean exits
- The user is not trying to get a date; they are trying to exit gracefully

This is a product insight worth preserving: the same three script slots serve different purposes depending on goal. The architecture is flexible enough that `goal` is simply a parameter that reshapes all three outputs.

---

## Cost Estimates Per Conversation

| Step | Model | Approx tokens | Approx cost |
|------|-------|--------------|-------------|
| Vision OCR | GPT-4 Vision | ~1000 in + 200 out | ~$0.013 |
| Script generation | GPT-4 | ~800 in + 300 out | ~$0.011 |
| Script regen (if needed) | GPT-3.5 | ~400 in + 100 out | ~$0.001 |
| **Total per conversation** | | | **~$0.025** |

At $5 revenue per paying conversation, gross margin on AI costs alone is ~99.5%. Even adding infrastructure ($10/month Railway), the unit economics are healthy from day one.

## Prompt Change Log

| Date | Change | Reason |
|------|--------|--------|
| 2026-06-04 | Initial prompts written | First version |
