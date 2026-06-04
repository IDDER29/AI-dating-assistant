# Dependencies & System Boundaries — AI Dating Assistant

_Last updated: 2026-06-04_

---

## Table of Contents

1. [System Boundary Map](#1-system-boundary-map)
2. [External Services](#2-external-services)
   - 2.1 [Telegram Platform (MTProto)](#21-telegram-platform-mtproto)
   - 2.2 [Google Gemini API](#22-google-gemini-api)
   - 2.3 [@leomatchbot (Third-Party Bot)](#23-leomatchbot-third-party-bot)
3. [Direct Python Dependencies](#3-direct-python-dependencies)
   - 3.1 [pyrogram 2.0.106](#31-pyrogram-20106)
   - 3.2 [tgcrypto 1.2.5](#32-tgcrypto-125)
   - 3.3 [google-generativeai 0.8.6](#33-google-generativeai-086)
   - 3.4 [python-dotenv 1.2.2](#34-python-dotenv-122)
4. [Transitive Dependencies](#4-transitive-dependencies)
5. [Infrastructure Dependencies](#5-infrastructure-dependencies)
6. [Hidden & Implicit Dependencies](#6-hidden--implicit-dependencies)
7. [Dependency Risk Matrix](#7-dependency-risk-matrix)
8. [Removal Impact Analysis](#8-removal-impact-analysis)
9. [Internal vs External Boundary Definition](#9-internal-vs-external-boundary-definition)

---

## 1. System Boundary Map

```
╔══════════════════════════════════════════════════════════════════╗
║                     INTERNAL SYSTEM                              ║
║                                                                  ║
║   src/main.py       src/app.py        src/config.py             ║
║   src/state.py      src/leomatch.py   src/dialog.py             ║
║   src/ai_client.py  src/storage.py    src/logging_setup.py      ║
║   src/utils.py                                                   ║
║                                                                  ║
║   data/conversation_histories.json                               ║
║   data/whitelist.json                                            ║
║   ai_bot_logs.txt                                                ║
║   .env                                                           ║
╚══════════════╤═══════════════════════╤═════════════════════════╤═╝
               │                       │                         │
    ┌──────────▼──────────┐  ┌─────────▼──────────┐  ┌──────────▼──────────┐
    │  TELEGRAM PLATFORM  │  │  GOOGLE GEMINI API  │  │   LOCAL OS / HOST   │
    │                     │  │                     │  │                     │
    │  MTProto network    │  │  HTTPS REST API     │  │  Filesystem (r/w)   │
    │  @leomatchbot       │  │  gemini-1.5-flash   │  │  Python runtime     │
    │  Real user accounts │  │  generativeai SDK   │  │  asyncio event loop │
    │  (matches)          │  │                     │  │  Thread pool        │
    └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
          EXTERNAL                  EXTERNAL                 PLATFORM
```

**The system has exactly three external boundaries:**
1. Telegram network (bidirectional: receive events, send messages)
2. Google Gemini API (outbound only: send prompts, receive generated text)
3. Local OS / host (filesystem I/O, Python runtime, network stack)

Everything else — all business logic, state management, timing, simulation — is internal.

---

## 2. External Services

### 2.1 Telegram Platform (MTProto)

**What it is:** Telegram's native binary protocol for user clients. The system uses this to operate a real Telegram user account — not a bot account.

**What the system uses:**

| Operation | Pyrogram call | Purpose |
|-----------|--------------|---------|
| Read events | `MessageHandler`, `EditedMessageHandler` | Receive incoming messages from bot and users |
| Send message | `client.send_message()` | Send replies, dating bot commands |
| Send typing | `client.send_chat_action(TYPING)` | Show "typing..." indicator |
| Mark read | `client.read_chat_history()` | Send read receipt (double checkmark) |
| Resolve peer | `client.resolve_peer()` | Verify @leomatchbot is reachable at startup |
| Fetch history | `client.get_chat_history()` | Startup replay — get last bot message |

**Authentication model:**
```
First run:  phone number + OTP → creates ai_dating_user.session
All runs:   API_ID + API_HASH + .session file → resumes existing session
```
The `.session` file is a SQLite database containing session keys. It is equivalent in power to the account password — anyone who has it can act as the account.

**Why it cannot be replaced:**
`@leomatchbot` only communicates with real user accounts. Telegram's Bot API cannot interact with other bots in private chats, cannot send read receipts from a user perspective, and cannot appear as a real person. MTProto is the only protocol that satisfies all three requirements simultaneously.

**Failure modes:**

| Failure | Effect | Recovery |
|---------|--------|---------|
| Telegram network down | Bot stops receiving and sending | Automatic reconnect by Pyrogram on network restoration |
| Session invalidated (logout, TOS ban) | `AuthKeyUnregistered` exception | Delete `.session` file, re-authorize manually |
| Account banned by Telegram | `UserDeactivated` exception | No recovery — account is lost |
| Rate limiting by Telegram | `FloodWait` exception | Pyrogram handles most automatically; aggressive behavior may trigger |
| `@leomatchbot` changes its message format | Silent breakage — regex fails to match | Must update `ANKET_PATTERN` and message handling logic |

**Lock-in level:** **Absolute.** Telegram is the only platform the system supports. The entire architecture is built around Telegram's event model, MTProto's capabilities, and `@leomatchbot`'s specific protocol. Migrating to a different dating platform would require rewriting `leomatch.py`, `dialog.py`, `app.py`, and swapping Pyrogram entirely.

**Cost:** Free (Telegram API is free for personal use). The `API_ID` and `API_HASH` are personal developer credentials tied to the operator's Telegram account — misuse can result in API key revocation.

**ToS exposure:** Automating a user account violates Telegram's Terms of Service (Section 8.3). This is the single highest external risk in the system.

---

### 2.2 Google Gemini API

**What it is:** Google's generative AI API, providing access to the Gemini family of language models. The system uses `gemini-1.5-flash-latest` — a fast, cost-efficient model optimized for high-frequency calls.

**What the system uses:**

| Operation | SDK call | Purpose |
|-----------|---------|---------|
| Configure auth | `genai.configure(api_key=...)` | Global SDK initialization |
| One-shot generation | `model.generate_content(prompt)` | Generate opening messages |
| Chat session | `model.start_chat(history=...)` | Initialize stateful conversation |
| Chat response | `chat.send_message(message)` | Generate conversation replies |

**Request volume estimate:**
- Scout: 1 API call per mutual match (opener generation)
- Interlocutor: 1 API call per conversation reply

At normal dating bot usage (dozens of matches/day, multiple active conversations), expect 20–100 API calls per day — comfortably within Gemini's free tier.

**Authentication:** API key in `.env`. The key is scoped to the project — revocation affects only this application, not other Google services.

**Why it cannot easily be replaced:**
The Gemini SDK is used for both stateless (`generate_content`) and stateful (`start_chat`) generation. Any replacement model (OpenAI GPT, Anthropic Claude, local LLM) would require:
- Changing `ai_client.py` completely
- Adapting the history format (role names, message structure)
- Re-validating that persona prompts produce equivalent output
- Handling different rate limits and pricing tiers

The coupling is moderate — all Gemini interaction is isolated in `ai_client.py`, so the swap surface is contained.

**Failure modes:**

| Failure | Effect | Recovery |
|---------|--------|---------|
| API key invalid / revoked | `generate_content` throws auth error | `state.model = None` → both generation functions return fallback strings |
| Rate limit (429) | `ResourceExhausted` exception | `with_rate_limit_handling()` retries up to 3× with parsed wait time |
| Model deprecated | Requests fail or return degraded output | Update model name in `config.py` |
| API outage | All AI calls fail after 3 retries | Fallback strings are sent; conversations continue with generic messages |
| Unexpected response format | `result.text` access fails | Fallback string returned; no crash |
| Prompt injection by user | Persona rules bypassed | ANTI-DEANON PROTOCOL in prompt provides some resistance |

**Lock-in level:** **Medium.** The entire AI interaction is behind the `ai_client.py` facade. The SDK is Google-specific but the interface exposed to the rest of the app (`generate_first_message`, `generate_conversation_response`) is provider-agnostic. Switching providers requires changing one file.

**Cost:** Free tier available (Gemini Flash has a generous free quota). Paid tier starts if usage exceeds ~1,500 requests/day. At current expected volume, cost is $0.

---

### 2.3 @leomatchbot (Third-Party Bot)

**What it is:** A Telegram dating bot — not a Google or Telegram service, but a third-party application operated by an unknown provider. The system is built entirely around this bot's specific message protocol.

**Protocol dependencies the system relies on:**

| Bot behavior | System dependency |
|-------------|-----------------|
| Sends profile cards as `Name, Age, City — Description` | `ANKET_PATTERN` regex |
| Sends "Write a message for this user" after match | Triggers opener generation |
| Sends "1. View profiles" as main menu | Handled in `process_leomatch_message` |
| Accepts `"1"` as navigation command | Sent to browse profiles |
| Accepts `"💌 / 📹"` as like signal | Sent to like profiles |
| Accepts `"👎"` as dislike signal | Sent to dislike profiles |
| Specific system messages to ignore | `KNOWN_SYSTEM_MESSAGES` set |

**This is the most fragile external dependency in the entire system.** `@leomatchbot` is:
- Not owned or controlled by the operator
- Not versioned or documented (from the operator's perspective)
- Can change its message format at any time without notice
- Can ban users for automated behavior
- Can go offline permanently

**Failure modes:**

| Failure | Effect | Recovery |
|---------|--------|---------|
| Bot changes profile card format | `ANKET_PATTERN` fails to match; all profiles treated as unrecognized | Update regex in `config.py` |
| Bot changes navigation commands | Sent `"1"` is ignored; bot gets stuck at menu | Update command strings in `leomatch.py` |
| Bot changes like/dislike signals | Actions silently fail | Update emoji strings in `leomatch.py` |
| Bot adds new system messages | New messages logged as warnings; no functional harm | Add to `KNOWN_SYSTEM_MESSAGES` |
| Bot detects automation and bans account | System stops working entirely | New account + re-authorization |
| Bot goes offline | No new profiles arrive; system idles | No impact; system waits for events |

**Lock-in level:** **Absolute.** The system has no abstract "dating platform" layer. It is hard-coded for `@leomatchbot`. Migrating to any other platform (Badoo, Mamba, Tinder, another Telegram bot) requires rewriting `leomatch.py` from scratch and adjusting `config.py`.

**Cost:** Free (from the system's perspective). The bot may have its own ToS around automated interaction.

---

## 3. Direct Python Dependencies

These are the four libraries listed in `requirements.txt`.

### 3.1 pyrogram 2.0.106

**License:** LGPLv3

**What it does:** Full async Python implementation of the Telegram MTProto protocol. Handles connection establishment, encryption, session management, event dispatching, and all Telegram API calls.

**System role:** The event bus and Telegram interface. Without Pyrogram, the entire communication layer is gone.

**Key capabilities used:**
- `Client` — manages MTProto session and connection lifecycle
- `MessageHandler` / `EditedMessageHandler` — event listener registration
- `filters` — message routing (private, chat, not-me)
- `enums.ChatAction.TYPING` — typing indicator
- All `client.*` method calls

**Indirect dependencies it pulls in:**
- `pyaes 1.6.1` — pure-Python AES (fallback when tgcrypto is absent)
- `pysocks 1.7.1` — SOCKS proxy support (unused in this project)

**Maintenance status:** Pyrogram 2.0.x is a stable but effectively unmaintained fork of the original. The original author (@delivrance) abandoned it; the community fork is [pyrofork](https://github.com/pyrogram/pyrogram). Version 2.0.106 is the last stable release on the original repository. **This is a moderate maintenance risk** — security vulnerabilities will not be patched upstream.

**Replacement cost:** High. Every Telegram interaction in the codebase uses Pyrogram types and conventions. Migration to `telethon` (the main alternative) would require rewriting `app.py`, `leomatch.py`, `dialog.py`, and all handler signatures.

---

### 3.2 tgcrypto 1.2.5

**License:** LGPLv3+

**What it does:** C extension providing fast AES-256-IGE encryption/decryption, required for Telegram's MTProto protocol. Without it, Pyrogram falls back to `pyaes` (pure Python, ~10× slower).

**System role:** Performance dependency, not functional. The system works without it (`pyaes` is the fallback) but MTProto message encryption/decryption becomes significantly slower, increasing latency for all Telegram operations.

**Risk:** Low. It is a well-maintained, single-purpose library. If unavailable, `pyaes` handles the same operations correctly.

---

### 3.3 google-generativeai 0.8.6

**License:** Apache 2.0

**What it does:** Google's official Python SDK for the Generative AI API. Provides `GenerativeModel`, `start_chat`, `generate_content`, and all model interaction primitives.

**System role:** The AI generation interface. All Gemini calls go through this SDK.

**Indirect dependencies it pulls in (partial list):**

| Package | Version | Purpose |
|---------|---------|---------|
| `google-ai-generativelanguage` | 0.6.15 | Low-level gRPC service client |
| `google-api-core` | 2.30.3 | HTTP/gRPC transport, retry logic, auth |
| `google-api-python-client` | (latest) | REST API client layer |
| `google-auth` | 2.53.0 | OAuth2 / API key authentication |
| `protobuf` | 5.29.6 | Binary serialization for API payloads |
| `pydantic` | 2.13.4 | Request/response validation |
| `proto-plus` | (latest) | Pythonic protobuf wrappers |
| `grpcio` | (latest) | Optional gRPC transport |
| `requests` | (latest) | HTTP transport fallback |
| `cryptography` | (latest) | TLS and key handling |

**Total transitive dependency tree:** ~15–20 packages pulled in by this single requirement. This is the largest dependency footprint in the project by a wide margin.

**Lock-in level:** Medium. All Gemini interaction is behind `ai_client.py`. The SDK can be replaced by any HTTP client making direct REST calls to the Gemini API, or by another provider's SDK.

---

### 3.4 python-dotenv 1.2.2

**License:** BSD-3-Clause

**What it does:** Reads key=value pairs from a `.env` file and loads them into `os.environ` at process startup.

**System role:** Development/deployment convenience. Eliminates the need to export environment variables manually before running the script.

**Usage:**
```python
# config.py — called at module import time
load_dotenv()
API_ID = os.getenv("TELEGRAM_API_ID")
```

**What happens if removed:** The system would still work correctly if the operator sets the three environment variables through another mechanism (shell export, systemd `EnvironmentFile=`, Docker `--env-file`, etc.). The `.env` file is not required at runtime — only `os.environ` is read.

**Risk:** None. Zero-risk utility library with no transitive dependencies and no external network calls.

---

## 4. Transitive Dependencies

These are not declared in `requirements.txt` but are installed and used at runtime through the dependency chain.

### Telegram stack (via pyrogram)

| Package | Version | Role | Risk |
|---------|---------|------|------|
| `pyaes` | 1.6.1 | AES encryption fallback when tgcrypto absent | Low — only used as fallback |
| `pysocks` | 1.7.1 | SOCKS proxy support | Low — unused in this project |

### AI stack (via google-generativeai)

| Package | Version | Role | Risk |
|---------|---------|------|------|
| `google-ai-generativelanguage` | 0.6.15 | gRPC service definition for Gemini API | Medium — tied to Gemini API version |
| `google-api-core` | 2.30.3 | Transport, retry, auth core | Low — stable Google library |
| `google-auth` | 2.53.0 | API key + OAuth2 handling | Low — stable |
| `google-api-python-client` | latest | REST API layer | Low |
| `protobuf` | 5.29.6 | Binary wire format | Medium — version pinning matters; protobuf 4→5 had breaking changes |
| `pydantic` | 2.13.4 | Request/response validation | Low — internal to SDK |
| `proto-plus` | latest | Pythonic protobuf wrappers | Low |
| `googleapis-common-protos` | latest | Shared API proto definitions | Low |
| `grpcio` | latest | gRPC transport (optional) | Low |
| `grpcio-status` | latest | gRPC status codes | Low |
| `requests` | latest | HTTP transport | Low |
| `httplib2` | latest | HTTP client for google-api-python-client | Low |
| `uritemplate` | latest | URI template expansion | Low |
| `cryptography` | latest | TLS, signing | Low — high quality, actively maintained |
| `pyasn1-modules` | latest | ASN.1 parsing for auth | Low |
| `annotated-types` | latest | Pydantic type annotations | Low |
| `pydantic-core` | latest | Pydantic Rust core | Low |
| `typing-extensions` | latest | Python typing backports | Low |
| `tqdm` | latest | Progress bars (unused in this project) | Low — display utility |

**Key observation:** The `google-generativeai` package brings in approximately 15–20 transitive packages, some with native extensions (pydantic-core is Rust, grpcio has C bindings, cryptography has C bindings). This means the project's actual dependency footprint is much larger than the 4 entries in `requirements.txt` suggest.

---

## 5. Infrastructure Dependencies

### Host machine / server

| Requirement | Why needed | If absent |
|------------|-----------|----------|
| Python 3.10+ | `str | None` union types, `match` patterns (not yet used but required by asyncio improvements) | Syntax errors on startup |
| Outbound TCP on port 443 | Telegram MTProto and Gemini API HTTPS calls | Bot cannot connect to anything |
| Outbound TCP on port 5222 | Alternative Telegram MTProto port (Pyrogram falls back) | May cause connection issues on restricted networks |
| Filesystem read/write access | JSON history files, log file, session file | Storage operations fail; histories lost |
| Persistent process (tmux / systemd) | 24/7 operation | Bot only runs while terminal is open |
| ~100 MB RAM | Python runtime + Pyrogram + Gemini SDK | OOM kill; data loss risk (see atomic write issue) |
| ~50 MB disk | venv, log file, session file, histories | Disk full = log write failure; non-fatal |

### Operating System

The code is **cross-platform compatible** (Python stdlib, no OS-specific calls) but is **deployed on Linux** (the tmux/Ubuntu deployment guide). The atomic write fix (`os.rename`) is guaranteed atomic on POSIX — on Windows it may fail if the destination file exists, requiring `os.replace()` instead. Not a current concern since deployment is Linux.

### Network

| Endpoint | Protocol | Port | Direction |
|----------|---------|------|-----------|
| `*.telegram.org` | MTProto over TCP | 443 / 5222 | Bidirectional |
| `generativelanguage.googleapis.com` | HTTPS REST / gRPC | 443 | Outbound only |

No inbound ports are opened. The system is a pure outbound client.

---

## 6. Hidden & Implicit Dependencies

These are not in `requirements.txt` but the system depends on them functioning correctly.

### Python Standard Library

| Module | Usage |
|--------|-------|
| `asyncio` | Entire concurrency model — event loop, tasks, sleep, to_thread |
| `json` | All persistence read/write |
| `logging` | All observability |
| `logging.handlers.RotatingFileHandler` | Log rotation |
| `pathlib.Path` | All file path operations |
| `os` | Environment variable reads |
| `re` | Profile card regex |
| `datetime` | Timestamps, cooldown calculation, session classification |
| `random` | Delay tier selection, typing jitter |
| `functools.partial` | Handler state injection |
| `dataclasses` | `BotState` definition |
| `typing` | Type hints throughout |

**Risk:** Near-zero. The stdlib is part of the Python runtime and changes only across major Python versions.

### Gemini API contract (implicit)

The system depends on specific undocumented behaviors of the Gemini API:

| Implicit assumption | Where relied upon | Risk if it changes |
|--------------------|------------------|-------------------|
| Chat history accepts alternating user/model roles only | `generate_conversation_response` history assembly | Would break system prompt injection; persona silently disabled |
| `result.text` attribute exists on response objects | `ai_client.py` — both generation functions | `AttributeError`; fallback string returned |
| `ResourceExhausted` exception carries retry-delay metadata | `with_rate_limit_handling` | Falls back to 60s retry; functional but suboptimal |
| Model follows `|||` frequency instruction (~30%) | `dialog.py` ladder split | Behavioral drift; not a crash |
| `gemini-1.5-flash-latest` resolves to a specific model | All AI calls | If Google retires the model name, all calls fail |

### @leomatchbot message protocol (implicit)

Covered in §2.3. The system has zero documentation of the bot's protocol — all knowledge is encoded in `config.py` and `leomatch.py` as hard-coded strings and a regex.

### Telegram MTProto protocol stability

Pyrogram 2.0.106 targets a specific version of the MTProto protocol. Telegram may update its protocol in ways that require Pyrogram updates. Since Pyrogram 2.0.x is effectively unmaintained, such updates would break the system until the community fork is adopted.

### Time and timezone correctness of the host

`dialog.py` session classification computes time-since-last-message using `datetime.now(datetime.timezone.utc)`. If the host's system clock is wrong (drifted, wrong timezone), session classification will be incorrect (e.g., treating active conversations as new sessions). This is a silent behavioral bug, not a crash.

---

## 7. Dependency Risk Matrix

| Dependency | Criticality | Failure probability | Impact if fails | Mitigation in code |
|-----------|-------------|--------------------|-----------------|--------------------|
| Telegram MTProto network | **Critical** | Low | Bot completely stops | Pyrogram auto-reconnect |
| Telegram account ban | **Critical** | Medium (ToS exposure) | Total system failure | None |
| @leomatchbot protocol change | **Critical** | Medium | Scout pipeline breaks silently | None |
| Google Gemini API | **High** | Low | AI falls back to static strings | Fallback strings, 3-retry handler |
| Gemini model deprecated | **High** | Low (annual) | All AI calls fail | None — manual update required |
| pyrogram library | **High** | Low (frozen) | Cannot connect to Telegram | None — frozen dependency |
| pyrogram security vuln | **Medium** | Medium (unmaintained) | Account compromise risk | None — migrate to pyrofork |
| Host filesystem | **Medium** | Very low | Cannot save/load histories | None |
| Python runtime | **Low** | Very low | Cannot run | None |
| python-dotenv | **Low** | Very low | Set env vars manually instead | `.env` is optional |
| tgcrypto | **Low** | Very low | Falls back to pyaes (slower) | Built-in pyaes fallback |
| protobuf version conflict | **Medium** | Low | SDK import errors | Pin versions in requirements.txt |

---

## 8. Removal Impact Analysis

What happens to the system if each external dependency is removed:

### Remove Telegram / MTProto
**Impact:** Total system failure. No events received. No messages sent. No read receipts. No typing indicators. The entire application has no purpose without Telegram.
**Alternative:** None. The product is Telegram-native.

### Remove Google Gemini API
**Impact:** Partial degradation. Both `generate_first_message` and `generate_conversation_response` detect `state.model is None` and return hardcoded fallback strings:
- Opener: `"your profile seemed very interesting, shall we chat?"`
- Reply: `"hm, something went wrong, repeat that"`
The bot continues to operate but sends the same generic messages to every person. Conversations become non-functional after a few turns.
**Alternative:** Replace `ai_client.py` with any other LLM provider (OpenAI, Anthropic, local Ollama). The facade pattern makes this a one-file change.

### Remove @leomatchbot
**Impact:** Scout pipeline becomes idle (no matching messages arrive). Interlocutor pipeline continues to function normally for existing private conversations. No new matches are generated. System idles.
**Alternative:** Adapt `leomatch.py` for another dating platform's message protocol.

### Remove pyrogram
**Impact:** Total failure. No Telegram interaction is possible without a MTProto client library.
**Alternative:** `telethon` (most mature alternative), `hydrogram` / `pyrofork` (pyrogram forks with active maintenance).

### Remove tgcrypto
**Impact:** Pyrogram falls back to `pyaes` (pure Python AES). System continues to function but all Telegram operations become ~10× slower due to software AES. At the volume of this application, this would add tens of milliseconds per operation — imperceptible.
**Alternative:** None needed; fallback is built in.

### Remove google-generativeai
**Impact:** Same as removing Gemini API — `ai_client.py` cannot import, `initialize_ai` fails, `state.model = None`, fallback strings used.
**Alternative:** Direct HTTP calls to `generativelanguage.googleapis.com` REST endpoints, or any other LLM SDK.

### Remove python-dotenv
**Impact:** The three credentials must be set as OS environment variables before running the script. System works identically if they are set. The `.env` file is simply not read.
**Alternative:** `export TELEGRAM_API_ID=... ` in shell, or systemd `EnvironmentFile=`, or Docker `--env-file`.

---

## 9. Internal vs External Boundary Definition

### Internal System
Everything the operator owns and controls:

```
src/
  main.py, app.py, config.py, state.py
  leomatch.py, dialog.py, ai_client.py
  storage.py, logging_setup.py, utils.py

data/
  conversation_histories.json
  whitelist.json

.env (credentials — owned but secret)
ai_dating_user.session (Telegram session — owned but secret)
ai_bot_logs.txt
```

**Characteristics of the internal system:**
- Fully under operator control
- Can be modified, deployed, and shut down at will
- No external approval required for changes
- Can be backed up, versioned, and restored

### External System — Telegram Platform

**Boundary:** The Pyrogram `Client` object is the crossing point. Everything the system does to influence the outside world passes through `client.*` method calls.

```
Internal → External crossing points:
  client.send_message()           ← crosses boundary outward
  client.send_chat_action()       ← crosses boundary outward
  client.read_chat_history()      ← crosses boundary outward
  MessageHandler callback         ← crosses boundary inward
  EditedMessageHandler callback   ← crosses boundary inward
```

**Operator controls:** what is sent, when, in response to what.
**Operator does not control:** Telegram's infrastructure, other users' actions, `@leomatchbot`'s behavior, ToS enforcement.

### External System — Google Gemini API

**Boundary:** The `with_rate_limit_handling(lambda: ...)` wrapper in `ai_client.py` is the crossing point. All AI requests pass through it; all responses come back through it.

```
Internal → External crossing points:
  model.generate_content(prompt)         ← crosses boundary outward
  chat_session.send_message(message)     ← crosses boundary outward
  result.text (response object)          ← crosses boundary inward
```

**Operator controls:** what prompts are sent, conversation history included, model selected.
**Operator does not control:** model output quality, API availability, pricing, model updates.

### External System — Local OS / Host

**Boundary:** Filesystem calls in `storage.py` and `logging_setup.py`.

```
Internal → External crossing points:
  path.open("r") / json.load()     ← crosses boundary inward
  path.open("w") / json.dump()     ← crosses boundary outward
  RotatingFileHandler writes       ← crosses boundary outward
```

**Operator controls:** file paths, server infrastructure, backup strategy.
**Operator does not control:** hardware failures, OOM killer, filesystem corruption.

---

### Summary: Boundary Principle

> **The internal system is the logic that decides what to do.**
> **The external systems are the infrastructure through which those decisions are enacted.**

The internal system can be understood, tested, and modified in complete isolation. Its three external boundaries are all clearly localized:
- All Telegram I/O → `app.py` (handler registration) + direct `client.*` calls in `leomatch.py` and `dialog.py`
- All AI I/O → `ai_client.py`
- All filesystem I/O → `storage.py` + `logging_setup.py`

This clean boundary structure means that any external system can be replaced by modifying exactly one module, without touching the business logic in `leomatch.py`, `dialog.py`, `state.py`, or `config.py`.
