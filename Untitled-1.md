# Project Overview: AI Dating Assistant

## What It Does
This project is an automated Telegram assistant that interacts with a dating bot and conducts private chats using a Gemini-based persona. It runs in two modes:

1) **Leomatch Mode (Bot Interaction)**
- Reads profile cards from the dating bot.
- Likes profiles with descriptions; dislikes empty profiles.
- Generates an opening line when prompted by the bot.

2) **Private Chat Mode (Direct Messaging)**
- Replies to users in DMs using a defined persona and conversation history.
- Simulates natural typing and staggered responses.
- Uses a debounce delay before replying to the latest message.

## How It Works (As-Is)
- **Startup**
  - Loads environment variables.
  - Initializes Gemini and Pyrogram.
  - Loads data files:
    - `data/conversation_histories.json`
    - `data/whitelist.json`
  - Registers handlers and checks the last bot message.

- **Leomatch Bot Flow**
  - Detects profile cards via regex.
  - Stores the latest profile text.
  - Likes profiles with meaningful descriptions; dislikes empty or short descriptions.
  - Generates a first message when asked by the bot.

- **Private Chat Flow**
  - Ignores users in the whitelist.
  - Marks messages as read.
  - Waits a grace period, then chooses a reply delay:
    - Short delay for active conversations.
    - Random longer delays for new sessions.
  - Generates a reply to the latest message using Gemini with conversation history.
  - If the model returns `|||`, it sends multiple short messages.

- **Persistence**
  - Saves conversation history after each AI response.
  - Uses JSON files for both history and whitelist.

## Key Files
- `src/main.py`: all logic and handlers (current single-file implementation).
- `data/conversation_histories.json`: conversation memory.
- `data/whitelist.json`: manual user whitelist.

## Current Behavior Notes
- The AI persona and rules are encoded in system prompts.
- The system uses a cooldown for bot actions and a debounce delay for chat replies.
- A small retry loop handles Gemini rate limits.