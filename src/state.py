from dataclasses import dataclass, field
import datetime
from typing import Any, Dict, List, Optional, Set


@dataclass
class BotState:
    last_seen_anket_text: Optional[str] = None
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
    active_dialogue_tasks: Dict[int, Any] = field(default_factory=dict)
    last_reply_times: Dict[int, Any] = field(default_factory=dict)
    meeting_signals_detected: Set[int] = field(default_factory=set)
    leomatch_task: Optional[Any] = None
    whitelist_ids: Set[int] = field(default_factory=set)
    model: Optional[Any] = None
    app: Optional[Any] = None
