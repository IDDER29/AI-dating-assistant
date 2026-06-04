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


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""


def validate_response(text: str) -> ValidationResult:
    """
    Returns ValidationResult(valid=True) if the response is safe to send.
    Returns ValidationResult(valid=False, reason=...) if it should be rejected.
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

    return ValidationResult(True)
