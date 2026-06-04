# ADR-004: Pricing Model — $5 Per Conversation (MVP Validation Price)

**Status:** Decided (MVP); Under Review (post-MVP)  
**Date:** 2026-06-04

---

## The Pricing Bug That Must Be Fixed

The original vision doc described "$5 one-time per conversation" but then set `premium_until = now + 1 year` on payment. That's a bug — one $5 payment becomes a year of free ultimatums. 

**Correct implementation for per-conversation pricing:**
- Gate the ultimatum on `payments` table: `WHERE conversation_id=? AND status='completed'`
- `premium_until` column is reserved for a future subscription model
- Do NOT link a one-time payment to user-level premium status

---

## MVP Pricing Decision

**$5 one-time per ultimatum script, per conversation.**

This is a **validation price**, not a sustainable price. Its purpose is to answer one question: will users give a credit card number to resolve conversation uncertainty? Not "would you" (survey), but actual Stripe charges.

---

## Why $5 (Not $15 or $20)

**The case for $5:**
- Low enough that payment hesitation doesn't block the validation signal
- If users won't pay $5, they definitely won't pay $15
- Early users should be rewarded with low prices for being early adopters and providing feedback
- Survey data says 62% would pay $10-20 — validate the behavior before optimizing the price

**The case against $5 permanently:**
- $5 signals a gimmick, not a professional tool
- Users with high pain are not price-sensitive at this range — they'd pay $20-30
- The product's value (clarity, certainty, resolution) is worth significantly more than $5 to the target user
- Unit economics at scale require a higher price or a subscription

---

## Post-MVP Pricing Options (Decide After 20+ Paying Users)

**Option A: Raise one-time price to $15**
- Simplest change
- Reduces volume but increases revenue per transaction
- Still no subscription complexity

**Option B: Add monthly subscription ($19.99/mo)**
- Unlimited ultimatums + auto-reminders + voice profiles
- Creates recurring revenue and stronger unit economics
- LTV calculation: 6-month avg retention × $19.99 = $120 LTV vs $5 LTV
- Requires deciding what the free tier includes permanently

**Option C: Tiered (both)**
- $5 one-time for low-frequency users
- $19.99/mo for power users (multiple conversations per month)
- Most complex but captures both segments

**Recommendation (post-validation):** Move to Option C. The $5 one-time stays as the entry point. The subscription unlocks unlimited + premium features. Do not force users to subscribe for their first interaction.

---

## Free Tier Definition

The free tier must provide enough value to attract users but not so much that there's no reason to pay.

**Free always:**
- Ghost risk score + signals (unlimited)
- Soft push script (first 3 per month)
- Firm boundary script (first 3 per month)
- 48h reminder (manual opt-in)

**Premium ($5 one-time or subscription):**
- Ultimatum script (or Goodbye Script for closure goal)
- Automated reminder follow-through

**Rationale for free ghost risk:** The diagnostic is the hook. Users will share "it said 87% ghost risk!" on social media. The free tier is the acquisition mechanism. Never paywalled the ghost risk.

---

## What Not to Do

- Do not give away the ultimatum script free forever — it's the only revenue trigger
- Do not price per-script (cognitive overhead; "which script should I pay for?")
- Do not require subscription before users have seen value (kills conversion for first-time users)
