# Security Hardening Guide

> This document covers the operational security steps required to harden a
> production deployment of the AI Dating Assistant. Run these once after
> initial setup and after any credential rotation.

---

## 1. File Permissions

Three files contain credentials that, if read by an attacker, lead to total
account compromise. Restrict them to owner-read-only:

```bash
chmod 600 .env
chmod 600 ai_dating_user.session
chmod 600 src/credentials.py   # if it ever contains values (should only read .env)
```

The bot checks permissions at startup and logs a warning if any of these files
are world- or group-readable. Look for:
```
[SECURITY] .env has permissive permissions (0o644). Recommended: chmod 600 .env
```

---

## 2. Verify `.gitignore` Coverage

Confirm that sensitive files are never committed:

```bash
git status --ignored | grep -E "\.env|\.session|credentials\.py"
```

All three must appear in the ignored list. If any do not appear, add them:
```
# .gitignore entries required:
.env
*.session
*.session-journal
src/credentials.py
```

---

## 3. Session File Rotation

`ai_dating_user.session` grants full access to the Telegram account with no
expiry. If you suspect compromise:

1. Log out all active sessions via **Telegram Settings → Devices → Terminate all other sessions**
2. Delete the local session file: `rm ai_dating_user.session`
3. Restart the bot: `python src/main.py` — it will re-authenticate interactively (phone + code)
4. Set permissions: `chmod 600 ai_dating_user.session`

---

## 4. Gemini API Key Rotation

1. Create a new key at [aistudio.google.com](https://aistudio.google.com) → API Keys
2. Update `GEMINI_API_KEY` in `.env`
3. Restart the bot: `sudo systemctl restart ai-dating-assistant` (or however you run it)
4. Revoke the old key in Google AI Studio

---

## 5. Telegram API Credentials

Telegram API credentials (`TELEGRAM_API_ID` / `TELEGRAM_API_HASH`) are tied to
the registered application and cannot be changed. If compromised:

1. Go to [my.telegram.org/apps](https://my.telegram.org/apps)
2. Disable or delete the application
3. Create a new application and update `.env` with the new credentials
4. Delete and re-create the session file (see §3 above)

---

## 6. Data Deletion (GDPR / Right to Erasure)

To delete all stored data for a specific user:

```bash
# Create the deletion request file:
echo "TELEGRAM_CHAT_ID" > data/delete_requests.txt

# Find the bot PID and send SIGUSR1:
kill -USR1 $(pgrep -f "python.*main.py")
```

The bot will:
1. Read `data/delete_requests.txt`
2. Delete the user's conversation history and memory from disk
3. Clear their in-memory rate-limit and meeting-signal state
4. Remove `delete_requests.txt`
5. Log confirmation: `[SYSTEM] Deleted data for user XXXXXX: {...}`

Note: `stats.json` contains only event types and timestamps (no message content).
It is not subject to deletion requests.

---

## 7. What the Bot Logs (and What It Does Not)

**Logged (metadata only):**
- Message length in characters
- Profile description length in characters
- AI response length in characters
- Chat IDs for routing and stats
- First 20 characters of profile text (for debugging unrecognized formats)

**Never logged:**
- Full message content
- Full profile card text
- AI response text
- User names (first names from Telegram)
- Conversation memory contents

---

## 8. Prompt Injection Defense

The bot has two layers of injection defense:

1. **Input sanitizer** (`src/input_sanitizer.py`): Detects injection patterns
   (e.g. "ignore all previous instructions") and logs a warning. Does not block
   — the ANTI-DEANON PROTOCOL in the system prompt handles deflection.

2. **Output validator** (`src/output_validator.py`): If a successful injection
   causes the AI to admit being a bot or break persona, the response is
   rejected and replaced with the fallback message. The user turn is also
   rolled back from history.

Neither layer is a guarantee — they are defense in depth alongside the
system prompt's own ANTI-DEANON PROTOCOL.
