# Performance & Scalability Analysis — AI Dating Assistant

_Last updated: 2026-06-04_

> Baseline context: the system is designed for one operator, one Telegram account,
> dozens of concurrent conversations. All performance observations are relative to
> that baseline and to what would happen if it were scaled beyond it.

---

## Table of Contents

1. [Operation Cost Inventory](#1-operation-cost-inventory)
2. [Bottleneck Analysis](#2-bottleneck-analysis)
3. [Memory Profile](#3-memory-profile)
4. [I/O Profile](#4-io-profile)
5. [Latency Budget Per Response](#5-latency-budget-per-response)
6. [Caching Strategy Audit](#6-caching-strategy-audit)
7. [Real-Time vs Batch Processing](#7-real-time-vs-batch-processing)
8. [Behavior Under Scale](#8-behavior-under-scale)
9. [What Breaks First Under Load](#9-what-breaks-first-under-load)
10. [Performance Risk Register](#10-performance-risk-register)
11. [Optimization Roadmap](#11-optimization-roadmap)

---

## 1. Operation Cost Inventory

Every operation the system performs, ranked by relative cost:

### Tier 1 — Dominant Cost (network-bound, external)

| Operation | Where | Frequency | Typical latency | Cost driver |
|-----------|-------|-----------|----------------|-------------|
| Gemini API call (conversation reply) | `ai_client.py` | Once per conversation reply | 500ms–3s | Network RTT + model inference |
| Gemini API call (opener generation) | `ai_client.py` | Once per mutual match | 500ms–3s | Network RTT + model inference |
| Telegram send_message | `dialog.py`, `leomatch.py` | Once per reply/action | 100–500ms | Network RTT |
| Telegram send_chat_action | `dialog.py` | Once per reply | 100–300ms | Network RTT |
| Telegram read_chat_history | `dialog.py` | Once per incoming message | 100–300ms | Network RTT |

### Tier 2 — Significant Cost (I/O-bound, local)

| Operation | Where | Frequency | Typical latency | Cost driver |
|-----------|-------|-----------|----------------|-------------|
| `save_json_data` (full history rewrite) | `storage.py` | After every AI reply | 1–50ms | Disk I/O proportional to file size |
| Log file write | All modules via logging | Dozens per event | <1ms each, batched by OS | Disk I/O (buffered) |

### Tier 3 — Cheap (CPU-bound, in-memory)

| Operation | Where | Frequency | Typical latency | Cost driver |
|-----------|-------|-----------|----------------|-------------|
| `ANKET_PATTERN.match(text)` | `leomatch.py` | Per bot message | <0.1ms | Regex evaluation |
| `cleanup_ai_response(text)` | `ai_client.py` | Per AI response | <0.1ms | String operations |
| History assembly for Gemini | `ai_client.py` | Per AI call | <0.1ms | List construction |
| History trim `history[-20:]` | `ai_client.py` | Per AI call | <0.1ms | Slice operation |
| Whitelist membership test | `dialog.py` | Per incoming message | <0.01ms | Hash set lookup |
| Session classification | `dialog.py` | Per task | <0.1ms | Timestamp arithmetic |
| `|||` split | `dialog.py` | Per AI response | <0.1ms | String split |
| `json.dump` serialization | `storage.py` | Per save | 1–10ms | JSON encoding |
| `json.load` deserialization | `storage.py` | Once at startup | 1–10ms | JSON decoding |

**Key insight:** The system is almost entirely network-bound. CPU cost is negligible. Memory pressure is low. The only meaningful computation is outsourced to Google's infrastructure.

---

## 2. Bottleneck Analysis

### Bottleneck 1 — Gemini API Response Time (primary bottleneck)

Every conversation reply blocks on a Gemini API call. This call takes 500ms–3s under normal conditions and can take minutes if rate-limited. The entire reply cycle for a conversation cannot progress until this call completes.

```
User sends message
  → 7s grace period
  → 15–10800s reply delay
  → [BLOCKED] Gemini API call: 0.5–3s   ← primary bottleneck
  → typing simulation: proportional to response length
  → message send
```

**Impact:** Under current single-operator scale, this is fine — conversations have long intentional delays anyway, so an extra 2 seconds is imperceptible. At scale (hundreds of simultaneous conversations all completing their delays at the same time), concurrent Gemini calls would pile up.

**Mitigant in current code:** `asyncio.to_thread` ensures Gemini calls don't block other conversations. Multiple simultaneous Gemini calls run in parallel OS threads. The bottleneck is Gemini's server capacity and the operator's API quota, not the application.

---

### Bottleneck 2 — JSON Full-Rewrite on Every Save

```python
def save_json_data(filepath, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
```

Every AI reply triggers a complete rewrite of `conversation_histories.json`. The cost is:
- `json.dump`: O(total messages × average message length)
- File I/O: O(file size)

**Current file size estimate:** Empty (currently `{}`). At peak operation:
- 100 users × 20 turns × 150 bytes/turn = ~300 KB
- `json.dump` on 300 KB: ~2–5ms
- File write (300 KB): ~1–10ms depending on storage

**At what scale does this matter?** At 1,000 active users, the file grows to ~3 MB. `json.dump` takes ~20–50ms. At this point, the synchronous file write inside the event loop becomes a source of event loop starvation.

**The critical path:**
```
asyncio event loop (single thread)
  ├── receive Telegram event (fast)
  ├── Gemini API call (in thread pool — doesn't block loop)
  └── save_histories() ← SYNCHRONOUS FILE I/O IN EVENT LOOP THREAD
        json.dump(all_data, f) ← blocks event loop during disk write
```

`save_histories()` is called from within `generate_conversation_response()`, which is called from within a `process_dialogue_task` coroutine — which runs in the event loop thread (not in `asyncio.to_thread`). The file I/O blocks the event loop.

At current scale (< 10 active conversations, < 50 KB file): imperceptible.
At 100 conversations (500 KB file): ~5ms block — still fine.
At 1,000 conversations (5 MB file): ~50ms block — noticeable.
At 10,000 conversations (50 MB file): ~500ms block — event loop effectively frozen for half a second per save.

---

### Bottleneck 3 — Single Event Loop Thread

The entire application runs in one asyncio event loop thread. All coroutines — all conversation tasks, the Scout task, all Pyrogram event processing — compete for this single thread.

During `save_histories()`:
- The thread is blocked on disk I/O
- No other coroutine can run
- Incoming Telegram messages are queued in Pyrogram's internal buffer
- Typing simulations are paused

At current scale: invisible. At higher scale: causes timing jitter in all operations.

---

### Bottleneck 4 — Startup: Full History Loaded into RAM

```python
state.conversation_histories = load_json_data(HISTORY_PATH, {})
```

At startup, the entire `conversation_histories.json` is read from disk and parsed into a Python dict in memory. This is a one-time cost at startup but it means:
1. Startup time scales with file size
2. Peak memory usage at startup = O(file size × ~3–5× for Python dict overhead)

At 1,000 users × 20 turns: ~3 MB JSON → ~10–15 MB Python dict.
At 10,000 users × 20 turns: ~30 MB JSON → ~100–150 MB Python dict.

For a personal server with 512 MB RAM this is trivially fine. For scale, it becomes a startup-time concern.

---

### Bottleneck 5 — History Assembly Per AI Call

For every conversation reply:
```python
history_for_api = [
    {"role": str(msg["role"]), "parts": list(msg["parts"])}
    for msg in state.conversation_histories[chat_id_str]
]
full_prompt_history = [
    {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
    {"role": "model", "parts": ["understood..."]},
]
full_prompt_history.extend(history_for_api)
```

This creates new list objects and dict objects on every call. With 20-turn histories, this creates ~22 dict objects per call. Python's garbage collector handles this easily. At thousands of calls per second this would be measurable — at current scale it's imperceptible.

The more significant cost: the `CONVERSATION_SYSTEM_PROMPT` string (~800 tokens) is included in every API call payload. This is re-serialized and re-transmitted on every request. It's not cached anywhere.

---

## 3. Memory Profile

### At current scale (single operator, ~50 active users)

| Component | Estimated memory | Notes |
|-----------|-----------------|-------|
| Python runtime | ~20–30 MB | Interpreter baseline |
| Pyrogram client | ~10–20 MB | MTProto session, update handlers, internal buffers |
| google-generativeai SDK | ~15–25 MB | Includes protobuf, grpcio if used |
| `state.conversation_histories` | ~1–5 MB | Depends on conversation volume |
| `state.whitelist_ids` | < 1 KB | Set of integers |
| `state.active_dialogue_tasks` | < 1 KB | Dict of task references |
| Active asyncio tasks | ~1–5 MB | Each task has stack frame + closure |
| Gemini thread pool | ~5–10 MB | OS threads during API calls |
| Log buffer (OS-level) | ~1 MB | Before flush to disk |
| **Total estimate** | **~55–90 MB** | Well within 512 MB server |

### Memory growth over time

The only growing memory consumer is `state.conversation_histories`. It grows as:
- New users send first messages (new keys added, never removed)
- Each conversation maintains at most 20 turns (constant per user)

Growth rate: ~3 KB per new user (initial 2 turns). Bounded per user at ~3 KB (20 turns × 150 bytes). At 10,000 total users: ~30 MB.

**No memory leak exists in the current design** for any other data structure. `active_dialogue_tasks` is cleaned by `finally` blocks. `leomatch_task` is replaced, not accumulated. Log handlers don't buffer in memory (RotatingFileHandler flushes to disk).

---

## 4. I/O Profile

### Network I/O

| Channel | Direction | Volume | Pattern |
|---------|-----------|--------|---------|
| Telegram MTProto | Bidirectional | Low (text messages) | Bursty — event-driven |
| Gemini API HTTPS | Outbound req / Inbound resp | Medium (800 token system prompt + 20 turns) | Bursty — one per reply cycle |

Payload size per Gemini call:
```
System prompt:   ~800 tokens  (~3,200 chars)
20 turns × 50 tokens avg = ~1,000 tokens  (~4,000 chars)
Current message: ~20 tokens   (~80 chars)
Total:           ~1,820 tokens per request
```

At $0.075 per million tokens (Gemini Flash input pricing as of 2024), each call costs ~$0.000136. At 100 calls/day: ~$0.014/day. Negligible.

**The 800-token system prompt overhead is the single biggest avoidable cost.** Using `system_instruction=` (see engineering decisions) would remove it from the per-call payload entirely, reducing each call's token count by ~44%.

### Disk I/O

| Operation | Frequency | Volume | Pattern |
|-----------|-----------|--------|---------|
| `save_histories` | After every AI reply | Full file rewrite (~1–500 KB) | Synchronous, blocking |
| Log write | Per event (dozens/minute) | ~100–500 bytes per line | Buffered, periodic flush |
| Session file | At startup + Pyrogram internals | ~50 KB | Infrequent |

**The log file is the highest-frequency disk writer** (dozens of writes per conversation cycle). However, Python's `RotatingFileHandler` uses OS-level buffered I/O — writes are typically batched by the OS buffer and flushed in blocks. Actual disk writes are much less frequent than individual log calls.

---

## 5. Latency Budget Per Response

A complete response cycle for a private conversation, from message receipt to delivery:

```
Phase                    Latency          Variable?  Operator-controlled?
─────────────────────────────────────────────────────────────────────────
Pyrogram event dispatch   <10ms            No         No
read_chat_history()       100–300ms        Yes        No (network)
Task creation             <1ms             No         No
─────────────────────────────────────────────────────────────────────────
GRACE PERIOD              7,000ms fixed    No         Yes (GRACE_PERIOD_SECONDS)
─────────────────────────────────────────────────────────────────────────
SESSION CLASSIFICATION    <1ms             No         No
─────────────────────────────────────────────────────────────────────────
REPLY DELAY               15s – 10,800s    Yes        Yes (REPLY_DELAY_CONFIG)
─────────────────────────────────────────────────────────────────────────
get_message_text()        <1ms             No         No
History assembly          <1ms             No         No
Gemini API call           500ms – 3,000ms  Yes        No (external)
History append            <1ms             No         No
save_histories()          1ms – 50ms       Yes        No (scales with data)
─────────────────────────────────────────────────────────────────────────
TYPING SIMULATION         len/8 + jitter   Yes        Yes (TYPING_SPEED_CPS)
                          (~5–20s typical)
─────────────────────────────────────────────────────────────────────────
send_message()            100–500ms        Yes        No (network)
─────────────────────────────────────────────────────────────────────────

MINIMUM POSSIBLE          ~7.7s  (grace + fast delay min + API + type + send)
MAXIMUM POSSIBLE          ~10,823s  (grace + long delay max + slow API + type + send)
TYPICAL (fast mode)       ~50–90s
TYPICAL (medium mode)     ~8–17 minutes
TYPICAL (long mode)       1–3+ hours
```

**The intentional delays dominate all other latency.** Grace period (7s) + minimum fast delay (15s) = 22 seconds minimum before an AI call is even made. The AI call itself (0.5–3s) is a rounding error in the total budget.

---

## 6. Caching Strategy Audit

### What is cached

| Data | Where cached | Invalidation | Notes |
|------|-------------|-------------|-------|
| Conversation histories | `state.conversation_histories` (RAM) | Never — full lifetime | Loaded once, written on every save, never evicted |
| Whitelist IDs | `state.whitelist_ids` (RAM) | Never — restart only | Correct for mostly-static data |
| Pyrogram session | `ai_dating_user.session` (disk) | Manual only | MTProto encryption keys |
| Compiled regex `ANKET_PATTERN` | Module-level constant | Never (module scope) | Compiled at import, reused forever ✓ |
| Gemini `GenerativeModel` instance | `state.model` | Never — restart only | Correct |

### What is NOT cached (but could be)

| Data | Current behavior | Potential caching |
|------|-----------------|------------------|
| Gemini system prompt tokens | Re-sent with every API call | Gemini API supports prompt caching — would reduce per-call token cost by ~44% |
| Profile card text → opener | Generated fresh per match; previous openers not remembered | Could cache openers per profile text hash to avoid duplicate AI calls for the same profile |
| Session classification result | Recomputed every task from history timestamps | Trivially cacheable per conversation — but computation is <1ms, not worth it |

**The biggest caching opportunity:** Gemini's API supports explicit prompt caching via the `CachedContent` API. The `CONVERSATION_SYSTEM_PROMPT` (~800 tokens) is identical in every API call. Caching it server-side at Google would:
- Reduce input tokens per call from ~1,820 to ~1,020 (44% reduction)
- Reduce API cost proportionally
- Potentially reduce latency (cached tokens process faster)

This requires using `google.generativeai`'s `caching` module and passing `cached_content=` to `start_chat()`. Not implemented in the current codebase.

---

## 7. Real-Time vs Batch Processing

### All processing is real-time (event-driven)

The system has no batch processing of any kind. Every operation is triggered by an incoming event and processed immediately (after intentional delays):

| Process | Type | Trigger |
|---------|------|---------|
| Profile like/dislike | Real-time | Profile card arrives |
| Opener generation | Real-time | "Write message" arrives |
| Conversation reply | Real-time (delayed) | User message arrives |
| History save | Real-time | AI response generated |
| Log write | Real-time | Any event |

### Implications of pure real-time processing

**Positive:** No batch job scheduling, no cron failures, no delayed processing queues. The system is simple and reactive.

**Negative:**
- Peak load (many users sending messages simultaneously after a long silence) cannot be smoothed by batching
- Save operations cannot be coalesced — if 10 conversations complete their delays within the same second, 10 full JSON rewrites occur in rapid succession
- No opportunity for write batching (e.g., save once per 30 seconds instead of per response)

### Natural load smoothing from intentional delays

The reply delay system accidentally provides load leveling: conversations that start at the same time will reply at different times because each gets an independent random delay. This spreads the peak Gemini API load across time, preventing a thundering-herd problem where hundreds of calls are made simultaneously.

For long-mode delays (1–3h), conversations are distributed across a ~7,200-second window. Even with 100 simultaneous active conversations, the expected Gemini API call rate is ~0.014 calls/second — essentially negligible.

---

## 8. Behavior Under Scale

### Scale dimension 1 — More simultaneous active conversations

| Conversations | Gemini calls/min | save_histories() writes/min | RAM for histories | Event loop blocking/save |
|--------------|-----------------|---------------------------|-------------------|--------------------------|
| 10 (current) | ~0.5 | ~0.5 | ~150 KB | ~1ms |
| 100 | ~5 | ~5 | ~1.5 MB | ~5ms |
| 1,000 | ~50 | ~50 | ~15 MB | ~50ms ← noticeable |
| 10,000 | ~500 | ~500 | ~150 MB | ~500ms ← degraded |

At 1,000 simultaneous conversations: each `save_histories()` call blocks the event loop for ~50ms. With 50 saves per minute, the event loop is blocked for ~2.5 seconds per minute — a 4% overhead. Other conversations experience ~50ms delays in event processing during each save. Manageable but noticeable.

At 10,000 conversations: `save_histories()` blocks the event loop for ~500ms per call, ~500 times per minute — the event loop is effectively blocked half the time. This is a hard scalability ceiling for the current architecture.

### Scale dimension 2 — More messages per conversation

Each conversation is bounded to 20 turns in the history. More messages per conversation doesn't increase memory or save cost beyond the 20-turn cap. **This dimension is effectively capped by design.** ✓

### Scale dimension 3 — More profiles processed per hour (Scout)

The Scout pipeline is throttled by the 70-second cooldown. Maximum Scout throughput: ~51 profiles/hour. This is a fixed ceiling regardless of how fast @leomatchbot sends profiles. The bottleneck is the intentional cooldown, not any system resource.

### Scale dimension 4 — More API calls hitting Gemini rate limits

Gemini Flash rate limits (free tier, as of 2024):
- 15 requests per minute (RPM)
- 1,000,000 tokens per minute (TPM)
- 1,500 requests per day (RPD)

At 10 simultaneous conversations with an average reply cycle, 15 RPM is reached at ~7 replies per minute across all conversations. With the delay system distributing replies, this is unlikely to be hit in normal operation. If many conversations are in "active session" mode (15–60s delays), 10+ concurrent active sessions could generate bursts that approach the free tier limit.

**The Gemini rate limit is the production ceiling for the current architecture.** Paid tier removes the RPM limit but keeps token limits. The 1,500 RPD limit is hit at ~1.04 calls/minute average — well within scope for a single operator.

### Scale dimension 5 — More users in conversation history

Users accumulate in `conversation_histories.json` indefinitely. Each user adds one dict entry that grows to at most ~3 KB (20 turns × 150 bytes). There is no eviction.

At 10,000 unique users (over the lifetime of the bot): `conversation_histories.json` = ~30 MB. Startup parse time: ~300ms. In-memory dict: ~100 MB.

This is manageable for personal server use. The file-based approach hits a practical wall at ~100,000 users (3 GB JSON file) — but this is far beyond any realistic single-operator scenario.

---

## 9. What Breaks First Under Load

In order of which limit is hit first as load increases:

### 1. Gemini API rate limit (free tier: 15 RPM) — First to break

**Trigger:** ~7–8 active conversations simultaneously completing their delays within the same minute.

**Symptom:** `ResourceExhausted` errors. `with_rate_limit_handling` adds 60-second retries. Reply latency increases by 60–180 seconds. Conversations experience cascading delays.

**Current mitigation:** 3-retry with backoff. Fallback string if all retries fail.
**Fix:** Upgrade to paid Gemini tier or implement exponential backoff with jitter.

---

### 2. Event loop starvation from synchronous save_histories() — Second to break

**Trigger:** ~200+ active conversations (extremely unlikely for single-operator use).

**Symptom:** Timing jitter in all operations. Read receipts delayed. Typing indicator timing off. Message sends delayed.

**Fix:** Move `save_histories()` to `asyncio.to_thread()`.

---

### 3. Telegram FloodWait — Third to break

**Trigger:** Rapid Scout actions (like/dislike) within a short period, or many simultaneous ladder-send messages.

**Symptom:** `FloodWait` exception, task abandoned, message lost.

**Fix:** Catch `FloodWait`, sleep for the required period, retry.

---

### 4. Thread pool exhaustion — Fourth to break

**Trigger:** Many simultaneous Gemini API calls, each spawning an OS thread via `asyncio.to_thread`.

Python's default thread pool for `asyncio.to_thread` uses `ThreadPoolExecutor(max_workers=min(32, os.cpu_count() + 4))`. On a single-core VPS: max_workers = 5. Five simultaneous Gemini calls would exhaust the thread pool; the sixth would queue.

**Symptom:** Sixth simultaneous API call is delayed until one of the five completes.

**Fix:** This is self-limiting — 5 simultaneous calls is already far beyond realistic single-operator scale.

---

### 5. Memory exhaustion — Distant ceiling

**Trigger:** Tens of thousands of unique users in conversation history + hundreds of active conversation tasks.

At realistic scale (< 1,000 users): ~50–100 MB total. Well within typical server limits.

---

## 10. Performance Risk Register

| Risk | Trigger point | Severity | Probability (at current scale) | Probability (at 10× scale) |
|------|--------------|---------|-------------------------------|---------------------------|
| Gemini free-tier RPM limit | ~7 simultaneous replies | High | Low | High |
| Event loop blocking from synchronous saves | ~200 conversations | Medium | Very Low | Low |
| FloodWait from rapid messages | Unusual use pattern | Medium | Low | Medium |
| Thread pool exhaustion | 5+ simultaneous AI calls | Low | Very Low | Low |
| Memory exhaustion | ~10,000 users | Low | Very Low | Very Low |
| Disk full stops saves | Disk management failure | High | Very Low | Low |
| JSON file grows large (slow startup) | 10,000+ users | Low | Very Low | Very Low |
| Token cost increase from system prompt re-send | Every API call | Low (financial) | Always | Always |

---

## 11. Optimization Roadmap

Ranked by impact-to-effort ratio:

### Priority 1 — Move `save_histories()` off the event loop thread

**Effort:** 2 lines
**Impact:** Eliminates event loop blocking from disk I/O; unlocks scalability to thousands of concurrent conversations

```python
# In generate_conversation_response(), replace:
save_histories(state)

# With:
asyncio.create_task(_save_async(state))

async def _save_async(state):
    await asyncio.to_thread(save_histories, state)
```

Or more correctly, wrap the entire `save_json_data` call:
```python
await asyncio.to_thread(save_json_data, HISTORY_PATH, state.conversation_histories)
```

---

### Priority 2 — Cache Gemini system prompt (reduce token cost 44%)

**Effort:** 10–20 lines
**Impact:** Reduces API cost and latency on every conversation reply

```python
# In initialize_ai():
from google.generativeai import caching
import datetime

cached = caching.CachedContent.create(
    model="gemini-1.5-flash-latest",
    contents=[
        {"role": "user",  "parts": [CONVERSATION_SYSTEM_PROMPT]},
        {"role": "model", "parts": ["understood, I'm ready. no periods and no extra stuff"]},
    ],
    ttl=datetime.timedelta(hours=1),
)
state.model = genai.GenerativeModel.from_cached_content(cached)
```

Or use `system_instruction=` (already identified as the correct fix in engineering decisions), which achieves the same token reduction:
```python
state.model = genai.GenerativeModel(
    "gemini-1.5-flash-latest",
    system_instruction=CONVERSATION_SYSTEM_PROMPT
)
```

---

### Priority 3 — Implement write coalescing for histories

**Effort:** ~20 lines
**Impact:** Reduces disk write frequency under high concurrent load; reduces risk of partial write on busy I/O

```python
# In BotState, add:
_pending_save: bool = False

# Replace direct save_histories() calls with:
async def schedule_save(state):
    if state._pending_save:
        return  # already scheduled
    state._pending_save = True
    await asyncio.sleep(5)  # coalesce writes over 5-second window
    state._pending_save = False
    await asyncio.to_thread(save_histories, state)
```

One write per 5 seconds regardless of how many conversations completed during that window.

---

### Priority 4 — Atomic JSON write

**Effort:** 3 lines
**Impact:** Eliminates data loss on crash during save (already identified as Critical in failure analysis)

```python
# In save_json_data():
tmp_path = path.with_suffix(".tmp")
with tmp_path.open("w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
tmp_path.replace(path)  # atomic on POSIX
```

This is both a correctness fix and a performance improvement: a failed write no longer destroys data, allowing retries without data loss.

---

### Priority 5 — Add FloodWait handling with retry

**Effort:** ~10 lines
**Impact:** Prevents message loss under Telegram rate limiting

```python
from pyrogram.errors import FloodWait

async def safe_send_message(client, chat_id, text):
    for attempt in range(3):
        try:
            return await client.send_message(chat_id, text)
        except FloodWait as e:
            logging.warning(f"FloodWait: sleeping {e.x}s")
            await asyncio.sleep(e.x)
    logging.error(f"send_message failed after 3 FloodWait retries for chat {chat_id}")
```

---

### Priority 6 — Per-user reply rate limiting

**Effort:** ~15 lines
**Impact:** Prevents Gemini quota exhaustion by adversarial users; prevents FloodWait from high-volume users

```python
# In BotState, add:
user_last_reply: Dict[int, datetime] = field(default_factory=dict)

# In process_dialogue_task(), before AI call:
MIN_REPLY_INTERVAL = 30  # seconds
last_reply = state.user_last_reply.get(chat_id)
if last_reply and (datetime.now(UTC) - last_reply).total_seconds() < MIN_REPLY_INTERVAL:
    logging.info(f"[DIALOG] Rate limiting reply to {user_name}")
    return
state.user_last_reply[chat_id] = datetime.now(UTC)
```

---

### Priority 7 — SQLite for conversation histories (long-term)

**Effort:** ~2 hours refactoring
**Impact:** Eliminates full-rewrite bottleneck; enables lazy loading; enables per-user eviction; enables atomic writes natively; unlocks 100,000+ user scale

```
Current: one JSON dict, full rewrite on every save
SQLite:  one row per conversation turn, append-only writes, indexed by user_id + timestamp
```

At current scale (< 1,000 users): SQLite provides no meaningful benefit over JSON and adds setup complexity. At 10,000+ users: SQLite becomes necessary.

---

### Summary Table

| Optimization | Effort | Impact | Fixes |
|-------------|--------|--------|-------|
| Move save to asyncio.to_thread | 2 lines | High | Event loop blocking |
| Use system_instruction= | 1 line | Medium | 44% token reduction |
| Atomic JSON write | 3 lines | Critical | Data loss on crash |
| Write coalescing | 20 lines | Medium | I/O frequency under load |
| FloodWait handler | 10 lines | High | Message loss |
| Per-user rate limit | 15 lines | High | Quota exhaustion |
| SQLite (long-term) | 2h | Very High | Scalability ceiling |
