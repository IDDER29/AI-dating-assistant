# Plan 0.3 — Configuration & Optimization

**Builds:** Final CLAUDE.md rules, memory verification, targeted permission allowlist  
**Depends on:** Plans 0, 0.1, 0.2 complete  
**Time:** ~5 minutes

---

## State Before
- CLAUDE.md exists with comprehensive rules (written in Plan 0)
- memory/wins.md and memory/losses.md exist with real content
- No settings.local.json

## State After
- CLAUDE.md has 2 additional rules merged from Phase 3 template
- Memory folder verified
- `~/.claude/settings.local.json` with targeted allowlist (NOT dangerously-skip-permissions)

---

## What Phase 3 Specifies vs. What's Right

### CLAUDE.md template
The Phase 3 template references `src/llm/` (wrong path — ours is `core/llm_client.py`) and
Alembic migrations (not used — we use plain SQLite per ADR-002). Do NOT replace CLAUDE.md.
Add only the 2 rules that are genuinely missing:
- Rule: Use TDD for Stripe webhook handlers and APScheduler jobs
- Rule: Run security-audit skill before committing payment/auth code

### Memory folder
Already exists with real project-specific content. `touch` would be a no-op. Skip.

### `dangerously-skip-permissions: true`
**Do not implement.** Blanket `allow: ["*"]` with dangerously-skip-permissions gives Claude
approval to run any Bash command without prompting — including destructive ones (drop DB,
delete files, git reset --hard). TURN handles Stripe keys, payment records, and user data.
The permission prompt is the safety net on destructive operations.

**Instead:** Implement a targeted allowlist for operations that are genuinely safe and
interrupt flow (read ops, test runs, Python execution, safe git reads).

---

## Task 0.3.1 — Merge 2 rules into CLAUDE.md

Add to the existing rules section:
- TDD for Stripe webhooks and APScheduler jobs
- Security audit before payment/auth code commits

## Task 0.3.2 — settings.local.json (targeted allowlist)

Location: `~/.claude/settings.local.json` (user-level, applies across all projects)

Allowlist covers only genuinely safe, high-frequency operations:
- Python execution (tests, config checks, one-liners)
- Pytest runs
- pip list/show (read-only package inspection)
- Read-only git operations (status, log, diff)
- File reads (already allowed by default but explicit is clearer)

NOT in allowlist (always require prompt):
- `git push`, `git reset`, `git checkout --`
- `pip install` / `pip uninstall` (modifies environment)
- Any `rm` or file deletion
- Any database write operations via shell

---

## Acceptance Criteria

- [x] CLAUDE.md exists with comprehensive rules (pre-existing)
- [x] memory/wins.md and memory/losses.md exist with content (pre-existing)
- [ ] CLAUDE.md has TDD rule for Stripe/APScheduler
- [ ] CLAUDE.md has security-audit rule for payment code
- [ ] `~/.claude/settings.local.json` exists with targeted allowlist
- [ ] `dangerously-skip-permissions` is NOT present anywhere in settings
