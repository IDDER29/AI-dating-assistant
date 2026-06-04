# Product Overview — AI Dating Assistant

_Last updated: 2026-06-04_

---

## What This Project Is

**AI Dating Assistant** is an automated social bot that impersonates a real person on the Telegram dating platform `@leomatchbot`. It acts as a fully autonomous digital avatar that browses profiles, initiates contact, and holds extended conversations — all without the human operator lifting a finger.

---

## Core Idea

The system logs into a real Telegram account and controls it like a human would: it scrolls through dating profiles, decides who is interesting, sends a custom opening line, then switches into "relationship mode" to nurture the conversation until the other person suggests a real-world meeting.

---

## Main Problem It Solves

Dating apps are time-consuming and emotionally draining. The operator wants the benefits (meeting people, getting dates) without spending hours swiping, crafting openers, and maintaining small talk. The bot handles the entire top-of-funnel — from discovery to warm lead — autonomously.

---

## Target Users & Their Needs

| User | Need |
|------|------|
| The operator (one person running it) | Outsource the tedious early stages of online dating; only step in when a real connection is established |
| (Unknowingly) the matches | They believe they are talking to a real person |

---

## Two-Brain Architecture

The system has two distinct AI modes:

### 1. Scout
Lives inside the `@leomatchbot` interface. Reads incoming profile cards, applies a quality filter, auto-likes or auto-dislikes, and generates a unique witty opener when a mutual match is made.

### 2. Interlocutor
Activates in private chats after a match. Plays a fully fleshed-out fictional persona (with a job, hobbies, humor style, personal anecdotes) and steers the dialogue toward the goal: the other person suggesting a real meeting.

---

## Human-Simulation Layer

A set of techniques sits on top of both brains to prevent the AI from feeling robotic:

- **Informal writing style** — no sentence-ending periods, uses slang, AI "academic" language is stripped in post-processing.
- **Ladder sending** — one thought is sometimes split into several short messages sent in quick succession.
- **Dynamic reply delay** — fast responses in active dialogues; realistic multi-minute or multi-hour delays when resuming a cold conversation.
- **Debounce (smart timer)** — if the match sends several messages in a row, the bot waits for a pause and replies to the full block at once.
- **Read receipts + typing indicator** — messages are marked read immediately; "typing…" status appears before each reply.

---

## Reliability Features

- **Whitelist** — specific user IDs bypass AI processing, allowing the operator to take over manually.
- **Persistent memory** — all conversation histories saved to a JSON file; bot survives restarts.
- **API rate-limit handling** — respects retry-after headers from Gemini API.
- **24/7 design** — intended to run continuously on a remote server (e.g. Ubuntu + tmux).

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Telegram interface | Pyrogram (async MTProto) |
| AI model | Google Gemini 1.5 Flash |
| Persistence | JSON flat files |
| Env config | python-dotenv |

---

## Overall System Goal

Fully automate the discovery and early-conversation phase of online dating, producing warm "leads" (people who want to meet in person) that the operator can then convert into real interactions — with zero manual effort required before that point.

---

## Disclaimer

This project is described as an educational experiment in AI and automation. Responsible and ethical use is expected.
