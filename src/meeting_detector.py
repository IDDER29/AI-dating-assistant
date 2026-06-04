"""
Detects when a user suggests a real-world meeting in a conversation message.
"""

SIGNALS_RU = [
    "встретимся", "встретиться", "увидимся", "увидеться",
    "давай встретимся", "предлагаю встретиться", "пойдем куда-нибудь",
    "сходим", "когда ты свободен", "когда ты свободна",
    "выпьем кофе", "попьем кофе", "кофе вместе",
    "погулять вместе", "давай погуляем",
    "встреча", "встретиться лично", "увидеться вживую",
]

SIGNALS_EN = [
    "let's meet", "want to meet", "we should meet",
    "meet up", "hang out", "get together",
    "grab coffee", "get coffee", "coffee sometime",
    "when are you free", "are you free",
    "let's get together", "in person", "face to face",
    "go for a walk", "take a walk",
]

ALL_SIGNALS = SIGNALS_RU + SIGNALS_EN


def detect_meeting_signal(text: str) -> bool:
    """
    Returns True if the text contains a meeting suggestion signal.
    Case-insensitive substring match.
    """
    if not text:
        return False
    lower = text.lower()
    return any(signal in lower for signal in ALL_SIGNALS)
