# Runtime Behavior — AI Dating Assistant

_Last updated: 2026-06-04_

> This document describes what actually happens when the system runs.
> Every flow is traced step by step, module by module, with exact data movement.

---

## Table of Contents

1. [System Boot](#1-system-boot)
2. [Flow A — Profile Card Arrives (New Profile)](#2-flow-a--profile-card-arrives-new-profile)
3. [Flow B — Mutual Match Established (Opener Sent)](#3-flow-b--mutual-match-established-opener-sent)
4. [Flow C — Real User Sends First Message](#4-flow-c--real-user-sends-first-message)
5. [Flow D — Real User Sends Follow-Up in Active Conversation](#5-flow-d--real-user-sends-follow-up-in-active-conversation)
6. [Flow E — User Sends Burst of Messages (Debounce in Action)](#6-flow-e--user-sends-burst-of-messages-debounce-in-action)
7. [Flow F — Whitelisted User Sends a Message](#7-flow-f--whitelisted-user-sends-a-message)
8. [Flow G — Gemini API Rate Limit Hit](#8-flow-g--gemini-api-rate-limit-hit)
9. [Flow H — Bot Navigates Dating Bot Menu](#9-flow-h--bot-navigates-dating-bot-menu)
10. [Flow I — Graceful Shutdown (Ctrl+C)](#10-flow-i--graceful-shutdown-ctrlc)
11. [Flow J — Crash and Restart Recovery](#11-flow-j--crash-and-restart-recovery)
12. [Timing Diagram — Full Conversation from First Sight to Reply](#12-timing-diagram--full-conversation-from-first-sight-to-reply)
13. [Concurrency Snapshot — Multiple Simultaneous Events](#13-concurrency-snapshot--multiple-simultaneous-events)

---

## 1. System Boot

**Trigger:** Operator runs `python3 src/main.py`

**Preconditions:** `.env` file present with all three credentials. `ai_dating_user.session` file exists (account already authorized).

### Step-by-step execution

```
[PROCESS START]
  Python imports src/main.py
  → imports app, storage (which imports config)
  → config.py executes at import time:
      load_dotenv() reads .env → os.environ populated
      ANKET_PATTERN compiled
      All constants set

[main.py: __main__ block]
  asyncio.run(run())
  → Python event loop created
  → run() coroutine scheduled

[app.py: run()]
  Step 1: setup_logging()
    → root logger configured
    → RotatingFileHandler attached to ai_bot_logs.txt
    → StreamHandler attached to stdout
    → From this point all logging.* calls produce output

  Step 2: state = BotState()
    → state.last_action_time = datetime.min (UTC)  ← never blocks first cooldown
    → state.conversation_histories = {}
    → state.whitelist_ids = set()
    → state.model = None
    → state.app = None
    → state.leomatch_task = None
    → state.active_dialogue_tasks = {}

  Step 3: initialize_ai(state)   [ai_client.py]
    → genai.configure(api_key=GEMINI_API_KEY)
    → state.model = genai.GenerativeModel("gemini-1.5-flash-latest")
    → LOG: "Google Gemini model successfully initialized."

  Step 4: initialize_app(state)   [app.py]
    → checks API_ID, API_HASH, GEMINI_API_KEY are all non-None
    → state.app = Client("ai_dating_user", api_id=..., api_hash=...)
    → LOG: (Pyrogram internal connection logs)

  Step 5: load_histories(state)   [storage.py]
    → opens data/conversation_histories.json
    → json.load() → state.conversation_histories = {...}
    → LOG: "Conversation histories loaded."

  Step 6: load_whitelist(state)   [storage.py]
    → opens data/whitelist.json
    → json.load() → [123456789, ...]
    → state.whitelist_ids = {123456789, ...}
    → LOG: "Whitelist loaded. Users in list: 1."

  Step 7: async with state.app:
    → Pyrogram opens TCP connection to Telegram MTProto servers
    → Session keys from .session file used to authenticate
    → Telegram accepts connection

  Step 8: resolve_peer("leomatchbot")
    → Pyrogram sends GetUsers RPC to Telegram
    → Returns peer info for @leomatchbot
    → If fails: LOG critical, return (shutdown)

  Step 9: Register handlers
    → app.add_handler(MessageHandler(leomatch_cb, scout_filter))
    → app.add_handler(EditedMessageHandler(leomatch_cb, scout_filter))
    → app.add_handler(MessageHandler(private_cb, dialog_filter))
    → LOG: "[SYSTEM] Handler for @leomatchbot registered."
    → LOG: "[SYSTEM] Handler for private dialogues registered."

  Step 10: STARTUP REPLAY
    → get_chat_history(leomatchbot_peer.user_id, limit=1)
    → Pyrogram fetches last 1 message from @leomatchbot chat

    CASE A — last message exists:
      text = get_message_text(last_message)
      → process_leomatch_message(app, text, state, is_startup=True)
      → (see Flow H or Flow A depending on message content)

    CASE B — chat is empty (first ever run):
      → app.send_message("leomatchbot", "1")
      → Starts the dating bot's main menu flow

  Step 11: asyncio.Event().wait()
    → Event loop now runs indefinitely
    → Pyrogram's internal dispatch loop handles all incoming events
    → System is fully operational
    → LOG: "[SYSTEM] Startup complete. Bot is running in two modes."
```

**Total startup time:** ~1–3 seconds (dominated by Telegram MTProto handshake and Pyrogram session restoration).

**State after boot:**
- `state.model` → live Gemini model
- `state.app` → live Pyrogram client, connected and authenticated
- `state.conversation_histories` → all prior conversations loaded
- `state.whitelist_ids` → whitelist loaded as set
- All three event handlers registered and active

---

## 2. Flow A — Profile Card Arrives (New Profile)

**Trigger:** `@leomatchbot` sends a new profile card message to the operator's Telegram account.

**Profile card format:**
```
Anna, 24, Moscow — I love hiking and coding. Looking for someone who enjoys both.
```

**Pyrogram receives this as a `Message` with `.text` or `.caption` containing the card text.**

### Step-by-step execution

```
[PYROGRAM EVENT DISPATCH]
  MTProto update received from Telegram servers
  → Pyrogram parses binary MTProto packet
  → Creates Message object: {chat_id: leomatchbot_id, text: "Anna, 24, Moscow — ..."}
  → Matches filter: filters.private & filters.chat("leomatchbot") & ~filters.me
  → Calls leomatch_cb(client, message)
  → leomatch_cb = partial(leomatch_handler, state=state)
  → Actual call: leomatch_handler(client, message, state=state)

[leomatch.py: leomatch_handler()]
  event_type = "NEW"  (message.edit_date is None)
  LOG: "[LEOMATCH-DISPATCHER] Received event (Type: NEW)"

  text = get_message_text(message)
  → utils.get_message_text: return message.text or message.caption
  → text = "Anna, 24, Moscow — I love hiking and coding..."

  text is not None/empty → continue

  ANKET_PATTERN.match(text)?
  → re: "^(.+?),\s*(\d+),\s*(.+?)(?:[-–—]\s*(.*))?$"
  → Match! group(1)="Anna" group(2)="24" group(3)="Moscow"
             group(4)="I love hiking and coding. Looking for someone who enjoys both."
  → YES — this is a profile card

  existing leomatch_task exists and not done?
  → state.leomatch_task is None (first profile) OR task.done() → no cancellation

  state.leomatch_task = asyncio.create_task(
      process_leomatch_task(client, message, state)
  )
  → Background task created, scheduled on event loop
  → leomatch_handler() returns immediately
  → Event loop thread is free

[ASYNCIO EVENT LOOP: process_leomatch_task() runs]
  time_since_last_action = (now - state.last_action_time).total_seconds()
  → state.last_action_time = datetime.min → time_since = ~years
  → time_since > ACTION_COOLDOWN_SECONDS (70) → no wait needed

  text = get_message_text(message)  ← re-reads from message object
  LOG: "[LEOMATCH-TASK] Cooldown over. Processing last profile."

  → calls process_leomatch_message(client, text, state, is_startup=False)

[leomatch.py: process_leomatch_message()]
  text_str = "Anna, 24, Moscow — I love hiking and coding..."
  LOG: "[LEOMATCH-EXECUTOR] Analyzing text: \"Anna, 24, Moscow — I love hiking...\""

  any KNOWN_SYSTEM_MESSAGES in text? → NO
  "1. View profiles" in text? → NO

  ANKET_PATTERN.match(text)?
  → YES, match again
  → state.last_seen_anket_text = full text   ← PendingProfile CREATED
  LOG: "[LEOMATCH-EXECUTOR] Profile 'Anna' saved to memory."

  description = match.group(4) = "I love hiking and coding. Looking for someone who enjoys both."
  len(description.strip()) = 57 > 10 → LIKE

  LOG: "[LEOMATCH-EXECUTOR] Profile with description. Liking..."
  await asyncio.sleep(3)   ← 3-second human-like delay before action

  await client.send_message("leomatchbot", "💌 / 📹")
  → Pyrogram encodes message, sends MTProto RPC to Telegram
  → Telegram delivers "💌 / 📹" to @leomatchbot
  → @leomatchbot interprets this as a like

  state.last_action_time = datetime.now(UTC)   ← cooldown starts
  LOG: "[LEOMATCH-EXECUTOR] Cooldown for 70 sec. started."

  → process_leomatch_message() returns
  → process_leomatch_task() returns
  → task is done
```

**Data movement summary:**
- `IncomingMessage` (Telegram → Pyrogram → handler)
- `state.last_seen_anket_text` set to profile card text
- `state.last_action_time` updated
- `"💌 / 📹"` sent to Telegram

**State after flow:**
- `state.last_seen_anket_text = "Anna, 24, Moscow — ..."`
- `state.last_action_time = <now>`
- `state.leomatch_task` = completed task object

---

## 3. Flow B — Mutual Match Established (Opener Sent)

**Trigger:** Anna also liked the operator's profile. `@leomatchbot` sends:
`"Write a message for this user"`

**Precondition:** `state.last_seen_anket_text` contains Anna's profile card from Flow A.

### Step-by-step execution

```
[PYROGRAM EVENT DISPATCH]
  New message from @leomatchbot: "Write a message for this user"
  → Matches scout filter
  → leomatch_handler(client, message, state) called

[leomatch.py: leomatch_handler()]
  text = "Write a message for this user"
  ANKET_PATTERN.match(text)? → NO (not a profile card format)
  → Direct call (no background task): process_leomatch_message(client, text, state)

[leomatch.py: process_leomatch_message()]
  any KNOWN_SYSTEM_MESSAGES? → NO
  "1. View profiles"? → NO
  ANKET_PATTERN match? → NO

  "Write a message for this user" in text? → YES

  state.last_seen_anket_text is not None?
  → YES: "Anna, 24, Moscow — I love hiking and coding..."
  LOG: "[LEOMATCH-EXECUTOR] Message request. Generating..."

  await generate_first_message(state.last_seen_anket_text, state)

  [ai_client.py: generate_first_message()]
    anket_text = "Anna, 24, Moscow — I love hiking and coding..."

    match = ANKET_PATTERN.match(anket_text)
    → group(4) = "I love hiking and coding. Looking for someone who enjoys both."
    profile_text = "I love hiking and coding. Looking for someone who enjoys both."

    len(profile_text) = 57 ≥ 15 → no substitution

    prompt = FIRST_MESSAGE_PROMPT.format(profile_text=profile_text)
    → Full prompt assembled with Anna's description injected

    result = await with_rate_limit_handling(
        lambda: state.model.generate_content(prompt)
    )

    [with_rate_limit_handling()]
      attempt 1:
        asyncio.to_thread(lambda: state.model.generate_content(prompt))
        → spawns OS thread
        → thread executes synchronous genai SDK call
        → HTTPS POST to generativelanguage.googleapis.com
        → Gemini processes prompt
        → Returns response object with .text

      result.text = "so you like hiking — ever done it at 2am when the
                     city's asleep and everything feels like a secret)"

    cleanup_ai_response(result.text):
      → no dashes to replace
      → strip() → no change
      → rstrip(".?!") → removes nothing (ends with ")")
      → collapse spaces → no change
      → return: "so you like hiking — ever done it at 2am when the city's
                 asleep and everything feels like a secret)"
      Wait — dash found: "so you like hiking  ever done it at 2am..."
      → after replacement: "so you like hiking  ever done it at 2am..."
      → after collapse: "so you like hiking ever done it at 2am when the
                         city's asleep and everything feels like a secret)"

    return "so you like hiking ever done it at 2am when the city's asleep and everything feels like a secret)"

  [back in process_leomatch_message()]
  intro_message = "so you like hiking ever done it at 2am..."
  len(intro_message) = 91 ≤ 300 → no fallback needed

  await asyncio.sleep(5)   ← human-like delay before sending opener

  await client.send_message("leomatchbot", intro_message)
  → Pyrogram sends MTProto message to Telegram
  → @leomatchbot delivers opener to Anna's inbox

  state.last_seen_anket_text = None   ← PendingProfile CONSUMED
  LOG: "[LEOMATCH-EXECUTOR] Message sent, memory cleared."
```

**Data movement summary:**
- `state.last_seen_anket_text` → extracted → formatted into prompt
- Prompt → HTTPS → Gemini API → raw text response
- Raw text → `cleanup_ai_response()` → cleaned opener string
- Opener string → MTProto → Telegram → Anna's inbox
- `state.last_seen_anket_text` → `None`

**Anna's experience:** She sees a message in her Telegram inbox appearing to come from a real person: *"so you like hiking ever done it at 2am when the city's asleep and everything feels like a secret)"*

---

## 4. Flow C — Real User Sends First Message

**Trigger:** Anna replies to the opener: *"haha omg yes, with headphones and coffee)"*

**Precondition:** `state.conversation_histories` has no entry for Anna's `chat_id`. Anna is not in `state.whitelist_ids`.

### Step-by-step execution

```
[PYROGRAM EVENT DISPATCH]
  Anna's message arrives: private chat, not from @leomatchbot, not from self
  → Matches interlocutor filter
  → private_chat_handler(client, message, state) called

[dialog.py: private_chat_handler()]
  chat_id = message.chat.id  (e.g., 987654321)

  chat_id in state.whitelist_ids?
  → 987654321 not in {123456789} → NO → continue

  await client.read_chat_history(chat_id)
  → Pyrogram sends ReadHistory MTProto RPC to Telegram
  → Telegram marks all messages in this chat as read
  → Anna sees double blue checkmarks on her message  ← INSTANT
  LOG: "[DISPATCHER] Message from Anna marked as read."

  chat_id in state.active_dialogue_tasks?
  → {} → NO → no cancellation needed

  task = asyncio.create_task(process_dialogue_task(client, message, state))
  state.active_dialogue_tasks[987654321] = task
  → handler returns immediately

[ASYNCIO EVENT LOOP: process_dialogue_task() runs after handler returns]
  chat_id = 987654321
  user_name = "Anna"

  LOG: "[DIALOG] Waiting 7 sec. in case Anna is typing more..."
  await asyncio.sleep(7)   ← GRACE PERIOD
  → 7 seconds pass with no new messages from Anna
  → task resumes

  CLASSIFY SESSION:
  chat_id_str = "987654321"
  "987654321" in state.conversation_histories? → NO
  → is_new_session = True (no prior history)

  LOG: "[DIALOG] Detected NEW session with Anna."
  rand = random.random()  e.g., 0.42

  config_new = REPLY_DELAY_CONFIG["new_session"]
  rand (0.42) < config_new["long"]["chance"] (0.05)?   → NO
  rand (0.42) < 0.05 + 0.35 = 0.40?                   → NO
  → mode = "fast", delay_config = {"min_sec": 15, "max_sec": 60}

  delay = random.randint(15, 60)  e.g., 34
  LOG: "[DIALOG] Reply for Anna will be sent in ~0m 34s (mode: fast)."
  await asyncio.sleep(34)   ← HUMAN-LIKE DELAY

  LOG: "[DIALOG] Time is up. Generating reply for Anna..."

  user_message = get_message_text(message)
  → "haha omg yes, with headphones and coffee)"

  ai_response = await generate_conversation_response(987654321, user_message, state)

  [ai_client.py: generate_conversation_response()]
    chat_id_str = "987654321"
    now_iso = "2026-06-04T14:35:22.000000+00:00"

    "987654321" not in state.conversation_histories
    → state.conversation_histories["987654321"] = []   ← NEW ENTRY

    APPEND USER TURN:
    state.conversation_histories["987654321"].append({
        "role": "user",
        "parts": ["haha omg yes, with headphones and coffee)"],
        "timestamp": "2026-06-04T14:35:22.000000+00:00"
    })
    → len = 1, ≤ 20, no trimming

    BUILD API HISTORY:
    history_for_api = [
        {"role": "user",  "parts": ["haha omg yes, with headphones and coffee)"]}
        # (no model turns yet)
    ]
    full_prompt_history = [
        {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},   ← ~800 tokens
        {"role": "model", "parts": ["understood, I'm ready..."]},
        {"role": "user",  "parts": ["haha omg yes, with headphones and coffee)"]}
    ]
    history_to_send = full_prompt_history[:-1]  ← remove last user message
    = [
        {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
        {"role": "model", "parts": ["understood, I'm ready..."]}
    ]

    chat_session = state.model.start_chat(history=history_to_send)

    result = await with_rate_limit_handling(
        lambda: chat_session.send_message(
            ["haha omg yes, with headphones and coffee)"]
        )
    )
    → asyncio.to_thread() spawns OS thread
    → HTTPS POST to Gemini API with:
        - 2-turn fake system exchange as history
        - user message "haha omg yes, with headphones and coffee)"
    → Gemini processes with full persona context
    → Returns response

    result.text = "now that's the right way to do it) what music though, be honest"

    cleanup_ai_response("now that's the right way to do it) what music though, be honest")
    → no dashes
    → strip() → no change
    → rstrip(".?!") → "now that's the right way to do it) what music though, be honest"
    → (ends with "t" — no trailing punctuation to remove)
    → return: "now that's the right way to do it) what music though, be honest"

    APPEND MODEL TURN:
    state.conversation_histories["987654321"].append({
        "role": "model",
        "parts": ["now that's the right way to do it) what music though, be honest"],
        "timestamp": "2026-06-04T14:35:57.000000+00:00"
    })
    → len = 2

    save_histories(state)
    → storage.save_json_data(HISTORY_PATH, state.conversation_histories)
    → Opens data/conversation_histories.json in "w" mode
    → Writes entire dict to disk (2 turns for Anna's conversation)
    → File closed

    return "now that's the right way to do it) what music though, be honest"

  [back in process_dialogue_task()]
  ai_response = "now that's the right way to do it) what music though, be honest"

  "|||" in ai_response? → NO → single message mode

  typing_delay = len(ai_response) / 8 + random.uniform(0.5, 2.0)
  = 63 / 8 + 1.3  ≈ 9.2 seconds

  await client.send_chat_action(987654321, enums.ChatAction.TYPING)
  → Pyrogram sends SetTyping MTProto RPC
  → Anna sees "typing..." under the bot's name  ← VISIBLE TO ANNA

  LOG: "[DIALOG] Simulating typing 9.2s for message: '...'"
  await asyncio.sleep(9.2)

  await client.send_message(987654321, ai_response)
  → Pyrogram sends SendMessage MTProto RPC
  → Telegram delivers message to Anna's chat
  → Anna receives: "now that's the right way to do it) what music though, be honest"

  LOG: "[DIALOG] Full reply for Anna sent."

  [finally block]
  state.active_dialogue_tasks.pop(987654321, None)
  → task reference removed from dict
```

**Anna's timeline:**
```
T+0s    Anna sends her message
T+0s    Double blue checkmarks appear (read receipt — instant)
T+7s    Grace period expires (no more messages from Anna)
T+41s   Reply appears with "typing..." indicator for ~9 seconds beforehand
```

**Data written to disk:**
```json
{
  "987654321": [
    {"role": "user",  "parts": ["haha omg yes, with headphones and coffee)"],
     "timestamp": "2026-06-04T14:35:22..."},
    {"role": "model", "parts": ["now that's the right way to do it) what music though, be honest"],
     "timestamp": "2026-06-04T14:35:57..."}
  ]
}
```

---

## 5. Flow D — Real User Sends Follow-Up in Active Conversation

**Trigger:** Anna replies: *"macan mostly, sometimes big baby tape"*  (12 minutes after previous message)

**Precondition:** Anna has 2 turns in history. Last timestamp is 12 minutes ago → 12 min < SESSION_TIMEOUT_MINUTES (15) → active session.

### Step-by-step execution

```
[private_chat_handler()]
  chat_id = 987654321
  → not whitelisted
  → read_chat_history() → read receipt sent immediately

  existing task in active_dialogue_tasks[987654321]?
  → last task completed and was popped in finally → {} → NO

  new task created, stored

[process_dialogue_task()]
  sleep(7s grace period)

  CLASSIFY SESSION:
  last_msg_timestamp = "2026-06-04T14:35:57..." (model's last turn, 12 min ago)
  time_since = 12 * 60 = 720 seconds
  SESSION_TIMEOUT_MINUTES * 60 = 900 seconds
  720 < 900 → is_new_session = False

  LOG: "[DIALOG] Continuing ACTIVE session with Anna."
  delay_config = REPLY_DELAY_CONFIG["active_session"] = {"min_sec": 15, "max_sec": 60}
  mode = "active_session"
  delay = random.randint(15, 60)  e.g., 23
  LOG: "[DIALOG] Reply for Anna in ~0m 23s (mode: active_session)."
  await asyncio.sleep(23)

  user_message = "macan mostly, sometimes big baby tape"

  generate_conversation_response(987654321, "macan mostly...", state)

  [ai_client.py]
    EXISTING HISTORY:
    state.conversation_histories["987654321"] = [
        {role: "user",  parts: ["haha omg yes..."], timestamp: T1},
        {role: "model", parts: ["now that's the right way..."], timestamp: T2}
    ]

    APPEND USER TURN → len = 3

    BUILD API HISTORY:
    full_prompt_history = [
        {role: "user",  parts: [SYSTEM_PROMPT]},        ← injected
        {role: "model", parts: ["understood..."]},       ← injected
        {role: "user",  parts: ["haha omg yes..."]},
        {role: "model", parts: ["now that's the right way..."]},
        {role: "user",  parts: ["macan mostly, sometimes big baby tape"]}   ← current
    ]
    history_to_send = first 4 entries (all except last)
    chat_session = model.start_chat(history=history_to_send)

    send_message(["macan mostly, sometimes big baby tape"])
    → Gemini sees full 2-turn conversation context + persona
    → Response: "macan's good, big baby tape has some hits too) taste checks out —
                 what do you listen to on those night hikes"

    APPEND MODEL TURN → len = 4
    save_histories()  ← disk write

  ai_response = "macan's good, big baby tape has some hits too) taste checks out — what do you listen to on those night hikes"

  cleanup: "—" → " " → "macan's good, big baby tape has some hits too) taste checks out  what do you listen to on those night hikes"
  → collapse spaces → "macan's good, big baby tape has some hits too) taste checks out what do you listen to on those night hikes"

  "|||" in ai_response? → NO

  typing_delay = 101 / 8 + jitter ≈ 14.1s
  send_chat_action(TYPING)
  sleep(14.1s)
  send_message(987654321, ai_response)
  → delivered to Anna
```

**Key difference from Flow C:** Session is classified as "active" (12 min < 15 min threshold), so delay is only 15–60 seconds instead of potentially 1–3 hours. The conversation feels responsive.

---

## 6. Flow E — User Sends Burst of Messages (Debounce in Action)

**Trigger:** Anna sends three messages in rapid succession:
- T+0s: *"actually i wanted to ask"*
- T+2s: *"do you ever feel like night walks are almost meditative"*
- T+4s: *"like the city is yours and no one else exists"*

### Step-by-step execution

```
[T+0s: First message arrives]
  private_chat_handler():
    read_chat_history() → read receipt on first message ← INSTANT
    no existing task → create task_1 for "actually i wanted to ask"
    state.active_dialogue_tasks[chat_id] = task_1

  task_1 starts:
    sleep(7s grace period) ← COUNTING DOWN

[T+2s: Second message arrives — task_1 still in grace period]
  private_chat_handler():
    read_chat_history() → read receipt on second message ← INSTANT
    chat_id in active_dialogue_tasks? → YES → task_1.cancel()
    → CancelledError raised in task_1's asyncio.sleep(7)
    → task_1's except CancelledError block:
        LOG: "[DISPATCHER] Task for chat with Anna cancelled."
    → task_1 finally block: active_dialogue_tasks.pop(chat_id)
    → task_1 is gone

    create task_2 for "do you ever feel like night walks are almost meditative"
    state.active_dialogue_tasks[chat_id] = task_2

  task_2 starts:
    sleep(7s grace period) ← COUNTING DOWN FROM ZERO AGAIN

[T+4s: Third message arrives — task_2 at 2 seconds into grace period]
  private_chat_handler():
    read_chat_history() → read receipt on third message ← INSTANT
    chat_id in active_dialogue_tasks? → YES → task_2.cancel()
    → task_2 cancelled in grace period sleep
    → task_2 cleaned up

    create task_3 for "like the city is yours and no one else exists"
    state.active_dialogue_tasks[chat_id] = task_3

  task_3 starts:
    sleep(7s grace period) ← COUNTING DOWN

[T+11s: Grace period expires — no more messages from Anna]
  task_3 resumes

  SESSION CLASSIFICATION: active session
  delay = random.randint(15, 60)  e.g., 19s
  sleep(19s)

  user_message = get_message_text(message)
  → "like the city is yours and no one else exists"
  ← ONLY THE THIRD MESSAGE IS SENT TO AI

  generate_conversation_response(chat_id, "like the city is yours...", state)
  → Gemini sees only this message as the latest user input
  → The first two messages ("actually i wanted to ask" and
    "do you ever feel like night walks...") are NOT visible to Gemini
  → However, read receipts were sent for all three
```

**Anna's experience:**
```
T+0s   First message: double checkmarks instantly
T+2s   Second message: double checkmarks instantly
T+4s   Third message: double checkmarks instantly
T+30s  "typing..." appears
T+34s  AI response arrives — but only addresses the THIRD message
```

**Behavioral gap:** The AI's reply may feel disconnected from the first two messages, because it only sees the last one. In practice, conversational follow-up messages often build on each other, and the final message in a burst is usually the complete thought. But for this example, the AI misses *"do you ever feel like night walks are almost meditative"* entirely.

---

## 7. Flow F — Whitelisted User Sends a Message

**Trigger:** User ID 123456789 (in `whitelist.json`) sends a message.

### Step-by-step execution

```
[PYROGRAM EVENT DISPATCH]
  Message arrives from user 123456789
  → Matches interlocutor filter (private, not bot, not self)
  → private_chat_handler(client, message, state) called

[dialog.py: private_chat_handler()]
  chat_id = 123456789

  chat_id in state.whitelist_ids?
  → 123456789 in {123456789} → YES

  LOG: "[DISPATCHER] User <name> (ID: 123456789) is in whitelist. Ignoring."
  → return immediately

  NO read receipt sent.
  NO task created.
  NO AI call made.
  NO response sent.
```

**Total execution time:** < 1 millisecond. The message is silently ignored. The operator sees it in their Telegram app and responds manually.

**Note:** The absence of a read receipt is the only visible difference from non-whitelisted users. The operator's Telegram app will show an unread badge, signaling that manual attention is needed.

---

## 8. Flow G — Gemini API Rate Limit Hit

**Trigger:** Gemini API returns HTTP 429 (Too Many Requests) during a conversation reply.

### Step-by-step execution

```
[process_dialogue_task() is running, after delay]
  generate_conversation_response(chat_id, user_message, state) called

  [ai_client.py: generate_conversation_response()]
    HISTORY ASSEMBLED
    chat_session.send_message([user_message]) called via to_thread

    [with_rate_limit_handling()]
      ATTEMPT 1:
        asyncio.to_thread(lambda: chat_session.send_message([...]))
        → Gemini API returns 429 ResourceExhausted
        → google.api_core.exceptions.ResourceExhausted raised in thread
        → Exception propagated back to asyncio.to_thread
        → Caught by except google_exceptions.ResourceExhausted as e

        retry_delay = 60  (default)
        if hasattr(e, "error") and hasattr(e.error, "metadata"):
          for meta in e.error.metadata:
            if meta[0] == "retry-delay":
              retry_delay = int(meta[1].seconds) + 1
              break
        → Let's say API says: retry in 47 seconds
        → retry_delay = 48

        LOG: "API limit reached. Retrying in 48 seconds..."
        await asyncio.sleep(48)
        ← event loop is FREE during this sleep
        ← other conversations can still be processed
        ← new messages can still arrive and be handled

      ATTEMPT 2 (after 48s):
        asyncio.to_thread(lambda: chat_session.send_message([...]))
        → This time API returns 200 OK
        → result = response object
        → return result

    result.text = "yeah, exactly that feeling — the silence has a different texture at night"
    cleanup → return cleaned string

  APPEND MODEL TURN
  save_histories()
  return response

  [back in process_dialogue_task()]
  ai_response received
  typing simulation + send
```

**Key behavior:** During the 48-second retry wait, `asyncio.sleep()` yields the event loop. All other active conversation tasks continue normally. The rate-limited conversation simply waits longer before its reply is sent — the user sees no error, just a longer delay (which is indistinguishable from a long human pause).

**Worst case (3 failures):**
```
with_rate_limit_handling():
  attempt 1 → 429 → sleep 60s
  attempt 2 → 429 → sleep 60s
  attempt 3 → 429 → sleep 60s
  all attempts exhausted
  LOG: "Failed to execute API request after several attempts."
  return None

back in generate_conversation_response():
  result = None
  → hasattr(None, "text") → False
  → return "hm, something went wrong, repeat that"   ← FALLBACK STRING

back in process_dialogue_task():
  ai_response = "hm, something went wrong, repeat that"
  → sent to user after typing simulation
```

---

## 9. Flow H — Bot Navigates Dating Bot Menu

**Trigger:** `@leomatchbot` sends its main menu:
```
1. View profiles
2. My profile
3. Settings
```

### Step-by-step execution

```
[leomatch_handler()]
  text = "1. View profiles\n2. My profile\n3. Settings"
  ANKET_PATTERN.match(text)? → NO (doesn't match Name, Age, City format)
  → process_leomatch_message(client, text, state) [direct call]

[process_leomatch_message()]
  any KNOWN_SYSTEM_MESSAGES in text? → NO

  "1. View profiles" in text? → YES
  LOG: "[LEOMATCH-EXECUTOR] Main menu. Pressing '1'."
  await asyncio.sleep(2)   ← brief pause before responding
  await client.send_message("leomatchbot", "1")
  → @leomatchbot receives "1" as navigation command
  → @leomatchbot sends the next profile card
  return
```

**This is the event loop** that keeps the Scout pipeline continuously running:
```
@leomatchbot sends profile → bot likes/dislikes → @leomatchbot sends next profile
                                                    (or sends main menu if session expires)
main menu arrives → bot sends "1" → @leomatchbot sends next profile
```

---

## 10. Flow I — Graceful Shutdown (Ctrl+C)

**Trigger:** Operator presses Ctrl+C in the terminal.

### Step-by-step execution

```
[OS → Python runtime]
  SIGINT signal sent to Python process
  → Python raises KeyboardInterrupt in the asyncio event loop
  → asyncio.run() propagates KeyboardInterrupt upward
  → Pyrogram context manager (__aexit__) runs:
      → disconnects from Telegram gracefully
      → closes MTProto connection

[main.py: except KeyboardInterrupt]
  LOG: "Script stopped by user. Saving history..."
  state = get_state()   ← retrieves _STATE global from app.py
  if state:
    save_histories(state)
    → storage.save_json_data(HISTORY_PATH, state.conversation_histories)
    → Full JSON rewrite to disk

  [All in-flight asyncio tasks are abandoned]
    → Any active dialogue tasks (conversations mid-delay) are lost
    → The leomatch_task (if running) is lost
    → No partial state is saved beyond conversation_histories

  Python process exits with code 0
```

**What is saved:** All completed conversation turns (up to the last write before shutdown).

**What is lost:**
- Any conversation turns from API calls that were in progress
- Delay timers (active conversation tasks restart from scratch)
- The pending profile text (`last_seen_anket_text`)

---

## 11. Flow J — Crash and Restart Recovery

**Scenario:** The process crashes mid-operation (OOM, unhandled exception, server reboot).

### During the crash

```
[Unhandled exception propagates to main.py]
  except Exception as e:
    LOG CRITICAL: "An unexpected critical error occurred: ..."
    state = get_state()
    if state:
      save_histories(state)   ← best-effort save
    process exits

[If OOM / SIGKILL — no Python code runs]
  → conversation_histories.json may be mid-write → CORRUPTED
  → No save occurs
```

### On next startup

```
[app.py: run()]
  load_histories(state):
    path.exists() and stat().st_size > 0? → maybe YES (if crash was mid-write: size=0 or partial)
    json.load() → JSONDecodeError?
      → YES (corrupt file): LOG error, overwrite with {}, return {}
      → NO (clean file): return full history dict

  load_whitelist(state) → unchanged

  STARTUP REPLAY:
  get_chat_history(@leomatchbot, limit=1)
  → Returns whatever the last message from @leomatchbot was

  CASE: Last message was a profile card (bot crashed during cooldown):
    process_leomatch_message(text, is_startup=True)
    → ANKET_PATTERN matches
    → state.last_seen_anket_text = profile text
    → description > 10 chars → send "💌"  ← DOUBLE LIKE (if like was already sent)
    → state.last_action_time updated
    (No cooldown check because last_action_time reset to datetime.min)

  CASE: Last message was "Write a message for this user":
    process_leomatch_message(text, is_startup=True)
    → "Write a message" in text → YES
    → state.last_seen_anket_text is None (lost on crash)
    → LOG WARNING: "Message request, but profile not found in memory. Ignoring."
    → Opener is NOT sent  ← MISSED MATCH

  CASE: Last message was unrecognized:
    → is_startup=True suppresses warning
    → nothing happens

  System resumes normal operation
```

**Recovery quality:**
- Conversation history: fully recovered (from JSON) unless mid-write crash
- Active conversations: reply cycle must restart from the next incoming message
- Scout state: partially recovered (last message replayed)
- Missed opener: unrecoverable without manual intervention

---

## 12. Timing Diagram — Full Conversation from First Sight to Reply

```
WALL CLOCK    OPERATOR ACCOUNT    @LEOMATCHBOT    TELEGRAM         ANNA'S PHONE
────────────────────────────────────────────────────────────────────────────────
T+0s          profile card ◄───────────────────────────────
T+0s          [ANKET_PATTERN matches]
T+0s          [task created]
T+70s         [cooldown expires if recent action]
T+73s         "💌" ────────────────────────────────────────────►
T+73s         [state.last_seen_anket_text = profile]
T+?           (Anna likes back — unknown timing)
T+?           "Write a message" ◄──────────────────────────────
T+?           [generate_first_message called]
T+?+1s        HTTPS → Gemini ───────────────────────────────────────────────────
T+?+2s        ◄─ Gemini response ─────────────────────────────────────────────
T+?+7s        opener ─────────────────────────────────────────────────────────► (Anna inbox)
              ──────────────────────────────────────────────────────────────────
(later)       Anna reads opener, replies
T+0s          message from Anna ◄─────────────────────────────────────────────
T+0s          [read_chat_history] ──────────────────────────────────────────────► ✓✓ (instant)
T+7s          [grace period expires]
T+7s          [session = new, rand = 0.42 → fast mode]
T+7s          [delay = 34s]
T+41s         [generate_conversation_response called]
T+41s         HTTPS → Gemini ───────────────────────────────────────────────────
T+42s         ◄─ Gemini response ─────────────────────────────────────────────
T+42s         [send_chat_action TYPING] ────────────────────────────────────────► "typing..." (Anna sees)
T+51s         send_message ──────────────────────────────────────────────────────► reply (Anna inbox)
────────────────────────────────────────────────────────────────────────────────
Total time from Anna sending first message to receiving reply: ~51 seconds (fast mode)
Maximum possible delay (long mode): 3+ hours
```

---

## 13. Concurrency Snapshot — Multiple Simultaneous Events

**Scenario:** Three things happen within the same second:
- Anna sends a message
- Barb sends a message (different private chat)
- @leomatchbot sends a new profile card

```
EVENT LOOP THREAD (single thread, cooperative):

[T=0ms]   Pyrogram receives MTProto update from Anna
          private_chat_handler(client, anna_msg, state) called
            → read_chat_history(anna_chat_id)   [YIELDS to event loop — network I/O]
            ← receipt confirmed
            → create task_anna = process_dialogue_task(anna_msg)
            → return  [handler done in ~5ms]

[T=5ms]   Pyrogram receives MTProto update from Barb
          private_chat_handler(client, barb_msg, state) called
            → read_chat_history(barb_chat_id)   [YIELDS]
            ← receipt confirmed
            → create task_barb = process_dialogue_task(barb_msg)
            → return

[T=10ms]  Pyrogram receives MTProto update from @leomatchbot
          leomatch_handler(client, profile_msg, state) called
            → ANKET_PATTERN matches
            → create task_leomatch = process_leomatch_task(profile_msg)
            → return

[T=10ms–7000ms]  Three tasks all sleep concurrently:
          task_anna:    sleeping grace period (7000ms)
          task_barb:    sleeping grace period (7000ms)
          task_leomatch: sleeping cooldown (potentially 0ms if cooldown expired)

[T=7000ms]  task_anna wakes from grace period
              → classify session, determine delay (e.g., 34s)
              → sleep(34000ms)   [YIELDS — both barb and leomatch can run]

            task_barb wakes from grace period (same time, ~ms apart)
              → classify session, determine delay (e.g., 2400s — medium mode!)
              → sleep(2400000ms)   [YIELDS immediately]

[T=7000ms+]  task_leomatch wakes from cooldown (if expired)
              → process_leomatch_message()
              → decide to like/dislike
              → sleep(3000ms) before sending action  [YIELDS]

[T=10000ms]  task_leomatch sends "💌" to @leomatchbot
              → state.last_action_time updated
              → task_leomatch completes

[T=41000ms]  task_anna wakes from 34s delay
              → generate_conversation_response called
              → asyncio.to_thread(gemini_call)  [YIELDS — OS thread spawned]
              ← Gemini response received (1-2s)
              → send_chat_action (TYPING)  [YIELDS — network]
              → sleep typing delay  [YIELDS — task_barb still sleeping]
              → send_message  [YIELDS — network]
              → task_anna completes

[T=2407000ms (~40 min)]  task_barb wakes from medium delay
              → ... same pattern as Anna
```

**The critical insight:** All of this runs in one thread. None of these tasks actually execute simultaneously — they interleave by yielding at every `await`. The event loop runs exactly one coroutine at a time. The illusion of parallelism is created entirely by cooperative yielding at I/O operations and sleep calls.

**Resource usage during peak:**
- 1 OS thread for asyncio event loop
- 1 OS thread per active Gemini API call (spawned by `asyncio.to_thread`)
- In the scenario above: 3 active tasks, potentially 1–2 Gemini threads
- Total: 2–4 OS threads maximum at any instant
