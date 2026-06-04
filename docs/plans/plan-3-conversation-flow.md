# Plan 3 — Conversation Flow Completeness

_Week: 2 | Prerequisite: Plans 1 + 2 complete | Must complete before: Plan 5_

> **Goal:** Close the product's most impactful behavioral gaps.
> Make every conversation contextually complete from the first message onward.

---

## Issues Addressed

| Issue | Summary |
|-------|---------|
| ISSUE-12 | Opener never stored — every conversation starts amnesiac |
| ISSUE-13 | Burst messages truncated — only last message reaches AI |
| ISSUE-14 | Profile quality filter is character count, not content intelligence |
| ISSUE-15 | Context window discards early conversation facts permanently |
| ISSUE-16 | SIGTERM not handled — history unsaved on managed shutdown |
| ISSUE-17 | Opener cleared unconditionally even when send fails |
| ISSUE-31 | Reply delay has a hard binary cliff at 15-minute boundary |

---

## Task 3.1 — Store Opener in Conversation History

**Status:** ⬜ Not started
**Files:** `src/state.py`, `src/leomatch.py`, `src/ai_client.py`
**Estimated effort:** 2 hours
**Depends on:** Plan 1 complete (reliable storage), Plan 2 Task 2.1

### Problem
The opener (first message to a match) is sent through `@leomatchbot` and never written to `conversation_histories`. When the match replies privately, the Interlocutor starts with no memory of what was said first. The AI cannot build on, reference, or stay consistent with its own opening message.

The root blocker: the match's Telegram user ID is unknown at opener-send time (openers go through the bot, not directly to the user). The user ID becomes known only when they send their first private message.

### Implementation

**Step 1:** Add `sent_openers` to `BotState` in `state.py`:

```python
# state.py
sent_openers: list = field(default_factory=list)
# Format: [{"text": str, "sent_at": str (ISO timestamp)}, ...]
# Bounded to last 5 entries (handles rapid mutual matches)
```

**Step 2:** In `leomatch.py`, `process_leomatch_message()`, move `last_seen_anket_text = None` to after a confirmed send, and store the opener (this also fixes ISSUE-17):

```python
# leomatch.py — replace the opener-send block:
if "Write a message for this user" in text:
    if state.last_seen_anket_text:
        logging.info("[LEOMATCH-EXECUTOR] Message request. Generating...")
        intro_message = await generate_first_message(state.last_seen_anket_text, state)
        if len(intro_message) > 300:
            logging.warning(
                f"[LEOMATCH-EXECUTOR] AI message too long ({len(intro_message)} chars). "
                "Using fallback."
            )
            intro_message = (
                "your profile caught my eye, but my brain is on strike today) "
                "tell me something about yourself that's not in the profile"
            )
        try:
            await asyncio.sleep(5)
            await client.send_message(BOT_USERNAME, intro_message)

            # Store opener AFTER confirmed send
            state.sent_openers.append({
                "text": intro_message,
                "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            })
            state.sent_openers = state.sent_openers[-5:]  # keep last 5
            state.last_seen_anket_text = None             # clear only after success
            logging.info("[LEOMATCH-EXECUTOR] Opener sent and stored. Memory cleared.")

        except Exception as e:
            logging.error(f"[LEOMATCH-EXECUTOR] Failed to send opener: {e}")
            # last_seen_anket_text preserved — startup replay may retry
    else:
        logging.warning(
            "[LEOMATCH-EXECUTOR] Write message request but no profile in memory. "
            "Ignoring."
        )
    return
```

**Step 3:** In `ai_client.py`, `generate_conversation_response()`, inject the opener as the first model turn for new conversations:

```python
# ai_client.py — at the start of generate_conversation_response(), before appending user turn:

chat_id_str = str(chat_id)
now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

# If this is a brand-new conversation, inject the most recent opener
if chat_id_str not in state.conversation_histories or \
        not state.conversation_histories[chat_id_str]:
    if state.sent_openers:
        oldest_opener = state.sent_openers.pop(0)  # FIFO
        state.conversation_histories[chat_id_str] = [{
            "role": "model",
            "parts": [oldest_opener["text"]],
            "timestamp": oldest_opener["sent_at"]
        }]
        logging.info(
            f"[AI] Injected sent opener as first model turn for user {chat_id}."
        )
    else:
        state.conversation_histories[chat_id_str] = []
```

### Verification
```bash
# 1. Start bot fresh (clear sent_openers field)
# 2. Trigger a mutual match: send opener through @leomatchbot
# 3. Verify: sent_openers has one entry in state
# 4. Reply to the match (simulate their first private message)
# 5. Verify: conversation_histories[user_id][0] is the opener (role: "model")
# 6. Verify: AI's first reply references or builds on the opener content
```

