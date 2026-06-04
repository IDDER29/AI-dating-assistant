# Deployment Guide

> This guide covers first-time server setup and ongoing operations.
> See also: [SECURITY.md](SECURITY.md) for credential hardening steps.

---

## Prerequisites

- Linux server (Ubuntu 20.04+ / Debian 11+)
- Python 3.11+
- A Telegram account with API credentials from [my.telegram.org](https://my.telegram.org/apps)
- A Gemini API key from [aistudio.google.com](https://aistudio.google.com)

---

## First-Time Setup

### 1. Clone and install

```bash
cd /home/developer
git clone <repo-url> AI-dating-assistant
cd AI-dating-assistant
pip install -r requirements.txt
```

### 2. Create `.env`

```bash
cat > .env << 'EOF'
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
GEMINI_API_KEY=your_gemini_key
EOF
chmod 600 .env
```

### 3. Create the Telegram session (interactive — run once manually)

The session file is created the first time Pyrogram connects. It requires
interactive input (phone number + SMS/app code), so it cannot run as a service.

```bash
python src/main.py
# Follow the prompts: enter your phone number and the confirmation code
# The bot will start — press Ctrl+C after it logs "Startup complete"
chmod 600 ai_dating_user.session
```

### 4. Install and start the systemd service

```bash
# Copy the unit file (edit User= and WorkingDirectory= first if needed)
sudo cp deploy/ai-dating-assistant.service /etc/systemd/system/

# Edit paths if your server layout differs
sudo nano /etc/systemd/system/ai-dating-assistant.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable ai-dating-assistant
sudo systemctl start ai-dating-assistant

# Verify it started
sudo systemctl status ai-dating-assistant
```

---

## Operations Reference

### Status and logs

```bash
sudo systemctl status ai-dating-assistant          # current status
sudo journalctl -u ai-dating-assistant -f          # follow live logs
sudo journalctl -u ai-dating-assistant --since "1 hour ago"
tail -f ai_bot_logs.txt                            # bot's own rotating log
```

### Start / stop / restart

```bash
sudo systemctl start ai-dating-assistant           # start
sudo systemctl stop ai-dating-assistant            # graceful stop (SIGTERM)
sudo systemctl restart ai-dating-assistant         # stop then start
```

**Note:** `systemctl stop` sends SIGTERM. The bot will:
1. Cancel all active dialogue tasks (up to 10s)
2. Save conversation histories and memories to disk
3. Log `[SHUTDOWN] Shutdown complete` and exit cleanly

### Reload whitelist without restart

```bash
# After editing data/whitelist.json:
kill -HUP $(systemctl show -p MainPID --value ai-dating-assistant)
# Log confirms: [SYSTEM] Whitelist reloaded via SIGHUP. Users in list: N
```

### Delete a user's data (GDPR right to erasure)

```bash
echo "TELEGRAM_CHAT_ID" > data/delete_requests.txt
kill -USR1 $(systemctl show -p MainPID --value ai-dating-assistant)
# Log confirms: [SYSTEM] Deleted data for user XXXXXX: {...}
```

### Deploy a code update

```bash
git pull
sudo systemctl restart ai-dating-assistant
# Watch logs to confirm clean startup
sudo journalctl -u ai-dating-assistant -f --since "now"
```

### View stats

```bash
python scripts/stats_report.py              # last 24h
python scripts/stats_report.py --days 7    # last 7 days
python scripts/stats_report.py --all       # all time
```

---

## Auto-restart Behaviour

The systemd unit is configured with:
- `Restart=on-failure` — restarts on crash or signal death
- `RestartSec=30s` — waits 30s before restarting (avoids tight crash loops)
- `StartLimitBurst=5` — stops restarting after 5 failures in 10 minutes

If the bot keeps restarting, check logs for the root cause:
```bash
sudo journalctl -u ai-dating-assistant --since "30 minutes ago"
```

Common causes:
- **AuthKeyUnregistered** → Session expired. Delete `.session`, re-run manual login.
- **UserDeactivated** → Account banned. Check Telegram.
- **Missing env vars** → Check `.env` file contents.
- **Model not found** → Update `GEMINI_PRIMARY_MODEL` in `src/settings.py`.

---

## File Layout

```
AI-dating-assistant/
├── src/                    # Python source
├── deploy/
│   └── ai-dating-assistant.service   # systemd unit template
├── data/                   # runtime data (created automatically)
│   ├── conversation_histories.json
│   ├── conversation_memories.json
│   ├── whitelist.json
│   └── stats.json
├── scripts/
│   └── stats_report.py     # stats query tool
├── .env                    # credentials (chmod 600, not in git)
├── ai_dating_user.session  # Telegram session (chmod 600, not in git)
├── ai_bot_logs.txt         # rotating log (up to ~15MB)
└── requirements.txt
```
