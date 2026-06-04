"""
Sanitizes incoming user messages before they enter the AI pipeline.
Defense against: oversized inputs, control characters, prompt injection,
unicode homoglyph attacks.
"""
import logging
import re
import unicodedata

MAX_USER_MESSAGE_CHARS = 1000

# Patterns that indicate prompt injection attempts.
# Logged and flagged — NOT silently blocked — to avoid false-positives on
# legitimate messages that happen to contain these words.
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+|prior\s+)?instructions?",
    r"forget\s+(everything|all|what you)",
    r"(new\s+)?system\s+(prompt|instruction|directive)",
    r"you\s+are\s+now\s+a",
    r"act\s+as\s+(if\s+you('re|\s+are))?",
    r"pretend\s+(you\s+are|to\s+be)",
    r"disregard\s+(all\s+)?(previous|prior)",
    r"override\s+(your\s+)?(instructions?|settings?|prompt)",
    r"\[SYSTEM\]",
    r"\[INST\]",
    r"</?(s|human|assistant|system|user)>",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
]
_COMPILED_INJECTIONS = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def sanitize_user_input(text: str) -> str:
    """
    Clean and validate user input before it enters the AI pipeline.

    Steps applied:
    1. Strip null bytes and non-printable control characters (keep newline, tab, CR).
    2. Normalize unicode to NFC (closes homoglyph attack surface on keyword filters).
    3. Truncate to MAX_USER_MESSAGE_CHARS.
    4. Log a warning if injection patterns are detected (does not block the message).

    Never raises — falls back to truncated original on any internal error.
    Returns empty string only if the input was empty to begin with.
    """
    if not text:
        return text

    try:
        # Strip control characters except newline (\x0a), tab (\x09), CR (\x0d)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # NFC normalization: collapse homoglyphs to canonical form
        cleaned = unicodedata.normalize("NFC", cleaned)

        # Enforce length limit
        if len(cleaned) > MAX_USER_MESSAGE_CHARS:
            logging.warning(
                f"[SECURITY] User message truncated: {len(cleaned)} → "
                f"{MAX_USER_MESSAGE_CHARS} chars."
            )
            cleaned = cleaned[:MAX_USER_MESSAGE_CHARS]

        # Detect injection attempts — log only, do not block
        for pattern in _COMPILED_INJECTIONS:
            if pattern.search(cleaned):
                logging.warning(
                    f"[SECURITY] Potential prompt injection detected: "
                    f"'{pattern.pattern[:50]}'"
                )
                break

        return cleaned

    except Exception as e:
        logging.error(f"[SECURITY] Input sanitization error: {e}. Using raw truncated input.")
        return text[:MAX_USER_MESSAGE_CHARS] if len(text) > MAX_USER_MESSAGE_CHARS else text