---

## Task 3.2 — Burst Message Accumulation

**Status:** ⬜ Not started
**Files:** `src/state.py`, `src/dialog.py`
**Estimated effort:** 1.5 hours
**Depends on:** Nothing (independent)

### Problem
When a user sends multiple messages rapidly, only the last message reaches the AI. Earlier messages generate read receipts but their content is invisible to the AI. Multi-part thoughts are silently truncated.

### Implementation

**Step 1:** Add `message_buffers` to `BotState` in `state.py`:

```python
# state.py
message_buffers: Dict[int, list] = field(default_factory=dict)
# {chat_id: [message_text_1, message_text_2, ...]}
```

**Step 2:** In `dialog.py`, `private_chat_handler()`, accumulate messages before creating the task:

```python
# dialog.py — private_chat_handler(), before task creation:

# Accumulate message text into buffer
text = get_message_text(message)
if text:
    if chat_id not in state.message_buffers:
        state.message_buffers[chat_id] = []
    state.message_buffers[chat_id].append(text)

# Cancel existing task (debounce — unchanged)
if chat_id in state.active_dialogue_tasks:
    state.active_dialogue_tasks[chat_id].cancel()
    logging.info(
        f"[DISPATCHER] User {message.from_user.first_name} wrote again. Timer restarted."
    )

task = asyncio.create_task(process_dialogue_task(client, message, state))
state.active_dialogue_tasks[chat_id] = task
```

**Step 3:** In `process_dialogue_task()`, collect the buffer after the grace period:

```python
# dialog.py — process_dialogue_task(), after sleep(GRACE_PERIOD_SECONDS):

# Collect all buffered messages for this chat
buffered = state.message_buffers.pop(chat_id, [])

if not buffered:
    # Fallback: use the message text from the task's closure
    user_message = get_message_text(message)
    if not user_message:
        logging.warning(f"[DIALOG] No message content for {user_name}. Cancelling.")
        return
else:
    # Combine all accumulated messages into one input
    user_message = "\n".join(buffered)
    if len(buffered) > 1:
        logging.info(
            f"[DIALOG] Combined {len(buffered)} buffered messages for {user_name}."
        )
```

**Step 4:** In the `finally` block of `process_dialogue_task()`, also clear the buffer:

```python
finally:
    state.active_dialogue_tasks.pop(chat_id, None)
    state.message_buffers.pop(chat_id, None)  # ← add this line
```

### Verification
```bash
# Send 3 messages in under 7 seconds (within grace period):
#   "actually wait"
#   "I have a question"
#   "do you believe in fate?"
# Verify in logs: "[DIALOG] Combined 3 buffered messages for <name>"
# Verify: AI response addresses all three messages, not just the last
```

---

## Task 3.3 — Intelligent Profile Quality Filter

**Status:** ⬜ Not started
**Files:** `src/ai_client.py`, `src/leomatch.py`
**Estimated effort:** 2 hours
**Depends on:** Plan 2 Tasks 2.1, 2.2

### Problem
The like/dislike decision is based on `len(description) > 10`. A 70-character meaningless profile gets liked; a 6-character meaningful profile ("artist") gets disliked. The README claims intelligent quality filtering — the code counts characters.

### Implementation

**Step 1:** Add `classify_profile_quality()` to `ai_client.py`:

```python
async def classify_profile_quality(description: str, state) -> bool:
    """
    Returns True if the profile description is worth messaging.
    Falls back to character-count logic if AI is unavailable.
    """
    if not state.model:
        return len(description.strip()) > 10  # fallback

    # Fast binary classification prompt
    prompt = (
        f'Dating profile description: "{description}"\n\n'
        "Is this profile worth sending a first message to?\n"
        "Consider: genuine personality, conversation hooks, real effort.\n"
        "Ignore: blank, bot-like, purely transactional, or copy-paste profiles.\n"
        "Answer with only YES or NO."
    )
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
    if result and hasattr(result, "text"):
        answer = result.text.strip().upper()
        decision = answer.startswith("YES")
        logging.info(
            f"[AI] Profile classification: '{description[:50]}...' → {'LIKE' if decision else 'DISLIKE'}"
        )
        return decision

    # Fallback if AI call failed
    return len(description.strip()) > 10
```

**Step 2:** In `leomatch.py`, `process_leomatch_message()`, replace the character-count like/dislike block:

