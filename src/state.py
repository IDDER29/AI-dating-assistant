from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    # Imported only during type-checking (mypy / pylance) — not at runtime.
    # Avoids circular imports and prevents loading heavy SDKs just for type hints.
    import pyrogram
    import google.generativeai as genai


@dataclass
class PendingMatch:
    """Holds the profile card for a liked match, waiting for an opener to be sent."""
    anket_text: str
    liked_at: str                          # ISO UTC timestamp
    description: str = ""                 # extracted description text
    opener_text: Optional[str] = None     # filled after opener is generated


@dataclass
class BotState:
    """
    Central mutable state for the bot.
    All fields are owned by the module that writes them.
    Do not add business logic here — only data.
    """
    pending_match: Optional[PendingMatch] = None

    last_action_time: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc
        )
    )
    start_time: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    conversation_histories: Dict[str, list] = field(default_factory=dict)
    conversation_memories: Dict[str, str] = field(default_factory=dict)
    sent_openers: List[dict] = field(default_factory=list)
    message_buffers: Dict[int, List[str]] = field(default_factory=dict)

    active_dialogue_tasks: Dict[int, Any] = field(default_factory=dict)  # asyncio.Task
    last_reply_times: Dict[int, datetime.datetime] = field(default_factory=dict)
    meeting_signals_detected: Set[int] = field(default_factory=set)

    leomatch_task: Optional[Any] = None   # asyncio.Task
    whitelist_ids: Set[int] = field(default_factory=set)

    active_model_name: Optional[str] = None
    model: Optional["genai.GenerativeModel"] = None
    app: Optional["pyrogram.Client"] = None

    def __post_init__(self):
        if self.last_action_time.tzinfo is None:
            raise ValueError("BotState.last_action_time must be timezone-aware")
        if self.start_time.tzinfo is None:
            raise ValueError("BotState.start_time must be timezone-aware")
