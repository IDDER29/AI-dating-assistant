# Plan 0.1 — Environment Setup

**Builds:** Working dev environment with venv, uv, railway CLI, pip tools, and all MCP servers configured  
**Depends on:** Plan 0 complete (skeleton exists)  
**Time:** ~30 minutes

---

## State Before
- Python 3.11.4 installed (system)
- Node 24 + npm installed
- No venv in turn_mvp/
- No uv/uvx
- No railway CLI
- No gmcp, mcp-alchemy, semgrep, pip-audit
- ~/.claude/settings.json written (MCP configs present but servers not yet verified)

## State After
- turn_mvp/venv/ exists and all requirements installed into it
- uv/uvx installed and on PATH
- railway CLI installed (login requires user action)
- gmcp, mcp-alchemy, semgrep, pip-audit installed
- All MCP servers verified reachable (those not requiring auth tokens)
- .env filled with real values (requires user action)

---

## What Needs User Action (cannot be automated)

These require browser auth or secret values — do them manually:

| Task | Command | Where to get the value |
|---|---|---|
| Fill .env | Edit `turn_mvp/.env` | Telegram BotFather, OpenAI dashboard, Stripe dashboard |
| Context7 API key | context7.com/dashboard | Free account |
| Brave Search key | brave.com/search/api | Free account |
| GitHub PAT | GitHub → Settings → Developer settings → Fine-grained PAT | Scope to TURN repo only |
| Railway login | `railway login` in terminal | Railway account |
| Stripe test key | Already in Stripe dashboard | Use `sk_test_` — never `sk_live_` |

After filling keys, update `~/.claude/settings.json` (context7, brave) and `.claude/settings.json` (stripe, github).

---

## Epic 1 — Virtual Environment

### Task 0.1.1 — Create venv

```powershell
cd C:\Users\developer\Documents\GitHub\TURN\turn_mvp
python -m venv venv
```

**Verify:** `turn_mvp/venv/` exists.

### Task 0.1.2 — Install requirements into venv

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Verify:** `pip list` shows python-telegram-bot, openai, stripe, apscheduler.

---

## Epic 2 — Install uv/uvx

uv is required for `mcp-server-git` and `mcp-alchemy` MCP servers.

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Restart terminal after this
uvx --version
```

**Verify:** `uvx --version` prints a version string.

---

## Epic 3 — Install Railway CLI

```powershell
npm install -g @railway/cli
railway --version
# Then authenticate (requires browser):
railway login
```

**Verify:** `railway --version` prints a version string.

---

## Epic 4 — Install Python Dev Tools

```powershell
# Into the venv (semgrep intentionally excluded — see note):
pip install gmcp mcp-alchemy pip-audit
```

**NOTE: Do NOT install semgrep into the project venv.** Semgrep pulls in `httpx 0.28.x` which conflicts with `python-telegram-bot 20.7`'s requirement of `httpx~=0.25.2`. Run semgrep in isolation via uvx instead:

```powershell
uvx semgrep --version   # downloads and caches on first run
uvx semgrep --config=p/python .
```

**Verify:** `gmcp --help`, `pip-audit --version` resolve. `uvx semgrep --version` resolves (may be slow on first run).

---

## Epic 5 — Verify MCP Servers

The MCP configs are already written. Verify the servers that don't need auth tokens start correctly:

```powershell
# Test fetch server starts
npx -y @modelcontextprotocol/server-fetch --help

# Test sequential-thinking server starts
npx -y @modelcontextprotocol/server-sequentialthinking --help

# Test filesystem server starts
npx -y @modelcontextprotocol/server-filesystem . --help

# Test git server (requires uvx)
uvx mcp-server-git --help

# Test mcp-alchemy (requires uvx)
uvx --from mcp-alchemy mcp-alchemy --help
```

**Verify:** Each prints help text without error.

---

## Epic 6 — Fill Keys in Settings Files

### ~/.claude/settings.json
Replace these two placeholders:
- `REPLACE_WITH_KEY_FROM_context7.com/dashboard` → your Context7 key
- `REPLACE_WITH_KEY_FROM_brave.com/search/api` → your Brave key

### turn_mvp/.claude/settings.json
Replace these two placeholders:
- `REPLACE_WITH_sk_test_KEY` → your Stripe test secret key
- `REPLACE_WITH_FINE_GRAINED_PAT_SCOPED_TO_TURN_REPO` → your GitHub PAT

### turn_mvp/.env
Copy `.env.example` to `.env` and fill all values.

---

## Acceptance Criteria — Plan 0.1 Complete When:

- [x] PTB 22.7 imports cleanly in venv
- [x] `uvx --version` → 0.11.19
- [x] `railway --version` → 5.0.0
- [x] `gmcp` imports cleanly
- [x] `mcp_alchemy` imports cleanly
- [x] `uvx semgrep --version` resolves (isolated, no venv conflict)
- [x] `pip-audit -r requirements.txt` → No known vulnerabilities found
- [x] `pytest tests/test_db.py -v` → 11/11 passed
- [ ] `.env` filled with real values (Telegram token, OpenAI key, Stripe keys) — USER ACTION
- [ ] `~/.claude/settings.json` Context7 + Brave keys filled — USER ACTION
- [ ] `.claude/settings.json` Stripe test key + GitHub PAT filled — USER ACTION
- [ ] `railway login` completed — USER ACTION
- [ ] `python main.py` starts bot without error — blocked on .env

## Key Decision Made During Execution

**PTB upgraded 20.7 → 22.7.** PTB 20.7 had 15 CVEs via tornado 6.3.3. PTB 22.7 uses tornado~=6.5 (clean) and httpx>=0.27,<0.29. Plan 0 skeleton code is API-compatible. See `memory/wins.md`.