```python
# leomatch.py — replace the profile action block:
match = ANKET_PATTERN.match(text)
if match:
    state.last_seen_anket_text = text
    logging.info(
        f"[LEOMATCH-EXECUTOR] Profile '{match.group(1).strip()}' saved to memory."
    )
    description = (match.group(4) or "").strip()

    if description:
        should_like = await classify_profile_quality(description, state)
    else:
        should_like = False
        logging.info("[LEOMATCH-EXECUTOR] No description. Disliking.")

    if should_like:
        logging.info("[LEOMATCH-EXECUTOR] Profile approved. Liking...")
        await asyncio.sleep(3)
        await client.send_message(BOT_USERNAME, "💌 / 📹")
    else:
        logging.info("[LEOMATCH-EXECUTOR] Profile rejected. Disliking...")
        await asyncio.sleep(3)
        await client.send_message(BOT_USERNAME, "👎")

    state.last_action_time = datetime.datetime.now(datetime.timezone.utc)
    logging.info(
        f"[LEOMATCH-EXECUTOR] Cooldown for {ACTION_COOLDOWN_SECONDS}s started."
    )
    return
```

### Verification
```bash
# Test with 4 profile descriptions:
# 1. Short meaningful: "artist" → should LIKE
# 2. Long meaningless: "idk what to write here just trying this app" → should DISLIKE
# 3. Good description with hooks → LIKE
# 4. Empty → DISLIKE (no AI call needed)
# Verify decision log lines appear correctly
```

---

## Task 3.4 — Persistent Conversation Memory

**Status:** ⬜ Not started
**Files:** `src/state.py`, `src/ai_client.py`, `src/storage.py`, `src/app.py`, `src/config.py`
**Estimated effort:** 3 hours
**Depends on:** Plan 1 complete, Plan 2 Task 2.1

### Problem
The 20-turn sliding window permanently discards early conversation content. The AI forgets names, stated preferences, personal disclosures, and anything mentioned before the last 20 turns. Conversations that span more than 10 exchanges lose coherence.

### Implementation

**Step 1:** Add `conversation_memories` to `BotState` in `state.py`:

```python
# state.py
conversation_memories: Dict[str, str] = field(default_factory=dict)
# {user_id_str: "compact string of key facts about this person"}
```

**Step 2:** Add `MEMORY_PATH` and persist/load functions to `storage.py`:

```python
# config.py
MEMORY_PATH = DATA_DIR / "conversation_memories.json"

# storage.py
def load_memories(state):
    state.conversation_memories = load_json_data(MEMORY_PATH, {})
    logging.info("Conversation memories loaded.")

def save_memories(state):
    save_json_data(MEMORY_PATH, state.conversation_memories)
```

**Step 3:** Load memories in `app.py`, after `load_histories(state)`:

```python
from storage import load_memories
load_memories(state)
```

**Step 4:** Add background memory update function in `ai_client.py`:

```python
async def _update_memory(chat_id_str: str, recent_turns: list, state):
    """Extract and store key facts from recent turns into persistent memory."""
    if not state.model:
        return
    existing = state.conversation_memories.get(chat_id_str, "")
    turns_text = "\n".join(
        f"{t['role'].upper()}: {t['parts'][0]}" for t in recent_turns
    )
    prompt = (
        f"Existing notes about this person: {existing}\n\n"
        f"Recent conversation:\n{turns_text}\n\n"
        "Update the notes with any NEW key facts about the user "
        "(their name, job, hobbies, stated preferences, important things they mentioned). "
        "Be extremely concise — maximum 2 sentences. Facts only, no analysis. "
        "If nothing new is mentioned, return the existing notes unchanged."
    )
    result = await with_rate_limit_handling(lambda: state.model.generate_content(prompt))
    if result and hasattr(result, "text"):
        updated = result.text.strip()
        if updated:
            state.conversation_memories[chat_id_str] = updated
            asyncio.create_task(
                asyncio.to_thread(save_memories, state)
            )
            logging.info(f"[AI] Memory updated for user {chat_id_str}: {updated[:80]}")
```

**Step 5:** Trigger memory update every 4 turns in `generate_conversation_response()`, after appending the model turn:

```python
# After appending model_turn:
turns = state.conversation_histories[chat_id_str]
if len(turns) % 4 == 0 and len(turns) >= 4:
    asyncio.create_task(_update_memory(chat_id_str, turns[-4:], state))
```

**Step 6:** Inject memory at the start of each API history build in `generate_conversation_response()`:

```python
# After building history_for_api, before slicing:
memory = state.conversation_memories.get(chat_id_str, "")
if memory and history_for_api:
    # Prepend memory as a context note in the first user turn's content
    # Do NOT modify the stored history — create a modified copy for the API only
    history_for_api_with_memory = list(history_for_api)
    if history_for_api_with_memory[0]["role"] == "user":
        first_turn = dict(history_for_api_with_memory[0])
        first_turn["parts"] = [f"[About this person: {memory}]\n\n{first_turn['parts'][0]}"]
        history_for_api_with_memory[0] = first_turn
    history_for_api = history_for_api_with_memory
```

