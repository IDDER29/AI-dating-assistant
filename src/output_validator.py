"""
Validates AI-generated response text before delivery to users.
"""
from dataclasses import dataclass

MAX_RESPONSE_CHARS = 600
MAX_LADDER_PARTS = 4

PROMPT_LEAK_MARKERS = [
    "dossier",
    "your task is to",
    "anti-deanon",
    "communication rules",
    "system prompt",
    "you are the ai avatar",
    "you are an ai",
    "i am an ai",
    "as an ai language model",
]

# Phrases that indicate the AI has broken persona — either admitted AI nature
# or adopted a formal register that signals successful prompt injection.
PERSONA_COLLAPSE_MARKERS = [
    "i am an ai",
    "i'm an ai",
    "as an ai",
    "i am a language model",
    "i'm a language model",
    "as a language model",
    "i cannot fulfill",
    "i'm not able to",
    "i am not able to",
    "i cannot assist",
    "i cannot help with",
    "i'm just a bot",
    "i am just a bot",
    "i was programmed",
    "my programming",
    "as your assistant",
    "i don't have personal",
    "i don't have feelings",
    "i don't have emotions",
    "as an artificial",
    "i need to be transparent",
    "i must be honest",
    "it would be unethical",
]


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""


def validate_response(text: str) -> ValidationResult:
    """
    Returns ValidationResult(valid=True) if the response is safe to send.
    Returns ValidationResult(valid=False, reason=...) if it should be rejected.

    Checks (in order):
    1. Empty / whitespace-only
    2. Exceeds MAX_RESPONSE_CHARS
    3. Exceeds MAX_LADDER_PARTS ladder parts
    4. Contains prompt leak markers (system prompt leakage)
    5. Contains persona collapse markers (AI nature admission)
    """
    if not text or not text.strip():
        return ValidationResult(False, "empty response")

    if len(text) > MAX_RESPONSE_CHARS:
        return ValidationResult(False, f"response too long ({len(text)} chars)")

    parts = [p for p in text.split("|||") if p.strip()]
    if len(parts) > MAX_LADDER_PARTS:
        return ValidationResult(False, f"too many ladder parts ({len(parts)})")

    lower = text.lower()

    for marker in PROMPT_LEAK_MARKERS:
        if marker in lower:
            return ValidationResult(False, f"possible prompt leak: '{marker}'")

    for marker in PERSONA_COLLAPSE_MARKERS:
        if marker in lower:
            return ValidationResult(False, f"persona collapse: '{marker}'")

    return ValidationResult(True)
