# ADR-002: SQLite for MVP, Not PostgreSQL + Redis

**Status:** Decided  
**Date:** 2026-06-04

---

## Context

The original TURN orchestrator spec called for PostgreSQL (Neon/Supabase) + Redis (Upstash). The MVP technical spec revised this to SQLite + APScheduler with SQLite job store.

---

## Decision

Use SQLite for all MVP persistence (conversations, users, payments, ML labels, scheduled jobs). Migrate to PostgreSQL + Redis when concurrent users exceed ~50-100.

---

## Reasons

**1. Zero ops.**
SQLite requires no external service, no connection strings to manage, no service to go down. The entire database is a file. Railway and Render both support persistent volumes for that file. Operational complexity at MVP stage is a real cost — every hour spent on infra is an hour not spent on users.

**2. APScheduler integrates natively with SQLite.**
The SQLAlchemy job store for APScheduler can point to the same SQLite file. This gives us persistent reminders (survive restarts) without Redis. No second service to provision.

**3. Scale limits are not relevant at MVP.**
SQLite handles ~50-100 concurrent writes before contention becomes noticeable. The MVP success gate is 20 paying users and 50 conversations with outcomes. That's not a SQLite problem.

**4. State-from-DB pattern works cleanly.**
Every handler reads conversation `status` from DB before acting. This pattern is identical whether the DB is SQLite or PostgreSQL. Migration later requires only changing the connection string and switching to psycopg2. The application code is unchanged.

---

## What This Changes From the Orchestrator Spec

The orchestrator spec (`../docs/TURN-ORCHESTRATOR.md`) described Redis for state management and PostgreSQL for persistence. That spec was written for a scale that doesn't exist yet. This ADR supersedes it for MVP.

Specifically:
- Redis sorted set for reminders → APScheduler SQLite job store
- Redis `turn:user:{id}:conv:{id}` state keys → `conversations.status` column in SQLite
- `context.user_data` in Telegram → used as a session cache only; DB is truth

---

## One Critical Nuance

`context.user_data` in python-telegram-bot is convenient but ephemeral — it's cleared on bot restart. The pattern is:

```python
# WRONG — trusting in-memory state:
conv_id = context.user_data.get('conv_id')

# RIGHT — DB is truth, memory is cache:
active = db.get_active_conversation(user_id)
conv_id = active['id'] if active else None
context.user_data['conv_id'] = conv_id  # cache for this session
```

Every handler must be able to recover state from DB alone, with no in-memory context. This makes the bot resumable after any restart.

---

## Migration Path (When Needed)

When to migrate: >50 concurrent active conversations OR >1000 pending reminder jobs OR response latency >2s due to DB contention.

Migration steps:
1. Provision Neon (PostgreSQL) — free tier sufficient initially
2. Provision Upstash (Redis) — free tier sufficient for reminders
3. Convert SQLite schema to PostgreSQL (UUID primary keys, TIMESTAMPTZ, JSONB)
4. Switch APScheduler job store to RedisJobStore
5. Move reminder logic to Redis sorted set + background thread (see orchestrator spec)
6. Data migration: one-time script to copy SQLite → PostgreSQL
7. Zero code changes in handlers (only `db.py` changes)

---

## Consequences

- Deployment is simpler (one service, one file)
- No Redis connection pooling, no Supabase IAM, no connection limits
- If the bot crashes mid-conversation, all in-flight conversations resume cleanly (status from DB)
- Scheduled reminders survive restarts (SQLite job store)
- Technical debt: will need to migrate when scale demands it, but not before
