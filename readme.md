# AI Assistant for Telegram Dating Bot

This project is an advanced AI assistant in Python, designed to automate interaction with the Telegram dating bot `@leomatchbot`. It's a full-fledged digital avatar that learns a specific personality to conduct realistic, human-like dialogues. The ultimate goal of the assistant is to make the interlocutor take the initiative and suggest meeting.

The project was developed as a social and technical experiment to explore the boundaries of AI application in human communication and to test the hypothesis of whether a machine can effectively reproduce a complex and subtle communication style.

## Key Features

-   **"Dual-Brain" Architecture:** The script works with two different AI-based "brains":
    1.  **"Scout":** Works inside the dating bot, automatically filters profiles by quality of description and generates unique, witty first messages.
    2.  **"Interlocutor":** Activated in private chats, uses a deeply personalized persona to lead conversations, remember context, and steer the dialogue toward the set goal.

-   **Deep Personalization:** The AI personality is not template-based. It's built on a detailed "dossier" laid out in the system prompt: profession, hobbies, sense of humor, tastes, and even personal stories. This makes its responses consistent and plausible.

-   **Hyper-realistic Interaction Engine:** To avoid "machine-like" communication, the assistant uses several advanced techniques:
    *   **"Live" Writing Style:** Follows an informal communication style (no periods at the end, using slang) and applies post-processing to clean up AI responses from "academic" language.
    *   **"Ladder" Sending:** Mimics the human way of typing, sometimes breaking one thought into several short, quickly sent messages.
    *   **Dynamic Response Delay:** Calculates response time based on context. Fast responses for active dialogues and more realistic delays (from a few minutes to hours) when resuming a conversation.
    *   **"Smart Timer" (Debounce):** If the user sends several messages in a row, the AI waits for a pause before composing a single, coherent response to the entire block of messages.
    *   **"Read" Status and Typing Indication:** Instantly marks incoming messages as read (two checkmarks) and shows the "typing..." status before responding, creating an effect of presence.

-   **Reliability and Autonomy:**
    *   **"Whitelist":** Allows the operator to manually exclude certain users from AI processing, ensuring a smooth transition to manual communication.
    *   **Persistent Memory:** Saves all dialogue histories in a JSON file, allowing the bot to withstand restarts and remember every conversation.
    *   **API Limit Handling:** Correctly handles request limiting errors from the API, waiting for the recommended time before retrying.
    *   **24/7 Operation:** The script is designed for deployment on a server (e.g., Ubuntu) for continuous autonomous operation.

## Technology Stack

-   **Language:** Python 3.10+
-   **Main library:** [Pyrogram](https://pyrogram.org/) (for asynchronous interaction with the Telegram API)
-   **AI Model:** Google Gemini 1.5 Flash
-   **Dependencies:** `google-generativeai`, `tgcrypto`, `python-dotenv`

## Installation and Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-login/repository-name.git
    cd repository-name
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure your keys:**
    *   Copy the example environment variables file: `cp .env.example .env`
    *   Open the `.env` file in a text editor (e.g., `nano .env`).
    *   Fill in your `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (get them at [my.telegram.org](https://my.telegram.org)), and `GEMINI_API_KEY` (get it at [Google AI Studio](https://ai.google.dev/)).

5.  **(Optional) Configure AI Personality:**
    *   Open `src/config.py` and carefully edit the `FIRST_MESSAGE_PROMPT` and `CONVERSATION_SYSTEM_PROMPT` variables to define your AI's personality and goals.

6.  **(Optional) Add users to "Whitelist":**
    *   Find out the Telegram User ID of the desired people (e.g., by forwarding their message to the `@userinfobot` bot).
    *   Add their numerical IDs to the `data/whitelist.json` file.
    ```json
    [
        123456789,
        987654321
    ]
    ```

## Running the Bot

1.  **First run for authorization:** Run the script directly to log in to your Telegram account. Pyrogram will request a phone number and a confirmation code.
    ```bash
    python3 src/main.py
    ```
    After successful login, a `.session` file will be created. You can stop the script (`Ctrl+C`).

2.  **Run in background for 24/7 operation:** For continuous operation on a server, it's best to use a terminal multiplexer like `tmux`.
    ```bash
    # Start a new tmux session
    tmux new -s dating_bot

    # Run the script inside the session
    python3 src/main.py

    # You can detach from the session by pressing Ctrl+B, then D. The script will continue running.
    # To return to the session later: tmux attach -t dating_bot
    ```

## Disclaimer

This project is an educational experiment in AI and automation. Please use it responsibly and ethically. The author is not responsible for the results of its use.