### Verification
```bash
# Have a 6-turn conversation where the user mentions their job and a hobby in turn 1-2
# Reach turn 5 (memory should update after turn 4)
# Check data/conversation_memories.json — should contain extracted facts
# Have a 12-turn conversation, push early messages out of window
# Verify: AI still references the user's name/job from the memory
```

---

## Task 3.5 — Smooth Reply Delay Curve

**Status:** ⬜ Not started
**Files:** `src/config.py`, `src/dialog.py`
**Estimated effort:** 1 hour
**Depends on:** Nothing (independent)

### Problem
The binary 15-minute session threshold creates an abrupt behavioral cliff: a 14:59 gap always gets a fast reply; a 15:01 gap potentially gets a 3-hour delay. Real people's response speeds vary continuously, not in hard tiers.

### Implementation

**Step 1:** Add `compute_reply_delay()` to `config.py`:

```python
import math

def compute_reply_delay(gap_seconds: float) -> int:
    """
    Compute a natural reply delay based on time since last message.
    Short gaps → fast replies. Longer gaps → increasingly slower replies.
    Returns delay in seconds.
    """
    import random

    if gap_seconds < 120:
        # Very active conversation: 15–45s
        return random.randint(15, 45)

    elif gap_seconds < 900:
        # Active conversation (2–15 min): 15–90s, slightly slower
        return random.randint(15, 90)

    elif gap_seconds < 3600:
        # Cooling off (15 min–1h): mostly medium, occasionally fast
        p_medium = min(0.8, (gap_seconds - 900) / 2700)
        if random.random() < p_medium:
            return random.randint(120, 600)
        return random.randint(15, 90)

    elif gap_seconds < 86400:
        # Cold (1h–24h): mix of medium and long
        p_long = min(0.25, (gap_seconds - 3600) / 82800 * 0.25)
        if random.random() < p_long:
            return random.randint(1800, 7200)
        return random.randint(300, 1200)

    else:
        # Very cold (24h+): treat as new contact
        if random.random() < 0.05:
            return random.randint(3600, 10800)
        return random.randint(300, 1800)
```

**Step 2:** In `dialog.py`, `process_dialogue_task()`, replace the tiered delay logic with the function call:

```python
# dialog.py — replace session classification + delay calculation block:

# Compute gap since last message
gap_seconds = 0.0
if chat_id_str in state.conversation_histories and state.conversation_histories[chat_id_str]:
    last_ts_str = state.conversation_histories[chat_id_str][-1].get("timestamp")
    if last_ts_str:
        try:
            last_ts = datetime.datetime.fromisoformat(last_ts_str)
            gap_seconds = (datetime.datetime.now(datetime.timezone.utc) - last_ts).total_seconds()
        except ValueError:
            pass

delay = compute_reply_delay(gap_seconds)
logging.info(
    f"[DIALOG] Reply for {user_name} in ~{delay // 60}m {delay % 60}s "
    f"(gap: {gap_seconds:.0f}s)."
)
await asyncio.sleep(delay)
```

**Step 3:** Remove `REPLY_DELAY_CONFIG` and `SESSION_TIMEOUT_MINUTES` from `config.py` once `compute_reply_delay` is confirmed working (or keep as fallback).

### Verification
```bash
# Test delay outputs for various gap values:
# gap=30s   → expect 15–45s delay
# gap=600s  → expect 15–90s delay
# gap=1800s → expect 120–600s delay (mostly)
# gap=7200s → expect 300–1200s delay
# Confirm no abrupt behavioral jump at any specific gap value
```

---

## Completion Checklist

```
[ ] Task 3.1 — Opener stored and injected: verify first reply references opener
[ ] Task 3.2 — Burst accumulation: verify all 3 burst messages reach AI
[ ] Task 3.3 — Profile quality filter: verify AI classification (4 test cases)
[ ] Task 3.4 — Conversation memory: verify facts persist beyond 20-turn window
[ ] Task 3.5 — Smooth delay curve: verify no cliff at 15-minute boundary
[ ] ISSUE-17 fix: verify opener cleared only after confirmed send (implicit in 3.1)
[ ] Full end-to-end smoke test: profile → opener → conversation → memory → meeting
[ ] Update plan status in plans/README.md
```

## What Changes After This Plan

- Every conversation has the opener as its first context turn
- Multi-part user thoughts are fully represented to the AI
- Profile selection is based on content intelligence, not character count
- Long conversations remember early facts through the memory system
- Reply timing is natural and continuous, not binary
- **Plan 5 (product intelligence) can now be started**
