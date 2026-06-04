# Engineering Decisions Review — AI Dating Assistant

_Last updated: 2026-06-04_

> Perspective: senior software architect reviewing a working single-operator automation tool.
> The goal is not to judge it against an enterprise standard, but to evaluate whether its
> decisions are internally consistent, appropriate for its scale, and aware of their own risks.

---

## Table of Contents

1. [Decision 1 — Single-process asyncio over multi-process or threaded design](#1-single-process-asyncio)
2. [Decision 2 — MTProto (user account) over Bot API](#2-mtproto-user-account-over-bot-api)
3. [Decision 3 — Single shared mutable BotState](#3-single-shared-mutable-botstate)
4. [Decision 4 — JSON flat-file persistence](#4-json-flat-file-persistence)
5. [Decision 5 — AI prompt embedded in config, not external files](#5-ai-prompt-embedded-in-config)
6. [Decision 6 — System prompt injected as fake chat turn](#6-system-prompt-as-fake-chat-turn)
7. [Decision 7 — Debounce via cancel-and-replace asyncio tasks](#7-debounce-via-cancel-and-replace)
8. [Decision 8 — Probabilistic reply delay tiers](#8-probabilistic-reply-delay-tiers)
9. [Decision 9 — Binary profile quality filter (10-char threshold)](#9-binary-profile-quality-filter)
10. [Decision 10 — Ladder send controlled by AI output (|||)](#10-ladder-send-controlled-by-ai-output)
11. [Decision 11 — History trimming by count, not tokens or time](#11-history-trimming-by-count)
12. [Decision 12 — Full JSON rewrite on every save](#12-full-json-rewrite-on-every-save)
13. [Decision 13 — No graceful shutdown or SIGTERM handling](#13-no-graceful-shutdown)
14. [Decision 14 — Startup replay on restart](#14-startup-replay-on-restart)
15. [Decision 15 — Whitelist as a set in memory, JSON on disk](#15-whitelist-as-set-in-memory)
16. [Summary: Architectural Quality Assessment](#summary-architectural-quality-assessment)

---

## 1. Single-process asyncio

### The decision
The entire system — two event pipelines, multiple concurrent conversations, AI API calls — runs inside a single Python process with a single `asyncio` event loop.

### Why it makes sense here
The workload is almost entirely I/O-bound. The process spends its time waiting on:
- Telegram network events (incoming messages)
- Gemini API calls (AI responses)
- Deliberate sleep delays (human simulation)

None of these need CPU parallelism. A single `asyncio` event loop handles all of them efficiently through cooperative multitasking. Adding processes or threads would introduce synchronization complexity with zero throughput benefit.

### What it costs
- The Gemini SDK is synchronous. Without `asyncio.to_thread`, a single AI call would freeze the entire event loop — blocking all incoming messages and all other conversations. The current code wraps every Gemini call in `asyncio.to_thread`, which is correct but easy to forget when adding new AI calls in the future.
- There is no parallelism within a single conversation's reply cycle. While one conversation is sleeping its 3-hour "long mode" delay, that's an asyncio task — all other conversations run normally. This is correct and is a strength of the design, not a weakness.

### Risk
**Low.** The design is appropriate for the scale. The only real risk is a future developer adding a synchronous blocking call (database query, file read, HTTP call) outside of `asyncio.to_thread` and unknowingly freezing the event loop. There are no guards against this.

---

## 2. MTProto (user account) over Bot API

### The decision
The system uses Pyrogram to operate a real Telegram **user account** via the MTProto protocol, rather than registering a Telegram Bot and using the Bot API.

### Why it was necessary
`@leomatchbot` is a dating bot that only interacts with real user accounts. Bot accounts cannot follow other bots (Telegram prevents bot-to-bot messaging in most contexts). Read receipts, the "typing..." indicator visible in private chats, and the appearance of a real person's profile — none of these would be possible with a Bot API token. The entire premise of the system (impersonating a real person) requires this choice.

### What it costs
- **Legal and ToS exposure.** Pyrogram operating a user account for automation violates Telegram's Terms of Service. The account can be banned without notice. This is an accepted risk for the operator, not an oversight — but it deserves explicit acknowledgment as a single point of failure.
- **Session file is a critical secret.** The `.session` file, combined with the API credentials, is equivalent to full account access. If it leaks, the operator's Telegram account is compromised. The `.gitignore` presumably excludes it, but there's no documented secret rotation procedure.
- **API_ID + API_HASH are personal credentials.** Unlike a bot token (which is account-independent), Telegram API credentials are tied to the developer's Telegram account. Misuse or automation detection can lead to API key revocation, not just session banning.

### Risk
**High — externally.** The technical implementation is sound. The risk is entirely in Telegram's enforcement policy, which is unpredictable. The system has no mitigation strategy for account banning (no backup account, no detection of ban state, no alerting).

---

## 3. Single shared mutable BotState

### The decision
All runtime state is stored in a single `BotState` dataclass instance, created once in `app.py` and passed by reference to every component.

### Why it makes sense
The application has one operator, one Telegram session, one AI model. There's no multi-tenancy and no need for state isolation between components. A single shared state object is the simplest architecture that satisfies these requirements. It avoids:
- Global variables scattered across modules (hard to test)
- A dependency injection framework (overkill for this scale)
- Message-passing between components (unnecessary complexity for what is essentially a sequential pipeline)

### What it costs
- **No encapsulation.** Any module can write any field on `BotState`. There are no access controls, no validation hooks, no change notifications. `leomatch.py` directly writes `state.last_action_time`; `ai_client.py` directly mutates `state.conversation_histories`. This works today because the codebase is small and the team is (presumably) one person. It becomes a maintenance risk as the codebase grows.
- **`model: Optional[Any]` and `app: Optional[Any]`** use `Any` typing, sacrificing type safety to avoid circular import issues. The downstream effect is that any IDE autocomplete for `state.model.generate_content()` or `state.app.send_message()` is blind — no type checking, no documentation hints.

### Risk
**Low now, medium if the codebase grows.** The pattern is internally consistent for the current scope. The `Any` typing is the most concrete thing to address — replacing with `Optional["genai.GenerativeModel"]` and `Optional["pyrogram.Client"]` with string-quoted forward references would improve IDE support without changing runtime behavior.

---

## 4. JSON flat-file persistence

### The decision
All persistent data (conversation histories, whitelist) is stored as JSON files on the local filesystem. No database engine is used.

### Why it makes sense
The dataset is tiny. Even with 100 active conversations of 20 messages each, the JSON file is under 1 MB. JSON is human-readable, easily backed up with `cp`, and requires no infrastructure. For a single-operator bot running on a personal server, SQLite would be the next logical step but is genuinely unnecessary right now.

### What it costs

**No atomic writes.** This is the most concrete technical risk in the entire codebase. The save path is:
```python
with path.open("w", encoding="utf-8") as f:   # truncates file immediately
    json.dump(data, f, ...)                     # writes new content
```
Between the file being truncated and the write completing, the file contains nothing (or partial JSON). A kill signal, power loss, or OOM at this moment produces a zero-byte or invalid JSON file. The recovery in `load_json_data` is to overwrite it with `{}` — silently destroying all conversation history. The correct pattern is:
```python
tmp_path = path.with_suffix(".tmp")
with tmp_path.open("w") as f:
    json.dump(data, f, ...)
tmp_path.replace(path)   # atomic on POSIX (rename syscall)
```

**Full rewrite on every AI response.** Every conversation reply triggers a complete rewrite of all conversations. This is O(total history size), not O(new message size). Currently negligible; would become noticeable at hundreds of active conversations.

**No concurrent access protection.** If two coroutines called `save_histories` simultaneously (which the current code prevents through asyncio's single-threaded nature), file corruption would result. This is safe today but fragile — `asyncio.to_thread` for Gemini calls means real threads exist, and if `save_histories` were ever accidentally called from within a thread, there'd be no protection.

### Risk
**Medium.** The atomic write omission is a real data loss risk on crash. For a 24/7 deployment on a server, crashes do happen (OOM killer, hardware issues, power). The fix is a three-line change.

---

## 5. AI prompt embedded in config

### The decision
Both AI prompts (`FIRST_MESSAGE_PROMPT` and `CONVERSATION_SYSTEM_PROMPT`) are stored as Python string constants in `config.py`, not in external files (`.txt`, `.yaml`, `.json`).

### Why it makes sense
For a single operator maintaining their own persona, having the prompt in the same repository as the code means version control tracks prompt changes alongside code changes. There's no out-of-sync problem between "what the code expects" and "what the prompt says." The `{profile_text}` placeholder is validated at format time.

### What it costs
- **Prompt changes require a code change.** To update the persona, the operator must edit a Python file, not a text file. For a technical operator, this is no burden. For a non-technical user wanting to adapt the tool, it's a significant barrier.
- **No prompt versioning beyond git history.** There's no `CONVERSATION_SYSTEM_PROMPT_V2` in staging; experiments require overwriting the production prompt.
- **`config.py` becomes long and mixed-concern.** The file mixes authentication secrets (`API_ID`, `API_HASH`), timing tuning (`GRACE_PERIOD_SECONDS`), regex patterns (`ANKET_PATTERN`), and multi-paragraph natural language text (prompts). Reading the file requires mentally context-switching between very different types of content.

### Risk
**Low for current use. Medium if the system is shared.** The decision is appropriate for a solo operator. A separate `prompts/` directory with plain text files would be a clean improvement without architectural cost.

---

## 6. System prompt as fake chat turn

### The decision
Because Gemini's chat API has no system-role field, the conversation system prompt is injected as a synthetic first exchange: a fake user message containing the full prompt, followed by a fake model acknowledgment.

### Why it was necessary
This is a workaround for a real API limitation. The `start_chat(history=...)` parameter expects alternating `user`/`model` turns. The `GenerativeModel` class does have a `system_instruction` parameter, but at the time this code was written (or the version of the SDK used), the developers either weren't aware of it or it wasn't yet available. The fake-exchange approach works reliably.

### What it costs
- **Silent breakage risk.** If Gemini's handling of the first message in history changes (e.g., the model starts treating the first user message as a regular user query rather than system context), the persona would break silently. There'd be no error — just a bot that ignores its personality rules.
- **Token waste.** Every API call includes the full system prompt as part of the history payload. At ~800 tokens for `CONVERSATION_SYSTEM_PROMPT`, this is 800 tokens per request that the model re-processes on every single turn. Caching or a proper system instruction field would eliminate this cost.
- **The model's fake acknowledgment is fragile:** `"understood, I'm ready. no periods and no extra stuff"`. If the model ever surfaces this string in a reply (theoretically possible if it confuses history and generation), it would be sent to the user verbatim.

### The correct approach
`genai.GenerativeModel` accepts a `system_instruction` parameter:
```python
state.model = genai.GenerativeModel(
    "gemini-1.5-flash-latest",
    system_instruction=CONVERSATION_SYSTEM_PROMPT
)
```
This would remove the need for the fake exchange entirely, reduce token usage, and be semantically correct. This is the most impactful single-line improvement available in the codebase.

### Risk
**Medium.** The workaround functions correctly today. The token waste is real but not budget-critical at current usage. The silent-breakage risk is the real concern — it would manifest as the bot ignoring persona rules rather than throwing an error.

---

## 7. Debounce via cancel-and-replace asyncio tasks

### The decision
Both the Scout pipeline (profile processing) and the Interlocutor pipeline (private replies) implement debounce by cancelling the existing task for a given slot and creating a new one on each new event.

### Why it's the right approach for asyncio
The `asyncio.CancelledError` mechanism is designed exactly for this use case. Cancelling a coroutine that's sleeping (the most common state for both tasks) is instantaneous and clean. The tasks handle `CancelledError` with a log line and silent exit. There's no polling, no flag-checking, and no shared-memory signaling.

### What it costs
- **The grace period message text issue.** In `dialog.py`, the message object is captured at task creation. When a task is cancelled and replaced, the replacement captures the *new* message. But the new message may be the second part of a thought the user split across two messages — e.g., "I was thinking" (cancel) → "about going out tonight" (replacement). The AI only sees the second message, losing the first. The 7-second grace period mitigates this in most cases, but doesn't eliminate it. A proper solution would accumulate messages and concatenate them before sending to the AI.
- **Task reference management.** `active_dialogue_tasks` is keyed by `chat_id` and cleaned up in a `finally` block. If the `finally` block somehow fails (it can't in practice, but in principle), dead task references accumulate indefinitely. The single `leomatch_task` slot is even simpler — replace-on-new, no cleanup needed.

### Risk
**Low.** The pattern is idiomatic asyncio and correct. The message-accumulation gap is a behavioral limitation, not a technical bug.

---

## 8. Probabilistic reply delay tiers

### The decision
New-session reply delays are chosen probabilistically: 60% fast (15–60s), 35% medium (5–15m), 5% long (1–3h). Active-session replies are always fast (15–60s).

### Why it's effective
Uniform random delays within a single range (e.g., always 15–60 seconds) would be detectable as non-human — real people have contextual patterns. The three-tier system creates a realistic distribution: usually responsive, occasionally slow, rarely very late. The 5% long-mode tier is especially important — it simulates the "I was genuinely busy" scenario that a uniform distribution can't produce.

### What it costs
- **No contextual awareness.** The delay is selected before the message is read. A short "hey" might trigger a 2-hour delay; a "my mom just died" might get a 15-second response. The delay is decorative (signals human-ness) but not intelligent (doesn't respond to message urgency or content).
- **Long-mode creates a UX cliff.** In 5% of new-session openings, the reply comes 1–3 hours later. If the match sends a follow-up during this window, the follow-up triggers a new task (cancelling the delayed one) and a fresh delay calculation. Net effect: a series of unanswered messages could each independently trigger a new delay, extending silence further. There's no cap on total silence duration.
- **Session timeout is fixed at 15 minutes.** A conversation paused for 16 minutes is classified as "new session" and gets a probabilistic delay. A conversation paused for 14 minutes is "active session" and gets an instant reply. This binary threshold creates a sharp behavioral discontinuity around the 15-minute mark.

### Risk
**Low for the current use case.** The probabilistic model is good enough for one-operator use. The long-mode UX cliff is a real issue but occurs infrequently (5% of new sessions).

---

## 9. Binary profile quality filter

### The decision
Profiles are liked if their description is longer than 10 characters; disliked otherwise. No other signal is used.

### Why it was simplified
AI-based profile evaluation (using Gemini to assess quality) would add 1–2 seconds of latency and API cost to every profile processed. Given the volume of profiles on a dating bot, this adds up. The 10-character threshold is a reasonable heuristic: a profile with less than 10 characters of description is almost always a blank or trivially empty ("...", "idk", "hi").

### What it costs
- **False negatives:** Profiles with meaningful short descriptions ("artist", "curious") get disliked.
- **False positives:** Profiles with long but meaningless descriptions ("I don't know what to write here, just trying this app I guess") get liked.
- **No variety in behavior.** The bot likes 100% of profiles that pass the threshold. A real person would have preferences, moods, and aesthetic criteria. This is perhaps the most obvious tell that something automated is happening, at the dating bot operator level (not visible to individual users).

### Risk
**Low.** The filter's purpose is to avoid messaging people who clearly haven't invested in their profile. That goal is achieved. The heuristic is good enough.

---

## 10. Ladder send controlled by AI output (|||)

### The decision
The AI model is instructed to insert `|||` separators in ~30% of responses. The application splits on this delimiter and sends each part as a separate message with typing simulation between them.

### Why it's clever
It offloads the structural decision ("should this be one message or three?") to the AI, which has full context of the conversation. The AI can decide that "hm, wait" + "|||" + "actually let me think about this differently" reads more naturally as two messages than one. The delimiter is arbitrary enough that it won't appear organically in conversational Russian/English text.

### What it costs
- **No output validation.** If the AI produces `part1 ||| part2 |||` (trailing separator), the split produces an empty third part. The current code guards against this with `if p.strip()` in the list comprehension — this is handled correctly.
- **The AI doesn't always follow the 30% instruction.** Prompt instructions about frequency are treated as suggestions, not constraints. The actual ladder frequency depends on model behavior, which can change between model versions.
- **`|||` could appear in quoted text.** If the AI quotes something from the conversation that happens to contain `|||` (extremely unlikely but theoretically possible), it would be split erroneously.
- **Semantic coherence is not guaranteed.** The AI might split mid-sentence if it misunderstands the delimiter's role.

### Risk
**Low.** The delimiter is well-chosen and the code handles edge cases. The behavioral unpredictability of the AI following the frequency instruction is a minor concern.

---

## 11. History trimming by count

### The decision
Conversation history is trimmed to the last 20 messages using a sliding window (`history[-MAX_HISTORY_LENGTH:]`).

### Why it's simple and usually correct
Twenty conversational turns is more context than most dating app conversations carry. The sliding window is O(1) to implement and reason about. For the target use case, this is sufficient.

### What it costs
- **Count ≠ tokens.** Gemini's context window is measured in tokens. A history of 20 very long messages could exceed the context window; a history of 20 short messages uses a fraction of it. The current code doesn't count tokens at all — it relies on messages staying short, which is true given the prompt's instruction for "1–3 sentence" replies.
- **Context loss on long conversations.** After 20 turns, early context (how the person introduced themselves, things they mentioned in the first few messages) is gone. The AI may contradict earlier statements or ask questions it already answered. This is a real behavioral degradation in long conversations.
- **Count includes both user and model turns.** At `MAX_HISTORY_LENGTH=20`, the window holds 10 user messages and 10 model responses. This is actually only ~10 conversation rounds — less than it appears.

### Risk
**Low-medium.** The truncation behavior is correct at current scale. Token count awareness would be a meaningful improvement for longer conversations.

---

## 12. Full JSON rewrite on every save

### The decision
`save_json_data` opens the target file in write mode (`"w"`) and serializes the entire histories dict on every call. It is called after every AI-generated response.

### Why it exists in this form
It's the simplest possible implementation. `json.dump(data, f)` writes everything; there's no concept of "append the delta." For a small file this is functionally equivalent to a more sophisticated approach.

### What it costs
- **Non-atomic write = data loss risk on crash.** Covered in detail in Decision 4. This is the most serious unaddressed risk in the codebase.
- **O(total data) per response.** Write time grows linearly with the total history file size, not with the size of the new message. Currently sub-millisecond; would become noticeable at large scale.
- **File lock contention is theoretically possible.** If two conversations complete their AI calls simultaneously (possible — `asyncio.to_thread` creates real threads), two `save_json_data` calls could interleave their file writes. In practice, asyncio's cooperative scheduling makes this extremely unlikely, but it's not impossible.

### Risk
**Medium.** The atomic-write fix is a 3-line change and should be treated as a high-priority reliability improvement.

---

## 13. No graceful shutdown or SIGTERM handling

### The decision
The application has no `signal.signal(SIGTERM, handler)` registration. When a process manager (systemd, supervisor, tmux kill) sends `SIGTERM`, the process is killed immediately. `SIGINT` (`Ctrl+C`) raises `KeyboardInterrupt`, which is caught and triggers a history save.

### Why it wasn't addressed
For a tmux-based deployment, the operator always uses `Ctrl+C` to stop the bot. `SIGTERM` is irrelevant in that workflow. The choice is implicit rather than deliberate.

### What it costs
- **Deployment on systemd/supervisor loses the last conversation turns.** If the bot is managed by a proper process supervisor that sends `SIGTERM` before `SIGKILL`, the histories are not saved. The bot restarts with stale history.
- **In-flight AI calls are abandoned without cleanup.** A running `asyncio.to_thread` call to Gemini doesn't get a chance to complete or cancel cleanly.
- **Active dialogue tasks are not awaited.** If 10 conversations have tasks sleeping their delay period, they all die instantly on `SIGTERM` with no cleanup.

### The fix
```python
import signal

def handle_sigterm(signum, frame):
    raise KeyboardInterrupt  # piggyback on existing handler

signal.signal(signal.SIGTERM, handle_sigterm)
```
This routes `SIGTERM` through the existing `KeyboardInterrupt` handler in `main.py`, enabling clean shutdown on process manager termination.

### Risk
**Low-medium.** For tmux-based operation, this is a non-issue. For any production deployment (systemd, Docker), it becomes a reliability problem.

---

## 14. Startup replay on restart

### The decision
On every startup, `app.py` fetches the last message from `@leomatchbot` and re-processes it with `is_startup=True`. If the chat is empty, it sends `"1"` to initialize the dating bot.

### Why it's important
Without replay, a restart in the middle of a dating bot interaction would leave the bot in an unknown state — waiting for the next event to arrive organically. If the last event was "Write a message for this user" and the bot crashed before responding, it would never respond (the dating bot doesn't re-send prompts). The replay ensures continuity across restarts.

### What it costs
- **Re-processing an already-handled message.** If the last bot message was a profile card that was already liked before the crash, the replay will like it again. The `is_startup=True` flag suppresses the "unrecognized text" warning but does not prevent duplicate action. The cooldown mechanism mitigates this (if the crash was recent, the cooldown will be active), but a crash immediately after the cooldown expired would result in a double-like.
- **Limited to 1 message.** The replay only looks at the most recent message. If multiple messages arrived between the last successful processing and the restart, only the last one is replayed. This is usually correct (the last state is the relevant one) but could miss a "mutual match" notification that was followed by another message.

### Risk
**Low.** The double-action edge case is benign (liking a profile twice is not a meaningful failure). The replay is a net reliability improvement.

---

## 15. Whitelist as set in memory, JSON on disk

### The decision
The whitelist is loaded once at startup from `whitelist.json` into `state.whitelist_ids` (a Python `set`). It is never written back to disk by the application. Changes require manual JSON editing and a restart.

### Why it's appropriate
The whitelist is an operator control mechanism, not a user-facing feature. It changes rarely (when the operator decides to take over a conversation manually). Requiring a restart to apply whitelist changes is acceptable given that the operator is presumably monitoring the bot.

The `set` data structure gives O(1) membership lookup — the whitelist check fires on every incoming private message, so lookup performance matters at volume.

### What it costs
- **No runtime modification.** Adding someone to the whitelist requires stopping the bot, editing JSON, and restarting. An in-bot command (e.g., forwarding a message to trigger whitelist add) would be more ergonomic but would require a command parser.
- **No `save_whitelist` function.** The asymmetry (whitelist is loaded but never saved programmatically) is a design smell. Future features that add users to the whitelist automatically (e.g., after a certain conversation milestone) would need to add this capability.

### Risk
**Low.** The design matches the use case. The lack of runtime modification is a UX limitation, not a technical risk.

---

## Summary: Architectural Quality Assessment

### Strengths

| Strength | Evidence |
|----------|---------|
| **Appropriate complexity for scale** | Single process, flat files, no frameworks. Matches the problem size exactly. |
| **Clean separation of the two pipelines** | `leomatch.py` and `dialog.py` are entirely independent. Changes to one don't risk breaking the other. |
| **Idiomatic asyncio** | Debounce, background tasks, `to_thread` for blocking calls — all done correctly. |
| **Centralized configuration** | No magic numbers scattered in business logic. All tuning in one place. |
| **Resilient startup** | Replay mechanism handles restarts without operator intervention. |
| **Good logging** | Every significant state transition is logged with enough context to diagnose issues. |
| **Crash-safe history save** | `KeyboardInterrupt` and general `Exception` both trigger save before exit. |

### Weaknesses by Severity

| Severity | Issue | Module | Fix complexity |
|----------|-------|--------|----------------|
| **High** | Non-atomic JSON write (data loss on crash) | `storage.py` | Low — 3-line change |
| **High** | System prompt via fake chat turn (should use `system_instruction=`) | `ai_client.py` | Low — 1-line change |
| **Medium** | No SIGTERM handling | `main.py` | Low — 3-line change |
| **Medium** | `Optional[Any]` types on `state.model` and `state.app` | `state.py` | Low — type hints only |
| **Medium** | Long-mode silence cliff (debounce resets delay on each new message) | `dialog.py` | Medium |
| **Medium** | Burst message accumulation not implemented (only last message sent to AI) | `dialog.py` | Medium |
| **Low** | History trimmed by count, not tokens | `ai_client.py` | Medium |
| **Low** | Prompts mixed into config alongside secrets and constants | `config.py` | Low — move to `prompts/` |
| **Low** | No structured logging | `logging_setup.py` | Medium |
| **Low** | No health check / watchdog | — | Medium |

### Consistency Assessment

The codebase is **highly consistent** in its patterns:
- Every module uses `logging.info/warning/error` with `[MODULE-NAME]` prefixes.
- Every handler uses the same `functools.partial(handler, state=state)` injection pattern.
- Every background task uses the same cancel-on-new debounce pattern.
- Every external call uses the same `await with_rate_limit_handling(lambda: ...)` wrapper.

There are two minor inconsistencies:
1. `ai_client.py` calls `save_histories()` internally (a side effect of generation), while all other writes go through explicit caller-initiated saves. This is a hidden side effect that violates the principle of least surprise.
2. `leomatch.py` calls `client.send_message` directly, while `dialog.py` uses `client.send_chat_action` + `client.send_message`. The Scout sends messages without typing simulation; the Interlocutor does. This asymmetry is intentional (the Scout doesn't need to appear human to the dating bot) but undocumented.

### Verdict

This is **well-engineered for its stated purpose and scale**. The decisions are coherent, the architecture is clean, and the code is readable. The three changes that would meaningfully improve reliability — atomic JSON writes, `system_instruction` usage, and SIGTERM handling — are each under 5 lines of code. The system as built reflects a developer who understood the problem deeply, chose the right level of complexity, and executed consistently.
