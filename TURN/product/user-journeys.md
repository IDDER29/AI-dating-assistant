# User Journeys

> These are the exact step-by-step flows a user experiences in the MVP Telegram bot.
> Every message shown is the actual UI copy. These drive the implementation, not the other way around.

---

## Journey 1 — New User, First Conversation (Pays for Ultimatum)

```
User: /start

Bot: "👋 I'm TURN.
     Send me a screenshot of any conversation you're unsure about —
     dating, friendship, or work.
     I'll tell you the ghost risk and give you 3 scripts to move it forward.
     
     Soft push, firm boundary, or ultimatum. You pick.
     
     Send your screenshot to begin."

---

User: [sends screenshot]

Bot: "Analyzing... ⏳"

[2-3 seconds]

Bot: "Ghost Risk: 74% 🔴
     
     Signals:
     • No questions asked in their last 4 messages
     • 3-day gap before their last reply
     • Replies getting shorter
     
     Let me ask you 3 quick things to build your script."

Bot: "What's your main goal?
     [A] Get a real meetup
     [B] Get closure / end it cleanly
     [C] Just want advice"

---

User: [taps A — Get a real meetup]

Bot: "Have you met this person in real life before?
     [A] Yes, we've met
     [B] No, still online only"

---

User: [taps B — No, still online only]

Bot: "On a scale of 1-10, how much would it sting if they never replied?
     (1 = barely care, 10 = would genuinely hurt)
     
     [1] [2] [3] [4] [5] [6] [7] [8] [9] [10]"

---

User: [taps 7]

Bot: "Got it. Generating your scripts... ✍️"

[1-2 seconds]

Bot: "Here are your 3 options. Copy the one that fits and send it.
     
     💬 Soft Push:
     'Hey, still down to grab coffee? I'm free Wednesday or Thursday afternoon.'
     
     ⚡ Firm Boundary:
     'I'd love to meet but I need a yes or no by tomorrow. No hard feelings either way.'
     
     [💬 Use Soft] [⚡ Use Firm] [🔒 Ultimatum ($5)] [👎 Not for me]"

---

User: [taps 🔒 Ultimatum ($5)]

Bot: "The ultimatum script cuts through the noise.
     Unlock it for $5 — one-time for this conversation.
     
     [Pay $5 and unlock →]"

[Stripe checkout link opens]

---

User: [completes payment in browser]

Bot: "✅ Unlocked.
     
     🔒 Ultimatum:
     'I'll check back in 24 hours. If I don't hear from you, I'll take that as a no — 
     no hard feelings, genuinely.'
     
     Copy that and send it. I'll check back with you in 48 hours.
     
     [✅ Sent it] [Skip reminder]"

---

User: [taps ✅ Sent it]

Bot: "Done. I'll check in with you in 48 hours.
     Good luck — you've done your part."

---

[48 hours later — scheduler fires]

Bot: "⏰ Hey — did they reply to your message?
     
     [🎉 Yes, we're meeting!] [💬 Yes, still texting] [👻 They ghosted] [🚶 I moved on]"

---

User: [taps 🎉 Yes, we're meeting!]

Bot: "That's the one. 🎉
     You pushed, it worked.
     
     Come back next time you need a script. /start"
```

---

## Journey 2 — User Gets Ghosted (Closure Path)

```
[Same start as Journey 1 through script selection]
[User selected firm boundary, set reminder]

[48 hours later]

Bot: "⏰ Hey — did they reply to your message?
     [🎉 Yes, we're meeting!] [💬 Yes, still texting] [👻 They ghosted] [🚶 I moved on]"

---

User: [taps 👻 They ghosted]

Bot: "You already knew. The ghost risk was 74%.
     
     You sent the message. You got your answer.
     That's the win — you didn't spend another week wondering.
     
     This conversation is closed. When you're ready for the next one, just send a new screenshot."
```

---

## Journey 3 — User Wants Closure (Not a Meetup)

```
[Screenshot sent, ghost risk shown]

Bot: "What's your main goal?
     [A] Get a real meetup
     [B] Get closure / end it cleanly
     [C] Just want advice"

---

User: [taps B — Get closure]

Bot: "How long has this been going on?
     [A] Less than 2 weeks
     [B] 2-8 weeks
     [C] More than 2 months"

---

User: [taps C — More than 2 months]

Bot: "Got it. Writing your closure scripts..."

Bot: "Here are your options.
     
     💬 Gentle Exit:
     'Hey, it's been a while and I think we've both lost momentum. 
      No hard feelings — hope you're well.'
     
     ⚡ Direct Close:
     'I've enjoyed chatting but I don't think this is going anywhere for either of us.
      Take care.'
     
     [💬 Use Gentle] [⚡ Use Direct] [🔒 Goodbye Script ($5)] [👎 Not for me]"

Note: When goal=closure, "Ultimatum" is renamed "Goodbye Script" in the UI.
     The script itself is a final, clean farewell, not a demand.
```

---

## Journey 4 — User Rejects Scripts

```
[Scripts shown as in Journey 1]

User: [taps 👎 Not for me]

Bot: "What didn't land?
     [A] Too aggressive
     [B] Too weak / passive
     [C] Doesn't sound like me
     [D] Other"

---

User: [taps C — Doesn't sound like me]

Bot: "Got it — rewriting to match a more natural tone... ✍️"

[1-2 seconds]

Bot: "New version:
     
     💬 'Hey, been a minute — still want to find a time to hang?
          Let me know if you're up for it.'
     
     [✅ Use this] [Skip — just set a reminder]"

---

User: [taps Skip — just set a reminder]

Bot: "No problem. Want me to check in with you in 48 hours
     to see how things went?
     [Yes, remind me] [No thanks]"
```

---

## Journey 5 — User Sends Text Instead of Screenshot

```
User: "hey she hasn't replied in 3 days and I sent a pretty long message"

Bot: "Got it — you can paste the conversation directly if you don't have a screenshot.
     
     Paste the last 5-10 messages (just copy from your chat) and I'll analyze it."

---

User: [pastes text]

Bot: [continues with same flow as screenshot path, skipping vision step]
```

---

## Edge Case Behaviors

**User sends second screenshot while conversation is active:**
```
Bot: "You have an active conversation in progress.
     Finish it or type /cancel to start fresh.
     
     [Continue current] [/cancel]"
```

**User types /cancel:**
```
Bot: "Current conversation cancelled. Send a new screenshot whenever you're ready."
```

**OpenAI timeout:**
```
Bot: "Analysis is taking longer than expected. Trying again... ⏳"
[retry once]
[if second failure]
Bot: "AI is busy right now. Please try again in 30 seconds."
```

**Screenshot unreadable:**
```
Bot: "I couldn't read the conversation clearly.
     Try a screenshot with better contrast, or paste the text directly."
```

**User sends /delete_my_data:**
```
Bot: "Are you sure? This will permanently delete all your conversations and data.
     [Yes, delete everything] [Cancel]"
[on confirm]
Bot: "Done. All your data has been deleted. Goodbye."
[delete all user rows from DB]
```
